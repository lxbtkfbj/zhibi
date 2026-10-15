"""Global prompt overrides and request / raw response observability.

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_overrides",
        sa.Column("name", sa.String(100), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column("llm_calls", sa.Column("request", postgresql.JSONB(), nullable=True))
    op.add_column("llm_calls", sa.Column("response", sa.Text(), nullable=True))
    op.create_index("ix_llm_calls_book_id_id", "llm_calls", ["book_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_book_id_id", table_name="llm_calls")
    op.drop_column("llm_calls", "response")
    op.drop_column("llm_calls", "request")
    op.drop_table("prompt_overrides")
