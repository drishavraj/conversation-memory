from alembic import op
import sqlalchemy as sa
revision="0005"
down_revision="0004"
branch_labels=None
depends_on=None

def upgrade():
    op.add_column("entries",sa.Column("input_type",sa.String(32),nullable=False,server_default="text"))
    op.add_column("entries",sa.Column("event_local",sa.String(64)))
    op.add_column("entries",sa.Column("index_status",sa.String(32),nullable=False,server_default="pending"))
    op.add_column("entries",sa.Column("index_error",sa.String(64)))
    op.create_table("assets",sa.Column("entry_id",sa.String(36),sa.ForeignKey("entries.id"),primary_key=True),sa.Column("filename",sa.String(200),nullable=False),sa.Column("mime_type",sa.String(100),nullable=False),sa.Column("content",sa.LargeBinary,nullable=False),sa.Column("sha256",sa.String(64),nullable=False))
    op.create_table("search_records",sa.Column("id",sa.String(64),primary_key=True),sa.Column("entry_id",sa.String(36),sa.ForeignKey("entries.id"),nullable=False),sa.Column("knowledge_id",sa.String(36),sa.ForeignKey("knowledge.id")),sa.Column("knowledge_version",sa.Integer),sa.Column("text",sa.Text,nullable=False),sa.Column("start",sa.Integer),sa.Column("end",sa.Integer),sa.Column("model",sa.String(100),nullable=False),sa.Column("vector",sa.JSON,nullable=False))
    op.create_index("ix_search_records_entry_id","search_records",["entry_id"])

def downgrade():
    op.drop_table("search_records")
    op.drop_table("assets")
    for column in ["index_error","index_status","event_local","input_type"]:op.drop_column("entries",column)
