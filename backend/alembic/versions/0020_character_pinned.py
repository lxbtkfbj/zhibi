"""人物置顶：characters.pinned_at（有就是置顶了，后置顶的排在上面）。原来定位是「主角」的都置顶。"""

import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("characters", sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE characters SET pinned_at = created_at WHERE role_type = '主角'")


def downgrade() -> None:
    op.drop_column("characters", "pinned_at")
