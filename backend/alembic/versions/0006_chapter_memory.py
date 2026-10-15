"""chapter writing: unit / volume recaps, lorekeeper materials, per-chapter bible change log

Revision ID: 0006
Revises: 0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _jsonb(table: str, name: str) -> None:
    op.add_column(
        table,
        sa.Column(name, postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )


def upgrade() -> None:
    op.add_column("plot_units", sa.Column("recap", sa.Text(), server_default="", nullable=False))
    op.add_column("volumes", sa.Column("recap", sa.Text(), server_default="", nullable=False))
    _jsonb("chapters", "materials")
    _jsonb("chapters", "bible_changes")


def downgrade() -> None:
    op.drop_column("chapters", "bible_changes")
    op.drop_column("chapters", "materials")
    op.drop_column("volumes", "recap")
    op.drop_column("plot_units", "recap")
