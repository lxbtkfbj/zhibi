"""聊天摘要与作者要求的有效范围。"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("author_requirements", sa.Column("scope", sa.String(10), nullable=False, server_default="always"))
    op.add_column("author_requirements", sa.Column("chapter_index", sa.Integer(), nullable=True))
    op.add_column("author_requirements", sa.Column("volume_index", sa.Integer(), nullable=True))
    op.add_column("author_requirements", sa.Column("message_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_requirements_message",
        "author_requirements",
        "meeting_messages",
        ["message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_table(
        "chat_threads",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("book_id", postgresql.UUID(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread", sa.String(20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("summarized_until", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("reset_after", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("book_id", "thread"),
    )
    op.create_index("ix_chat_threads_book_id", "chat_threads", ["book_id"])


def downgrade() -> None:
    op.drop_table("chat_threads")
    op.drop_constraint("fk_requirements_message", "author_requirements", type_="foreignkey")
    for name in ("message_id", "volume_index", "chapter_index", "scope"):
        op.drop_column("author_requirements", name)
