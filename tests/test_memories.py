import pytest
from tenant_fixtures import Session
from sqlalchemy import select, update
from app.models import Entry, Knowledge
from app.memory_models import ProjectEntry, MemoryRecord, MemoryProposal
from app.memory_worker import process_memory_one
from app.database import session_factory
from app.main import create_app
from fastapi.testclient import TestClient
from test_api import client, headers, TOKEN

@pytest.fixture(autouse=True)
def memory_flag(monkeypatch):monkeypatch.setenv('MEMORIES_ENABLED','true')

def project(client,headers,theme='office',name='PNB Edge'):
    r=client.post('/api/memories/projects',headers=headers,json={'name':name,'theme_id':theme})
    assert r.status_code==201,r.text
    return r.json()['id']

def source(client,theme='office',text='Launch is confirmed for Friday.'):
    with Session(client.app.state.engine) as db:
        entry=Entry(title='Review meeting',original_text=text,theme_id=theme,status='ready');db.add(entry);db.flush()
        item=Knowledge(entry_id=entry.id,kind='decision',text=text,evidence=text,evidence_start=0,evidence_end=len(text),theme_id=theme,certainty='explicit',version=1)
        db.add(item);db.commit();return entry.id,item.id

def link(client,headers,p,e,topics=[]):
    return client.post(f'/api/memories/projects/{p}/entries',headers=headers,json={'entry_id':e,'topic_ids':topics})

class Proposer:
    def __init__(self,target=None,operation='new',fake=False):self.target=target;self.operation=operation;self.fake=fake;self.context=None
    def generate(self,schema,prompt,context):
        self.context=context
        s=context['source_records'][0]
        return {'proposals':[{'operation':self.operation,'target_id':self.target,'kind':'decision','text':s['text'],'certainty':s['certainty'],'source_ids':['invented' if self.fake else s['id']],'reason':'Explicit meeting statement'}]}

def run(client,provider=None):
    return process_memory_one(session_factory(client.app.state.engine),provider or Proposer())

def detail(client,headers,p):return client.get('/api/memories/projects/'+p,headers=headers).json()
def accept(client,headers,p,proposal):
    return client.post(f'/api/memories/projects/{p}/proposals/{proposal["id"]}/review',headers=headers,json={'decision':'accept','expected_version':proposal['current']['version'] if proposal.get('current') else None,'reason':'Verified against meeting'})

def test_owner_gate_feature_flag_and_names(client,headers,monkeypatch):
    assert client.get('/api/memories/projects').status_code==401
    assert client.post('/api/memories/projects',headers=headers,json={'name':'  ','theme_id':'office'}).status_code==422
    p=project(client,headers)
    assert client.post('/api/memories/projects',headers=headers,json={'name':'pnb edge','theme_id':'office'}).status_code==409
    assert client.get('/api/memories/projects?theme_id=personal',headers=headers).json()['items']==[]
    monkeypatch.setenv('MEMORIES_ENABLED','false')
    assert client.get('/api/memories/projects',headers=headers).status_code==404

def test_theme_and_topic_isolation_and_idempotent_link(client,headers):
    p=project(client,headers);other=project(client,headers,name='Other')
    topic=client.post(f'/api/memories/projects/{other}/topics',headers=headers,json={'name':'Demo'}).json()['id']
    e,k=source(client,theme='personal')
    assert link(client,headers,p,e).status_code==422
    e,k=source(client)
    assert link(client,headers,p,e,[topic]).status_code==422
    assert link(client,headers,p,e).status_code==200
    assert link(client,headers,p,e).status_code==200
    assert len(detail(client,headers,p)['entries'])==1
    assert client.get(f'/api/memories/projects/{p}?topic_id={topic}',headers=headers).status_code==422

def test_queue_review_dedup_history_and_stale_review(client,headers):
    p=project(client,headers);e,k=source(client);assert link(client,headers,p,e).status_code==200
    assert run(client)
    d=detail(client,headers,p);assert d['memories']==[] and len(d['proposals'])==1
    proposal=d['proposals'][0];assert accept(client,headers,p,proposal).status_code==200
    assert accept(client,headers,p,proposal).status_code==409
    m=detail(client,headers,p)['memories'][0]
    # Retry exactly the same sources creates no duplicate review proposal.
    assert client.post(f'/api/memories/projects/{p}/entries/{e}/retry',headers=headers).status_code==200
    assert run(client);assert not detail(client,headers,p)['proposals']
    e2,k2=source(client,text='Launch has moved to Monday.')
    link(client,headers,p,e2);assert run(client,Proposer(m['id'],'replace'))
    proposal=detail(client,headers,p)['proposals'][0]
    assert proposal['current']['text']=='Launch is confirmed for Friday.'
    assert accept(client,headers,p,proposal).status_code==200
    after=detail(client,headers,p)['memories'][0]
    assert after['text']=='Launch has moved to Monday.' and after['version']==2
    history=client.get(f'/api/memories/projects/{p}/memories/{m["id"]}/history',headers=headers).json()
    assert len(history)==2 and history[-1]['before']['text']=='Launch is confirmed for Friday.'

def test_hallucinated_sources_fail_without_publishing(client,headers):
    p=project(client,headers);e,k=source(client);link(client,headers,p,e)
    assert run(client,Proposer(fake=True))
    d=detail(client,headers,p);assert not d['proposals'];assert d['entries'][0]['memory_status']=='failed'
    assert d['entries'][0]['error']=='memory_evidence_invalid'

