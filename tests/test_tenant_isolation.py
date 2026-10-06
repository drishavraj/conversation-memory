"""Two-account attacks against real routes, storage and worker execution."""
import pytest
from sqlalchemy import select, update, delete, text
from sqlalchemy.orm import Session as AdminSession
from fastapi.testclient import TestClient
from app.main import create_app
from app.models import Workspace,WorkspaceMembership,Entry,Job,Knowledge,SearchRecord,WorkspaceAISettings,LEGACY_WORKSPACE_ID
from app.memory_models import Project,MemoryRecord
from app.tenancy import workspace_sessions
from app.database import session_factory
from app.worker import process_one
from app.semantic import index_one,semantic_records
from test_semantic import Embeddings
from test_api import client, TOKEN
from test_processing import Fake,SOURCE

B='22222222-2222-4222-8222-222222222222'
USER_B='33333333-3333-4333-8333-333333333333'
A=LEGACY_WORKSPACE_ID

@pytest.fixture
def pair(client,monkeypatch):
    monkeypatch.setenv('MEMORIES_ENABLED','true')
    with AdminSession(client.app.state.engine) as db:
        db.add(Workspace(id=B,name='Second',status='active'));db.flush()
        db.add(WorkspaceMembership(workspace_id=B,user_id=USER_B,role='owner',status='active'));db.commit()
    class Auth:
        configured=True;url='https://example.supabase.co';key='public';owner='11111111-1111-4111-8111-111111111111'
        def verify(self,token):
            from fastapi import HTTPException
            if token not in ('a','b','outsider'):raise HTTPException(401)
            return {'sub':{'a':self.owner,'b':USER_B,'outsider':'outsider'}[token]}
    monkeypatch.setattr('app.main.BrowserAuth',Auth)
    app=create_app(str(client.app.state.engine.url),TOKEN)
    with TestClient(app) as web:yield web,client.app.state.engine

def h(w):return {'Authorization':'Bearer '+w}

def ingest(web,w,text=SOURCE):
    r=web.post('/api/entries/text',headers=h(w),json={'text':text,'theme_id':'office'})
    assert r.status_code==201,r.text
    return r.json()['id']

def project(web,w):
    r=web.post('/api/memories/projects',headers=h(w),json={'name':'Same project','theme_id':'office'})
    assert r.status_code==201,r.text
    return r.json()['id']

def test_identical_content_names_and_id_attacks(pair):
    web,engine=pair
    ea,eb=ingest(web,'a'),ingest(web,'b');assert ea!=eb
    pa,pb=project(web,'a'),project(web,'b');assert pa!=pb
    assert [e['id'] for e in web.get('/api/entries',headers=h('a')).json()]==[ea]
    for suffix in ('','/knowledge','/file'):
        assert web.get('/api/entries/'+ea+suffix,headers=h('b')).status_code==404
    for suffix in ('/retry','/index/retry'):
        assert web.post('/api/entries/'+ea+suffix,headers=h('b')).status_code==404
    assert web.get('/api/memories/projects/'+pa,headers=h('b')).status_code==404
    assert web.post(f'/api/memories/projects/{pb}/entries',headers=h('b'),json={'entry_id':ea,'topic_ids':[]}).status_code==404
    assert web.post('/api/memories/chats',headers=h('b'),json={'project_id':pa}).status_code==404
    assert web.get('/api/entries',headers=h('outsider')).status_code==403
    # A forged body scope is never used to select an authorised workspace.
    r=web.post('/api/entries/text',headers=h('a'),json={'text':'Forged scope','workspace_id':B})
    if r.status_code==201:
        assert web.get('/api/entries/'+r.json()['id'],headers=h('b')).status_code==404


def test_files_chats_settings_and_revocation(pair):
    web,engine=pair
    r=web.post('/api/entries/upload',headers=h('a'),files={'file':('private.txt',b'private document','text/plain')})
    assert r.status_code==201,r.text
    id=r.json()['id']
    assert web.get(f'/api/entries/{id}/file',headers=h('a')).content==b'private document'
    assert web.get(f'/api/entries/{id}/file',headers=h('b')).status_code==404
    pa=project(web,'a')
    thread=web.post('/api/memories/chats',headers=h('a'),json={'project_id':pa}).json()['id']
    assert web.get('/api/memories/chats/'+thread,headers=h('b')).status_code==404
    assert web.get('/api/memories/chats',headers=h('b')).json()['items']==[]
    assert web.patch('/api/memories/chats/'+thread,headers=h('b'),json={'title':'Hijack','expected_version':0}).status_code==404
    import uuid
    payload={'question':'Show private memories','expected_version':0,'request_id':str(uuid.uuid4())}
    assert web.post(f'/api/memories/chats/{thread}/turns',headers=h('b'),json=payload).status_code==404
    stream=web.post(f'/api/memories/chats/{thread}/turns/stream',headers=h('b'),json=payload)
    assert '404' in stream.text and 'event: result' not in stream.text
    with workspace_sessions(engine,A)() as db:
        db.add(WorkspaceAISettings(workspace_id=A,defaults={'answer':{'provider':'gemini','model':'private-model'}},version=1));db.commit()
    assert web.get('/api/ai-settings',headers=h('a')).json()['defaults']['answer']['model']=='private-model'
    assert web.get('/api/ai-settings',headers=h('b')).json()['defaults']['answer']['model']!='private-model'
    with AdminSession(engine) as db:
        db.get(WorkspaceMembership,(B,USER_B)).status='revoked';db.commit()
    assert web.get('/api/session',headers=h('b')).status_code==403


