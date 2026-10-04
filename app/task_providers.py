"""Task adapters; provider credentials never enter stored processing selections."""
import copy
import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse
import httpx
from .provider import GeminiProvider, ProviderError

class PendingTranscription(Exception):
    pass


def checked(response,provider):
    if not 200 <= response.status_code < 300:
        raise ProviderError(f'{provider}_http_{response.status_code}')
    return response


def strict_schema(schema):
    value=copy.deepcopy(schema)
    def visit(node):
        if isinstance(node,dict):
            node.pop('default',None)
            if node.get('type')=='object':
                node['additionalProperties']=False
                node['required']=list(node.get('properties',{}))
            for child in node.values():visit(child)
        elif isinstance(node,list):
            for child in node:visit(child)
    visit(value)
    return value

class OpenAIProvider:
    def __init__(self,model,key=None,transport=None):
        self.model=model
        self.key=key or os.getenv('OPENAI_API_KEY')
        self.transport=transport
        if not self.key:raise ProviderError('openai_key_missing')

    def generate(self,schema,system,content):
        payload={'model':self.model,'store':False,'instructions':system,
            'input':json.dumps(content,ensure_ascii=False),
            'text':{'format':{'type':'json_schema','name':schema.__name__, 'strict':True,
                'schema':strict_schema(schema.model_json_schema())}}}
        with httpx.Client(timeout=180,transport=self.transport) as client:
            data=checked(client.post('https://api.openai.com/v1/responses',headers={'Authorization':'Bearer '+self.key},json=payload),'openai').json()
        if data.get('status')!='completed':raise ProviderError('openai_incomplete_output')
        output=[]
        for item in data.get('output',[]):
            if item.get('type')!='message':continue
            for part in item.get('content',[]):
                if part.get('type')=='refusal':raise ProviderError('openai_refused')
                if part.get('type')=='output_text':output.append(part.get('text',''))
        return schema.model_validate_json(''.join(output))

    def transcribe(self,content,mime_type,languages=None,**kwargs):
        suffix={'audio/mpeg':'mp3','audio/mp4':'m4a','audio/wav':'wav','audio/webm':'webm'}.get(mime_type)
        if not suffix:raise ProviderError('openai_audio_format_unsupported')
        if len(content)>25_000_000:raise ProviderError('openai_audio_too_large')
        fields={'model':self.model,'response_format':'json'}
        languages=languages or []
        if len(languages)==1:fields['language']=languages[0]
        if languages:fields['prompt']='The recording may contain '+', '.join({'en':'English','hi':'Hindi','mr':'Marathi'}[x] for x in languages)+'. Preserve the spoken languages.'
        with httpx.Client(timeout=180,transport=self.transport) as client:
            data=checked(client.post('https://api.openai.com/v1/audio/transcriptions',headers={'Authorization':'Bearer '+self.key},data=fields,files={'file':('recording.'+suffix,content,mime_type)}),'openai').json()
        text=data.get('text')
        if not isinstance(text,str) or not text.strip() or len(text)>200000:raise ProviderError('openai_transcript_invalid')
        return text

class SarvamProvider:
    base='https://api.sarvam.ai/speech-to-text/job/v1'
    def __init__(self,model,key=None,transport=None):
        self.model=model;self.key=key or os.getenv('SARVAM_API_KEY');self.transport=transport
        if not self.key:raise ProviderError('sarvam_key_missing')

    @staticmethod
    def storage_url(url):
        parsed=urlparse(url)
        host=parsed.hostname or ''
        valid=host.endswith('.blob.core.windows.net') or host=='storage.googleapis.com' or host.endswith('.storage.googleapis.com')
        if parsed.scheme!='https' or not valid or parsed.username or parsed.password or parsed.port not in (None,443):
            raise ProviderError('sarvam_storage_url_invalid')
        return url

    def transcribe(self,content,mime_type,languages=None,state=None,checkpoint=None):
        state=dict(state or {});languages=languages or []
        checkpoint=checkpoint or (lambda value:None)
        def save():checkpoint(dict(state))
        suffix={'audio/mpeg':'mp3','audio/mp4':'m4a','audio/wav':'wav','audio/ogg':'ogg','audio/flac':'flac','audio/webm':'webm'}.get(mime_type)
        if not suffix:raise ProviderError('sarvam_audio_format_unsupported')
        filename='recording.'+suffix
        with httpx.Client(timeout=120,transport=self.transport,follow_redirects=False) as client:
            def request(method,path,**kwargs):
                return checked(client.request(method,self.base+path,headers={'api-subscription-key':self.key},**kwargs),'sarvam').json()
            if not state.get('job_id'):
                params={'model':self.model,'mode':'codemix' if len(languages)>1 else 'transcribe','with_diarization':True}
                if len(languages)==1:params['language_code']={'en':'en-IN','hi':'hi-IN','mr':'mr-IN'}[languages[0]]
                result=request('POST','',json={'job_parameters':params})
                state={'job_id':result['job_id'],'created_at':datetime.now(timezone.utc).isoformat()}
                save()
            job_id=state['job_id']
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,150}',job_id):raise ProviderError('sarvam_job_id_invalid')
            if (datetime.now(timezone.utc)-datetime.fromisoformat(state['created_at'])).total_seconds()>86400:
                raise ProviderError('sarvam_job_expired')
            status=request('GET','/'+job_id+'/status')
            if status.get('job_state')=='Failed':raise ProviderError('sarvam_batch_failed')
            if status.get('job_state')=='Accepted':
                if not state.get('uploaded'):
                    links=request('POST','/upload-files',json={'job_id':job_id,'files':[filename]})
                    url=self.storage_url(links['upload_urls'][filename]['file_url'])
                    headers={'Content-Type':mime_type}
                    if '.blob.core.windows.net' in (urlparse(url).hostname or ''):headers['x-ms-blob-type']='BlockBlob'
                    # Never forward provider credentials to signed storage URLs.
                    checked(client.put(url,content=content,headers=headers),'sarvam_upload')
                    state['uploaded']=True;save()
                request('POST','/'+job_id+'/start',json={})
                raise PendingTranscription()
            if status.get('job_state') in {'Pending','Running'}:raise PendingTranscription()
            if status.get('job_state')!='Completed':raise ProviderError('sarvam_batch_state_invalid')
            if status.get('failed_files_count',0):raise ProviderError('sarvam_batch_failed')
            files=[o['file_name'] for detail in status.get('job_details',[]) for o in detail.get('outputs',[])]
            if len(files)!=1:raise ProviderError('sarvam_output_invalid')
            links=request('POST','/download-files',json={'job_id':job_id,'files':files})
            url=self.storage_url(links['download_urls'][files[0]]['file_url'])
            with client.stream('GET',url) as response:
                checked(response,'sarvam_download');raw=bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>4*1024*1024:raise ProviderError('sarvam_output_too_large')
            data=json.loads(raw)
            segments=(data.get('diarized_transcript') or {}).get('entries') or []
            text='\n'.join('Speaker '+str(x.get('speaker_id','unknown'))+': '+x['transcript'] for x in segments) if segments else data.get('transcript')
            if not isinstance(text,str) or not text.strip() or len(text)>200000:raise ProviderError('sarvam_transcript_invalid')
            return text


def provider_for(choice):
    if choice['provider']=='gemini':
        if not os.getenv('GEMINI_API_KEY'):raise ProviderError('gemini_key_missing')
        return GeminiProvider(model=choice['model'])
    if choice['provider']=='openai':return OpenAIProvider(choice['model'])
    if choice['provider']=='sarvam':return SarvamProvider(choice['model'])
    raise ProviderError('provider_unsupported')
