from datetime import datetime, timezone, date
from uuid import uuid4
from sqlalchemy import String, Text, DateTime, ForeignKey, Date
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def now():
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

class Theme(Base):
    __tablename__ = "themes"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)

class Entry(Base):
    __tablename__ = "entries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(200))
    original_text: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    theme_id: Mapped[str | None] = mapped_column(ForeignKey("themes.id"), nullable=True)
    event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    status: Mapped[str] = mapped_column(String(32), default="queued")

class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    entry_id: Mapped[str] = mapped_column(ForeignKey("entries.id"), unique=True)
    stage: Mapped[str] = mapped_column(String(32), default="normalize")
    status: Mapped[str] = mapped_column(String(32), default="queued")
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class ProcessedEntry(Base):
    __tablename__ = "processed_entries"
    entry_id: Mapped[str] = mapped_column(ForeignKey("entries.id"), primary_key=True)
    english_text: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    suggested_theme: Mapped[str | None] = mapped_column(ForeignKey("themes.id"), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(64))

class Knowledge(Base):
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

class KnowledgeChange(Base):
    __tablename__ = "knowledge_changes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    knowledge_id: Mapped[str] = mapped_column(ForeignKey("knowledge.id"))
    before_json: Mapped[str] = mapped_column(Text)
    after_json: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
