"""0014 在随机独立数据库验证旧书升级、降级和重升，不连接作者书库。"""

import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import sqlalchemy as sa
from alembic.config import Config
from psycopg import sql
from sqlalchemy.dialects.postgresql import JSONB

from alembic import command
from app.library_config import BUILTIN_CATEGORIES, OLD_CATEGORY_MAP, category_style, normalize_category


def _insert(connection, table, **values):
    """按旧表结构补必填值，避免夹具依赖 0014 的 ORM。"""
    for column in table.columns:
        if column.name in values or column.nullable or column.server_default is not None:
            continue
        if isinstance(column.type, sa.Uuid):
            values[column.name] = uuid.uuid4()
        elif isinstance(column.type, JSONB):
            values[column.name] = []
        elif isinstance(column.type, sa.Boolean):
            values[column.name] = False
        elif isinstance(column.type, sa.Integer):
            values[column.name] = 0
        else:
            values[column.name] = ""
    connection.execute(table.insert().values(**values))


def _table(connection, name):
    return sa.Table(name, sa.MetaData(), autoload_with=connection)


def _rows(connection, name):
    return [dict(row) for row in connection.execute(sa.select(_table(connection, name))).mappings()]


def _canonical_snapshot(connection):
    """迁移条目重建时 UUID 和时间会变，其余内容必须完全一致。"""
    snapshot = {}
    for table in ("books", "world_entries", "characters", "story_nodes", "volumes", "plot_units", "chapters"):
        rows = []
        for row in _rows(connection, table):
            if table == "world_entries" and row["source"] == "migration":
                row = {key: value for key, value in row.items() if key not in ("id", "created_at", "updated_at")}
            rows.append(row)
        snapshot[table] = sorted(rows, key=lambda row: str(row.get("id", row.get("name"))))
    return snapshot


def test_library_category_configuration():
    for old, new in OLD_CATEGORY_MAP.items():
        assert normalize_category(old) == new
    for category in BUILTIN_CATEGORIES:
        assert normalize_category(category["key"]) == category["key"]
        assert category_style(category["key"], {}) == category["style"]
    assert normalize_category("custom:ligui") == "custom:ligui"
    assert normalize_category("未识别的旧类别") == "特殊规则"
    assert category_style("custom:ligui", {"custom:ligui": "card"}) == "card"


