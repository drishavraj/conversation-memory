"""Projects, evidence-backed memories and durable review proposals."""
from alembic import op
import sqlalchemy as s
revision='0007'
down_revision='0006'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('memory_projects',s.Column('id',s.String(36),primary_key=True),s.Column('name',s.String(100),nullable=False),s.Column('name_key',s.String(100),nullable=False),s.Column('theme_id',s.String(32),s.ForeignKey('themes.id'),nullable=False),s.Column('description',s.Text,nullable=False),s.Column('created_at',s.DateTime(timezone=True),nullable=False),s.UniqueConstraint('theme_id','name_key'))
    op.create_table('memory_topics',s.Column('id',s.String(36),primary_key=True),s.Column('project_id',s.String(36),s.ForeignKey('memory_projects.id'),nullable=False),s.Column('name',s.String(100),nullable=False),s.Column('name_key',s.String(100),nullable=False),s.Column('created_at',s.DateTime(timezone=True),nullable=False),s.UniqueConstraint('project_id','name_key'))
    op.create_index('ix_memory_topics_project_id','memory_topics',['project_id'])
    op.create_table('memory_project_entries',s.Column('project_id',s.String(36),s.ForeignKey('memory_projects.id'),primary_key=True),s.Column('entry_id',s.String(36),s.ForeignKey('entries.id'),primary_key=True),s.Column('topic_ids',s.JSON,nullable=False),s.Column('status',s.String(20),nullable=False),s.Column('error',s.String(100),nullable=True),s.Column('model',s.JSON,nullable=False),s.Column('version',s.Integer,nullable=False),s.Column('claimed_at',s.DateTime(timezone=True),nullable=True),s.Column('created_at',s.DateTime(timezone=True),nullable=False))
    op.create_table('memory_records',s.Column('id',s.String(36),primary_key=True),s.Column('project_id',s.String(36),s.ForeignKey('memory_projects.id'),nullable=False),s.Column('kind',s.String(20),nullable=False),s.Column('text',s.Text,nullable=False),s.Column('certainty',s.String(20),nullable=False),s.Column('topic_ids',s.JSON,nullable=False),s.Column('evidence',s.JSON,nullable=False),s.Column('version',s.Integer,nullable=False),s.Column('updated_at',s.DateTime(timezone=True),nullable=False))
    op.create_index('ix_memory_records_project_id','memory_records',['project_id'])
    op.create_table('memory_proposals',s.Column('id',s.String(36),primary_key=True),s.Column('project_id',s.String(36),s.ForeignKey('memory_projects.id'),nullable=False),s.Column('entry_id',s.String(36),s.ForeignKey('entries.id'),nullable=False),s.Column('fingerprint',s.String(64),nullable=False,unique=True),s.Column('payload',s.JSON,nullable=False),s.Column('evidence',s.JSON,nullable=False),s.Column('status',s.String(20),nullable=False),s.Column('created_at',s.DateTime(timezone=True),nullable=False))
    op.create_index('ix_memory_proposals_project_id','memory_proposals',['project_id'])
    op.create_table('memory_revisions',s.Column('id',s.String(36),primary_key=True),s.Column('memory_id',s.String(36),s.ForeignKey('memory_records.id'),nullable=False),s.Column('before',s.JSON,nullable=True),s.Column('after',s.JSON,nullable=False),s.Column('reason',s.Text,nullable=False),s.Column('created_at',s.DateTime(timezone=True),nullable=False))
    op.create_index('ix_memory_revisions_memory_id','memory_revisions',['memory_id'])

def downgrade():
    for name in ['memory_revisions','memory_proposals','memory_records','memory_project_entries','memory_topics','memory_projects']:op.drop_table(name)
