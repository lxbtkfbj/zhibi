"""Separate ordinary chat tool capability from structured output selection."""

import sqlalchemy as sa

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("llm_profiles", sa.Column("chat_tools", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_profiles", "chat_tools")
