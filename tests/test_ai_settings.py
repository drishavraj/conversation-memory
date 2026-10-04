import json
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import select
from test_api import client, headers
from app.database import session_factory
from app.models import Entry, Job, now
from app.provider import ProviderError
from app.worker import process_one
from app.pipeline import Translation, KnowledgeExtraction
from app.task_providers import OpenAIProvider, SarvamProvider, PendingTranscription, strict_schema


def settings(client, headers):
    return client.get('/api/ai-settings', headers=headers).json()


def test_settings_auth_versions_and_capabilities(client, headers, monkeypatch):
    assert client.get('/api/ai-settings').status_code == 401
    data = settings(client, headers)
    assert data['version'] == 0 and 'test-secret' not in json.dumps(data)
    defaults = data['defaults']
    defaults['summary'] = {'provider': 'openai', 'model': 'gpt-4.1-mini'}
    payload = {'defaults': defaults, 'expected_version': 0}
    assert client.put('/api/ai-settings', json=payload, headers=headers).status_code == 422
    monkeypatch.setenv('OPENAI_API_KEY', 'secret-openai')
    saved = client.put('/api/ai-settings', json=payload, headers=headers)
    assert saved.status_code == 200 and saved.json()['version'] == 1
    assert 'secret-openai' not in saved.text
    assert client.put('/api/ai-settings', json=payload, headers=headers).status_code == 409
    defaults['summary'] = {'provider': 'openai', 'model': 'gpt-4o-transcribe'}
    payload['expected_version'] = 1
    assert client.put('/api/ai-settings', json=payload, headers=headers).status_code == 422
    monkeypatch.setenv('SUMMARY_MODEL', 'custom-gemini')
    assert any(x['model'] == 'custom-gemini' for x in settings(client, headers)['catalog'])


def test_upload_frozen_choices_and_duplicate(client, headers, monkeypatch):
    monkeypatch.setenv('SARVAM_API_KEY', 'secret')
    processing = {'models': {'transcription': {'provider': 'sarvam', 'model': 'saaras:v3'}}, 'languages': ['en', 'hi', 'mr']}
    wav = b'RIFF0000WAVE' + b'0' * 64
    def upload(options):
        return client.post('/api/entries/upload', files={'file': ('meeting.wav', wav, 'audio/wav')}, data={'theme_id': 'office', 'processing': json.dumps(options)}, headers=headers)
    response = upload(processing)
    assert response.status_code == 201
    entry_id = response.json()['id']
    processing['models']['transcription']['model'] = 'saaras:v4'
    duplicate = upload(processing).json()
    assert duplicate['duplicate'] and duplicate['id'] == entry_id
    frozen = client.get('/api/entries/' + entry_id, headers=headers).json()['processing_config']
    assert frozen['models']['transcription']['model'] == 'saaras:v3'
    assert frozen['languages'] == ['en', 'hi', 'mr']
    assert client.post('/api/entries/text', headers=headers, json={'text': 'new', 'processing': processing}).status_code == 422
    monkeypatch.setenv('OPENAI_API_KEY', 'secret')
    processing['models']['transcription'] = {'provider': 'openai', 'model': 'gpt-4o-transcribe'}
    assert client.post('/api/entries/upload', files={'file': ('meeting.ogg', b'OggS00000', 'audio/ogg')}, data={'processing': json.dumps(processing)}, headers=headers).status_code == 422


