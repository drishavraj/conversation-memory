from uuid import uuid4
from datetime import timedelta
import pytest
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models import Knowledge, now
from app.memory_models import ChatTurn, ChatThread
from test_api import client, headers
from test_memories import project, source, link, run, detail, accept

@pytest.fixture(autouse=True)
def flag(monkeypatch):monkeypatch.setenv('MEMORIES_ENABLED','true')

class Answers:
    def __init__(self):self.calls=[];self.fail=False;self.invalid=False;self.callback=None
    def generate(self,schema,prompt,context):
        self.calls.append(context)
        if self.callback:self.callback()
        if self.fail:raise RuntimeError('secret provider error')
        return {'claims':[{'text':'The pilot is agreed.','source_ids':['fake' if self.invalid else context['records'][0]['id']]}]}

@pytest.fixture
def answers(monkeypatch):
    a=Answers();monkeypatch.setattr('app.memory_chats.provider_for',lambda model:a);return a

def setup(client,headers):
    p=project(client,headers);t=client.post(f'/api/memories/projects/{p}/topics',headers=headers,json={'name':'MVP'}).json()['id']
    e,k=source(client);link(client,headers,p,e,[t]);run(client);accept(client,headers,p,detail(client,headers,p)['proposals'][0]);return p,t,k

def thread(client,headers,p,t=None):
    r=client.post('/api/memories/chats',headers=headers,json={'project_id':p,'topic_id':t});assert r.status_code==201,r.text;return r.json()

def send(client,headers,t,question='What was agreed?',version=0,rid=None):
    return client.post(f'/api/memories/chats/{t}/turns',headers=headers,json={'question':question,'expected_version':version,'request_id':rid or str(uuid4())})

def test_scope_owner_gate_and_immutable_thread(client,headers,answers,monkeypatch):
    p,topic,k=setup(client,headers);other=project(client,headers,name='Other')
    assert client.get('/api/memories/chats').status_code==401
    assert client.post('/api/memories/chats',headers=headers,json={'project_id':other,'topic_id':topic}).status_code==422
    t=thread(client,headers,p,topic)
    assert client.patch('/api/memories/chats/'+t['id'],headers=headers,json={'project_id':other,'title':'Move','expected_version':0}).status_code==422
    empty=thread(client,headers,other)
    assert send(client,headers,empty['id']).json()['turn']['response']['status']=='no_evidence'
    assert not answers.calls
    monkeypatch.setenv('MEMORIES_ENABLED','false')
    assert client.get('/api/memories/chats/'+t['id'],headers=headers).status_code==404

def test_followups_isolation_citations_and_idempotency(client,headers,answers):
    p,topic,k=setup(client,headers);t=thread(client,headers,p,topic);rid=str(uuid4())
    first=send(client,headers,t['id'],rid=rid);assert first.status_code==200,first.text
    data=first.json();assert data['turn']['status']=='completed';assert data['turn']['response']['sources']
    assert send(client,headers,t['id'],rid=rid).json()['turn']['id']==data['turn']['id'];assert len(answers.calls)==1
    assert send(client,headers,t['id'],question='different',rid=rid).status_code==409
    assert send(client,headers,t['id']).status_code==409
    assert send(client,headers,t['id'],question='And what next?',version=1).status_code==200
    assert answers.calls[-1]['conversation']['recent'][0]['question']=='What was agreed?'
    independent=thread(client,headers,p,topic);send(client,headers,independent['id'])
    assert answers.calls[-1]['conversation']['recent']==[]
    assert answers.calls[-1]['scope']['topic_id']==topic
    rows=client.get('/api/memories/chats',headers=headers,params={'q':'agreed'}).json()['items'];assert len(rows)==2
    saved=client.get('/api/memories/chats/'+t['id'],headers=headers).json();assert len(saved['turns'])==2
    assert saved['turns'][0]['response']==data['turn']['response']

def test_failure_retry_same_turn_frozen_model_and_invalid_citation(client,headers,answers,monkeypatch):
    p,topic,k=setup(client,headers);t=thread(client,headers,p,topic);answers.invalid=True
    failed=send(client,headers,t['id']).json()['turn'];assert failed['status']=='failed';assert failed['error']=='answer_generation_unavailable'
    assert 'secret' not in str(failed)
    assert send(client,headers,t['id'],version=1).status_code==409
    answers.invalid=False;models=[]
    monkeypatch.setattr('app.memory_chats.provider_for',lambda model:(models.append(model) or answers))
    retry=client.post(f'/api/memories/chats/{t["id"]}/turns/{failed["id"]}/retry',headers=headers).json()['turn']
    assert retry['id']==failed['id'];assert retry['status']=='completed';assert models==[failed['model']]
    saved=client.get('/api/memories/chats/'+t['id'],headers=headers).json();assert len(saved['turns'])==1

