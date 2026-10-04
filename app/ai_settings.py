"""Non-secret task defaults and immutable ingestion snapshots."""
import os
import re
from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from .models import AISettings

TASKS = ('transcription', 'translation', 'summary', 'extraction', 'answer')
FILE_TASKS = TASKS[:-1]
KEYS = {'gemini':'GEMINI_API_KEY', 'openai':'OPENAI_API_KEY', 'sarvam':'SARVAM_API_KEY'}

class ModelChoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Literal['gemini', 'openai', 'sarvam']
    model: str = Field(min_length=1, max_length=100, pattern=r'^[a-zA-Z0-9._:\-]+$')

class ProcessingOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    models: dict[str, ModelChoice] = Field(default_factory=dict, max_length=4)
    languages: list[Literal['en','hi','mr']] = Field(default_factory=list, max_length=3)

class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=0)
    defaults: dict[str, ModelChoice]


def catalog():
    # Only adapter-compatible models are offered. Account access still needs live verification.
    gemini = list(dict.fromkeys(filter(None, [os.getenv('GENERATION_MODEL') or 'gemini-3.8-flash',
        *[os.getenv(f'{task.upper()}_MODEL') for task in TASKS if (os.getenv(f'{task.upper()}_PROVIDER') or 'gemini')=='gemini'],
        *os.getenv('GEMINI_MODELS','').split(',')])))
    gemini = [m.strip() for m in gemini if re.fullmatch(r'[a-zA-Z0-9._-]+',m.strip())]
    rows=[]
    def add(provider,model,tasks,note):
        rows.append({'provider':provider,'model':model,'tasks':list(tasks),
            'available':bool(os.getenv(KEYS[provider])), 'key_variable':KEYS[provider], 'note':note})
    for model in gemini:add('gemini',model,TASKS,'Original-language audio and structured text. Verify language quality with your recordings.')
    for model in ['gpt-4.1-mini','gpt-4.1']:
        add('openai',model,TASKS[1:],'Structured text: translation, summaries, extraction, and answers.')
    for model in ['gpt-4o-transcribe','gpt-4o-mini-transcribe']:
        add('openai',model,['transcription'],'Multilingual audio transcription; speaker names are not inferred. OGG/FLAC uploads are not supported by this adapter.')
    for model in ['saaras:v3','saaras:v4']:
        add('sarvam',model,['transcription'],'Batch transcription with speaker labels. English, Hindi, Marathi and mixed speech; up to 2 hours, subject to the app’s 25 MB limit.')
    return rows


def defaults_for(session):
    defaults={task:{'provider':'gemini','model':os.getenv(f'{task.upper()}_MODEL') or (os.getenv('GENERATION_MODEL') or 'gemini-3.8-flash')} for task in TASKS}
    for task in TASKS:defaults[task]['provider']=(os.getenv(f'{task.upper()}_PROVIDER') or 'gemini')
    row=session.get(AISettings,'defaults')
    if row:defaults.update(row.defaults)
    return defaults, row.version if row else 0


def validate_choices(choices,allowed=TASKS):
    if set(choices)-set(allowed):raise HTTPException(422,'Unsupported processing task')
    known={(m['provider'],m['model']):m for m in catalog()}
    for task,choice in choices.items():
        if isinstance(choice,ModelChoice):choice=choice.model_dump()
        model=known.get((choice['provider'],choice['model']))
        if not model or task not in model['tasks']:raise HTTPException(422,f'Model is not supported for {task}')
        if not model['available']:raise HTTPException(422,f"Configure {model['key_variable']} on both API and worker before selecting {choice['provider']}")


def snapshot(session,options=None,input_type='text'):
    options=options or ProcessingOptions()
    validate_choices(options.models,FILE_TASKS)
    defaults,version=defaults_for(session)
    tasks=FILE_TASKS if input_type=='audio' else FILE_TASKS[1:]
    if input_type!='audio' and 'transcription' in options.models:
        raise HTTPException(422,'Transcription settings apply only to audio')
    models={task:defaults[task] for task in tasks}
    models.update({k:v.model_dump() for k,v in options.models.items()})
    validate_choices(models,tasks)
    return {'version':1,'defaults_version':version,'models':models,'languages':sorted(set(options.languages)),
        'selected_at':datetime.now(timezone.utc).isoformat()}


def router_for(authorize,db):
    router=APIRouter(prefix='/api/ai-settings',dependencies=[Depends(authorize)])
    @router.get('')
    def get_settings(session=Depends(db)):
        defaults,version=defaults_for(session)
        return {'defaults':defaults,'version':version,'catalog':catalog(),
            'embedding':{'provider':'gemini','model':os.getenv('EMBEDDING_MODEL'),'managed_by':'environment'}}
    @router.put('')
    def put_settings(payload:SettingsUpdate,session=Depends(db)):
        if set(payload.defaults)!=set(TASKS):raise HTTPException(422,'Provide a default for every task')
        values={k:v.model_dump() for k,v in payload.defaults.items()}
        validate_choices(values)
        try:
            if payload.expected_version==0:
                session.add(AISettings(id='defaults',defaults=values,version=1))
                session.flush()
            else:
                changed=session.execute(update(AISettings).where(AISettings.id=='defaults',AISettings.version==payload.expected_version).values(defaults=values,version=payload.expected_version+1))
                if changed.rowcount!=1:raise HTTPException(409,'Settings changed; reload before saving')
            session.commit()
        except IntegrityError:
            session.rollback();raise HTTPException(409,'Settings changed; reload before saving')
        return get_settings(session)
    return router
