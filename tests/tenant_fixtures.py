"""Explicit legacy workspace scope for pre-tenancy regression fixture setup."""
from app.models import LEGACY_WORKSPACE_ID
from app.tenancy import workspace_sessions

def Session(engine):
    return workspace_sessions(engine,LEGACY_WORKSPACE_ID)()
