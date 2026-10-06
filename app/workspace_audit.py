"""Read-only ownership audit: python -m app.workspace_audit. Never prints source data."""
import json
import sqlalchemy as sa
from .database import make_engine
from .models import Base
from . import memory_models  # register all owned tables


def audit(engine):
    result={'tables':{},'unclaimed_workspaces':0,'invalid_memberships':0,'ok':True}
    with engine.connect() as db:
        for table in Base.metadata.sorted_tables:
            if 'workspace_id' not in table.c or table.name in ('workspace_memberships','workspace_ai_settings'):
                continue
            rows=db.execute(sa.text(f'SELECT count(*) FROM {table.name}')).scalar_one()
            invalid=db.execute(sa.text(f'SELECT count(*) FROM {table.name} t LEFT JOIN workspaces w ON t.workspace_id=w.id WHERE w.id IS NULL')).scalar_one()
            result['tables'][table.name]={'rows':rows,'invalid_workspace':invalid}
            result['ok'] &= invalid==0
        result['unclaimed_workspaces']=db.execute(sa.text("SELECT count(*) FROM workspaces w WHERE NOT EXISTS (SELECT 1 FROM workspace_memberships m WHERE m.workspace_id=w.id AND m.role='owner' AND m.status='active')")).scalar_one()
        result['ok'] &= result['unclaimed_workspaces']==0
    return result

if __name__=='__main__':
    report=audit(make_engine())
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report['ok'] else 1)
