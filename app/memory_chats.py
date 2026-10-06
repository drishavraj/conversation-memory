"""Durable single-owner chat turns. Scope is immutable; retries never duplicate messages."""
from datetime import timedelta, timezone
from uuid import UUID, uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update, or_, func
from .models import now
from .memory_models import ChatThread, ChatTurn, MemoryRecord, Project, Topic
from .memories import require_enabled, project_or_404, check_topics, visible_memory, answer_project, MemoryQuestion
from .ai_settings import defaults_for
from .task_providers import provider_for

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')

class ThreadInput(Strict):
    project_id: str
    topic_id: str | None=None
    title: str=Field(default='New chat',min_length=1,max_length=120)
    @field_validator('title')
    @classmethod
    def clean(cls,v):
        if not v.strip():raise ValueError('Title must not be blank')
        return v.strip()

class TurnInput(Strict):
    request_id: UUID
    expected_version: int=Field(ge=0)
    question: str=Field(min_length=1,max_length=1000)
    include_history: bool=False
    @field_validator('question')
    @classmethod
    def clean(cls,v):
        if not v.strip():raise ValueError('Question must not be blank')
        return v.strip()

class Rename(Strict):
    title: str=Field(min_length=1,max_length=120)
    expected_version: int=Field(ge=0)
    @field_validator('title')
    @classmethod
    def clean(cls,v):return ThreadInput.clean(v)

def checked(session,id,lock=False):
    if lock:
        # Serialize submission/retry against this thread on both SQLite and Postgres.
        session.execute(update(ChatThread).where(ChatThread.id==id).values(version=ChatThread.version))
    thread=session.get(ChatThread,id,populate_existing=True)
    if not thread:raise HTTPException(404,'Chat not found')
    project_or_404(session,thread.project_id)
    if thread.topic_id:check_topics(session,thread.project_id,[thread.topic_id])
    return thread

def describe(session,t):
    p=session.get(Project,t.project_id);topic=session.get(Topic,t.topic_id) if t.topic_id else None
    return {'id':t.id,'title':t.title,'project_id':t.project_id,'project_name':p.name,'theme_id':p.theme_id,'topic_id':t.topic_id,'topic_name':topic.name if topic else None,'version':t.version,'pending_turn_id':t.pending_turn_id,'created_at':t.created_at.isoformat(),'updated_at':t.updated_at.isoformat()}

def source_changed(session,thread,snapshot):
    row=session.get(MemoryRecord,snapshot['id'],populate_existing=True)
    if not row or row.project_id!=thread.project_id or (thread.topic_id and thread.topic_id not in row.topic_ids):return True
    current=visible_memory(session,session.get(Project,thread.project_id),row)
    return current['needs_review'] or current['version']!=snapshot['version'] or current['evidence']!=snapshot['evidence']

def serialize_turn(session,thread,turn):
    result={k:getattr(turn,k) for k in ['id','request_id','sequence','question','include_history','status','response','error','model','context_info']}
    result.update(created_at=turn.created_at.isoformat(),updated_at=turn.updated_at.isoformat())
    stamp=turn.updated_at.replace(tzinfo=timezone.utc) if turn.updated_at.tzinfo is None else turn.updated_at
    result['retry_after_seconds']=max(0,int((stamp+timedelta(minutes=15)-now()).total_seconds())) if turn.status=='running' else 0
    result['changed_source_ids']=[s['id'] for s in (turn.response or {}).get('sources',[]) if source_changed(session,thread,s)]
    return result

def conversation_context(session,thread,before):
    # Recent turns plus explicitly truncated excerpts. No model-generated statement is promoted to evidence.
    rows=session.scalars(select(ChatTurn).where(ChatTurn.thread_id==thread.id,ChatTurn.sequence<before,ChatTurn.status=='completed').order_by(ChatTurn.sequence.desc()).limit(32)).all()[::-1]
    def compact(t,limit):
        # Discard stale assistant text; keep the user's question as a reference only.
        stale=any(source_changed(session,thread,s) for s in (t.response or {}).get('sources',[]))
        return {'question':t.question[:limit],'assistant_context_not_evidence':None if stale else ' '.join(c['text'] for c in (t.response or {}).get('claims',[]))[:limit],'prior_evidence_changed':stale}
    recent=[compact(t,1000) for t in rows[-12:]]
    older=[compact(t,150) for t in rows[:-12]]
    total=session.scalar(select(func.count()).select_from(ChatTurn).where(ChatTurn.thread_id==thread.id,ChatTurn.sequence<before,ChatTurn.status=='completed'))
    return {'recent':recent,'earlier_excerpts':older,'earlier_excerpts_are_truncated':bool(older),'omitted_turns':max(0,total-len(rows))}

