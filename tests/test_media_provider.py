import json
import httpx
import pytest
from app.provider import GeminiProvider, ProviderError

def test_audio_files_protocol_and_cleanup():
    events=[]
    def handler(request):
        events.append((request.method,str(request.url)))
        path=request.url.path
        if path=='/upload/v1beta/files':
            assert request.headers['x-goog-api-key']=='test-secret'
            assert request.headers['X-Goog-Upload-Protocol']=='resumable'
            return httpx.Response(200,headers={'x-goog-upload-url':'https://generativelanguage.googleapis.com/upload-final'})
        if path=='/upload-final':
            assert request.content==b'audio'
            return httpx.Response(200,json={'file':{'name':'files/test-audio','state':'ACTIVE','uri':'https://generativelanguage.googleapis.com/v1beta/files/test-audio'}})
        if path.endswith(':generateContent'):
            body=json.loads(request.content)
            assert body['contents'][0]['parts'][1]['fileData']['mimeType']=='audio/wav'
            return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps({'text':'Speaker 1: Haan, kal bhej dunga.'})}]}}]})
        if request.method=='DELETE':return httpx.Response(200,json={})
        raise AssertionError(path)
    provider=GeminiProvider('test-secret','test-model',httpx.MockTransport(handler))
    assert 'Haan' in provider.transcribe(b'audio','audio/wav')
    assert events[-1][0]=='DELETE'

def test_audio_generation_failure_still_deletes_file():
    deletes=[]
    def handler(request):
        if request.url.path=='/upload/v1beta/files':return httpx.Response(200,headers={'x-goog-upload-url':'https://generativelanguage.googleapis.com/final'})
        if request.url.path=='/final':return httpx.Response(200,json={'file':{'name':'files/audio','state':'ACTIVE','uri':'uri'}})
        if request.method=='DELETE':deletes.append(True);return httpx.Response(200)
        return httpx.Response(429)
    with pytest.raises(ProviderError):GeminiProvider('secret','model',httpx.MockTransport(handler)).transcribe(b'audio','audio/wav')
    assert deletes==[True]
