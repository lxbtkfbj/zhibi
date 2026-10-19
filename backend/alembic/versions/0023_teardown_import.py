"""拆书第一批：书、章的拆书信息及只在确认期间保留的原文件。"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("books", sa.Column("teardown", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.add_column("chapters", sa.Column("teardown", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.create_table(
        "teardown_sources",
        sa.Column("book_id", sa.Uuid(), sa.ForeignKey("books.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("encoding", sa.String(20), nullable=False, server_default=""),
        sa.Column("preview", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("teardown_sources")
    op.drop_column("chapters", "teardown")
    op.drop_column("books", "teardown")
