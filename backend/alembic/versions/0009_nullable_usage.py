"""Distinguish missing future provider usage from an explicit zero.

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing zero values are intentionally untouched: historical availability cannot be inferred.
    for name in ("prompt_tokens", "completion_tokens"):
        op.alter_column("llm_calls", name, existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    for name in ("prompt_tokens", "completion_tokens"):
        op.execute(sa.text(f"UPDATE llm_calls SET {name}=0 WHERE {name} IS NULL"))
        op.alter_column("llm_calls", name, existing_type=sa.Integer(), nullable=False)