def test_settings_library_upgrade_downgrade_reupgrade(migration_database_urls):
    name = f"zhibi_library_test_{uuid.uuid4().hex}"
    assert name.startswith("zhibi_library_test_") and name.replace("_", "").isalnum()
    admin_url, url = migration_database_urls(name)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    engine = sa.create_engine(url)
    try:
        command.upgrade(config, "0013")
        legacy = sa.MetaData()
        legacy.reflect(bind=engine)
        book_id, old_book_id, null_book_id, fallback_book_id = (uuid.uuid4() for _ in range(4))
        hero_id, second_hero_id, friend_id, node_id, volume_id, unit_id = (uuid.uuid4() for _ in range(6))
        world = {
            "surface": "不许盖掉已存在的世界概况。",
            "power": "凝气、筑基。越级需要燃烧寿元。",
            "maps": [
                {
                    "name": "青阳城",
                    "powers": "城主与三家",
                    "ceiling": "筑基",
                    "rules": "夜间禁行",
                    "start": "城外",
                    "gains": "残卷",
                },
                {"name": "空山", "powers": "", "ceiling": None, "rules": "人不得入", "start": "", "gains": ""},
                {"name": "青阳城", "powers": "重复的条目不能写入"},
            ],
            "far_maps": [{"name": "天外", "line": "一句远景"}],
            "shadow": "门后有人。",
            "mystery": "天为何有缝？",
            "mystery_answer": "天是牢笼。",
        }
        protagonist = {
            "name": "卡片里的旧名",
            "personality": "坚定而谨慎。",
            "style": "先退后进",
            "bottom_line": "不弃朋友",
            "voice": "话少直白",
            "start": "旧城少年。还有下一句。",
            "root": "旧约",
            "pursuit": "带所有人回家",
            "trigger": "寻找失踪者",
            "finger": "听见回声",
            "finger_later": "看见来路",
            "flaw": "怕火",
            "arc_end": "学会担当",
            "cared": [{"name": "楚青", "relation": "旧友", "why": "救命之恩"}],
        }
        with engine.begin() as connection:
            _insert(
                connection,
                legacy.tables["books"],
                id=book_id,
                title="第二包旧书",
                status="writing",
                world=world,
                protagonist=protagonist,
                concept={"title": "不能改的定调", "story": "作者的定调"},
            )
            _insert(connection, legacy.tables["books"], id=old_book_id, title="更老的书")
            _insert(
                connection,
                legacy.tables["books"],
                id=null_book_id,
                title="历史 JSON 空值",
                world=None,
                protagonist=None,
            )
            _insert(
                connection,
                legacy.tables["books"],
                id=fallback_book_id,
                title="按姓名找主角",
                protagonist={"name": "秦苏", "personality": "平静。", "cared": None},
                world={"maps": None},
            )
            _insert(connection, legacy.tables["characters"], book_id=fallback_book_id, name="秦苏", role_type="龙套")
            _insert(
                connection,
                legacy.tables["world_entries"],
                book_id=book_id,
                category="地理",
                name="世界概况",
                content="作者已经写好。保留下一句。",
            )
            _insert(
                connection,
                legacy.tables["world_entries"],
                book_id=old_book_id,
                category="力量体系",
                name="旧修炼体系",
                content="气" * 80 + "。后文",
            )
            for old in ["势力", "历史", "物品", "规则", "其他", "无类别", "世界与地图"]:
                _insert(
                    connection,
                    legacy.tables["world_entries"],
                    book_id=old_book_id,
                    category=old,
                    name=old,
                    content="第一句。第二句。",
                )
            _insert(
                connection,
                legacy.tables["characters"],
                id=hero_id,
                book_id=book_id,
                name="林岚",
                role_type="主角",
                personality="作者亲自写的性格。",
                notes="作者备注\n软肋：怕火",
                is_alive=True,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                background="",
            )
            _insert(
                connection,
                legacy.tables["characters"],
                id=second_hero_id,
                book_id=book_id,
                name="后来主角",
                role_type="主角",
                created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=1),
            )
            _insert(
                connection, legacy.tables["characters"], id=friend_id, book_id=book_id, name="楚青", role_type="反派"
            )
            _insert(
                connection,
                legacy.tables["story_nodes"],
                id=node_id,
                book_id=book_id,
                title="青阳城篇",
                position=2,
                status="pinned",
                segment={"stage": "青阳城", "goal": "出城"},
            )
            _insert(
                connection,
                legacy.tables["story_nodes"],
                book_id=book_id,
                title="保留篇",
                position=3,
                segment={"title": "作者的篇名", "text": "作者的一段话"},
            )
            _insert(connection, legacy.tables["story_nodes"], book_id=null_book_id, title="空 JSON", segment=None)
            _insert(
                connection,
                legacy.tables["volumes"],
                id=volume_id,
                book_id=book_id,
                index=1,
                title="旧卷",
                target_node_id=node_id,
            )
            _insert(
                connection,
                legacy.tables["plot_units"],
                id=unit_id,
                book_id=book_id,
                volume_id=volume_id,
                index=1,
                title="旧单元",
            )
            _insert(
                connection,
                legacy.tables["chapters"],
                book_id=book_id,
                volume_id=volume_id,
                unit_id=unit_id,
                index=1,
                title="旧章",
                content="不能改的正文。",
                outline={"goal": "旧章纲"},
                status="final",
            )
            before_books = _rows(connection, "books")
            before_chapters = _rows(connection, "chapters")
            legacy_tables = set(legacy.tables)

        command.upgrade(config, "0014")
        with engine.connect() as connection:
            assert _rows(connection, "books") == before_books
            assert _rows(connection, "chapters") == before_chapters
            entries = {(row["book_id"], row["name"]): row for row in _rows(connection, "world_entries")}
            assert len(entries) == 15
            surface = entries[book_id, "世界概况"]
            assert surface["content"] == "作者已经写好。保留下一句。"
            assert (surface["category"], surface["one_line"], surface["source"]) == (
                "世界与地图",
                "作者已经写好。",
                "ai",
            )
            power = entries[old_book_id, "旧修炼体系"]
            assert (power["category"], power["style"], power["levels"], power["one_line"]) == (
                "等级体系",
                "ladder",
                [],
                "气" * 60,
            )
            assert power["content"] == "气" * 80 + "。后文"
            for old in ["势力", "历史", "物品", "规则", "其他", "无类别", "世界与地图"]:
                assert entries[old_book_id, old]["category"] == normalize_category(old)
                assert entries[old_book_id, old]["one_line"] == "第一句。"
            assert entries[book_id, "力量体系"]["style"] == "ladder"
            assert entries[book_id, "力量体系"]["content"] == world["power"]
            assert (
                entries[book_id, "青阳城"]["content"]
                == "谁说了算：城主与三家\n天花板：筑基\n规矩：夜间禁行\n主角起步：城外\n能拿到什么：残卷"
            )
            assert entries[book_id, "空山"]["content"] == "规矩：人不得入"
            assert (entries[book_id, "天外"]["status"], entries[book_id, "天外"]["one_line"]) == ("later", "一句远景")
            assert (entries[book_id, "终极敌人的影子"]["status"], entries[book_id, "终极敌人的影子"]["one_line"]) == (
                "one",
                "门后有人。",
            )
            mystery = entries[book_id, "核心谜团"]
            assert (mystery["content"], mystery["tags"], mystery["locked"]) == (
                "谜面：天为何有缝？\n谜底：天是牢笼。",
                ["底牌"],
                True,
            )
            assert all(
                row["source"] == "migration"
                for row in entries.values()
                if row["book_id"] == book_id and row["name"] != "世界概况"
            )
            cast = {row["id"]: row for row in _rows(connection, "characters")}
            hero = cast[hero_id]
            assert hero["personality"] == "作者亲自写的性格。"
            assert hero["background"] == "旧城少年。还有下一句。\n情感根源：旧约"
            assert hero["goal"] == "长远：带所有人回家\n眼下：寻找失踪者"
            assert hero["abilities"] == "听见回声\n以后：看见来路"
            assert hero["notes"] == "作者备注\n软肋：怕火\n成长的终点：学会担当"
            assert hero["tags"] == ["金手指"] and hero["one_line"] == "旧城少年。"
            assert hero["is_alive"] is True and hero["source"] == "ai"
            assert cast[second_hero_id]["background"] == "" and cast[second_hero_id]["tags"] == []
            assert cast[friend_id]["relation"] == "旧友：救命之恩" and cast[friend_id]["role_type"] == "反派"
            fallback = next(row for row in cast.values() if row["book_id"] == fallback_book_id)
            assert (fallback["personality"], fallback["one_line"], fallback["role_type"]) == (
                "平静。",
                "平静。",
                "龙套",
            )
            nodes = {row["id"]: row for row in _rows(connection, "story_nodes")}
            assert nodes[node_id]["segment"] == {"stage": "青阳城", "goal": "出城", "title": "青阳城篇", "text": ""}
            assert nodes[node_id]["status"] == "pinned"
            assert next(row for row in nodes.values() if row["title"] == "保留篇")["segment"] == {
                "title": "作者的篇名",
                "text": "作者的一段话",
            }
            assert next(row for row in nodes.values() if row["title"] == "空 JSON")["segment"] is None
            assert _rows(connection, "plot_units")[0]["summary"] == ""
            assert _rows(connection, "volumes")[0]["locked"] is False
            snapshot = _canonical_snapshot(connection)

        inspector = sa.inspect(engine)
        assert set(inspector.get_table_names()) == legacy_tables | {
            "setting_categories",
            "setting_versions",
            "setting_candidates",
            "setting_suggestions",
        }
        fks = {fk["constrained_columns"][0]: fk for fk in inspector.get_foreign_keys("world_entries")}
        assert fks["parent_id"]["options"]["ondelete"] == "SET NULL"
        assert fks["secret_id"]["options"]["ondelete"] == "SET NULL"
        for table in ["setting_categories", "setting_versions", "setting_candidates", "setting_suggestions"]:
            assert inspector.get_foreign_keys(table)[0]["options"]["ondelete"] == "CASCADE"
            assert any(item["column_names"] == ["book_id"] for item in inspector.get_indexes(table))
        assert any(
            item["column_names"] == ["book_id", "key"]
            for item in inspector.get_unique_constraints("setting_categories")
        )
        assert any(
            item["column_names"] == ["target_type", "target_id", "version"]
            for item in inspector.get_indexes("setting_versions")
        )

        command.downgrade(config, "0013")
        assert set(sa.inspect(engine).get_table_names()) == legacy_tables
        for table in ("world_entries", "characters", "volumes", "plot_units"):
            assert {column["name"] for column in sa.inspect(engine).get_columns(table)} == set(
                legacy.tables[table].columns.keys()
            )
        with engine.connect() as connection:
            assert _rows(connection, "books") == before_books
            assert _rows(connection, "chapters") == before_chapters
            assert len(_rows(connection, "world_entries")) == 9
            categories = {row["name"]: row["category"] for row in _rows(connection, "world_entries")}
            assert categories["世界概况"] == "地理" and categories["旧修炼体系"] == "力量体系"
            assert categories["其他"] == "规则" and categories["无类别"] == "规则"
            hero = next(row for row in _rows(connection, "characters") if row["id"] == hero_id)
            assert hero["notes"] == "作者备注\n软肋：怕火\n成长的终点：学会担当"
            assert hero["background"] == "旧城少年。还有下一句。\n情感根源：旧约"
        command.upgrade(config, "0014")
        with engine.connect() as connection:
            assert _canonical_snapshot(connection) == snapshot
    finally:
        engine.dispose()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
