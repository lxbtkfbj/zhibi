"""plot units: tropes and resolution (genre playbook, anti-repetition)

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "plot_units",
        sa.Column(
            "tropes", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
    )
    op.add_column("plot_units", sa.Column("resolution", sa.Text(), server_default="", nullable=False))


def downgrade() -> None:
    op.drop_column("plot_units", "resolution")
    op.drop_column("plot_units", "tropes")
