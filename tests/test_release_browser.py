"""Opt-in browser check against real HTTP routes, migrations and storage.
External identity and generation are deterministic doubles; no live credentials needed.
Run: RUN_RELEASE_BROWSER=1 python -m pytest tests/test_release_browser.py -q
"""
import os
import json
import base64
import socket
import subprocess
import threading
import time
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session
import uvicorn
from app.main import create_app
from app.models import Entry, Knowledge
from app.memory_models import Project, Topic, ProjectEntry, MemoryRecord
from app.memories import evidence_for

@pytest.mark.skipif(os.getenv('RUN_RELEASE_BROWSER')!='1',reason='Opt-in browser/HTTP release integration')
def test_browser_against_real_chat_api(tmp_path,monkeypatch):
    def encode(x):return base64.urlsafe_b64encode(json.dumps(x).encode()).decode().rstrip('=')
    token=encode({'alg':'ES256','typ':'JWT'})+'.'+encode({'sub':'11111111-1111-4111-8111-111111111111','aud':'authenticated','role':'authenticated','aal':'aal2','iss':'https://example.supabase.co/auth/v1','exp':int(time.time())+3600,'iat':int(time.time()),'amr':[{'method':'password'},{'method':'totp'}]})+'.test-signature'
    url=f'sqlite:///{tmp_path}/release.db'
    for k,v in {'DATABASE_URL':url,'OWNER_API_TOKEN':token,'ALLOW_OWNER_API_TOKEN':'true','SUPABASE_URL':'https://example.supabase.co','SUPABASE_PUBLISHABLE_KEY':'sb_publishable_test','AUTH_OWNER_USER_ID':'11111111-1111-4111-8111-111111111111','MEMORIES_ENABLED':'true','APP_ENV':'development','GEMINI_API_KEY':'test-only','GENERATION_MODEL':'test-model'}.items():monkeypatch.setenv(k,v)
    monkeypatch.delenv('REDIS_URL',raising=False)
    command.upgrade(Config('alembic.ini'),'head')
    contexts=[]
    class Provider:
        def generate(self,schema,prompt,context):
            contexts.append(context)
            return {'claims':[{'text':context['records'][0]['text'],'source_ids':[context['records'][0]['id']]}]}
    app=create_app(url,token,answer_provider=Provider())
    with Session(app.state.engine) as db:
        p=Project(name='Release pilot',name_key='release pilot',theme_id='office',description='Synthetic release check');db.add(p);db.flush()
        t=Topic(name='MVP',name_key='mvp',project_id=p.id);db.add(t);db.flush()
        e=Entry(title='Release meeting',original_text='We agreed a managed pilot.',theme_id='office',status='ready');db.add(e);db.flush()
        k=Knowledge(entry_id=e.id,text=e.original_text,kind='decision',theme_id='office',certainty='explicit',evidence=e.original_text,evidence_start=0,evidence_end=len(e.original_text));db.add(k);db.flush()
        db.add(ProjectEntry(project_id=p.id,entry_id=e.id,topic_ids=[t.id],status='completed',model={'provider':'gemini','model':'test-model'}))
        db.add(MemoryRecord(project_id=p.id,kind='decision',text=e.original_text,certainty='explicit',topic_ids=[t.id],evidence=[evidence_for(k,e)]));db.commit()
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error'))
    task=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);task.start()
    try:
        for _ in range(100):
            if server.started:break
            time.sleep(.05)
        assert server.started
        result=subprocess.run(['node','frontend/tests/release-integration.cjs'],env={**os.environ,'UI_BASE_URL':f'http://127.0.0.1:{port}','RELEASE_TEST_TOKEN':token},capture_output=True,text=True,timeout=90)
        assert result.returncode==0,result.stdout+result.stderr
        assert len(contexts)==2
        assert contexts[0]['conversation']['recent']==[]
        assert len(contexts[1]['conversation']['recent'])==1
    finally:
        server.should_exit=True;task.join(timeout=10);sock.close()
