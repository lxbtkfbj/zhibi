"""Chat history is now given whole: clear the summaries that were folded the old, lossy way."""

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 旧摘要是照旧剪法缩的，还把编辑部的提议写成了已定；清掉，每段对话都回到整段原话
    op.execute("UPDATE chat_conversations SET summary = '', summarized_until = 0")
    # 私聊「换个话题」的分界（reset_after）不动，摘要从分界起重新算
    op.execute("UPDATE chat_threads SET summary = '', summarized_until = reset_after")


def downgrade() -> None:
    # 摘要恢复不了，也不需要恢复
    pass
