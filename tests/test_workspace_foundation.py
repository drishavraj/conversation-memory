"""Migration ownership and relationship regression tests.
Optional PostgreSQL run uses a disposable empty database via TENANCY_TEST_DATABASE_URL.
"""
import os
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from app.database import make_engine

OWNER = '11111111-1111-4111-8111-111111111111'
LEGACY = '00000000-0000-4000-8000-000000000001'
OTHER = '22222222-2222-4222-8222-222222222222'

@pytest.fixture(params=['sqlite','postgresql'])
def migrated(request,tmp_path,monkeypatch):
    url = os.getenv('TENANCY_TEST_DATABASE_URL') if request.param=='postgresql' else f'sqlite:///{tmp_path}/tenant.db'
    if not url:
        pytest.skip('Set TENANCY_TEST_DATABASE_URL to a disposable PostgreSQL database')
    engine=make_engine(url)
    if sa.inspect(engine).get_table_names():
        pytest.fail('Refusing to run migration fixture on a nonempty database')
    monkeypatch.setenv('DATABASE_URL',url)
    monkeypatch.setenv('AUTH_OWNER_USER_ID',OWNER)
    cfg=Config('alembic.ini');command.upgrade(cfg,'0008')
    # Representative legacy source, dependent job, asset, and deployment settings.
    with engine.begin() as db:
        db.execute(sa.text("INSERT INTO entries (id,title,original_text,status,uploaded_at,index_status,input_type) VALUES ('e','Legacy','Keep this transcript','ready',CURRENT_TIMESTAMP,'pending','text')"))
        db.execute(sa.text("INSERT INTO jobs (id,entry_id,stage,status,attempts) VALUES ('j','e','normalize','completed',1)"))
        db.execute(sa.text("INSERT INTO ai_settings (id,defaults,version) VALUES ('defaults','{}',2)"))
    # Preserve coverage of the older chat migration's reversible round trip.
    command.downgrade(cfg,'0007');command.upgrade(cfg,'0008')
    command.upgrade(cfg,'0009')
    yield engine
    # Intentionally retain the disposable PostgreSQL DB for inspection; never drop it.
    engine.dispose()

def test_legacy_backfill_and_enforcement(migrated):
    engine=migrated
    with engine.begin() as db:
        assert db.execute(sa.text("SELECT workspace_id FROM entries WHERE id='e'")).scalar_one()==LEGACY
        assert db.execute(sa.text("SELECT original_text FROM entries WHERE id='e'")).scalar_one()=='Keep this transcript'
        assert db.execute(sa.text("SELECT workspace_id FROM jobs WHERE id='j'")).scalar_one()==LEGACY
        assert db.execute(sa.text('SELECT user_id FROM workspace_memberships')).scalar_one()==OWNER
        assert db.execute(sa.text('SELECT version FROM workspace_ai_settings')).scalar_one()==2
        db.execute(sa.text("INSERT INTO workspaces (id,name,status,created_at) VALUES (:id,'Other','active',CURRENT_TIMESTAMP)"),{'id':OTHER})
    for sql,params in [
        ("INSERT INTO jobs (id,entry_id,stage,status,attempts,workspace_id) VALUES ('wrong','e','normalize','queued',0,:w)",{'w':OTHER}),
        ("UPDATE jobs SET workspace_id=:w WHERE id='j'",{'w':OTHER}),
        ("UPDATE entries SET workspace_id=:w WHERE id='e'",{'w':OTHER}),
        ("UPDATE entries SET workspace_id=NULL WHERE id='e'",{}),
        ("DELETE FROM workspaces WHERE id=:w",{'w':LEGACY}),
    ]:
        with pytest.raises(sa.exc.IntegrityError):
            with engine.begin() as db:db.execute(sa.text(sql),params)
    with engine.begin() as db:
        # Existing application writers still use the explicit legacy bridge.
        db.execute(sa.text("INSERT INTO entries (id,title,original_text,status,uploaded_at,index_status,input_type) VALUES ('new','New','New transcript','queued',CURRENT_TIMESTAMP,'pending','text')"))
        assert db.execute(sa.text("SELECT workspace_id FROM entries WHERE id='new'")).scalar_one()==LEGACY


def test_missing_owner_is_not_claimed(tmp_path,monkeypatch):
    url=f'sqlite:///{tmp_path}/unclaimed.db'
    monkeypatch.setenv('DATABASE_URL',url);monkeypatch.delenv('AUTH_OWNER_USER_ID',raising=False)
    command.upgrade(Config('alembic.ini'),'0009')
    with make_engine(url).connect() as db:
        assert db.execute(sa.text('SELECT status FROM workspaces')).scalar_one()=='unclaimed'
        assert db.execute(sa.text('SELECT count(*) FROM workspace_memberships')).scalar_one()==0


def test_invalid_owner_fails_before_schema_changes(tmp_path,monkeypatch):
    url=f'sqlite:///{tmp_path}/invalid.db'
    monkeypatch.setenv('DATABASE_URL',url);monkeypatch.setenv('AUTH_OWNER_USER_ID','not-a-user-uuid')
    cfg=Config('alembic.ini');command.upgrade(cfg,'0008')
    with pytest.raises(ValueError):command.upgrade(cfg,'0009')
    assert 'workspaces' not in sa.inspect(make_engine(url)).get_table_names()
