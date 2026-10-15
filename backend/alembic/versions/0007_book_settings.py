"""Book settings, application defaults and the sole author requirement ledger.

Revision ID: 0007
Revises: 0006
"""

import json
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# Frozen migration data: later application defaults must not change this migration.
DEFAULTS = {
    "title_style": "short", "title_custom": "", "person": "third", "intimacy": "fade",
    "intimacy_custom": "", "chapter_words": None, "other_rules": "", "playbook": "auto",
    "effort_preset": "balanced", "max_rewrites": 2, "pitches": 2, "review_strictness": "standard",
    "volume_audit": True, "volume_approval": True, "trial_read": True,
}


def upgrade() -> None:
    op.create_table("app_settings", sa.Column("key", sa.String(100), primary_key=True),
                    sa.Column("value", postgresql.JSONB(), nullable=False))
    op.create_table(
        "author_requirements",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("book_id", sa.Uuid(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.clock_timestamp(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_author_requirements_book_id", "author_requirements", ["book_id"])
    op.add_column("books", sa.Column("settings", postgresql.JSONB(), nullable=False,
                                      server_default=sa.text("'{}'::jsonb")))
    connection = op.get_bind()
    connection.execute(sa.text("INSERT INTO app_settings (key,value) VALUES ('new_book_defaults',CAST(:value AS jsonb))"),
                       {"value": json.dumps(DEFAULTS)})
    connection.execute(sa.text("UPDATE books SET settings=CAST(:settings AS jsonb)"),
                       {"settings": json.dumps({**DEFAULTS, "title_style": "chief"})})
    rows = connection.execute(sa.text("SELECT id,requirements,updated_at FROM books")).mappings()
    for row in rows:
        base_id = uuid.uuid4().int
        for index, text in enumerate(dict.fromkeys(row["requirements"] or [])):
            if not str(text).strip():
                continue
            connection.execute(sa.text(
                "INSERT INTO author_requirements (id,book_id,text,source,created_at,updated_at) "
                "VALUES (:id,:book_id,:text,'legacy',:time,:time)"
            ), {"id": uuid.UUID(int=base_id + index), "book_id": row["id"], "text": text, "time": row["updated_at"]})
    op.drop_column("books", "requirements")


def downgrade() -> None:
    op.add_column("books", sa.Column("requirements", postgresql.JSONB(), nullable=False,
                                      server_default=sa.text("'[]'::jsonb")))
    op.execute("UPDATE books b SET requirements=(SELECT coalesce(jsonb_agg(r.text ORDER BY r.created_at,r.id),'[]'::jsonb) "
               "FROM author_requirements r WHERE r.book_id=b.id)")
    op.drop_column("books", "settings")
    op.drop_table("author_requirements")
    op.drop_table("app_settings")
