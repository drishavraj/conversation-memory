"""Task defaults and frozen per-entry processing selections."""
from alembic import op
import sqlalchemy as sa
revision='0006'
down_revision='0005'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('ai_settings',sa.Column('id',sa.String(32),primary_key=True),sa.Column('defaults',sa.JSON,nullable=False),sa.Column('version',sa.Integer,nullable=False))
    op.add_column('entries',sa.Column('processing_config',sa.JSON,nullable=True))
    op.add_column('entries',sa.Column('processing_outputs',sa.JSON,nullable=True))
    op.add_column('jobs',sa.Column('next_attempt_at',sa.DateTime(timezone=True),nullable=True))

def downgrade():
    op.drop_column('jobs','next_attempt_at')
    op.drop_column('entries','processing_outputs')
    op.drop_column('entries','processing_config')
    op.drop_table('ai_settings')
