"""整本书的存档：book_objects 按内容存，book_saves 一档一行。"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "book_objects",
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_book_objects_book_id_books"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("book_id", "hash", name=op.f("pk_book_objects")),
    )
    op.create_table(
        "book_saves",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("clock_timestamp()"), nullable=False
        ),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("actor", sa.String(length=20), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tree", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("chapters_final", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("restored_from", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_book_saves_book_id_books"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["book_saves.id"], name=op.f("fk_book_saves_parent_id_book_saves"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["restored_from"],
            ["book_saves.id"],
            name=op.f("fk_book_saves_restored_from_book_saves"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_book_saves")),
    )
    op.create_index("ix_book_saves_book", "book_saves", ["book_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_book_saves_book", table_name="book_saves")
    op.drop_table("book_saves")
    op.drop_table("book_objects")
