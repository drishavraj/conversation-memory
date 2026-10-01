import argparse
from datetime import timedelta
from sqlalchemy import select, update, delete
from .database import make_engine, session_factory
from .models import Entry, Job, Knowledge, ProcessedEntry, now
from .extraction import Extraction, validate_evidence, PROMPT_VERSION
from .provider import GeminiProvider, ProviderError
from pydantic import ValidationError
import httpx

def safe_error(error):
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
        job = db.scalar(select(Job).where(Job.status == "queued").order_by(Job.id).limit(1))
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
        claim_attempt = job.attempts
        db.commit()
    try:
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
                db.add(Knowledge(entry_id=entry_id, kind=item.kind, text=item.text, evidence=item.evidence, evidence_start=start, evidence_end=start+len(item.evidence), theme_id=item.theme_id or theme, certainty=item.certainty, owner=item.owner, due_date=item.due_date))
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

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    sessions = session_factory(make_engine())
    if args.recover:
        recover(sessions)
    else:
        process_one(sessions, GeminiProvider())

if __name__ == "__main__":
    main()