def test_source_correction_and_unlink_invalidate_memory(client,headers):
    p=project(client,headers);e,k=source(client);link(client,headers,p,e);run(client)
    proposal=detail(client,headers,p)['proposals'][0]
    with Session(client.app.state.engine) as db:
        db.get(Knowledge,k).version+=1;db.commit()
    assert accept(client,headers,p,proposal).status_code==409
    # Regenerate to get evidence pinned to the new source version.
    client.post(f'/api/memories/projects/{p}/entries/{e}/retry',headers=headers);run(client)
    d=detail(client,headers,p);fresh=next(x for x in d['proposals'] if not x['stale']);assert accept(client,headers,p,fresh).status_code==200
    client.delete(f'/api/memories/projects/{p}/entries/{e}',headers=headers)
    assert detail(client,headers,p)['memories'][0]['needs_review']
    assert client.post(f'/api/memories/projects/{p}/ask',headers=headers,json={'question':'When is launch?'}).json()['status']=='no_evidence'

def test_pending_conversation_waits_until_ready(client,headers):
    p=project(client,headers);e,k=source(client)
    with Session(client.app.state.engine) as db:db.get(Entry,e).status='queued';db.commit()
    link(client,headers,p,e);assert not run(client)
    with Session(client.app.state.engine) as db:db.get(Entry,e).status='ready';db.commit()
    assert run(client)

def test_scoped_answers_cite_only_accepted_memory(client,headers,monkeypatch):
    p=project(client,headers);p2=project(client,headers,name='Different project')
    e,k=source(client);link(client,headers,p,e);run(client);accept(client,headers,p,detail(client,headers,p)['proposals'][0])
    class Answerer:
        def generate(self,schema,prompt,context):
            assert all(r['project_id']==p for r in context['records'])
            return {'claims':[{'text':'Friday is confirmed.','source_ids':[context['records'][0]['id']]}]}
    from app import task_providers
    monkeypatch.setattr(task_providers,'provider_for',lambda *_:Answerer())
    r=client.post(f'/api/memories/projects/{p}/ask',headers=headers,json={'question':'When is launch?','include_history':True})
    assert r.status_code==200,r.text
    assert r.json()['status']=='answered' and r.json()['sources'][0]['history']
    assert client.post(f'/api/memories/projects/{p2}/ask',headers=headers,json={'question':'When is launch?'}).json()['status']=='no_evidence'

def test_reject_does_not_modify_memory_and_records_reason(client,headers):
    p=project(client,headers);e,k=source(client);link(client,headers,p,e);run(client)
    proposal=detail(client,headers,p)['proposals'][0]
    response=client.post(f'/api/memories/projects/{p}/proposals/{proposal["id"]}/review',headers=headers,json={'decision':'reject','reason':'This was a proposal, not a decision'})
    assert response.status_code==200
    assert not detail(client,headers,p)['memories']
    with Session(client.app.state.engine) as db:assert db.get(MemoryProposal,proposal['id']).payload['review_reason']=='This was a proposal, not a decision'

def test_unlink_during_generation_cannot_publish(client,headers):
    p=project(client,headers);e,k=source(client);link(client,headers,p,e)
    class Unlinking(Proposer):
        def generate(self,*args):
            client.delete(f'/api/memories/projects/{p}/entries/{e}',headers=headers)
            return super().generate(*args)
    run(client,Unlinking())
    assert not detail(client,headers,p)['proposals']

def test_cross_project_target_cannot_publish(client,headers):
    p=project(client,headers);other=project(client,headers,name='Other');e,k=source(client);link(client,headers,other,e);run(client)
    accept(client,headers,other,detail(client,headers,other)['proposals'][0]);target=detail(client,headers,other)['memories'][0]['id']
    link(client,headers,p,e);run(client,Proposer(target,'replace'))
    assert detail(client,headers,p)['entries'][0]['memory_status']=='failed'
    assert not detail(client,headers,p)['proposals']

def test_topic_membership_and_exact_duplicate_evidence(client,headers):
    p=project(client,headers)
    t=client.post(f'/api/memories/projects/{p}/topics',headers=headers,json={'name':'Demo'}).json()['id']
    for _ in range(2):
        e,k=source(client);link(client,headers,p,e,[t]);run(client);accept(client,headers,p,detail(client,headers,p)['proposals'][0])
    memories=client.get(f'/api/memories/projects/{p}?topic_id={t}',headers=headers).json()['memories']
    assert len(memories)==1 and len(memories[0]['evidence'])==2

def test_restore_is_versioned_and_requires_live_evidence(client,headers):
    p=project(client,headers);e,k=source(client);link(client,headers,p,e);run(client);accept(client,headers,p,detail(client,headers,p)['proposals'][0])
    m=detail(client,headers,p)['memories'][0]
    hist=client.get(f'/api/memories/projects/{p}/memories/{m["id"]}/history',headers=headers).json()
    e2,k2=source(client,text='Launch has moved to Monday.');link(client,headers,p,e2);run(client,Proposer(m['id'],'replace'));accept(client,headers,p,detail(client,headers,p)['proposals'][0])
    url=f'/api/memories/projects/{p}/memories/{m["id"]}/restore'
    body={'revision_id':hist[0]['id'],'expected_version':1,'reason':'Monday update was entered in error'}
    assert client.post(url,headers=headers,json=body).status_code==409
    body['expected_version']=2
    r=client.post(url,headers=headers,json=body);assert r.status_code==200,r.text
    assert r.json()['version']==3 and r.json()['text']==m['text']
    client.delete(f'/api/memories/projects/{p}/entries/{e}',headers=headers)
    body['expected_version']=3
    assert client.post(url,headers=headers,json=body).status_code==409
