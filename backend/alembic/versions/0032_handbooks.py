"""Handbooks and immutable saves; move legacy skills overrides without trimming their bodies."""

import hashlib
import re
import uuid
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def _parts(content):
    # Frozen migration parser: remove only the first heading and first directory line.
    lines = content.splitlines(keepends=True)
    name = lines.pop(0).rstrip("\r\n").removeprefix("# ").strip() if lines else ""
    when = ""
    for index, line in enumerate(lines):
        if line.startswith("什么时候翻："):
            when = line.removeprefix("什么时候翻：").strip()
            lines.pop(index)
            break
    while lines and not lines[0].strip():
        lines.pop(0)
    return name, when, "".join(lines)


def _files():
    folder = Path(__file__).resolve().parents[2] / "app" / "prompts" / "skills"
    return {
        path.stem: path.read_bytes()
        for path in sorted(folder.glob("*.md"))
        if re.fullmatch(r"[a-z][a-z0-9_]*", path.stem)
    }


def upgrade() -> None:
    handbooks = op.create_table(
        "handbooks",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("when", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("system_hash", sa.String(64), nullable=True),
        sa.Column("saved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    saves = op.create_table(
        "handbook_saves",
        sa.Column("key", sa.String(100), sa.ForeignKey("handbooks.key", ondelete="CASCADE"), primary_key=True),
        sa.Column("saved", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("when", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("restore_saved", sa.Integer(), nullable=True),
        sa.Column("follows_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    connection = op.get_bind()
    files = _files()
    overrides = (
        connection.execute(
            sa.text("SELECT name, content, updated_at FROM prompt_overrides WHERE name LIKE 'skills.%' ORDER BY name")
        )
        .mappings()
        .all()
    )
    for override in overrides:
        old_key = override["name"].split(".", 1)[1]
        system = old_key in files
        key = old_key if system else "mine_" + uuid.uuid4().hex
        name, when, body = _parts(override["content"])
        connection.execute(
            handbooks.insert().values(
                key=key,
                source="system" if system else "mine",
                enabled=system,
                name=name,
                when=when,
                body=body,
                saved=1,
                system_hash=hashlib.sha256(files[old_key]).hexdigest() if system else None,
                created_at=override["updated_at"],
                updated_at=override["updated_at"],
            )
        )
        connection.execute(
            saves.insert().values(
                key=key, saved=1, name=name, when=when, body=body, kind="migrated", saved_at=override["updated_at"]
            )
        )
        connection.execute(sa.text("DELETE FROM prompt_overrides WHERE name = :name"), {"name": override["name"]})


def downgrade() -> None:
    connection = op.get_bind()
    overrides = sa.table("prompt_overrides", sa.column("name"), sa.column("content"), sa.column("updated_at"))
    for row in connection.execute(
        sa.text("SELECT * FROM handbooks WHERE source = 'system' AND name IS NOT NULL")
    ).mappings():
        content = f"# {row['name']}\n\n什么时候翻：{row['when']}\n\n{row['body']}"
        statement = insert(overrides).values(name="skills." + row["key"], content=content, updated_at=row["updated_at"])
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=["name"],
                set_={"content": statement.excluded.content, "updated_at": statement.excluded.updated_at},
            )
        )
    op.drop_table("handbook_saves")
    op.drop_table("handbooks")
