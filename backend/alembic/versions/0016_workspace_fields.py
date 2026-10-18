"""新工作台：角色卡自定栏目的内容、每本书各类设定的栏目。"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("extra", postgresql.JSONB(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "books",
        sa.Column("card_layouts", postgresql.JSONB(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("books", "card_layouts")
    op.drop_column("characters", "extra")
