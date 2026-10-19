"""本书设置的「其他规矩」并进写作要求：每一行挪成一条一直有效的写作要求，设置里清空。

新书默认里的其他规矩不动：新建的书建好时照样挪进那本书的写作要求（services/requirements.absorb_other_rules）。"""

import json
import uuid

import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, settings->>'other_rules' FROM books WHERE coalesce(settings->>'other_rules', '') <> ''")
    ).fetchall()
    for book_id, rules in rows:
        have = set(conn.execute(sa.text("SELECT text FROM author_requirements WHERE book_id = :book"), {"book": book_id}).scalars())
        for line in dict.fromkeys(line.strip() for line in rules.splitlines() if line.strip()):
            if line in have:
                continue
            conn.execute(
                sa.text(
                    "INSERT INTO author_requirements (id, book_id, text, source, scope) "
                    "VALUES (:id, :book, :text, 'manual', 'always')"
                ),
                {"id": uuid.uuid4(), "book": book_id, "text": line},
            )
        conn.execute(
            sa.text("UPDATE books SET settings = settings || CAST(:patch AS jsonb) WHERE id = :book"),
            {"patch": json.dumps({"other_rules": ""}), "book": book_id},
        )


def downgrade() -> None:
    # 挪过去的已经和别的写作要求混在一起，分不出来；退回去也不影响读写
    pass