def test_changed_source_keeps_old_snapshot_but_excludes_stale_followup(client,headers,answers):
    p,topic,k=setup(client,headers);t=thread(client,headers,p,topic)
    old=send(client,headers,t['id']).json()['turn']['response']
    with Session(client.app.state.engine) as db:
        item=db.get(Knowledge,k);item.version+=1;db.commit()
    saved=client.get('/api/memories/chats/'+t['id'],headers=headers).json()['turns'][0]
    assert saved['response']==old;assert saved['changed_source_ids']
    follow=send(client,headers,t['id'],version=1).json()['turn'];assert follow['response']['status']=='no_evidence';assert len(answers.calls)==1

def test_source_changes_during_generation_fail_safely(client,headers,answers):
    p,topic,k=setup(client,headers);t=thread(client,headers,p,topic)
    def change():
        with Session(client.app.state.engine) as db:
            item=db.get(Knowledge,k);item.version+=1;db.commit()
    answers.callback=change
    turn=send(client,headers,t['id']).json()['turn'];assert turn['status']=='failed';assert turn['error']=='sources_changed_retry';assert turn['response'] is None

def test_lease_recovery_and_cross_thread_retry(client,headers,answers):
    p,topic,k=setup(client,headers);t=thread(client,headers,p,topic);answers.fail=True
    turn=send(client,headers,t['id']).json()['turn'];other=thread(client,headers,p,topic)
    assert client.post(f'/api/memories/chats/{other["id"]}/turns/{turn["id"]}/retry',headers=headers).status_code==404
    with Session(client.app.state.engine) as db:
        row=db.get(ChatTurn,turn['id']);row.status='running';row.updated_at=now();db.get(ChatThread,t['id']).pending_turn_id=row.id;db.commit()
    url=f'/api/memories/chats/{t["id"]}/turns/{turn["id"]}/retry'
    assert client.post(url,headers=headers).status_code==409
    with Session(client.app.state.engine) as db:
        db.get(ChatTurn,turn['id']).updated_at=now()-timedelta(minutes=16);db.commit()
    answers.fail=False;assert client.post(url,headers=headers).json()['turn']['status']=='completed'

def test_bounded_context_pagination_and_rename(client,headers,answers):
    p,topic,k=setup(client,headers);t=thread(client,headers,p,topic)
    with Session(client.app.state.engine) as db:
        for i in range(40):db.add(ChatTurn(thread_id=t['id'],request_id=str(uuid4()),sequence=i+1,question='Question '+str(i),status='completed',response={'claims':[],'sources':[]},model={},lease=str(uuid4())))
        db.get(ChatThread,t['id']).version=40;db.commit()
    result=send(client,headers,t['id'],version=40).json()['turn'];info=result['context_info']
    assert info['recent_turns']==12;assert info['earlier_excerpt_turns']==20;assert info['omitted_turns']==8
    first=client.get('/api/memories/chats/'+t['id'],headers=headers,params={'limit':10}).json();assert first['has_older'];assert first['turns'][-1]['sequence']==41
    earlier=client.get('/api/memories/chats/'+t['id'],headers=headers,params={'before':first['turns'][0]['sequence'],'limit':10}).json();assert earlier['turns'][-1]['sequence']==31
    rename=client.patch('/api/memories/chats/'+t['id'],headers=headers,json={'title':'Review preparation','expected_version':41});assert rename.status_code==200
    assert client.patch('/api/memories/chats/'+t['id'],headers=headers,json={'title':'Stale','expected_version':41}).status_code==409

def test_pending_turn_rejects_second_message_and_duplicate_is_read_only(client,headers,answers):
    p,topic,k=setup(client,headers);t=thread(client,headers,p,topic);rid=str(uuid4());seen=[]
    def concurrent():
        seen.append(send(client,headers,t['id'],rid=rid).json()['turn']['status'])
        seen.append(send(client,headers,t['id'],version=1).status_code)
    answers.callback=concurrent
    result=send(client,headers,t['id'],rid=rid)
    assert result.json()['turn']['status']=='completed';assert seen==['running',409];assert len(answers.calls)==1

def test_chat_migration_roundtrip_preserves_existing_memories(client,headers):
    from alembic import command
    from alembic.config import Config
    p,topic,k=setup(client,headers)
    cfg=Config('alembic.ini');command.downgrade(cfg,'0007');command.upgrade(cfg,'head')
    assert detail(client,headers,p)['memories']
    assert thread(client,headers,p,topic)['version']==0

def test_sibling_topic_has_no_access_to_mvp_evidence(client,headers,answers):
    p,topic,k=setup(client,headers)
    sibling=client.post(f'/api/memories/projects/{p}/topics',headers=headers,json={'name':'Demo'}).json()['id']
    t=thread(client,headers,p,sibling)
    assert send(client,headers,t['id']).json()['turn']['response']['status']=='no_evidence'
    assert answers.calls==[]

def test_obsolete_execution_cannot_overwrite_new_lease(client,headers,answers):
    p,topic,k=setup(client,headers);t=thread(client,headers,p,topic)
    def supersede():
        with Session(client.app.state.engine) as db:
            turn=db.scalar(select(ChatTurn).where(ChatTurn.thread_id==t['id']))
            turn.lease=str(uuid4());turn.status='failed';turn.error='newer_execution';db.commit()
    answers.callback=supersede
    result=send(client,headers,t['id']).json()['turn']
    assert result['error']=='newer_execution';assert result['response'] is None
