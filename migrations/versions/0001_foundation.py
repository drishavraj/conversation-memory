from alembic import op
import sqlalchemy as sa
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("themes", sa.Column("id", sa.String(32), primary_key=True), sa.Column("name", sa.String(64), nullable=False, unique=True))
    op.bulk_insert(sa.table("themes", sa.column("id", sa.String), sa.column("name", sa.String)), [{"id": "personal", "name": "Personal"}, {"id": "side-projects", "name": "Side Projects"}, {"id": "office", "name": "Office"}])
    op.create_table("entries", sa.Column("id", sa.String(36), primary_key=True), sa.Column("title", sa.String(200), nullable=False), sa.Column("original_text", sa.Text, nullable=False), sa.Column("theme_id", sa.String(32), sa.ForeignKey("themes.id")), sa.Column("event_at", sa.DateTime(timezone=True)), sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False), sa.Column("status", sa.String(32), nullable=False))
    op.create_table("jobs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("entry_id", sa.String(36), sa.ForeignKey("entries.id"), nullable=False, unique=True), sa.Column("stage", sa.String(32), nullable=False), sa.Column("status", sa.String(32), nullable=False), sa.Column("attempts", sa.Integer, nullable=False), sa.Column("error", sa.Text))

def downgrade():
    op.drop_table("jobs")
    op.drop_table("entries")
    op.drop_table("themes")
