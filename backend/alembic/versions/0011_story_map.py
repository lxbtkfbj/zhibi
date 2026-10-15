"""关键节点、人物锚点、信息差与第一包数据底座。

Revision ID: 0011
Revises: 0010
"""

import string
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def legacy_nodes(spine: dict) -> list[dict]:
    """只转换旧快照，不依赖会继续演进的应用代码。"""
    nodes = []
    if spine.get("opening"):
        nodes.append({"kind": "opening", "title": "开篇", "event": spine["opening"]})
    for milestone in sorted(spine.get("milestones") or [], key=lambda item: item.get("index") or 0):
        nodes.append(
            {
                "kind": "milestone",
                "title": milestone.get("title", ""),
                "event": milestone.get("event", ""),
                "volume": milestone.get("volume"),
                "consequence": milestone.get("change", ""),
            }
        )
    if spine.get("ending"):
        nodes.append({"kind": "ending", "title": "结局", "event": spine["ending"]})
    return [
        {
            "position": index,
            "prerequisite": "",
            "consequence": "",
            "volume": None,
            "status": "pencil",
            "origin": "ai",
            "editor_note": "",
            "techniques": [],
            **node,
        }
        for index, node in enumerate(nodes, 1)
    ]


def volume_target(nodes: list[dict], volume: int, last_volume: int) -> tuple[uuid.UUID | None, bool]:
    for node in nodes:
        if node["kind"] not in {"milestone", "ending"}:
            continue
        target_volume = node["volume"]
        if node["kind"] == "ending" and target_volume is None:
            target_volume = last_volume
        if target_volume is not None and target_volume >= volume:
            return node["id"], target_volume == volume
    return None, False


def character_secrets(name: str, items: list, first_seq: int) -> list[dict]:
    out = []
    for text in items:
        if not isinstance(text, str) or not text.strip():
            continue
        out.append(
            {
                "seq": first_seq + len(out),
                "title": text[:12].rstrip(string.punctuation + "，。！？；：、…—“”‘’（）【】《》"),
                "truth": text,
                "knowers": [{"name": name, "since_chapter": None, "how": "开书设定"}],
                "reader_knows": None,
                "status": "hidden",
            }
        )
    return out


def _json(name: str, default: str = "[]") -> sa.Column:
    return sa.Column(name, postgresql.JSONB(), nullable=False, server_default=sa.text(f"'{default}'::jsonb"))


def _text(name: str) -> sa.Column:
    return sa.Column(name, sa.Text(), nullable=False, server_default="")


