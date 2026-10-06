"""Single-owner memory workspace. Access is guarded by the application's owner auth."""
from sqlalchemy import String, Text, JSON, ForeignKey, UniqueConstraint, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from uuid import uuid4
from datetime import datetime
from .models import Base, now

def uid(): return str(uuid4())

class Project(Base):
    __tablename__='memory_projects'
    __table_args__=(UniqueConstraint('theme_id','name_key'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    name: Mapped[str]=mapped_column(String(100))
    name_key: Mapped[str]=mapped_column(String(100))
    theme_id: Mapped[str]=mapped_column(ForeignKey('themes.id'))
    description: Mapped[str]=mapped_column(Text,default='')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class Topic(Base):
    __tablename__='memory_topics'
    __table_args__=(UniqueConstraint('project_id','name_key'),)
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str]=mapped_column(ForeignKey('memory_projects.id'),index=True)
    name: Mapped[str]=mapped_column(String(100))
    name_key: Mapped[str]=mapped_column(String(100))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class ProjectEntry(Base):
    __tablename__='memory_project_entries'
    project_id: Mapped[str]=mapped_column(ForeignKey('memory_projects.id'),primary_key=True)
    entry_id: Mapped[str]=mapped_column(ForeignKey('entries.id'),primary_key=True)
    topic_ids: Mapped[list]=mapped_column(JSON,default=list)
    status: Mapped[str]=mapped_column(String(20),default='queued')
    error: Mapped[str | None]=mapped_column(String(100),nullable=True)
    model: Mapped[dict]=mapped_column(JSON)
    version: Mapped[int]=mapped_column(default=1)
    claimed_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class MemoryRecord(Base):
    __tablename__='memory_records'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str]=mapped_column(ForeignKey('memory_projects.id'),index=True)
    kind: Mapped[str]=mapped_column(String(20))
    text: Mapped[str]=mapped_column(Text)
    certainty: Mapped[str]=mapped_column(String(20))
    topic_ids: Mapped[list]=mapped_column(JSON,default=list)
    evidence: Mapped[list]=mapped_column(JSON,default=list)
    version: Mapped[int]=mapped_column(default=1)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class MemoryProposal(Base):
    __tablename__='memory_proposals'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str]=mapped_column(ForeignKey('memory_projects.id'),index=True)
    entry_id: Mapped[str]=mapped_column(ForeignKey('entries.id'))
    fingerprint: Mapped[str]=mapped_column(String(64),unique=True)
    payload: Mapped[dict]=mapped_column(JSON)
    evidence: Mapped[list]=mapped_column(JSON)
    status: Mapped[str]=mapped_column(String(20),default='pending')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class MemoryRevision(Base):
    __tablename__='memory_revisions'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    memory_id: Mapped[str]=mapped_column(ForeignKey('memory_records.id'),index=True)
    before: Mapped[dict | None]=mapped_column(JSON,nullable=True)
    after: Mapped[dict]=mapped_column(JSON)
    reason: Mapped[str]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
