import argparse
import signal
from threading import Event
from datetime import timedelta
from sqlalchemy import select, update, delete, or_
from .database import make_engine, session_factory
from .models import Entry, Job, Knowledge, ProcessedEntry, Asset, now
from .documents import parse_document, DocumentError
from pathlib import Path
from datetime import datetime
from .extraction import Extraction, validate_evidence, PROMPT_VERSION
from .provider import ProviderError
from pydantic import ValidationError
from .task_providers import provider_for, PendingTranscription
from .pipeline import process_tasks
from .ai_settings import snapshot
import httpx

def safe_error(error):
    if isinstance(error, DocumentError):
        return str(error)
    if isinstance(error, ProviderError):
        return error.code
    if isinstance(error, httpx.TimeoutException):
        return "provider_timeout"
    if isinstance(error, httpx.RequestError):
        return "provider_connection_failed"
    if isinstance(error, ValidationError):
        return "output_schema_invalid"
    if isinstance(error, ValueError) and str(error) == "Unsupported evidence":
        return "source_quote_mismatch"
    if isinstance(error, ValueError) and str(error) == "Due date requires event time":
        return "event_date_required"
    return "processing_failed"

class StaleClaim(Exception):
    pass

def process_one(sessions, provider=None):
    from .tenancy import across_workspaces
    return across_workspaces(_process_one,sessions,provider)

def _process_one(sessions, provider=None):
    # Conditional update provides a single claimant even with concurrent pollers.
    with sessions() as db:
        job = db.scalar(select(Job).join(Entry, Entry.id == Job.entry_id).where(Job.status == "queued", or_(Job.next_attempt_at.is_(None), Job.next_attempt_at <= now())).order_by(Entry.uploaded_at, Job.id).limit(1))
        if not job:
            return False
        job_id = job.id
        claimed = db.execute(update(Job).where(Job.id == job_id, Job.status == "queued", or_(Job.next_attempt_at.is_(None), Job.next_attempt_at <= now())).values(status="processing", attempts=Job.attempts + 1, claimed_at=now()).execution_options(synchronize_session="fetch"))
        if claimed.rowcount != 1:
            db.rollback()
            return False
        entry = db.get(Entry, job.entry_id)
        entry.status = "processing"
        source, theme, event_at, entry_id = entry.original_text, entry.theme_id, entry.event_at, entry.id
        if entry.event_local:
            event_at = datetime.fromisoformat(entry.event_local)
        input_type = entry.input_type
        claim_attempt = job.attempts
        config=entry.processing_config
        outputs=dict(entry.processing_outputs or {})
        db.commit()
    def stage(name):
        with sessions() as db:
            current=db.get(Job,job_id)
            if current.status!='processing' or current.attempts!=claim_attempt:raise StaleClaim()
            current.stage=name;db.commit()

    def checkpoint(name,value):
        with sessions() as db:
            current=db.get(Job,job_id)
            if current.status!='processing' or current.attempts!=claim_attempt:raise StaleClaim()
            row=db.get(Entry,entry_id)
            saved=dict(row.processing_outputs or {});saved[name]=value
            row.processing_outputs=saved
            if name=='transcription':row.original_text=value['text']
            db.commit()
        outputs[name]=value

    try:
        if provider is None and config is None:
            with sessions() as db:
                current=db.get(Job,job_id)
                if current.status!='processing' or current.attempts!=claim_attempt:raise StaleClaim()
                config=snapshot(db,input_type=input_type)
                db.get(Entry,entry_id).processing_config=config
                db.commit()
        if not source and input_type in {"audio","document"}:
            with sessions() as db:
                asset=db.get(Asset,entry_id)
                if asset is None:raise DocumentError("source_file_missing")
                content,mime,filename=asset.content,asset.mime_type,asset.filename
            stage('transcription' if input_type=='audio' else 'parse')
            if input_type=='audio':
                if provider is not None:source=provider.transcribe(content,mime)
                else:
                    source=provider_for(config['models']['transcription']).transcribe(content,mime,
                        languages=config.get('languages',[]),state=outputs.get('_sarvam'),
                        checkpoint=lambda state:checkpoint('_sarvam',state))
                checkpoint('transcription',{'text':source})
            else:source=parse_document(content,Path(filename).suffix.lower())
            if not source.strip() or len(source)>200000:raise DocumentError("transcript_empty_or_too_large")
            # Checkpoint parsing/transcription before extraction; retries reuse it.
            with sessions() as db:
                current=db.get(Job,job_id)
                if current.status!="processing" or current.attempts!=claim_attempt:return True
                db.get(Entry,entry_id).original_text=source
                current.stage="normalize"
                db.commit()
        if provider is not None:
            result = Extraction.model_validate(provider.extract(source, theme, event_at))
        else:
            result = process_tasks(source,theme,event_at,config,outputs,stage,checkpoint)
        validate_evidence(result, source, event_at)
        with sessions() as db:
            job = db.get(Job, job_id)
            # Recovery may have released the claim; a stale worker must not publish.
            if job.status != "processing" or job.claimed_at is None or job.attempts != claim_attempt:
                return True
            db.execute(delete(Knowledge).where(Knowledge.entry_id == entry_id))
            db.execute(delete(ProcessedEntry).where(ProcessedEntry.entry_id == entry_id))
            db.add(ProcessedEntry(entry_id=entry_id, english_text=result.english_text, summary=result.summary, suggested_theme=result.suggested_theme, prompt_version=PROMPT_VERSION if provider is not None else "task-pipeline-v1"))
            for item in result.items:
                start = source.index(item.evidence)
                db.add(Knowledge(entry_id=entry_id, kind=item.kind, text=item.text, evidence=item.evidence, evidence_start=start, evidence_end=start+len(item.evidence), theme_id=item.theme_id or theme, certainty=item.certainty, owner=item.owner, due_date=item.due_date, date_basis=item.date_basis))
            db.get(Entry, entry_id).status = "ready"
            job.next_attempt_at=None
            job.status, job.error, job.claimed_at = "completed", None, None
            db.commit()
    except StaleClaim:
        return True
    except PendingTranscription:
        with sessions() as db:
            current=db.get(Job,job_id)
            if current.status=='processing' and current.attempts==claim_attempt:
                current.status='queued';current.claimed_at=None;current.next_attempt_at=now()+timedelta(seconds=10)
                db.get(Entry,entry_id).status='queued';db.commit()
    except Exception as error:
        code = safe_error(error)
        print(f"Processing failed: {code}", flush=True)
        with sessions() as db:
            job = db.get(Job, job_id)
            if job.status == "processing" and job.attempts == claim_attempt:
                job.status, job.error, job.claimed_at = "failed", code, None
                db.get(Entry, entry_id).status = "failed"
                db.commit()
    return True

