"""Move the author ledger into globally numbered, reversible memories."""

import sqlalchemy as sa

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("book_id", sa.UUID(), sa.ForeignKey("books.id", ondelete="CASCADE")),
        sa.Column("kind", sa.String(20), nullable=False, server_default="writing"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("source", sa.String(30), nullable=False, server_default="你加的"),
        sa.Column("scope", sa.String(10), nullable=False, server_default="always"),
        sa.Column("chapter_index", sa.Integer()),
        sa.Column("volume_index", sa.Integer()),
        sa.Column("message_id", sa.BigInteger(), sa.ForeignKey("meeting_messages.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.clock_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index("ix_memories_book_id", "memories", ["book_id"])
    op.execute("""
        INSERT INTO memories (book_id, summary, detail, source, scope, chapter_index,
                              volume_index, message_id, created_at, updated_at)
        SELECT r.book_id,
               CASE WHEN char_length(r.text) > 40 THEN left(r.text, 40) || '……' ELSE r.text END,
               r.text,
               CASE WHEN r.source = 'note' OR r.source LIKE 'private:%' OR r.source LIKE 'chat:%'
                    THEN '聊天里记的'
                    WHEN r.source = 'plan' THEN '方案卡'
                    WHEN r.source = 'answer' THEN '开书时答的'
                    WHEN r.source = 'trial' OR r.source LIKE 'volume:%' OR r.source LIKE 'unit:%'
                         OR r.source LIKE 'segment:%' THEN '看稿时说的'
                    ELSE '你加的' END,
               r.scope, r.chapter_index, r.volume_index, r.message_id, r.created_at, r.updated_at
        FROM author_requirements r JOIN books b ON b.id = r.book_id
        WHERE b.source != 'teardown'
        ORDER BY r.seq
    """)
    # Receipts on old messages must point at the new integer number, never at a
    # retired UUID/diff capable of restoring the old table through chat undo.
    connection = op.get_bind()
    rows = connection.execute(
        sa.text("""
        SELECT old.id::text AS old_id, m.* FROM (
            SELECT r.id, row_number() OVER (ORDER BY r.seq) AS memory_id
            FROM author_requirements r JOIN books b ON b.id = r.book_id
            WHERE b.source != 'teardown'
        ) old JOIN memories m ON m.id = old.memory_id
    """)
    ).mappings()
    by_id = {row["old_id"]: dict(row) for row in rows}

    def convert(value):
        if isinstance(value, list):
            return [convert(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: convert(item) for key, item in value.items()}
        if result.get("kind") not in ("requirement", "to_job"):
            return result
        for key in ("change", "diff", "redo"):
            result.pop(key, None)
        row = by_id.get(str(result.get("requirement_id")))
        if row:
            label = (
                "一直有效"
                if row["scope"] == "always"
                else f"只管第 {row['chapter_index']} 章"
                if row["scope"] == "chapter"
                else f"只管第 {row['volume_index']} 卷"
            )
            result["requirement_id"] = str(row["id"])
            result["memory"] = {
                "id": row["id"],
                "version": row["version"],
                "summary": row["summary"],
                "kind": "writing",
                "book_id": str(row["book_id"]),
                "label": label,
                "working": result["kind"] == "to_job",
            }
        return result

    import json

    for message in connection.execute(
        sa.text("SELECT id, payload FROM meeting_messages WHERE payload IS NOT NULL")
    ).mappings():
        updated = convert(message["payload"])
        if updated != message["payload"]:
            connection.execute(
                sa.text("UPDATE meeting_messages SET payload = CAST(:payload AS jsonb) WHERE id = :id"),
                {"id": message["id"], "payload": json.dumps(updated, ensure_ascii=False)},
            )


def downgrade() -> None:
    # The retired table is deliberately retained; never overwrite it with author edits.
    op.drop_index("ix_memories_book_id", table_name="memories")
    op.drop_table("memories")
