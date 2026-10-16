"""记录暂定节点由哪一卷的卷纲调整。

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("story_nodes", sa.Column("updated_by_volume", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("story_nodes", "updated_by_volume")
