"""第二包数据底座：主角卡、世界与地图、段规划及当前目标。

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("books", sa.Column("protagonist", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.add_column("books", sa.Column("world", postgresql.JSONB(), nullable=False, server_default="{}"))
    op.add_column("story_nodes", sa.Column("segment", postgresql.JSONB(), nullable=True))
    op.add_column("characters", sa.Column("want", sa.Text(), nullable=False, server_default=""))
    op.add_column("volumes", sa.Column("want", sa.Text(), nullable=False, server_default=""))
    op.add_column("volumes", sa.Column("pressure", sa.Text(), nullable=False, server_default=""))
    op.add_column("plot_units", sa.Column("loop", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("plot_units", "loop")
    op.drop_column("volumes", "pressure")
    op.drop_column("volumes", "want")
    op.drop_column("characters", "want")
    op.drop_column("story_nodes", "segment")
    op.drop_column("books", "world")
    op.drop_column("books", "protagonist")