def test_pipeline_retry_keeps_completed_tasks_and_models(client, headers, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-openai')
    source = 'Rishav: I will send the checklist.'
    entry_id = client.post('/api/entries/text', headers=headers, json={'text': source, 'theme_id': 'office', 'processing': {'models': {'summary': {'provider': 'openai', 'model': 'gpt-4.1-mini'}}}}).json()['id']
    calls = []
    fail = [True]
    class Provider:
        def __init__(self, choice): self.choice = choice
        def generate(self, schema, prompt, content):
            calls.append((schema.__name__, self.choice['model']))
            assert content['source'] == source
            if schema.__name__ == 'Translation': return {'english_text': source}
            if schema.__name__ == 'Summary':
                if fail[0]: raise ProviderError('synthetic_failure')
                return {'summary': 'Rishav will send the checklist.'}
            return {'suggested_theme': 'office', 'items': [{'kind': 'action', 'text': 'Send checklist', 'evidence': 'I will send the checklist.', 'certainty': 'explicit', 'owner': 'Rishav'}]}
    monkeypatch.setattr('app.pipeline.provider_for', Provider)
    sessions = session_factory(client.app.state.engine)
    assert process_one(sessions)
    entry = client.get('/api/entries/' + entry_id, headers=headers).json()
    assert entry['status'] == 'failed' and entry['completed_stages'] == ['translation']
    assert entry['job']['stage'] == 'summary'
    monkeypatch.setenv('GENERATION_MODEL', 'new-model')
    fail[0] = False
    assert client.post('/api/entries/' + entry_id + '/retry', headers=headers).status_code == 200
    assert process_one(sessions)
    assert calls == [('Translation', 'test-model'), ('Summary', 'gpt-4.1-mini'), ('Summary', 'gpt-4.1-mini'), ('KnowledgeExtraction', 'test-model')]
    entry = client.get('/api/entries/' + entry_id, headers=headers).json()
    assert entry['status'] == 'ready'
    assert set(entry['completed_stages']) == {'translation', 'summary', 'extraction'}
    assert client.get('/api/entries/' + entry_id + '/knowledge', headers=headers).json()['items'][0]['evidence'] in source


def test_batch_pending_releases_worker_and_preserves_job(client, headers, monkeypatch):
    wav = b'RIFF0000WAVE' + b'0' * 32
    entry_id = client.post('/api/entries/upload', headers=headers, files={'file': ('a.wav', wav)}).json()['id']
    class Pending:
        def transcribe(self, content, mime, **kwargs):
            assert kwargs['state'] in (None, {'job_id': 'existing'})
            kwargs['checkpoint']({'job_id': 'existing'})
            raise PendingTranscription()
    monkeypatch.setattr('app.worker.provider_for', lambda _: Pending())
    sessions = session_factory(client.app.state.engine)
    assert process_one(sessions)
    assert not process_one(sessions)
    with sessions() as db:
        entry = db.get(Entry, entry_id)
        assert entry.processing_outputs['_sarvam']['job_id'] == 'existing'
        job = db.scalar(select(Job).where(Job.entry_id == entry_id))
        assert job.status == 'queued' and job.claimed_at is None
        job.next_attempt_at = now() - timedelta(seconds=1)
        db.commit()
    assert process_one(sessions)


def test_openai_structured_contract_and_errors():
    schema = strict_schema(KnowledgeExtraction.model_json_schema())
    item = schema['$defs']['EvidenceItem']
    assert set(item['required']) == set(item['properties'])
    assert item['additionalProperties'] is False
    assert 'default' not in item['properties']['owner']
    def handler(request):
        assert request.headers['authorization'] == 'Bearer private-key'
        body = json.loads(request.content)
        assert body['store'] is False and body['text']['format']['strict'] is True
        return httpx.Response(200, json={'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"english_text":"Hello"}'}]}]})
    provider = OpenAIProvider('gpt-4.1-mini', 'private-key', httpx.MockTransport(handler))
    assert provider.generate(Translation, 'translate', {'source': 'Hello'}).english_text == 'Hello'
    provider.transport = httpx.MockTransport(lambda r: httpx.Response(401, text='private-key'))
    with pytest.raises(ProviderError) as error: provider.generate(Translation, '', {})
    assert error.value.code == 'openai_http_401' and 'private-key' not in str(error.value)


def test_openai_audio_language_contract():
    def handler(request):
        assert request.url.path == '/v1/audio/transcriptions'
        assert b'name="language"\r\n\r\nmr' in request.content
        assert b'Marathi' in request.content and b'filename="recording.wav"' in request.content
        return httpx.Response(200, json={'text': 'नमस्कार'})
    provider = OpenAIProvider('gpt-4o-transcribe', 'secret', httpx.MockTransport(handler))
    assert provider.transcribe(b'RIFF', 'audio/wav', ['mr']) == 'नमस्कार'


