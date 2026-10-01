import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field, field_validator
from .models import Asset, Entry, Job
from .fingerprint import fingerprint

AUDIO={'.mp3':'audio/mpeg','.m4a':'audio/mp4','.wav':'audio/wav','.ogg':'audio/ogg','.flac':'audio/flac','.webm':'audio/webm'}
DOCUMENT={'.txt':'text/plain','.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}

class Metadata(BaseModel):
    title: str = Field(min_length=1,max_length=200)
    theme_id: Literal['personal','side-projects','office'] | None=None
    event_at: datetime | None=None
    @field_validator('event_at')
    @classmethod
    def timezone_required(cls,v):
        if v is not None and v.utcoffset() is None:raise ValueError('event_at needs timezone')
        return v

def sniff(data,suffix):
    valid={'.wav':data[:4]==b'RIFF' and data[8:12]==b'WAVE', '.mp3':data[:3]==b'ID3' or (len(data)>1 and data[0]==255 and data[1]&224==224), '.m4a':data[4:8]==b'ftyp', '.ogg':data[:4]==b'OggS', '.flac':data[:4]==b'fLaC', '.webm':data[:4]==b'\x1aE\xdf\xa3', '.pdf':data[:5]==b'%PDF-', '.docx':data[:2]==b'PK', '.txt':True}
    return valid.get(suffix,False)

def router_for(authorize,db):
    router=APIRouter(prefix='/api',dependencies=[Depends(authorize)])
    @router.post('/entries/upload',status_code=201)
    async def upload(file: UploadFile=File(...),title: str | None=Form(None),theme_id: str | None=Form(None),event_at: str | None=Form(None),session=Depends(db)):
        filename=Path((file.filename or 'upload').replace('\\','/')).name[:200]
        suffix=Path(filename).suffix.lower()
        if suffix not in AUDIO and suffix not in DOCUMENT:
            raise HTTPException(415,'Supported: MP3, M4A, WAV, OGG, FLAC, WebM, TXT, DOCX, text-based PDF')
        try:
            metadata=Metadata(title=title or filename,theme_id=theme_id or None,event_at=event_at or None)
        except Exception:
            raise HTTPException(422,'Invalid title, theme or event time; include timezone')
        limit=(25 if suffix in AUDIO else 10)*1024*1024
        content=bytearray()
        while chunk:=await file.read(1024*1024):
            if len(content)+len(chunk)>limit:
                raise HTTPException(413,f'File exceeds {limit//1024//1024} MiB limit')
            content.extend(chunk)
        if not content:raise HTTPException(422,'File is empty')
        if not sniff(content,suffix):raise HTTPException(422,'File content does not match extension')
        content=bytes(content)
        digest=hashlib.sha256(content).hexdigest()
        key=fingerprint('file:'+suffix+':'+digest,metadata.theme_id,metadata.event_at)
        existing=session.scalar(select(Entry).where(Entry.fingerprint==key))
        if existing:
            return JSONResponse(status_code=200,content={'id':existing.id,'status':existing.status,'duplicate':True})
        entry=Entry(title=metadata.title,original_text='',input_type='audio' if suffix in AUDIO else 'document',event_at=metadata.event_at,event_local=metadata.event_at.isoformat() if metadata.event_at else None,theme_id=metadata.theme_id,fingerprint=key)
        try:
            session.add(entry);session.flush()
            session.add(Asset(entry_id=entry.id,filename=filename,mime_type=(AUDIO|DOCUMENT)[suffix],content=content,sha256=digest))
            session.add(Job(entry_id=entry.id,stage='transcribe' if suffix in AUDIO else 'parse'))
            session.commit()
        except IntegrityError:
            session.rollback()
            existing=session.scalar(select(Entry).where(Entry.fingerprint==key))
            if existing:return JSONResponse(status_code=200,content={'id':existing.id,'status':existing.status,'duplicate':True})
            raise
        return {'id':entry.id,'title':entry.title,'input_type':entry.input_type,'status':entry.status,'duplicate':False}

    @router.get('/entries/{entry_id}/file')
    def original_file(entry_id: str, session=Depends(db)):
        asset=session.get(Asset,entry_id)
        if not asset:raise HTTPException(404,'Original file not found')
        # Avoid injecting user-supplied names into headers.
        return Response(asset.content,media_type=asset.mime_type,headers={'Content-Disposition':'attachment','X-Content-Type-Options':'nosniff'})
    return router
