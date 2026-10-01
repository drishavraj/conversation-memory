from test_api import client, headers
from test_knowledge import setup_items

class Answers:
    calls=0
    def generate(self,schema,system,content):
        self.calls+=1
        row=content['records'][0]
        return {'claims':[{'text':row['text'],'source_ids':[row['id']]}]}

def test_cited_chat_and_scope(client,headers,monkeypatch):
    setup_items(client,headers)
    provider=Answers()
    monkeypatch.setattr('app.chat.GeminiProvider',lambda:provider)
    response=client.post('/api/chat',json={'question':'What was said about UAT?','theme_id':'office'},headers=headers)
    assert response.status_code==200
    result=response.json()
    assert result['status']=='answered'
    assert result['claims'][0]['source_ids'][0]==result['sources'][0]['id']
    assert result['sources'][0]['certainty']=='tentative'
    assert client.post('/api/chat',json={'question':'UAT','theme_id':'personal'},headers=headers).json()['status']=='no_evidence'
    assert provider.calls==1

def test_unknown_citation_rejected(client,headers,monkeypatch):
    setup_items(client,headers)
    class Bad:
        def generate(self,*args):return {'claims':[{'text':'Invented','source_ids':['unknown-id']}]}
    monkeypatch.setattr('app.chat.GeminiProvider',lambda:Bad())
    assert client.post('/api/chat',json={'question':'UAT'},headers=headers).status_code==503

def test_no_evidence_no_provider_call(client,headers,monkeypatch):
    def fail():raise AssertionError('Must not call provider')
    monkeypatch.setattr('app.chat.GeminiProvider',fail)
    assert client.post('/api/chat',json={'question':'Anything about elephants?'},headers=headers).json()['status']=='no_evidence'
    assert client.post('/api/chat',json={'question':'UAT'}).status_code==401
    assert client.post('/api/chat',json={'question':'   '},headers=headers).status_code==422

def test_corrected_text_retrieved(client,headers,monkeypatch):
    item=setup_items(client,headers)[0]
    client.patch('/api/knowledge/'+item['id'],json={'expected_version':1,'reason':'Corrected','text':'Certification confirmed Thursday'},headers=headers)
    monkeypatch.setattr('app.chat.GeminiProvider',lambda:Answers())
    result=client.post('/api/chat',json={'question':'Certification'},headers=headers).json()
    assert result['sources'][0]['origin']=='user_corrected'
    assert client.post('/api/chat',json={'question':'Wednesday'},headers=headers).json()['status']=='no_evidence'
