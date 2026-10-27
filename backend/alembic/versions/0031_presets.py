"""Global author presets and their immutable save history."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "presets",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("based_on", postgresql.JSONB(), nullable=False),
        sa.Column("blocks", postgresql.JSONB(), nullable=False),
        sa.Column("saved", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_presets_kind", "presets", ["kind"])
    op.create_table(
        "preset_saves",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("preset_id", sa.UUID(), sa.ForeignKey("presets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("saved", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("blocks", postgresql.JSONB(), nullable=False),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("preset_id", "saved"),
    )
    op.create_index("ix_preset_saves_preset_id", "preset_saves", ["preset_id"])


def downgrade() -> None:
    op.execute("DELETE FROM app_settings WHERE key = 'active_preset.chief_group'")
    op.drop_index("ix_preset_saves_preset_id", table_name="preset_saves")
    op.drop_table("preset_saves")
    op.drop_index("ix_presets_kind", table_name="presets")
    op.drop_table("presets")
