"""Workspace cutover: no implicit owner, scoped uniqueness, PostgreSQL RLS."""
from alembic import op
import sqlalchemy as sa
revision='0010'
down_revision='0009'
branch_labels=None
depends_on=None
LEGACY='00000000-0000-4000-8000-000000000001'
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
    bind=op.get_bind()
    # Last refresh of the single-owner defaults immediately before application cutover.
    bind.execute(sa.text("DELETE FROM workspace_ai_settings WHERE workspace_id=:w"),{'w':LEGACY})
    bind.execute(sa.text("INSERT INTO workspace_ai_settings (workspace_id,defaults,version) SELECT :w,defaults,version FROM ai_settings WHERE id='defaults'"),{'w':LEGACY})
    uniques={'entries':(['fingerprint'],['workspace_id','fingerprint']),
             'memory_projects':(['theme_id','name_key'],['workspace_id','theme_id','name_key']),
             'memory_proposals':(['fingerprint'],['workspace_id','fingerprint'])}
    op.drop_index('uq_entries_fingerprint',table_name='entries')
    if bind.dialect.name=='sqlite':
        triggers=list(bind.execute(sa.text("SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name LIKE 'tenant_%'")))
        for name,_ in triggers:op.execute(f'DROP TRIGGER "{name}"')
        for table in TABLES:
            old=uniques.get(table)
            constraints=sa.inspect(bind).get_unique_constraints(table)
            with op.batch_alter_table(table,naming_convention={'uq':'uq_%(table_name)s_%(column_0_name)s'}) as batch:
                batch.alter_column('workspace_id',existing_type=sa.String(36),nullable=False,server_default=None)
                if old:
                    for c in constraints:
                        if c['column_names']==old[0]:batch.drop_constraint(c['name'] or f'uq_{table}_{old[0][0]}',type_='unique')
                    batch.create_unique_constraint('uq_'+table+'_tenant_unique',old[1])
        for _,sql in triggers:op.execute(sql)
        if list(bind.execute(sa.text('PRAGMA foreign_key_check'))):raise RuntimeError('Foreign key validation failed')
    else:
        for table in TABLES:
            op.alter_column(table,'workspace_id',existing_type=sa.String(36),nullable=False,server_default=None)
            if table in uniques:
                old,new=uniques[table]
                for c in sa.inspect(bind).get_unique_constraints(table):
                    if c['column_names']==old:op.drop_constraint(c['name'],table,type_='unique')
                op.create_unique_constraint('uq_'+table+'_tenant_unique',table,new)
        # FORCE includes ordinary table owners; superusers/BYPASSRLS still need
        # separate runtime credentials. The readiness check blocks non-owner login
        # until the actual runtime role and table policies have been verified.
        for table in [*TABLES,'workspace_ai_settings']:
            op.execute(f"CREATE POLICY workspace_isolation ON {table} USING (workspace_id = nullif(current_setting('app.workspace_id', true), '')) WITH CHECK (workspace_id = nullif(current_setting('app.workspace_id', true), ''))")
            op.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
            op.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')


def downgrade():
    raise RuntimeError('Do not remove tenant isolation; restore a verified backup for disaster recovery')
