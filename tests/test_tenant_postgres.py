"""Opt-in PostgreSQL RLS verification using an EMPTY disposable database.
TENANCY_RLS_TEST_DATABASE_URL must use a provisioning role able to create roles.
Does not run against a nonempty database. Never point this at Render dev/production.
"""
import os
from uuid import uuid4
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.database import make_engine
from app.models import Entry,WorkspaceAISettings,LEGACY_WORKSPACE_ID
from app.tenancy import workspace_sessions,runtime_isolation_ready

@pytest.mark.skipif(not os.getenv('TENANCY_RLS_TEST_DATABASE_URL'),reason='Disposable PostgreSQL with role provisioning required')
def test_postgres_force_rls_and_pool_context(monkeypatch):
    url=os.environ['TENANCY_RLS_TEST_DATABASE_URL'];admin=make_engine(url)
    assert admin.dialect.name=='postgresql'
    assert not sa.inspect(admin).get_table_names(),'Refusing a nonempty database'
    monkeypatch.setenv('DATABASE_URL',url);monkeypatch.setenv('MIGRATION_DATABASE_URL',url)
    monkeypatch.setenv('AUTH_OWNER_USER_ID','11111111-1111-4111-8111-111111111111')
    command.upgrade(Config('alembic.ini'),'head')
    a=LEGACY_WORKSPACE_ID;b=str(uuid4());role='test_tenant_'+uuid4().hex[:12]
    with admin.begin() as db:
        db.execute(sa.text('INSERT INTO workspaces (id,name,status,created_at) VALUES (:w,\'Second\',\'active\',CURRENT_TIMESTAMP)'),{'w':b})
        db.execute(sa.text(f'CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS NOINHERIT'))
        db.execute(sa.text(f'GRANT USAGE ON SCHEMA public TO {role}'))
        tables=[t for t in sa.inspect(db).get_table_names() if t not in ('alembic_version','ai_settings')]
        db.execute(sa.text(f'GRANT SELECT ON workspaces,workspace_memberships,themes TO {role}'))
        owned=[t for t in tables if t not in ('workspaces','workspace_memberships','themes')]
        db.execute(sa.text(f'GRANT SELECT,INSERT,UPDATE,DELETE ON '+','.join(owned)+f' TO {role}'))
    # Dedicated pool runs with SET ROLE on connect; same privileges as deployed role.
    restricted=make_engine(url)
    @sa.event.listens_for(restricted,'connect')
    def set_role(conn,record):
        with conn.cursor() as cursor:cursor.execute(f'SET ROLE {role}')
        conn.commit()
    try:
        assert runtime_isolation_ready(restricted)
        for wid in [a,b]:
            with workspace_sessions(restricted,wid)() as db:
                db.add(Entry(title=wid,original_text='same',fingerprint='same'))
                db.add(WorkspaceAISettings(workspace_id=wid,defaults={},version=1));db.commit()
        for wid in [a,b,a]:
            with workspace_sessions(restricted,wid)() as db:
                assert list(db.scalars(sa.select(Entry.title)))==[wid]
        with restricted.begin() as db:
            assert db.execute(sa.text('SELECT count(*) FROM entries')).scalar_one()==0
            db.execute(sa.text("SELECT set_config('app.workspace_id',:w,true)"),{'w':a})
            assert db.execute(sa.text('SELECT count(*) FROM entries')).scalar_one()==1
            assert db.execute(sa.text('UPDATE entries SET title=\'attack\' WHERE workspace_id=:w'),{'w':b}).rowcount==0
        with pytest.raises(sa.exc.DBAPIError):
            with restricted.begin() as db:
                db.execute(sa.text("SELECT set_config('app.workspace_id',:w,true)"),{'w':a})
                db.execute(sa.text("INSERT INTO entries (id,title,original_text,status,uploaded_at,index_status,input_type,workspace_id) VALUES ('attack','x','x','queued',CURRENT_TIMESTAMP,'pending','text',:w)"),{'w':b})
        with restricted.begin() as db:
            assert db.execute(sa.text('SELECT count(*) FROM entries')).scalar_one()==0
        with pytest.raises(sa.exc.DBAPIError):
            with restricted.begin() as db:db.execute(sa.text('DELETE FROM workspace_memberships'))
    finally:
        restricted.dispose()
        with admin.begin() as db:
            db.execute(sa.text(f'DROP OWNED BY {role}'))
            db.execute(sa.text(f'DROP ROLE {role}'))
        admin.dispose()
