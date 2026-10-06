from datetime import datetime, timezone, date
from uuid import uuid4
from sqlalchemy import String, Text, DateTime, ForeignKey, Date, LargeBinary, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def now():
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

LEGACY_WORKSPACE_ID = "00000000-0000-4000-8000-000000000001"

class WorkspaceOwned:
    # Temporary single-owner bridge. Phase 2 removes this default once all writers
    # supply authenticated workspace context; it is not an authorization mechanism.
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspaces.id"), nullable=False,
        default=LEGACY_WORKSPACE_ID, server_default=LEGACY_WORKSPACE_ID, index=True)

class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    role: Mapped[str] = mapped_column(String(20), default="owner")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class WorkspaceAISettings(Base):
    __tablename__ = "workspace_ai_settings"
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"), primary_key=True)
    defaults: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(default=1)

class Theme(Base):
    __tablename__ = "themes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)

class Entry(WorkspaceOwned, Base):
    __tablename__ = "entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(200))
    input_type: Mapped[str] = mapped_column(String(32), default="text")
    event_local: Mapped[str | None] = mapped_column(String(64), nullable=True)
    index_status: Mapped[str] = mapped_column(String(32), default="pending")
    index_error: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processing_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processing_outputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    original_text: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    theme_id: Mapped[str | None] = mapped_column(ForeignKey("themes.id"), nullable=True)
    event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    status: Mapped[str] = mapped_column(String(32), default="queued")

class Job(WorkspaceOwned, Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entry_id: Mapped[str] = mapped_column(ForeignKey("entries.id"), unique=True)
    stage: Mapped[str] = mapped_column(String(32), default="normalize")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class ProcessedEntry(WorkspaceOwned, Base):
    __tablename__ = "processed_entries"
    entry_id: Mapped[str] = mapped_column(ForeignKey("entries.id"), primary_key=True)
    english_text: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    suggested_theme: Mapped[str | None] = mapped_column(ForeignKey("themes.id"), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(64))

class Knowledge(WorkspaceOwned, Base):
    __tablename__ = "knowledge"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entry_id: Mapped[str] = mapped_column(ForeignKey("entries.id"))
    kind: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    evidence_start: Mapped[int]
    evidence_end: Mapped[int]
    theme_id: Mapped[str | None] = mapped_column(ForeignKey("themes.id"), nullable=True)
    certainty: Mapped[str] = mapped_column(String(32))
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_basis: Mapped[str] = mapped_column(String(32), default="unknown")
    status: Mapped[str] = mapped_column(String(32), default="active")

    origin: Mapped[str] = mapped_column(String(32), default="ai_extracted")
    version: Mapped[int] = mapped_column(default=1)

class KnowledgeChange(WorkspaceOwned, Base):
    __tablename__ = "knowledge_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge.id"))
    before_json: Mapped[str] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Asset(WorkspaceOwned, Base):
    __tablename__ = "assets"
    entry_id: Mapped[str] = mapped_column(ForeignKey("entries.id"), primary_key=True)
    filename: Mapped[str] = mapped_column(String(200))
    mime_type: Mapped[str] = mapped_column(String(100))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    sha256: Mapped[str] = mapped_column(String(64))

class SearchRecord(WorkspaceOwned, Base):
    __tablename__ = "search_records"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entry_id: Mapped[str] = mapped_column(ForeignKey("entries.id"), index=True)
    knowledge_id: Mapped[str | None] = mapped_column(ForeignKey("knowledge.id"), nullable=True)
    knowledge_version: Mapped[int | None] = mapped_column(nullable=True)
    text: Mapped[str] = mapped_column(Text)
    start: Mapped[int | None] = mapped_column(nullable=True)
    end: Mapped[int | None] = mapped_column(nullable=True)
    model: Mapped[str] = mapped_column(String(100))
    vector: Mapped[list] = mapped_column(JSON)

class AISettings(Base):
    __tablename__ = "ai_settings"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    defaults: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(default=1)