def test_sarvam_batch_resumes_and_storage_has_no_credentials():
    state = {}
    completed = [False]
    creates = []
    def checkpoint(value): state.update(value)
    def handler(request):
        path = request.url.path
        if request.url.host == 'example.blob.core.windows.net':
            assert 'api-subscription-key' not in request.headers
            assert 'authorization' not in request.headers
            if request.method == 'PUT': return httpx.Response(201)
            return httpx.Response(200, json={'diarized_transcript': {'entries': [{'speaker_id': 0, 'transcript': 'नमस्कार hello'}]}})
        assert request.headers['api-subscription-key'] == 'secret'
        if path.endswith('/v1'):
            creates.append(1)
            assert json.loads(request.content)['job_parameters']['mode'] == 'codemix'
            return httpx.Response(202, json={'job_id': 'job_123'})
        if path.endswith('/status'):
            return httpx.Response(200, json={'job_state': 'Completed' if completed[0] else 'Accepted', 'job_details': [{'outputs': [{'file_name': '0.json'}]}]})
        if path.endswith('/upload-files'): return httpx.Response(200, json={'upload_urls': {'recording.wav': {'file_url': 'https://example.blob.core.windows.net/upload?sig=secret'}}})
        if path.endswith('/start'): return httpx.Response(202, json={})
        if path.endswith('/download-files'): return httpx.Response(200, json={'download_urls': {'0.json': {'file_url': 'https://example.blob.core.windows.net/result?sig=secret'}}})
        raise AssertionError(path)
    provider = SarvamProvider('saaras:v4', 'secret', httpx.MockTransport(handler))
    with pytest.raises(PendingTranscription): provider.transcribe(b'audio', 'audio/wav', ['en', 'hi', 'mr'], state, checkpoint)
    assert state['uploaded'] and state['job_id'] == 'job_123'
    completed[0] = True
    assert provider.transcribe(b'audio', 'audio/wav', ['en', 'hi', 'mr'], state, checkpoint) == 'Speaker 0: नमस्कार hello'
    assert len(creates) == 1
    for url in ['http://example.blob.core.windows.net/a', 'https://evil.test/a', 'https://example.blob.core.windows.net.evil.test/a', 'https://user:password@example.blob.core.windows.net/a']:
        with pytest.raises(ProviderError): provider.storage_url(url)


def test_explicit_retry_restarts_terminal_sarvam_job(client, headers):
    entry_id = client.post('/api/entries/text', headers=headers, json={'text': 'Failed job test'}).json()['id']
    sessions = session_factory(client.app.state.engine)
    with sessions() as db:
        entry = db.get(Entry, entry_id)
        entry.status = 'failed'
        entry.processing_outputs = {'_sarvam': {'job_id': 'failed'}, 'translation': {'english_text': 'Saved'}}
        job = db.scalar(select(Job).where(Job.entry_id == entry_id))
        job.status, job.error = 'failed', 'sarvam_batch_failed'
        db.commit()
    assert client.post('/api/entries/' + entry_id + '/retry', headers=headers).status_code == 200
    with sessions() as db:
        assert db.get(Entry, entry_id).processing_outputs == {'translation': {'english_text': 'Saved'}}


def test_split_pipeline_rejects_invented_evidence(client, headers, monkeypatch):
    entry_id = client.post('/api/entries/text', headers=headers, json={'text': 'Original source'}).json()['id']
    class Provider:
        def generate(self, schema, prompt, content):
            if schema.__name__ == 'Translation': return {'english_text': 'Original source'}
            if schema.__name__ == 'Summary': return {'summary': 'A note'}
            return {'suggested_theme': None, 'items': [{'kind': 'action', 'text': 'Invented', 'evidence': 'Not in source', 'certainty': 'explicit'}]}
    monkeypatch.setattr('app.pipeline.provider_for', lambda _: Provider())
    process_one(session_factory(client.app.state.engine))
    result = client.get('/api/entries/' + entry_id, headers=headers).json()
    assert result['job']['error'] == 'source_quote_mismatch'
    assert 'extraction' not in result['completed_stages']
    assert client.get('/api/entries/' + entry_id + '/knowledge', headers=headers).json()['items'] == []
