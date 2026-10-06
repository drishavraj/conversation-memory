"""Durable, idempotent memory suggestions; never auto-overwrite accepted knowledge."""
import json
from hashlib import sha256
from datetime import timedelta
from sqlalchemy import select, update
from .models import Entry, Knowledge, now
from .memory_models import Project, ProjectEntry, MemoryRecord, MemoryProposal
from .memories import enabled, Suggestions, RECONCILE_PROMPT, evidence_for, memory_dict, valid_evidence
from .task_providers import provider_for

def process_memory_one(sessions,provider=None):
    from .tenancy import across_workspaces
    return across_workspaces(_process_memory_one,sessions,provider)

def _process_memory_one(sessions,provider=None):
    if not enabled():return False
    with sessions() as db:
        # Expired claims are safe to retry: proposals publish in one guarded transaction.
        db.execute(update(ProjectEntry).where(ProjectEntry.status=='processing',ProjectEntry.claimed_at<now()-timedelta(minutes=15)).values(status='queued',claimed_at=None,version=ProjectEntry.version+1))
        db.commit()
        link=db.scalar(select(ProjectEntry).join(Entry,Entry.id==ProjectEntry.entry_id).where(ProjectEntry.status=='queued',Entry.status=='ready').order_by(ProjectEntry.created_at,ProjectEntry.project_id).limit(1))
        if not link:return False
        project_id,entry_id,version=link.project_id,link.entry_id,link.version
        claim=db.execute(update(ProjectEntry).where(ProjectEntry.project_id==project_id,ProjectEntry.entry_id==entry_id,ProjectEntry.version==version,ProjectEntry.status=='queued').values(status='processing',claimed_at=now()))
        if claim.rowcount!=1:db.rollback();return False
        project=db.get(Project,project_id);entry=db.get(Entry,entry_id)
        topic_ids=list(link.topic_ids);model=dict(link.model)
        sources=[evidence_for(k,entry) for k in db.scalars(select(Knowledge).where(Knowledge.entry_id==entry_id,Knowledge.theme_id==project.theme_id,Knowledge.status!='dismissed').order_by(Knowledge.id).limit(501))]
        candidates=db.scalars(select(MemoryRecord).where(MemoryRecord.project_id==project_id).order_by(MemoryRecord.updated_at.desc()).limit(200)).all()
        targets={m.id:memory_dict(m) for m in candidates if valid_evidence(db,project,m.evidence)}
        context={'project':{'name':project.name,'description':project.description,'theme':project.theme_id},'source_records':sources,'current_memories':list(targets.values())}
        db.commit()
    try:
        if len(sources)>500:raise ValueError('Too many source items')
        result=Suggestions.model_validate((provider or provider_for(model)).generate(Suggestions,RECONCILE_PROMPT,context)) if sources else Suggestions(proposals=[])
        allowed={s['id']:s for s in sources}
        prepared=[]
        for suggestion in result.proposals:
            if not suggestion.text.strip() or not suggestion.reason.strip():raise ValueError('Empty suggestion')
            if not set(suggestion.source_ids)<=allowed.keys():raise ValueError('Invalid source citation')
            if suggestion.operation=='new' and suggestion.target_id is not None:raise ValueError('Unexpected target')
            if suggestion.operation!='new' and suggestion.target_id not in targets:raise ValueError('Invalid target')
            evidence=[allowed[id] for id in sorted(set(suggestion.source_ids))]
            if suggestion.certainty=='explicit' and all(e['certainty']=='tentative' for e in evidence):raise ValueError('Unsupported certainty')
            payload=suggestion.model_dump();payload['topic_ids']=topic_ids
            payload['target_version']=targets[suggestion.target_id]['version'] if suggestion.target_id else None
            payload['model']=model
            digest=sha256(json.dumps({'project':project_id,'entry':entry_id,'proposal':payload,'evidence':evidence},sort_keys=True).encode()).hexdigest()
            prepared.append((digest,payload,evidence))
        with sessions() as db:
            # Lock project before link to use the same ordering as review/unlink.
            db.execute(update(Project).where(Project.id==project_id).values(name=Project.name))
            link=db.get(ProjectEntry,(project_id,entry_id))
            if not link or link.status!='processing' or link.version!=version:return True
            project=db.get(Project,project_id)
            if any(len(valid_evidence(db,project,e))!=len(e) for _,_,e in prepared):raise ValueError('Source changed')
            for digest,payload,evidence in prepared:
                if not db.scalar(select(MemoryProposal.id).where(MemoryProposal.fingerprint==digest)):
                    db.add(MemoryProposal(project_id=project_id,entry_id=entry_id,fingerprint=digest,payload=payload,evidence=evidence))
            link.status='completed';link.error=None;link.claimed_at=None;db.commit()
    except Exception as error:
        from .worker import safe_error
        code='memory_evidence_invalid' if isinstance(error,ValueError) else safe_error(error)
        with sessions() as db:
            db.execute(update(ProjectEntry).where(ProjectEntry.project_id==project_id,ProjectEntry.entry_id==entry_id,ProjectEntry.version==version,ProjectEntry.status=='processing').values(status='failed',error=code,claimed_at=None));db.commit()
    return True
