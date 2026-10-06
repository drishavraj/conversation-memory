import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

def make_engine(url=None):
    url = url or os.environ["DATABASE_URL"]
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}, pool_pre_ping=True, hide_parameters=True)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
    return engine

def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
