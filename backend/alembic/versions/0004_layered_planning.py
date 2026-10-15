"""layered planning: threads, volume cards, chapter outlines, foreshadowing ledger

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_LIST = sa.text("'[]'::jsonb")
JSON_DICT = sa.text("'{}'::jsonb")


def _jsonb(name: str, default=JSON_LIST) -> sa.Column:
    return sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), server_default=default, nullable=False)


def _text(name: str) -> sa.Column:
    return sa.Column(name, sa.Text(), server_default="", nullable=False)


def upgrade() -> None:
    op.add_column("books", _jsonb("requirements"))
    op.add_column("books", sa.Column("trial_read_done", sa.Boolean(), server_default=sa.false(), nullable=False))

    op.create_table(
        "story_threads",
        sa.Column("book_id", sa.Uuid(), nullable=False),
        sa.Column("index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("kind", sa.String(length=20), server_default="其他", nullable=False),
        _text("summary"),
        _jsonb("characters"),
        _jsonb("beats"),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["book_id"], ["books.id"], name=op.f("fk_story_threads_book_id_books"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_story_threads")),
        sa.UniqueConstraint("book_id", "name", name=op.f("uq_story_threads_book_id")),
    )
    op.create_index(op.f("ix_story_threads_book_id"), "story_threads", ["book_id"], unique=False)

    for name in ("stage", "climax", "antagonist", "power_range"):
        op.add_column("volumes", _text(name))
    op.add_column("volumes", _jsonb("thread_beats"))
    op.add_column("volumes", _jsonb("new_characters"))

    op.add_column("plot_units", _jsonb("thread_beats"))
    op.add_column("plot_units", _jsonb("foreshadow_actions"))
    op.add_column("plot_units", sa.Column("status", sa.String(length=20), server_default="planned", nullable=False))

    op.add_column("chapters", _jsonb("outline", JSON_DICT))
    op.add_column("chapters", _text("summary"))
    op.add_column("chapters", _jsonb("review", JSON_DICT))
    op.add_column("chapters", sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
    op.alter_column("chapters", "status", server_default="planned")
    op.create_index(op.f("ix_chapters_unit_id"), "chapters", ["unit_id"], unique=False)

    op.add_column("foreshadowings", sa.Column("seq", sa.Integer(), server_default="0", nullable=False))
    op.add_column("foreshadowings", sa.Column("span", sa.String(length=10), server_default="中", nullable=False))
    op.add_column("foreshadowings", sa.Column("plant_volume", sa.Integer(), nullable=True))
    op.add_column("foreshadowings", sa.Column("payoff_volume", sa.Integer(), nullable=True))
    op.add_column("foreshadowings", _jsonb("hint_chapters"))
    # 已有的伏笔按创建顺序编号
    op.execute(
        """
        UPDATE foreshadowings f SET seq = n.rn
        FROM (SELECT id, row_number() OVER (PARTITION BY book_id ORDER BY created_at, id) AS rn FROM foreshadowings) n
        WHERE f.id = n.id
        """
    )


def downgrade() -> None:
    for name in ("hint_chapters", "payoff_volume", "plant_volume", "span", "seq"):
        op.drop_column("foreshadowings", name)
    op.drop_index(op.f("ix_chapters_unit_id"), table_name="chapters")
    op.alter_column("chapters", "status", server_default=None)
    for name in ("attempts", "review", "summary", "outline"):
        op.drop_column("chapters", name)
    for name in ("status", "foreshadow_actions", "thread_beats"):
        op.drop_column("plot_units", name)
    for name in ("new_characters", "thread_beats", "power_range", "antagonist", "climax", "stage"):
        op.drop_column("volumes", name)
    op.drop_index(op.f("ix_story_threads_book_id"), table_name="story_threads")
    op.drop_table("story_threads")
    op.drop_column("books", "trial_read_done")
    op.drop_column("books", "requirements")
