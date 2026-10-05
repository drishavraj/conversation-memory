import pytest
from alembic.config import Config
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.main import create_app
from app.models import Job

TOKEN = 'test-owner-token-that-is-long-enough'

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.delenv('REDIS_URL', raising=False)
    monkeypatch.setenv('GEMINI_API_KEY','test-secret')
    monkeypatch.setenv('GENERATION_MODEL','test-model')
    url = f'sqlite:///{tmp_path}/test.db'
    monkeypatch.setenv('DATABASE_URL', url)
    cfg = Config('alembic.ini')
    command.upgrade(cfg, 'head')
    app = create_app(url, TOKEN)
    with TestClient(app) as client:
        yield client

@pytest.fixture
def headers():
    return {'Authorization': f'Bearer {TOKEN}'}

def test_auth(client):
    assert client.get('/api/entries').status_code == 401
    assert client.post('/api/entries/text', json={'text':'secret'}).status_code == 401
    assert client.get('/api/themes', headers={'Authorization':'Bearer wrong'}).status_code == 401

def test_themes(client, headers):
    assert {x['id'] for x in client.get('/api/themes', headers=headers).json()} == {'personal','side-projects','office'}

def test_ingestion_and_job(client, headers):
    payload = {'text':'Haan credentials Friday tak aayenge.', 'title':'Test call','theme_id':'office','event_at':'2026-10-01T12:00:00+05:30'}
    result = client.post('/api/entries/text', json=payload, headers=headers)
    assert result.status_code == 201
    entry = result.json()
    assert entry['original_text'] == payload['text']
    detail = client.get('/api/entries/'+entry['id'], headers=headers).json()
    assert detail['job']['status'] == 'queued'
    with Session(client.app.state.engine) as db:
        assert db.scalar(select(Job).where(Job.entry_id == entry['id'])) is not None

def test_scope(client, headers):
    for theme in ['office','personal']:
        client.post('/api/entries/text', json={'text':theme,'theme_id':theme}, headers=headers)
    result = client.get('/api/entries?theme_id=office',headers=headers).json()
    assert len(result) == 1 and result[0]['theme_id'] == 'office'

def test_validation(client, headers):
    for payload in [{'text':'  '}, {'text':'ok','theme_id':'invalid'}, {'text':'ok','event_at':'2026-10-01T12:00:00'}]:
        assert client.post('/api/entries/text',json=payload,headers=headers).status_code == 422
    assert client.get('/api/entries?limit=1000',headers=headers).status_code == 422

def test_review_and_missing(client, headers):
    result = client.post('/api/entries/text', json={'text':'Unclassified note'},headers=headers).json()
    assert result['classification_status'] == 'needs_review'
    assert client.get('/api/entries/nonexistent',headers=headers).status_code == 404
    assert client.get('/health').status_code == 200


def test_conversation_search_respects_theme_and_literal_text(client, headers):
    for title, text, theme in [('Planning', 'Checklist for Monday', 'office'), ('Private checklist', 'Home note', 'personal'), ('Budget', '100% complete', 'office')]:
        assert client.post('/api/entries/text', headers=headers, json={'title': title, 'text': text, 'theme_id': theme}).status_code == 201
    result = client.get('/api/entries', headers=headers, params={'q': 'CHECKLIST', 'theme_id': 'office'}).json()
    assert len(result) == 1 and result[0]['title'] == 'Planning'
    result = client.get('/api/entries', headers=headers, params={'q': '%'}).json()
    assert len(result) == 1 and result[0]['title'] == 'Budget'
    assert client.get('/api/entries', headers=headers, params={'q': 'missing'}).json() == []
    assert client.get('/api/entries', headers=headers, params={'q': 'x' * 201}).status_code == 422
