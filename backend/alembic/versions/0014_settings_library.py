"""第三包数据底座：设定库、版本、候选和建议。

Revision ID: 0014
Revises: 0013

数据映射在本迁移中冻结，不导入会随产品演进的配置或 ORM。
降级保留角色已补的正文，但删除新增列及迁移来源的设定条目。
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

OLD_CATEGORY_MAP = {
    "地理": "世界与地图",
    "势力": "势力划分",
    "力量体系": "等级体系",
    "历史": "往事与秘密",
    "物品": "物品与功法",
    "规则": "特殊规则",
    "其他": "特殊规则",
}
WORLD_COLUMNS = {
    "style": (sa.String(10), "paragraph"),
    "status": (sa.String(10), "must"),
    "tags": (postgresql.JSONB(), "[]"),
    "one_line": (sa.Text(), ""),
    "aliases": (postgresql.JSONB(), "[]"),
    "fields": (postgresql.JSONB(), "[]"),
    "levels": (postgresql.JSONB(), "[]"),
    "locked": (sa.Boolean(), "false"),
    "source": (sa.String(20), "ai"),
    "position": (sa.Integer(), "0"),
}
CHARACTER_COLUMNS = {
    "one_line": (sa.Text(), ""),
    "relation": (sa.Text(), ""),
    "status": (sa.String(10), "must"),
    "tags": (postgresql.JSONB(), "[]"),
    "locked": (sa.Boolean(), "false"),
    "source": (sa.String(20), "ai"),
    "position": (sa.Integer(), "0"),
}


def _book_id():
    return sa.Column("book_id", postgresql.UUID(), sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False)


def _created_at():
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    # custom: 加最多 40 字符的类别 key，旧 String(30) 容纳不下。
    op.alter_column("world_entries", "category", existing_type=sa.String(30), type_=sa.String(47))
    for table, columns in (("world_entries", WORLD_COLUMNS), ("characters", CHARACTER_COLUMNS)):
        for name, (kind, default) in columns.items():
            op.add_column(table, sa.Column(name, kind, nullable=False, server_default=default))
    op.add_column("world_entries", sa.Column("parent_id", postgresql.UUID(), nullable=True))
    op.add_column("world_entries", sa.Column("secret_id", postgresql.UUID(), nullable=True))
    op.add_column("world_entries", sa.Column("created_chapter", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_world_entries_parent_id_world_entries",
        "world_entries",
        "world_entries",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_world_entries_secret_id_secrets", "world_entries", "secrets", ["secret_id"], ["id"], ondelete="SET NULL"
    )
    op.add_column("plot_units", sa.Column("summary", sa.Text(), nullable=False, server_default=""))
    for table in ("plot_units", "volumes"):
        op.add_column(table, sa.Column("locked", sa.Boolean(), nullable=False, server_default="false"))

    op.create_table(
        "setting_categories",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        _book_id(),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("style", sa.String(10), nullable=False),
        sa.Column("fields", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("hint", sa.Text(), nullable=False, server_default=""),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        _created_at(),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("book_id", "key"),
    )
    op.create_table(
        "setting_versions",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        _book_id(),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", postgresql.UUID(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        _created_at(),
    )
    op.create_index("ix_setting_versions_target", "setting_versions", ["target_type", "target_id", "version"])
    op.create_table(
        "setting_candidates",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        _book_id(),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", postgresql.UUID(), nullable=False),
        sa.Column("path", sa.String(200), nullable=False),
        sa.Column("base", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column("chosen", sa.Integer(), nullable=True),
        _created_at(),
    )
    op.create_table(
        "setting_suggestions",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        _book_id(),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=True),
        sa.Column("target_id", postgresql.UUID(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("origin", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        _created_at(),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    for table in ("setting_categories", "setting_versions", "setting_candidates", "setting_suggestions"):
        op.create_index(f"ix_{table}_book_id", table, ["book_id"])
    _migrate_books()


def _text(value):
    return value if isinstance(value, str) else ""


def _items(value):
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _first_sentence(value):
    text = _text(value)
    first, stop, _ = text.partition("。")
    return (first + stop)[:60]


def _lines(*items):
    return "\n".join(text for text in items if text)


def _label(label, value):
    text = _text(value)
    return f"{label}：{text}" if text else ""


def _category(value):
    if value in OLD_CATEGORY_MAP:
        return OLD_CATEGORY_MAP[value]
    if value in OLD_CATEGORY_MAP.values() or value.startswith("custom:"):
        return value
    return "特殊规则"


def _migrate_books():
    connection = op.get_bind()
    metadata = sa.MetaData()
    books = sa.Table("books", metadata, autoload_with=connection)
    entries = sa.Table("world_entries", metadata, autoload_with=connection)
    characters = sa.Table("characters", metadata, autoload_with=connection)
    nodes = sa.Table("story_nodes", metadata, autoload_with=connection)
    for book in connection.execute(sa.select(books)).mappings():
        book_id = book["id"]
        existing = set()
        for entry in connection.execute(sa.select(entries).where(entries.c.book_id == book_id)).mappings():
            category = _category(entry["category"])
            connection.execute(
                entries.update()
                .where(entries.c.id == entry["id"])
                .values(
                    category=category,
                    style="ladder" if category == "等级体系" else "paragraph",
                    one_line=_first_sentence(entry["content"]),
                )
            )
            existing.add((category, entry["name"]))

        def add(category, name, *, existing=existing, book_id=book_id, **values):
            if not name or (category, name) in existing:
                return
            connection.execute(
                entries.insert().values(
                    id=uuid.uuid4(),
                    book_id=book_id,
                    category=category,
                    name=name,
                    content=values.pop("content", ""),
                    source="migration",
                    **values,
                )
            )
            existing.add((category, name))

        world = book["world"] if isinstance(book["world"], dict) else {}
        if _text(world.get("surface")):
            add("世界与地图", "世界概况", content=world["surface"], position=0)
        if _text(world.get("power")):
            add("等级体系", "力量体系", style="ladder", content=world["power"])
        for item in _items(world.get("maps")):
            add(
                "世界与地图",
                _text(item.get("name")),
                content=_lines(
                    _label("谁说了算", item.get("powers")),
                    _label("天花板", item.get("ceiling")),
                    _label("规矩", item.get("rules")),
                    _label("主角起步", item.get("start")),
                    _label("能拿到什么", item.get("gains")),
                ),
            )
        for item in _items(world.get("far_maps")):
            add("世界与地图", _text(item.get("name")), status="later", one_line=_text(item.get("line")))
        if _text(world.get("shadow")):
            add("往事与秘密", "终极敌人的影子", status="one", one_line=world["shadow"])
        mystery, answer = _text(world.get("mystery")), _text(world.get("mystery_answer"))
        if mystery or answer:
            add(
                "往事与秘密",
                "核心谜团",
                content=_lines(_label("谜面", mystery), _label("谜底", answer)),
                tags=["底牌"] if answer else [],
                locked=bool(answer),
            )

        cast = [
            dict(row)
            for row in connection.execute(
                sa.select(characters)
                .where(characters.c.book_id == book_id)
                .order_by(characters.c.created_at, characters.c.id)
            ).mappings()
        ]
        protagonist = book["protagonist"] if isinstance(book["protagonist"], dict) else {}
        hero = next((item for item in cast if item["role_type"] == "主角"), None)
        if hero is None and _text(protagonist.get("name")):
            hero = next((item for item in cast if item["name"] == protagonist["name"]), None)
        if protagonist and hero is not None:
            values = {
                "personality": _lines(
                    _text(protagonist.get("personality")),
                    _label("做事", protagonist.get("style")),
                    _label("底线", protagonist.get("bottom_line")),
                    _label("说话", protagonist.get("voice")),
                ),
                "background": _lines(_text(protagonist.get("start")), _label("情感根源", protagonist.get("root"))),
                "goal": _lines(_label("长远", protagonist.get("pursuit")), _label("眼下", protagonist.get("trigger"))),
                "abilities": _lines(_text(protagonist.get("finger")), _label("以后", protagonist.get("finger_later"))),
            }
            for key, value in values.items():
                if not hero[key]:
                    hero[key] = value
            for note in (_label("软肋", protagonist.get("flaw")), _label("成长的终点", protagonist.get("arc_end"))):
                if note and note not in hero["notes"]:
                    hero["notes"] = _lines(hero["notes"], note)
            if _text(protagonist.get("finger")) and "金手指" not in hero["tags"]:
                hero["tags"] = [*hero["tags"], "金手指"]
            for cared in _items(protagonist.get("cared")):
                person = next((item for item in cast if item["name"] == cared.get("name")), None)
                if person is not None and not person["relation"]:
                    relation, why = _text(cared.get("relation")), _text(cared.get("why"))
                    person["relation"] = f"{relation}：{why}" if relation or why else ""
        for person in cast:
            if not person["one_line"]:
                person["one_line"] = _first_sentence(person["background"] or person["personality"])
            connection.execute(
                characters.update()
                .where(characters.c.id == person["id"])
                .values(
                    **{
                        key: person[key]
                        for key in (
                            "personality",
                            "background",
                            "goal",
                            "abilities",
                            "notes",
                            "tags",
                            "relation",
                            "one_line",
                        )
                    }
                )
            )

        for node in connection.execute(sa.select(nodes).where(nodes.c.book_id == book_id)).mappings():
            segment = node["segment"]
            if isinstance(segment, dict) and segment and "title" not in segment:
                segment = {**segment, "title": node["title"]}
                segment.setdefault("text", "")
                connection.execute(nodes.update().where(nodes.c.id == node["id"]).values(segment=segment))


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(sa.text("DELETE FROM world_entries WHERE source = 'migration'"))
    reverse = {
        "世界与地图": "地理",
        "势力划分": "势力",
        "等级体系": "力量体系",
        "往事与秘密": "历史",
        "物品与功法": "物品",
        "特殊规则": "规则",
    }
    for new, old in reverse.items():
        connection.execute(
            sa.text("UPDATE world_entries SET category = :old WHERE category = :new"), {"old": old, "new": new}
        )
    connection.execute(sa.text("UPDATE world_entries SET category = '其他' WHERE category LIKE 'custom:%'"))
    for table in ("setting_suggestions", "setting_candidates", "setting_versions", "setting_categories"):
        op.drop_table(table)
    for table in ("plot_units", "volumes"):
        op.drop_column(table, "locked")
    op.drop_column("plot_units", "summary")
    for name in ("parent_id", "secret_id", "created_chapter", *WORLD_COLUMNS):
        op.drop_column("world_entries", name)
    for name in CHARACTER_COLUMNS:
        op.drop_column("characters", name)
    op.alter_column("world_entries", "category", existing_type=sa.String(47), type_=sa.String(30))