def _common() -> list:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("book_id", sa.Uuid(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    op.create_table(
        "story_nodes",
        *_common(),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("title", sa.String(100), nullable=False, server_default=""),
        _text("event"),
        _text("prerequisite"),
        _text("consequence"),
        sa.Column("volume", sa.Integer()),
        sa.Column("status", sa.String(10), nullable=False, server_default="pencil"),
        sa.Column("origin", sa.String(10), nullable=False, server_default="ai"),
        _text("editor_note"),
        _json("techniques"),
    )
    op.create_index("ix_story_nodes_book_id", "story_nodes", ["book_id"])
    op.create_table(
        "node_anchors",
        *_common(),
        sa.Column("node_id", sa.Uuid(), sa.ForeignKey("story_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("character_id", sa.Uuid(), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        _text("note"),
    )
    for name in ("book_id", "node_id", "character_id"):
        op.create_index(f"ix_node_anchors_{name}", "node_anchors", [name])
    op.create_table(
        "secrets",
        *_common(),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(100), nullable=False, server_default=""),
        _text("truth"),
        _json("knowers"),
        sa.Column("reader_knows", sa.String(10)),
        _text("reveal_plan"),
        sa.Column("node_id", sa.Uuid(), sa.ForeignKey("story_nodes.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(10), nullable=False, server_default="hidden"),
        sa.Column("created_chapter", sa.Integer()),
        sa.UniqueConstraint("book_id", "seq", name="uq_secrets_book_id"),
    )
    op.create_index("ix_secrets_book_id", "secrets", ["book_id"])
    op.add_column("foreshadowings", sa.Column("kind", sa.String(10), nullable=False, server_default="伏笔"))
    for table, name in (("foreshadowings", "node_id"), ("volumes", "target_node_id")):
        op.add_column(table, sa.Column(name, sa.Uuid()))
        op.create_foreign_key(
            f"fk_{table}_{name}_story_nodes", table, "story_nodes", [name], ["id"], ondelete="SET NULL"
        )
    op.add_column("volumes", sa.Column("reaches_node", sa.Boolean(), nullable=False, server_default=sa.false()))
    for table in ("volumes", "plot_units"):
        op.add_column(table, _text("editor_note"))
        op.add_column(table, _json("techniques"))
    op.add_column("plot_units", _json("reveals"))
    op.add_column("plot_units", _json("plan_issues"))
    op.add_column("books", _json("setup_progress", "{}"))

    connection = op.get_bind()
    metadata = sa.MetaData()
    books, nodes, volumes, characters, secrets = [
        sa.Table(name, metadata, autoload_with=connection)
        for name in ("books", "story_nodes", "volumes", "characters", "secrets")
    ]
    for book in connection.execute(sa.select(books)).mappings():
        spine = dict(book["spine"] or {})
        new_nodes = [{"id": uuid.uuid4(), "book_id": book["id"], **node} for node in legacy_nodes(spine)]
        for node in new_nodes:
            connection.execute(nodes.insert().values(**node))
        for key in ("opening", "milestones", "ending"):
            spine.pop(key, None)
        values = {"spine": spine}
        if book["status"] != "setting_up":
            values["setup_progress"] = {
                "mode": "oneshot",
                "current": None,
                "pieces": {key: "confirmed" for key in ("concept", "nodes", "cast", "fill", "first_volume")},
            }
        connection.execute(books.update().where(books.c.id == book["id"]).values(**values))
        book_volumes = list(connection.execute(sa.select(volumes).where(volumes.c.book_id == book["id"])).mappings())
        last_volume = max((volume["index"] for volume in book_volumes), default=0)
        for volume in book_volumes:
            target, reaches = volume_target(new_nodes, volume["index"], last_volume)
            connection.execute(
                volumes.update().where(volumes.c.id == volume["id"]).values(target_node_id=target, reaches_node=reaches)
            )
        next_seq = 1
        for character in connection.execute(
            sa.select(characters)
            .where(characters.c.book_id == book["id"])
            .order_by(characters.c.created_at, characters.c.id)
        ).mappings():
            items = character_secrets(character["name"], character["secrets"] or [], next_seq)
            for item in items:
                connection.execute(secrets.insert().values(id=uuid.uuid4(), book_id=book["id"], **item))
            next_seq += len(items)
    op.drop_column("characters", "secrets")


def downgrade() -> None:
    op.add_column("characters", _json("secrets"))
    connection = op.get_bind()
    metadata = sa.MetaData()
    books, nodes, characters, secrets = [
        sa.Table(name, metadata, autoload_with=connection) for name in ("books", "story_nodes", "characters", "secrets")
    ]
    for book in connection.execute(sa.select(books)).mappings():
        spine = {**(book["spine"] or {}), "opening": "", "ending": "", "milestones": []}
        for node in connection.execute(
            sa.select(nodes).where(nodes.c.book_id == book["id"]).order_by(nodes.c.position)
        ).mappings():
            if node["kind"] in {"opening", "ending"}:
                spine[node["kind"]] = node["event"]
            else:
                spine["milestones"].append(
                    {
                        "index": len(spine["milestones"]) + 1,
                        "title": node["title"],
                        "event": node["event"],
                        "change": node["consequence"],
                        "volume": node["volume"],
                    }
                )
        connection.execute(books.update().where(books.c.id == book["id"]).values(spine=spine))
        by_name: dict[str, list[str]] = {}
        for secret in connection.execute(
            sa.select(secrets).where(secrets.c.book_id == book["id"]).order_by(secrets.c.seq)
        ).mappings():
            for knower in secret["knowers"] or []:
                values = by_name.setdefault(knower.get("name", ""), [])
                if secret["truth"] and secret["truth"] not in values:
                    values.append(secret["truth"])
        for name, values in by_name.items():
            connection.execute(
                characters.update()
                .where(characters.c.book_id == book["id"], characters.c.name == name)
                .values(secrets=values)
            )
    op.drop_column("books", "setup_progress")
    for name in ("plan_issues", "reveals", "techniques", "editor_note"):
        op.drop_column("plot_units", name)
    for name in ("techniques", "editor_note", "reaches_node", "target_node_id"):
        op.drop_column("volumes", name)
    op.drop_column("foreshadowings", "node_id")
    op.drop_column("foreshadowings", "kind")
    for table in ("secrets", "node_anchors", "story_nodes"):
        op.drop_table(table)
