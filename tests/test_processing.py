import json
import httpx
from sqlalchemy import select
from app.database import session_factory
from app.models import Job
from app.worker import process_one
from app.provider import GeminiProvider
from test_api import client, headers

SOURCE = 'Rahul: Credentials Friday tak aayenge. Maybe Wednesday UAT. Rishav: I will send the API document.'
RESULT = {'english_text':'Rahul: Credentials are expected Friday. Maybe Wednesday for UAT. Rishav: I will send the API document.', 'summary':'Credentials expected; UAT tentative; API document promised.', 'suggested_theme':'office','items':[{'kind':'decision','text':'UAT tentatively Wednesday','evidence':'Maybe Wednesday UAT.','theme_id':'office','certainty':'tentative','owner':None,'due_date':None},{'kind':'action','text':'Send API document','evidence':'Rishav: I will send the API document.','theme_id':'office','certainty':'explicit','owner':'Rishav','due_date':None}]}

class Fake:
    def __init__(self,result=RESULT): self.result=result; self.calls=0
    def extract(self,*args): self.calls+=1; return self.result

def save(client,headers):
    return client.post('/api/entries/text',headers=headers,json={'text':SOURCE,'theme_id':'personal'}).json()['id']

def test_worker_success(client,headers):
    entry_id=save(client,headers)
    sessions=session_factory(client.app.state.engine)
    provider=Fake()
    assert process_one(sessions,provider)
    assert not process_one(sessions,provider)
    assert provider.calls==1
    data=client.get(f'/api/entries/{entry_id}/knowledge',headers=headers).json()
    assert data['items'][0]['certainty']=='tentative'
    for item in data['items']:
        assert SOURCE[item['evidence_start']:item['evidence_end']]==item['evidence']
    entry=client.get(f'/api/entries/{entry_id}',headers=headers).json()
    assert entry['theme_id']=='personal' and entry['status']=='ready'
    assert data['items'][0]['theme_id']=='office'
    assert client.post(f'/api/entries/{entry_id}/retry',headers=headers).status_code==409

def test_unsupported_evidence_fails_atomically(client,headers):
    entry_id=save(client,headers)
    result=json.loads(json.dumps(RESULT));result['items'][0]['evidence']='Invented sentence'
    process_one(session_factory(client.app.state.engine),Fake(result))
    assert client.get(f'/api/entries/{entry_id}',headers=headers).json()['status']=='failed'
    assert client.get(f'/api/entries/{entry_id}/knowledge',headers=headers).json()['items']==[]
    assert client.post(f'/api/entries/{entry_id}/retry',headers=headers).status_code==200
    process_one(session_factory(client.app.state.engine),Fake())
    assert client.get(f'/api/entries/{entry_id}',headers=headers).json()['status']=='ready'

def test_unanchored_due_date_rejected(client,headers):
    entry_id=save(client,headers)
    result=json.loads(json.dumps(RESULT));result['items'][1]['due_date']='2026-10-02';result['items'][1]['date_basis']='relative'
    process_one(session_factory(client.app.state.engine),Fake(result))
    assert client.get(f'/api/entries/{entry_id}',headers=headers).json()['status']=='failed'

def test_provider_failure_is_redacted(client,headers):
    entry_id=save(client,headers)
    class Bad:
        def extract(self,*args): raise RuntimeError('SECRET API KEY')
    sessions=session_factory(client.app.state.engine)
    process_one(sessions,Bad())
    with sessions() as db:
        error=db.scalar(select(Job).where(Job.entry_id==entry_id)).error
        assert 'SECRET' not in error

def test_provider_contract():
    def handler(request):
        assert request.headers['x-goog-api-key']=='test-secret'
        assert 'key=' not in str(request.url)
        body=json.loads(request.content)
        assert 'responseJsonSchema' in body['generationConfig']
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(RESULT)}]}}]})
    provider=GeminiProvider('test-secret','test-model',httpx.MockTransport(handler))
    assert provider.extract(SOURCE,'office',None).items[0].certainty=='tentative'
