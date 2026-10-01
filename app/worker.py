import argparse
import signal
from threading import Event
from datetime import timedelta
from sqlalchemy import select, update, delete
from .database import make_engine, session_factory
from .models import Entry, Job, Knowledge, ProcessedEntry, Asset, now
from .documents import parse_document, DocumentError
from pathlib import Path
from datetime import datetime
from .extraction import Extraction, validate_evidence, PROMPT_VERSION
from .provider import GeminiProvider, ProviderError
from pydantic import ValidationError
import httpx

def safe_error(error):
    if isinstance(error, DocumentError):
        return str(error)
    if isinstance(error, ProviderError):
        return error.code
    if isinstance(error, httpx.TimeoutException):
        return "gemini_timeout"
    if isinstance(error, httpx.RequestError):
        return "gemini_connection_failed"
    if isinstance(error, ValidationError):
        return "output_schema_invalid"
    if isinstance(error, ValueError) and str(error) == "Unsupported evidence":
        return "source_quote_mismatch"
    if isinstance(error, ValueError) and str(error) == "Due date requires event time":
        return "event_date_required"
    return "processing_failed"

def process_one(sessions, provider):
    # Conditional update provides a single claimant even with concurrent pollers.
    with sessions() as db:
        job = db.scalar(select(Job).join(Entry, Entry.id == Job.entry_id).where(Job.status == "queued").order_by(Entry.uploaded_at, Job.id).limit(1))
        if not job:
            return False
        job_id = job.id
        claimed = db.execute(update(Job).where(Job.id == job_id, Job.status == "queued").values(status="processing", attempts=Job.attempts + 1, claimed_at=now()))
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
        db.commit()
    try:
        if not source and input_type in {"audio","document"}:
            with sessions() as db:
                asset=db.get(Asset,entry_id)
                if asset is None:raise DocumentError("source_file_missing")
                content,mime,filename=asset.content,asset.mime_type,asset.filename
            source=provider.transcribe(content,mime) if input_type=="audio" else parse_document(content,Path(filename).suffix.lower())
            if not source.strip() or len(source)>200000:raise DocumentError("transcript_empty_or_too_large")
            # Checkpoint parsing/transcription before extraction; retries reuse it.
            with sessions() as db:
                current=db.get(Job,job_id)
                if current.status!="processing" or current.attempts!=claim_attempt:return True
                db.get(Entry,entry_id).original_text=source
                current.stage="normalize"
                db.commit()
        result = Extraction.model_validate(provider.extract(source, theme, event_at))
        validate_evidence(result, source, event_at)
        with sessions() as db:
            job = db.get(Job, job_id)
            # Recovery may have released the claim; a stale worker must not publish.
            if job.status != "processing" or job.claimed_at is None or job.attempts != claim_attempt:
                return True
            db.execute(delete(Knowledge).where(Knowledge.entry_id == entry_id))
            db.execute(delete(ProcessedEntry).where(ProcessedEntry.entry_id == entry_id))
            db.add(ProcessedEntry(entry_id=entry_id, english_text=result.english_text, summary=result.summary, suggested_theme=result.suggested_theme, prompt_version=PROMPT_VERSION))
            for item in result.items:
                start = source.index(item.evidence)
                db.add(Knowledge(entry_id=entry_id, kind=item.kind, text=item.text, evidence=item.evidence, evidence_start=start, evidence_end=start+len(item.evidence), theme_id=item.theme_id or theme, certainty=item.certainty, owner=item.owner, due_date=item.due_date, date_basis=item.date_basis))
            db.get(Entry, entry_id).status = "ready"
            job.status, job.error, job.claimed_at = "completed", None, None
            db.commit()
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
    # Only use after confirming old workers are stopped; provider timeout is 120 seconds.
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
            run_forever(sessions, GeminiProvider(), stop, args.poll_seconds)
        else:
            if not process_one(sessions, GeminiProvider()):
                print("No queued job available", flush=True)
    finally:
        engine.dispose()

if __name__ == "__main__":
    main()
