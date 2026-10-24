"""Give web search its own key: copy the one it used to borrow from a DeepSeek model profile."""

from urllib.parse import urlparse

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def _host(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def upgrade() -> None:
    # 以前是借模型列表里最早建的、地址是 api.deepseek.com 的那套密钥；原样抄过去，升级后照样能搜
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT base_url, api_key_encrypted FROM llm_profiles "
            "WHERE provider = 'openai_compatible' AND api_key_encrypted <> '' ORDER BY created_at, id"
        )
    ).all()
    token = next((key for url, key in rows if _host(url) == "api.deepseek.com"), None)
    if token is None:
        return
    settings = sa.table("app_settings", sa.column("key", sa.String), sa.column("value", JSONB))
    exists = bind.execute(sa.select(settings.c.key).where(settings.c.key == "web_search")).first()
    if exists is None:
        op.bulk_insert(settings, [{"key": "web_search", "value": {"api_key_encrypted": token}}])


def downgrade() -> None:
    op.execute("DELETE FROM app_settings WHERE key = 'web_search'")
