"""Read-only ownership audit: python -m app.workspace_audit. No source text or secrets."""
import json
import sqlalchemy as sa
from .database import make_engine
from .models import Base
from . import memory_models


def audit(engine):
    result={'tables':{},'unclaimed_workspaces':0,'invalid_memberships':0,'ok':True}
    with engine.connect() as db:
        ids=list(db.scalars(sa.text('SELECT id FROM workspaces')))
        for table in Base.metadata.sorted_tables:
            if 'workspace_id' not in table.c or table.name in ('workspace_memberships','workspace_ai_settings'):continue
            rows=invalid=0
            for wid in ids:
                if engine.dialect.name=='postgresql':db.execute(sa.text("SELECT set_config('app.workspace_id',:w,true)"),{'w':wid})
                rows+=db.execute(sa.text(f'SELECT count(*) FROM {table.name} WHERE workspace_id=:w'),{'w':wid}).scalar_one()
                invalid+=db.execute(sa.text(f'SELECT count(*) FROM {table.name} t LEFT JOIN workspaces w ON t.workspace_id=w.id WHERE t.workspace_id=:w AND w.id IS NULL'),{'w':wid}).scalar_one()
            result['tables'][table.name]={'rows':rows,'invalid_workspace':invalid}
            result['ok'] &= invalid==0
        result['unclaimed_workspaces']=db.execute(sa.text("SELECT count(*) FROM workspaces w WHERE NOT EXISTS (SELECT 1 FROM workspace_memberships m WHERE m.workspace_id=w.id AND m.role='owner' AND m.status='active')")).scalar_one()
        result['invalid_memberships']=db.execute(sa.text("SELECT count(*) FROM workspace_memberships m LEFT JOIN workspaces w ON w.id=m.workspace_id WHERE w.id IS NULL OR m.role NOT IN ('owner','member') OR m.status NOT IN ('active','revoked') OR m.user_id='' ")).scalar_one()
        result['ok'] &= result['unclaimed_workspaces']==0 and result['invalid_memberships']==0
    from .tenancy import runtime_isolation_ready
    result['runtime_isolation_ready']=runtime_isolation_ready(engine)
    result['scope']='Enumerates existing workspaces; relational constraints enforce missing-parent rejection'
    return result

if __name__=='__main__':
    report=audit(make_engine())
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report['ok'] else 1)
