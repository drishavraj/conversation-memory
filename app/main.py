import os
import secrets
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .browser_auth import BrowserAuth
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from .fingerprint import fingerprint
from redis import Redis
from .database import make_engine, session_factory
from .models import Entry, Job, Theme, ProcessedEntry, Knowledge

class TextInput(BaseModel):
    text: str = Field(min_length=1, max_length=200000)
    title: str = Field(default="Untitled entry", min_length=1, max_length=200)
    theme_id: Literal["personal", "side-projects", "office"] | None = None
    event_at: datetime | None = None

    @field_validator("text", "title")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Must not be blank")
        return value

    @field_validator("event_at")
    @classmethod
    def timezone_required(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("Include timezone offset in event_at")
        return value

def create_app(database_url=None, owner_token=None, answer_provider=None, embedding_provider=None):
    token = owner_token or os.environ.get("OWNER_API_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("Set OWNER_API_TOKEN to at least 32 characters")
    engine = make_engine(database_url)
    sessions = session_factory(engine)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title="Conversation Memory", lifespan=lifespan)
    app.state.engine = engine
    security = HTTPBearer(auto_error=False)
    browser_auth = BrowserAuth()
    legacy_enabled = os.environ.get("ALLOW_OWNER_API_TOKEN", "false" if browser_auth.configured else "true").lower() == "true"

    @app.middleware("http")
    async def browser_headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api/") or request.url.path == "/":
            response.headers["Cache-Control"] = "no-store"
        if request.url.path == "/":
            origin = browser_auth.url if browser_auth.configured else ""
            response.headers["Content-Security-Policy"] = f"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self' {origin}; media-src 'self' blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        return response

    def authorize(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        if credentials is None:
            raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
        if legacy_enabled and secrets.compare_digest(credentials.credentials, token):
            return
        return browser_auth.verify(credentials.credentials)

    @app.get("/api/ui-config")
    def ui_config():
        return {"configured": browser_auth.configured, "supabase_url": browser_auth.url, "supabase_publishable_key": browser_auth.key}

    @app.get("/api/session", dependencies=[Depends(authorize)])
    def browser_session():
        return {"status": "authenticated"}

    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/ui", StaticFiles(directory=static_dir), name="ui")

        @app.get("/", include_in_schema=False)
        def home():
            return FileResponse(static_dir / "index.html", headers={"Cache-Control":"no-store"})

    def db():
        with sessions() as session:
            yield session

    def entry_dict(entry):
        return {"id": entry.id, "title": entry.title, "original_text": entry.original_text, "theme_id": entry.theme_id, "classification_status": "selected" if entry.theme_id else "needs_review", "event_at": entry.event_at, "uploaded_at": entry.uploaded_at, "status": entry.status,"input_type":entry.input_type,"index_status":entry.index_status,"index_error":entry.index_error}

    @app.get("/health")
    def health():
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            if os.environ.get("REDIS_URL"):
                client = Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=3, socket_timeout=3)
                try:
                    client.ping()
                finally:
                    client.close()
            return {"status": "ok"}
        except Exception:
            raise HTTPException(503, "Service unavailable")

    @app.get("/api/themes", dependencies=[Depends(authorize)])
    def themes(session=Depends(db)):
        return [{"id": row.id, "name": row.name} for row in session.scalars(select(Theme).order_by(Theme.id))]

    @app.post("/api/entries/text", status_code=201, dependencies=[Depends(authorize)])
    def ingest(payload: TextInput, session=Depends(db)):
        digest = fingerprint(payload.text, payload.theme_id, payload.event_at)
        existing = session.scalar(select(Entry).where(Entry.fingerprint == digest))
        if existing:
            return JSONResponse(status_code=200,content=jsonable_encoder({**entry_dict(existing),"duplicate":True}))
        entry = Entry(title=payload.title, original_text=payload.text, theme_id=payload.theme_id, event_at=payload.event_at, event_local=payload.event_at.isoformat() if payload.event_at else None, fingerprint=digest)
        try:
            session.add(entry)
            session.flush()
            session.add(Job(entry_id=entry.id))
            session.commit()
        except IntegrityError:
            session.rollback()
            existing = session.scalar(select(Entry).where(Entry.fingerprint == digest))
            if existing:
                return JSONResponse(status_code=200,content=jsonable_encoder({**entry_dict(existing),"duplicate":True}))
            raise
        return {**entry_dict(entry),"duplicate":False}

    @app.get("/api/entries", dependencies=[Depends(authorize)])
    def entries(theme_id: Literal["personal", "side-projects", "office"] | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), session=Depends(db)):
        query = select(Entry).order_by(Entry.uploaded_at.desc(), Entry.id)
        if theme_id:
            query = query.where(Entry.theme_id == theme_id)
        return [entry_dict(row) for row in session.scalars(query.offset(offset).limit(limit))]

    @app.get("/api/entries/{entry_id}", dependencies=[Depends(authorize)])
    def detail(entry_id: str, session=Depends(db)):
        entry = session.get(Entry, entry_id)
        if entry is None:
            raise HTTPException(404, "Entry not found")
        job = session.scalar(select(Job).where(Job.entry_id == entry_id))
        return {**entry_dict(entry), "job": {"stage": job.stage, "status": job.status, "attempts": job.attempts, "error": job.error} if job else None}

    @app.post("/api/entries/{entry_id}/retry", dependencies=[Depends(authorize)])
    def retry(entry_id: str, session=Depends(db)):
        entry = session.get(Entry, entry_id)
        if entry is None:
            raise HTTPException(404, "Entry not found")
        job = session.scalar(select(Job).where(Job.entry_id == entry_id))
        if not job or job.status != "failed":
            raise HTTPException(409, "Only failed jobs can be retried")
        job.status, job.error = "queued", None
        entry.status = "queued"
        session.commit()
        return {"status": "queued"}

    @app.get("/api/entries/{entry_id}/knowledge", dependencies=[Depends(authorize)])
    def knowledge(entry_id: str, session=Depends(db)):
        if session.get(Entry, entry_id) is None:
            raise HTTPException(404, "Entry not found")
        result = session.get(ProcessedEntry, entry_id)
        rows = session.scalars(select(Knowledge).where(Knowledge.entry_id == entry_id)).all()
        return {"english_text":result.english_text if result else None, "summary":result.summary if result else None, "suggested_theme":result.suggested_theme if result else None, "items":[{"id":r.id,"kind":r.kind,"text":r.text,"theme_id":r.theme_id,"certainty":r.certainty,"owner":r.owner,"due_date":r.due_date,"date_basis":r.date_basis,"evidence":r.evidence,"evidence_start":r.evidence_start,"evidence_end":r.evidence_end,"source_entry_id":r.entry_id,"status":r.status,"origin":r.origin,"version":r.version} for r in rows]}

    from .knowledge_api import router_for
    app.include_router(router_for(authorize, db))
    from .chat import router_for as chat_router
    app.include_router(chat_router(authorize, db, answer_provider, embedding_provider))
    from .uploads import router_for as upload_router
    app.include_router(upload_router(authorize, db))
    return app
