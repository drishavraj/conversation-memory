"""Scoped, persistent AI chat threads and idempotent turns."""
from alembic import op
import sqlalchemy as s
revision='0008'
down_revision='0007'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('memory_chat_threads',s.Column('id',s.String(36),primary_key=True),s.Column('project_id',s.String(36),s.ForeignKey('memory_projects.id'),nullable=False),s.Column('topic_id',s.String(36),s.ForeignKey('memory_topics.id'),nullable=True),s.Column('title',s.String(120),nullable=False),s.Column('version',s.Integer,nullable=False),s.Column('pending_turn_id',s.String(36),nullable=True),s.Column('created_at',s.DateTime(timezone=True),nullable=False),s.Column('updated_at',s.DateTime(timezone=True),nullable=False))
    op.create_index('ix_memory_chat_threads_project_id','memory_chat_threads',['project_id'])
    op.create_index('ix_memory_chat_threads_updated_at','memory_chat_threads',['updated_at'])
    op.create_table('memory_chat_turns',s.Column('id',s.String(36),primary_key=True),s.Column('thread_id',s.String(36),s.ForeignKey('memory_chat_threads.id'),nullable=False),s.Column('request_id',s.String(36),nullable=False),s.Column('sequence',s.Integer,nullable=False),s.Column('question',s.Text,nullable=False),s.Column('include_history',s.Boolean,nullable=False),s.Column('status',s.String(20),nullable=False),s.Column('response',s.JSON,nullable=True),s.Column('error',s.String(80),nullable=True),s.Column('model',s.JSON,nullable=False),s.Column('lease',s.String(36),nullable=False),s.Column('context_info',s.JSON,nullable=False),s.Column('created_at',s.DateTime(timezone=True),nullable=False),s.Column('updated_at',s.DateTime(timezone=True),nullable=False),s.UniqueConstraint('thread_id','request_id'),s.UniqueConstraint('thread_id','sequence'))
    op.create_index('ix_memory_chat_turns_thread_id','memory_chat_turns',['thread_id'])

def downgrade():
    op.drop_table('memory_chat_turns')
    op.drop_table('memory_chat_threads')
