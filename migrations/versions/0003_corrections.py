from alembic import op
import sqlalchemy as sa
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("knowledge", sa.Column("origin", sa.String(32), nullable=False, server_default="ai_extracted"))
    op.add_column("knowledge", sa.Column("version", sa.Integer, nullable=False, server_default="1"))
    op.create_table("knowledge_changes", sa.Column("id", sa.String(36), primary_key=True), sa.Column("knowledge_id", sa.String(36), sa.ForeignKey("knowledge.id"), nullable=False), sa.Column("before_json", sa.Text, nullable=False), sa.Column("after_json", sa.Text, nullable=False), sa.Column("reason", sa.Text, nullable=False), sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False))

def downgrade():
    op.drop_table("knowledge_changes")
    op.drop_column("knowledge", "version")
    op.drop_column("knowledge", "origin")
