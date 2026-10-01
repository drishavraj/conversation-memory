from alembic import op
import sqlalchemy as sa
import hashlib
import json
from datetime import timezone
revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("entries",sa.Column("fingerprint",sa.String(64),nullable=True))
    op.create_index("uq_entries_fingerprint","entries",["fingerprint"],unique=True)
    op.add_column("knowledge",sa.Column("date_basis",sa.String(32),nullable=False,server_default="unknown"))
    entries=sa.table("entries",sa.column("id",sa.String),sa.column("original_text",sa.Text),sa.column("theme_id",sa.String),sa.column("event_at",sa.DateTime(timezone=True)),sa.column("uploaded_at",sa.DateTime(timezone=True)),sa.column("fingerprint",sa.String))
    conn=op.get_bind()
    seen=set()
    for row in conn.execute(sa.select(entries).order_by(entries.c.uploaded_at,entries.c.id)).mappings():
        event=row['event_at']
        if event is not None:
            if event.tzinfo is None: event=event.replace(tzinfo=timezone.utc)
            event=event.astimezone(timezone.utc).isoformat()
        digest=hashlib.sha256(json.dumps([row['original_text'].strip(),row['theme_id'],event],ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
        if digest not in seen:
            conn.execute(entries.update().where(entries.c.id==row['id']).values(fingerprint=digest))
            seen.add(digest)
    # Existing duplicates are retained; this migration never deletes user data.

def downgrade():
    op.drop_column("knowledge","date_basis")
    op.drop_index("uq_entries_fingerprint",table_name="entries")
    op.drop_column("entries","fingerprint")
