"""群聊的一段对话能归档：chat_conversations.archived_at（有就是收起来了，以前的对话最下面能找回）。"""

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_conversations", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_conversations", "archived_at")
