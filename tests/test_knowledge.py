from test_api import client, headers
from test_processing import Fake, save
from app.database import session_factory
from app.worker import process_one

def setup_items(client,headers):
    entry_id=save(client,headers)
    process_one(session_factory(client.app.state.engine),Fake())
    return client.get(f'/api/entries/{entry_id}/knowledge',headers=headers).json()['items']

def test_correction_history_and_conflict(client,headers):
    item=setup_items(client,headers)[0]
    url=f"/api/knowledge/{item['id']}"
    payload={'expected_version':1,'reason':'Confirmed during follow-up','text':'UAT confirmed Thursday','certainty':'explicit'}
    result=client.patch(url,json=payload,headers=headers)
    assert result.status_code==200
    assert result.json()['origin']=='user_corrected'
    assert result.json()['version']==2
    assert result.json()['evidence']==item['evidence']
    assert client.patch(url,json=payload,headers=headers).status_code==409
    history=client.get(url+'/history',headers=headers).json()
    assert history[0]['before']['text']==item['text']
    assert history[0]['after']['text']=='UAT confirmed Thursday'

def test_actions_completion(client,headers):
    items=setup_items(client,headers)
    action=next(x for x in items if x['kind']=='action')
    assert len(client.get('/api/actions?theme_id=office',headers=headers).json())==1
    assert client.get('/api/actions?theme_id=personal',headers=headers).json()==[]
    response=client.patch('/api/knowledge/'+action['id'],json={'expected_version':1,'reason':'Sent document','status':'completed'},headers=headers)
    assert response.status_code==200
    assert client.get('/api/actions',headers=headers).json()==[]
    assert len(client.get('/api/actions?status=completed',headers=headers).json())==1
    decision=next(x for x in items if x['kind']=='decision')
    assert client.patch('/api/knowledge/'+decision['id'],json={'expected_version':1,'reason':'test','status':'completed'},headers=headers).status_code==422

def test_search_scope_and_dismissal(client,headers):
    items=setup_items(client,headers)
    result=client.get('/api/search?q=UAT&theme_id=office',headers=headers).json()
    assert result['scope']=='office' and len(result['results'])==1
    assert result['results'][0]['source_url'].startswith('/api/entries/')
    assert client.get('/api/search?q=UAT&theme_id=personal',headers=headers).json()['results']==[]
    item=items[0]
    client.patch('/api/knowledge/'+item['id'],json={'expected_version':1,'reason':'Not useful','status':'dismissed'},headers=headers)
    assert client.get('/api/search?q=UAT',headers=headers).json()['results']==[]
    assert client.get('/api/search?q=%',headers=headers).json()['results']==[]

def test_knowledge_auth_and_validation(client,headers):
    for url in ['/api/actions','/api/search?q=UAT','/api/knowledge/missing/history']:
        assert client.get(url).status_code==401
    assert client.patch('/api/knowledge/missing',json={'expected_version':1,'reason':'test','text':'edit'}).status_code==401
    items=setup_items(client,headers)
    url='/api/knowledge/'+items[0]['id']
    for fields in [{'text':None},{'text':' '},{'status':None},{}]:
        assert client.patch(url,json={'expected_version':1,'reason':'test',**fields},headers=headers).status_code==422
