from alembic import op
import sqlalchemy as sa
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("jobs", sa.Column("claimed_at", sa.DateTime(timezone=True)))
    op.create_table("processed_entries", sa.Column("entry_id", sa.String(36), sa.ForeignKey("entries.id"), primary_key=True), sa.Column("english_text", sa.Text, nullable=False), sa.Column("summary", sa.Text, nullable=False), sa.Column("suggested_theme", sa.String(32), sa.ForeignKey("themes.id")), sa.Column("prompt_version", sa.String(64), nullable=False))
    op.create_table("knowledge", sa.Column("id", sa.String(36), primary_key=True), sa.Column("entry_id", sa.String(36), sa.ForeignKey("entries.id"), nullable=False), sa.Column("kind", sa.String(32), nullable=False), sa.Column("text", sa.Text, nullable=False), sa.Column("evidence", sa.Text, nullable=False), sa.Column("evidence_start", sa.Integer, nullable=False), sa.Column("evidence_end", sa.Integer, nullable=False), sa.Column("theme_id", sa.String(32), sa.ForeignKey("themes.id")), sa.Column("certainty", sa.String(32), nullable=False), sa.Column("owner", sa.String(200)), sa.Column("due_date", sa.Date), sa.Column("status", sa.String(32), nullable=False))

def downgrade():
    op.drop_table("knowledge")
    op.drop_table("processed_entries")
    op.drop_column("jobs", "claimed_at")