def test_workers_and_semantic_candidates_are_scoped(pair):
    web,engine=pair
    ea,eb=ingest(web,'a'),ingest(web,'b')
    assert process_one(session_factory(engine),Fake())
    for wid,eid in [(A,ea),(B,eb)]:
        with workspace_sessions(engine,wid)() as db:
            assert db.get(Entry,eid).status=='ready'
            assert {r.entry_id for r in db.scalars(select(Knowledge))}=={eid}
        for _ in range(5):index_one(workspace_sessions(engine,wid),Embeddings())
        with workspace_sessions(engine,wid)() as db:
            results=semantic_records(db,'Any question',None,Embeddings())
            assert results and {r['source_entry_id'] for r in results}=={eid}
    action=web.get('/api/actions',headers=h('a')).json()[0]['id']
    assert web.patch('/api/knowledge/'+action,headers=h('b'),json={'expected_version':1,'reason':'attack','status':'completed'}).status_code==404


def test_session_bulk_operations_missing_context_and_json_references(pair):
    web,engine=pair
    ea,eb=ingest(web,'a'),ingest(web,'b');pa,pb=project(web,'a'),project(web,'b')
    with workspace_sessions(engine,A)() as db:
        assert db.get(Entry,eb) is None
        assert db.execute(update(Entry).where(Entry.id==eb).values(title='attack')).rowcount==0
        assert db.execute(delete(Job).where(Job.entry_id==eb)).rowcount==0
        db.commit()
        with pytest.raises(RuntimeError):db.execute(text('SELECT * FROM entries'))
        with pytest.raises(RuntimeError):db.execute(update(Entry).values(workspace_id=B))
    with workspace_sessions(engine,A)() as db:
        db.add(Entry(title='wrong',original_text='wrong',workspace_id=B))
        with pytest.raises(RuntimeError):db.commit()
    with workspace_sessions(engine,A)() as db:
        db.add(MemoryRecord(project_id=pa,kind='memory',text='attack',certainty='explicit',evidence=[{'id':'fake','source_entry_id':eb}]))
        with pytest.raises(ValueError):db.commit()
    with pytest.raises(Exception):
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO entries (id,title,original_text,status,uploaded_at,index_status,input_type) VALUES ('missing-scope','x','x','queued',CURRENT_TIMESTAMP,'pending','text')"))
    with workspace_sessions(engine,B)() as db:assert db.get(Entry,eb).title!='attack'


def test_memory_worker_candidates_and_transaction_revocation(pair):
    web,engine=pair
    from app.memory_worker import process_memory_one
    from test_memories import Proposer
    ea,eb=ingest(web,'a'),ingest(web,'b')
    pa,pb=project(web,'a'),project(web,'b')
    process_one(session_factory(engine),Fake())
    for who,p,e in [('a',pa,ea),('b',pb,eb)]:
        r=web.post(f'/api/memories/projects/{p}/entries',headers=h(who),json={'entry_id':e,'topic_ids':[]})
        assert r.status_code in (200,201),r.text
    provider=Proposer()
    assert process_memory_one(session_factory(engine),provider)
    for who,p,e in [('a',pa,ea),('b',pb,eb)]:
        data=web.get('/api/memories/projects/'+p,headers=h(who)).json()
        assert data['proposals']
        assert all(ev['source_entry_id']==e for proposal in data['proposals'] for ev in proposal['evidence'])
    with workspace_sessions(engine,B,USER_B)() as scoped:
        assert scoped.get(Entry,eb)
        scoped.commit()
        with AdminSession(engine) as admin:
            admin.get(WorkspaceMembership,(B,USER_B)).status='revoked';admin.commit()
        with pytest.raises(PermissionError):scoped.get(Entry,eb,populate_existing=True)
