"""Single-owner compatible workspace foundation; not multi-user authorization.

PostgreSQL uses composite foreign keys. SQLite uses equivalent relationship
triggers to avoid rebuilding live parent tables with foreign keys enabled.
JSON evidence references remain application-validated until Phase 2.
"""
import os
from uuid import UUID
from datetime import datetime, timezone
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None
LEGACY = '00000000-0000-4000-8000-000000000001'
TABLES = {
    'entries': 'id', 'jobs': 'id', 'processed_entries': 'entry_id',
    'knowledge': 'id', 'knowledge_changes': 'id', 'assets': 'entry_id',
    'search_records': 'id', 'memory_projects': 'id', 'memory_topics': 'id',
    'memory_project_entries': None, 'memory_records': 'id',
    'memory_proposals': 'id', 'memory_revisions': 'id',
    'memory_chat_threads': 'id', 'memory_chat_turns': 'id',
}
LINKS = {
    'jobs': [('entry_id','entries')],
    'processed_entries': [('entry_id','entries')],
    'knowledge': [('entry_id','entries')],
    'knowledge_changes': [('knowledge_id','knowledge')],
    'assets': [('entry_id','entries')],
    'search_records': [('entry_id','entries'),('knowledge_id','knowledge')],
    'memory_topics': [('project_id','memory_projects')],
    'memory_project_entries': [('project_id','memory_projects'),('entry_id','entries')],
    'memory_records': [('project_id','memory_projects')],
    'memory_proposals': [('project_id','memory_projects'),('entry_id','entries')],
    'memory_revisions': [('memory_id','memory_records')],
    'memory_chat_threads': [('project_id','memory_projects'),('topic_id','memory_topics')],
    'memory_chat_turns': [('thread_id','memory_chat_threads')],
}

def upgrade():
    bind = op.get_bind()
    owner = os.getenv('AUTH_OWNER_USER_ID', '').strip()
    # Never infer an owner from an email or bind existing data to the first signup.
    if owner:
        owner = str(UUID(owner))
    op.create_table('workspaces',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('name',sa.String(120),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('workspace_memberships',
        sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),primary_key=True),
        sa.Column('user_id',sa.String(36),primary_key=True),
        sa.Column('role',sa.String(20),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("role IN ('owner','member')", name='ck_membership_role'),
        sa.CheckConstraint("status IN ('active','revoked')", name='ck_membership_status'))
    op.create_index('ix_membership_user','workspace_memberships',['user_id','status'])
    op.create_table('workspace_ai_settings',
        sa.Column('workspace_id',sa.String(36),sa.ForeignKey('workspaces.id'),primary_key=True),
        sa.Column('defaults',sa.JSON,nullable=False),sa.Column('version',sa.Integer,nullable=False))
    stamp = datetime.now(timezone.utc)
    workspaces = sa.table('workspaces',sa.column('id'),sa.column('name'),sa.column('status'),sa.column('created_at'))
    bind.execute(workspaces.insert().values(id=LEGACY,name='Personal workspace',status='active' if owner else 'unclaimed',created_at=stamp))
    if owner:
        members = sa.table('workspace_memberships',*[sa.column(x) for x in ['workspace_id','user_id','role','status','created_at']])
        bind.execute(members.insert().values(workspace_id=LEGACY,user_id=owner,role='owner',status='active',created_at=stamp))
    bind.execute(sa.text('INSERT INTO workspace_ai_settings (workspace_id, defaults, version) SELECT :w, defaults, version FROM ai_settings WHERE id = :id'), {'w':LEGACY,'id':'defaults'})
    for table, key in TABLES.items():
        # Known single-owner archive: every existing row has the same owner.
        op.add_column(table,sa.Column('workspace_id',sa.String(36),nullable=False,server_default=LEGACY))
        op.create_index('ix_'+table+'_workspace_id',table,['workspace_id'])
        if key:
            op.create_index('uq_'+table+'_workspace_key',table,['workspace_id',key],unique=True)
    if bind.dialect.name == 'postgresql':
        for table in TABLES:
            op.create_foreign_key('fk_'+table+'_workspace',table,'workspaces',['workspace_id'],['id'])
            for col, parent in LINKS.get(table,[]):
                op.create_foreign_key('fk_'+table+'_'+col+'_workspace',table,parent,['workspace_id',col],['workspace_id',TABLES[parent]])
    elif bind.dialect.name == 'sqlite':
        for table in TABLES:
            checks = ["NOT EXISTS (SELECT 1 FROM workspaces WHERE id = NEW.workspace_id)"]
            for col,parent in LINKS.get(table,[]):
                checks.append(f'(NEW.{col} IS NOT NULL AND NOT EXISTS (SELECT 1 FROM {parent} WHERE {TABLES[parent]} = NEW.{col} AND workspace_id = NEW.workspace_id))')
            condition = ' OR '.join(checks)
            for action in ['INSERT','UPDATE']:
                op.execute(f"CREATE TRIGGER tenant_{table}_{action.lower()} BEFORE {action} ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT, 'workspace relationship mismatch'); END")
            # Disallow ownership reassignment, including parent-side changes.
            op.execute(f"CREATE TRIGGER tenant_{table}_immutable BEFORE UPDATE OF workspace_id ON {table} WHEN OLD.workspace_id != NEW.workspace_id BEGIN SELECT RAISE(ABORT, 'workspace ownership is immutable'); END")
        op.execute("CREATE TRIGGER tenant_workspace_delete BEFORE DELETE ON workspaces WHEN " + ' OR '.join(f'EXISTS (SELECT 1 FROM {t} WHERE workspace_id = OLD.id)' for t in TABLES) + " BEGIN SELECT RAISE(ABORT, 'workspace contains records'); END")
    else:
        raise RuntimeError('Workspace migration supports PostgreSQL and SQLite only')


def downgrade():
    # Downgrading would erase ownership boundaries; retain data and roll code back instead.
    raise RuntimeError('Workspace ownership cannot be downgraded automatically; restore a verified backup if required')
