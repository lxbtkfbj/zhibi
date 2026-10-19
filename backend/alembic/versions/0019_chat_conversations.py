"""群聊分成一段段对话：chat_conversations 一段一行，消息的 payload.conv 记着属于哪一段。

以前的群聊补成一段；换过话题（chat_threads 里群聊的 reset_after）的，换之前那些话另成一段。
私聊（payload.thread）不分段，照旧用 chat_threads。
"""

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

TITLE_LIMIT = 20
GROUP = "(m.payload IS NULL OR m.payload->>'thread' IS NULL)"
# 有的消息 payload 存的是 JSON 的 null，不能直接拼
OBJECT = "CASE WHEN jsonb_typeof(payload) = 'object' THEN payload ELSE '{}'::jsonb END"


def title_of(text):
    text = " ".join((text or "").split())
    return text[:TITLE_LIMIT] + ("…" if len(text) > TITLE_LIMIT else "")


def backfill(connection):
    books = connection.execute(sa.text(f"SELECT DISTINCT m.book_id FROM meeting_messages m WHERE {GROUP}")).scalars()
    for book_id in list(books):
        thread = connection.execute(
            sa.text(
                "SELECT reset_after, summary, summarized_until FROM chat_threads "
                "WHERE book_id = :b AND thread = 'group'"
            ),
            {"b": book_id},
        ).first()
        reset = thread.reset_after if thread else 0
        notes = f"{GROUP} AND m.speaker = 'author' AND m.kind = 'note'"
        before = reset and connection.scalar(
            sa.text(f"SELECT 1 FROM meeting_messages m WHERE m.book_id = :b AND m.id <= :r AND {notes} LIMIT 1"),
            {"b": book_id, "r": reset},
        )
        # 换话题之前说过话的：那些话另成一段；没说过的（只有编辑部干活的进度）并进后面那一段
        spans = [(0, reset, "", 0), (reset, None, thread.summary, thread.summarized_until)] if before else []
        spans = spans or [(0, None, thread.summary if thread else "", thread.summarized_until if thread else 0)]
        for low, high, summary, until in spans:
            where = "m.book_id = :b AND m.id > :low" + (" AND m.id <= :high" if high is not None else "")
            values = {"b": book_id, "low": low, "high": high}
            first = connection.scalar(
                sa.text(f"SELECT m.content FROM meeting_messages m WHERE {where} AND {notes} ORDER BY m.id LIMIT 1"),
                values,
            )
            span = connection.execute(
                sa.text(
                    f"SELECT min(m.created_at) AS created, max(m.created_at) FILTER (WHERE {notes}) AS spoke "
                    f"FROM meeting_messages m WHERE {where} AND {GROUP}"
                ),
                values,
            ).one()
            conv = connection.scalar(
                sa.text(
                    "INSERT INTO chat_conversations (id, book_id, title, created_at, last_at, summary, summarized_until) "
                    "VALUES (gen_random_uuid(), :b, :title, coalesce(:created, now()), "
                    "coalesce(:spoke, :created, now()), :summary, :until) RETURNING id"
                ),
                {
                    "b": book_id,
                    "title": title_of(first),
                    "created": span.created,
                    "spoke": span.spoke,
                    "summary": summary or "",
                    "until": until or 0,
                },
            )
            connection.execute(
                sa.text(
                    f"UPDATE meeting_messages m SET payload = {OBJECT} || jsonb_build_object('conv', CAST(:c AS text)) "
                    f"WHERE {where} AND {GROUP}"
                ),
                {**values, "c": str(conv)},
            )


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False
        ),
        sa.Column("last_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("summarized_until", sa.BigInteger(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_chat_conversations_book_id_books"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_conversations")),
    )
    op.create_index(op.f("ix_chat_conversations_book_id"), "chat_conversations", ["book_id"])
    backfill(op.get_bind())


def downgrade() -> None:
    op.execute("UPDATE meeting_messages SET payload = payload - 'conv' WHERE jsonb_typeof(payload) = 'object'")
    op.drop_index(op.f("ix_chat_conversations_book_id"), table_name="chat_conversations")
    op.drop_table("chat_conversations")
