import json
import httpx
import pytest
from sqlalchemy import select
from test_api import client, headers
from test_knowledge import setup_items
from app.database import session_factory
from app.models import SearchRecord, Entry
from app.semantic import index_one, semantic_records, normalize, DIMENSIONS, GeminiEmbeddings
from app.provider import ProviderError

VECTOR=[1.0]+[0.0]*(DIMENSIONS-1)
class Embeddings:
    model='synthetic-embedding'
    def embed(self,text):return VECTOR

def build(client,headers):
    items=setup_items(client,headers)
    sessions=session_factory(client.app.state.engine)
    provider=Embeddings()
    for _ in range(10):
        if not index_one(sessions,provider):break
    return items,sessions,provider

def test_semantic_without_word_overlap_and_theme(client,headers):
    items,sessions,provider=build(client,headers)
    with sessions() as db:
        # Synthetic vectors model semantic equivalence; no shared keywords required.
        result=semantic_records(db,'What did I promise?', 'office',provider)
        assert any(r['kind']=='action' for r in result)
        assert all(r['theme_id']=='office' for r in result)
        # Source entry deliberately Personal, so no Office transcript chunks leak across scope.
        assert not any(r['kind']=='transcript' for r in result)
        personal=semantic_records(db,'What did I promise?','personal',provider)
        assert personal==[]
        all_results=semantic_records(db,'Anything',None,provider)
        chunk=next(r for r in all_results if r['kind']=='transcript')
        source=db.get(Entry,chunk['source_entry_id']).original_text
        assert source[chunk['evidence_start']:chunk['evidence_end']]==chunk['evidence']

def test_correction_invalidates_old_vectors(client,headers):
    items,sessions,provider=build(client,headers)
    item=items[0]
    client.patch('/api/knowledge/'+item['id'],json={'expected_version':1,'reason':'Updated','text':'Certification Friday'},headers=headers)
    with sessions() as db:
        assert not any(r['id']==item['id'] for r in semantic_records(db,'Anything',None,provider))
    for _ in range(10):
        if not index_one(sessions,provider):break
    with sessions() as db:
        result=semantic_records(db,'Anything',None,provider)
        assert next(r for r in result if r['id']==item['id'])['text']=='Certification Friday'

def test_index_failure_does_not_break_processed_entry(client,headers):
    items=setup_items(client,headers);sessions=session_factory(client.app.state.engine)
    class Bad(Embeddings):
        def embed(self,text):raise ProviderError('embedding_http_404')
    index_one(sessions,Bad())
    detail=client.get('/api/entries/'+items[0]['source_entry_id'],headers=headers).json()
    assert detail['status']=='ready' and detail['index_status']=='failed'
    assert detail['index_error']=='embedding_http_404'
    assert client.post('/api/entries/'+items[0]['source_entry_id']+'/index/retry',headers=headers).status_code==200

def test_embedding_protocol_and_validation():
    def handler(request):
        assert request.headers['x-goog-api-key']=='secret'
        assert json.loads(request.content)['outputDimensionality']==768
        return httpx.Response(200,json={'embedding':{'values':VECTOR}})
    assert GeminiEmbeddings('secret','model',httpx.MockTransport(handler)).embed('question')==VECTOR
    for vector in [[],[1],[float('nan')]*768,[0]*768]:
        with pytest.raises(ProviderError):normalize(vector)

def test_chat_hybrid_and_fallback(client,headers,monkeypatch):
    items,sessions,provider=build(client,headers)
    monkeypatch.setenv('EMBEDDING_MODEL','synthetic-embedding')
    monkeypatch.setattr('app.semantic.GeminiEmbeddings',lambda:provider)
    response=client.post('/api/search/semantic',headers=headers,json={'question':'Launch blockers','theme_id':'office'})
    assert response.status_code==200 and response.json()['retrieval']=='hybrid'
    assert len(response.json()['results'])>0
    assert client.post('/api/search/semantic',json={'question':'Launch'}).status_code==401

def test_hybrid_chat_cites_semantic_record(client,headers,monkeypatch):
    items,sessions,provider=build(client,headers)
    monkeypatch.setenv('EMBEDDING_MODEL','synthetic-embedding')
    monkeypatch.setattr('app.semantic.GeminiEmbeddings',lambda:provider)
    class Answer:
        def generate(self,schema,system,content):
            row=content['records'][0]
            return {'claims':[{'text':row['text'],'source_ids':[row['id']]}]}
    monkeypatch.setattr('app.chat.GeminiProvider',lambda:Answer())
    result=client.post('/api/chat',headers=headers,json={'question':'Launch blockers','theme_id':'office'}).json()
    assert result['status']=='answered' and result['retrieval']=='hybrid'
    assert result['claims'][0]['source_ids'][0]==result['sources'][0]['id']

def test_embedding_failure_fallback_is_explicit(client,headers,monkeypatch):
    build(client,headers)
    class Bad:
        def __init__(self):raise ProviderError('embedding_http_404')
    monkeypatch.setenv('EMBEDDING_MODEL','bad')
    monkeypatch.setattr('app.semantic.GeminiEmbeddings',Bad)
    result=client.post('/api/search/semantic',headers=headers,json={'question':'UAT','theme_id':'office'}).json()
    assert result['retrieval']=='keyword' and result['warning']=='embedding_http_404'
    assert client.post('/api/search/semantic',headers=headers,json={'question':'Elephants','theme_id':'office'}).status_code==503