def recover(sessions):
    from .tenancy import across_workspaces
    return across_workspaces(_recover,sessions)

def _recover(sessions):
    # Only use after confirming old workers are stopped; release claims older than 15 minutes.
    with sessions() as db:
        for job in db.scalars(select(Job).where(Job.status == "processing", Job.claimed_at < now()-timedelta(minutes=15))):
            job.status, job.claimed_at = "queued", None
            db.get(Entry, job.entry_id).status = "queued"
        db.commit()

def run_forever(sessions, provider, stop, poll_seconds=5):
    if poll_seconds < 1 or poll_seconds > 60:
        raise ValueError("Poll interval must be between 1 and 60 seconds")
    print("Worker started; checking durable queue", flush=True)
    while not stop.is_set():
        try:
            processed = process_one(sessions, provider)
            from .memory_worker import process_memory_one
            processed = process_memory_one(sessions) or processed
            import os
            if os.environ.get("EMBEDDING_MODEL"):
                from .semantic import index_one, GeminiEmbeddings
                processed = index_one(sessions, GeminiEmbeddings()) or processed
        except Exception:
            # Database failures must not leak connection URLs or transcript content.
            print("Worker unavailable: database_or_processing_error", flush=True)
            processed = False
        if not processed:
            stop.wait(poll_seconds)
    print("Worker stopped", flush=True)

def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--recover", action="store_true")
    mode.add_argument("--loop", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=5, choices=range(1, 61))
    args = parser.parse_args()
    engine = make_engine()
    sessions = session_factory(engine)
    try:
        if args.recover:
            recover(sessions)
        elif args.loop:
            stop = Event()
            for signum in (signal.SIGTERM, signal.SIGINT):
                signal.signal(signum, lambda *_: stop.set())
            run_forever(sessions, None, stop, args.poll_seconds)
        else:
            if not process_one(sessions):
                print("No queued job available", flush=True)
    finally:
        engine.dispose()

if __name__ == "__main__":
    main()