def router_for(authorize,db,answer_provider=None):
    router=APIRouter(prefix='/api/memories/chats',dependencies=[Depends(authorize),Depends(require_enabled)])

    @router.post('',status_code=201)
    def create(payload:ThreadInput,session=Depends(db)):
        project_or_404(session,payload.project_id)
        if payload.topic_id:check_topics(session,payload.project_id,[payload.topic_id])
        t=ChatThread(**payload.model_dump());session.add(t);session.commit();return describe(session,t)

    @router.get('')
    def history(project_id:str|None=None,topic_id:str|None=None,q:str=Query('',max_length=200),offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100),session=Depends(db)):
        stmt=select(ChatThread).join(Project,Project.id==ChatThread.project_id).outerjoin(Topic,Topic.id==ChatThread.topic_id)
        if project_id:project_or_404(session,project_id);stmt=stmt.where(ChatThread.project_id==project_id)
        if topic_id:
            topic=session.get(Topic,topic_id)
            if not topic or (project_id and topic.project_id!=project_id):raise HTTPException(422,'Topic does not belong to project')
            stmt=stmt.where(ChatThread.topic_id==topic_id)
        if q.strip():stmt=stmt.where(or_(func.lower(ChatThread.title).contains(q.strip().lower(),autoescape=True),func.lower(Project.name).contains(q.strip().lower(),autoescape=True),func.lower(Topic.name).contains(q.strip().lower(),autoescape=True)))
        rows=session.scalars(stmt.order_by(ChatThread.updated_at.desc(),ChatThread.id).offset(offset).limit(limit+1)).all()
        return {'items':[describe(session,t) for t in rows[:limit]],'has_more':len(rows)>limit}

    @router.get('/{thread_id}')
    def detail(thread_id:str,before:int|None=Query(None,ge=1),limit:int=Query(30,ge=1,le=100),session=Depends(db)):
        t=checked(session,thread_id);stmt=select(ChatTurn).where(ChatTurn.thread_id==thread_id)
        if before is not None:stmt=stmt.where(ChatTurn.sequence<before)
        rows=session.scalars(stmt.order_by(ChatTurn.sequence.desc()).limit(limit+1)).all()
        return {**describe(session,t),'turns':[serialize_turn(session,t,row) for row in reversed(rows[:limit])],'has_older':len(rows)>limit}

    @router.patch('/{thread_id}')
    def rename(thread_id:str,payload:Rename,session=Depends(db)):
        t=checked(session,thread_id,True)
        if t.pending_turn_id or t.version!=payload.expected_version:raise HTTPException(409,'Chat changed or has a pending response; reload first')
        t.title=payload.title;t.version+=1;t.updated_at=now();session.commit();return describe(session,t)

    def run(session,t,turn):
        tid,turn_id,lease=t.id,turn.id,turn.lease
        context=conversation_context(session,t,turn.sequence)
        turn.context_info={'recent_turns':len(context['recent']),'earlier_excerpt_turns':len(context['earlier_excerpts']),'omitted_turns':context['omitted_turns'],'context_is_not_evidence':True,'prior_evidence_changed':any(r['prior_evidence_changed'] for r in context['recent']+context['earlier_excerpts'])}
        question=MemoryQuestion(question=turn.question,topic_id=t.topic_id,include_history=turn.include_history)
        project_id=t.project_id;model=turn.model;session.commit()
        result=None;error=None
        try:
            result=answer_project(session,project_id,question,answer_provider or provider_for(model),conversation=context)
        except Exception:
            error='answer_generation_unavailable'
        # End the read transaction and re-check sources after the external provider call.
        session.rollback();session.expire_all()
        t=checked(session,tid,True);turn=session.get(ChatTurn,turn_id,populate_existing=True)
        if turn.lease!=lease or turn.status!='running':session.rollback();return {'thread_version':t.version,'turn':serialize_turn(session,t,turn)}
        if result and any(source_changed(session,t,s) for s in result.get('sources',[])):
            result=None;error='sources_changed_retry'
        turn.response=result;turn.error=error;turn.status='failed' if error else 'completed';turn.updated_at=now()
        if t.pending_turn_id==turn.id:t.pending_turn_id=None
        t.updated_at=now();session.commit()
        return {'thread_version':t.version,'turn':serialize_turn(session,t,turn)}

    @router.post('/{thread_id}/turns')
    def send(thread_id:str,payload:TurnInput,session=Depends(db)):
        t=checked(session,thread_id,True)
        existing=session.scalar(select(ChatTurn).where(ChatTurn.thread_id==thread_id,ChatTurn.request_id==str(payload.request_id)))
        if existing:
            if existing.question!=payload.question or existing.include_history!=payload.include_history:raise HTTPException(409,'Request ID already used for a different message')
            session.commit();return {'thread_version':t.version,'turn':serialize_turn(session,t,existing)}
        if t.version!=payload.expected_version or t.pending_turn_id:raise HTTPException(409,'Chat changed or response pending; reload before sending')
        latest=session.scalar(select(ChatTurn).where(ChatTurn.thread_id==thread_id).order_by(ChatTurn.sequence.desc()).limit(1))
        if latest and latest.status=='failed':raise HTTPException(409,'Retry the failed turn before sending a follow-up')
        t.version+=1;t.updated_at=now()
        turn=ChatTurn(thread_id=t.id,request_id=str(payload.request_id),sequence=t.version,question=payload.question,include_history=payload.include_history,model=defaults_for(session)[0]['answer'],lease=str(uuid4()))
        session.add(turn);session.flush();t.pending_turn_id=turn.id
        if t.title=='New chat':t.title=payload.question[:120]
        session.commit();return run(session,t,turn)

    @router.post('/{thread_id}/turns/{turn_id}/retry')
    def retry(thread_id:str,turn_id:str,session=Depends(db)):
        t=checked(session,thread_id,True);turn=session.get(ChatTurn,turn_id)
        if not turn or turn.thread_id!=thread_id:raise HTTPException(404,'Turn not found')
        latest=session.scalar(select(ChatTurn.id).where(ChatTurn.thread_id==thread_id).order_by(ChatTurn.sequence.desc()).limit(1))
        if latest!=turn_id:raise HTTPException(409,'Only the latest turn can be retried')
        if turn.status=='completed':session.commit();return {'thread_version':t.version,'turn':serialize_turn(session,t,turn)}
        stamp=turn.updated_at.replace(tzinfo=timezone.utc) if turn.updated_at.tzinfo is None else turn.updated_at
        if turn.status=='running' and now()-stamp<timedelta(minutes=15):raise HTTPException(409,'Response still processing; retry after its lease expires')
        turn.status='running';turn.error=None;turn.lease=str(uuid4());turn.updated_at=now();t.pending_turn_id=turn.id;session.commit()
        return run(session,t,turn)
    @router.post('/{thread_id}/turns/stream')
    def stream(thread_id:str,payload:TurnInput,session=Depends(db)):
        # Only progress and the fully validated final answer are streamed. Never expose
        # unvalidated provider tokens before citation/source checks have completed.
        import asyncio
        import json
        from fastapi.responses import StreamingResponse
        from .tenancy import workspace_sessions
        engine=session.get_bind()
        isolated_sessions=workspace_sessions(engine,session.access.workspace_id,session.access.user_id)
        def execute():
            with isolated_sessions() as isolated:
                return send(thread_id,payload,isolated)
        async def events():
            future=asyncio.get_running_loop().run_in_executor(None,execute)
            yield 'event: status\ndata: '+json.dumps({'message':'Retrieving evidence and preparing your answer…'})+'\n\n'
            try:
                while not future.done():
                    done,_=await asyncio.wait({future},timeout=5)
                    if not done:yield ': keepalive\n\n'
                result=await future
                yield 'event: result\ndata: '+json.dumps(result)+'\n\n'
            except HTTPException as exc:
                yield 'event: error\ndata: '+json.dumps({'message':str(exc.detail),'status':exc.status_code})+'\n\n'
            except Exception:
                yield 'event: error\ndata: '+json.dumps({'message':'Connection interrupted. Check the saved chat before retrying.'})+'\n\n'
        return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    return router
