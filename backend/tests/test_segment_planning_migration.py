"""在随机独立测试库执行 0012 → 0013 → 0012 → 0013，保留所有旧行。"""

import uuid

import psycopg
import sqlalchemy as sa
from alembic.config import Config
from psycopg import sql
from sqlalchemy.dialects.postgresql import JSONB

from alembic import command

NEW_COLUMNS = {
    "books": {"protagonist": {}, "world": {}},
    "story_nodes": {"segment": None},
    "characters": {"want": ""},
    "volumes": {"want": "", "pressure": ""},
    "plot_units": {"loop": ""},
}
TABLES = (*NEW_COLUMNS, "chapters")


def insert_legacy_row(connection, table, **values):
    """只用旧表定义补齐必填列，不借用已更新的 ORM。"""
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


def old_rows(connection, metadata):
    return {
        name: [dict(row) for row in connection.execute(sa.select(metadata.tables[name])).mappings()] for name in TABLES
    }


def assert_new_columns(engine, before):
    inspector = sa.inspect(engine)
    with engine.connect() as connection:
        for table, expected in NEW_COLUMNS.items():
            columns = {column["name"]: column for column in inspector.get_columns(table)}
            assert set(columns) == set(before.tables[table].columns.keys()) | set(expected)
            for name, default in expected.items():
                column = columns[name]
                assert column["nullable"] is (default is None)
                assert isinstance(column["type"], JSONB if default is None or isinstance(default, dict) else sa.Text)
                assert (column["default"] is None) is (default is None)
                assert connection.scalar(sa.text(f'SELECT "{name}" FROM "{table}"')) == default
        assert connection.scalar(sa.text("SELECT segment IS NULL FROM story_nodes")) is True


def test_segment_planning_upgrade_downgrade_reupgrade_preserves_legacy_rows():
    name = f"zhibi_segment_test_{uuid.uuid4().hex}"
    assert name.startswith("zhibi_segment_test_") and name.replace("_", "").isalnum()
    admin_url = "postgresql://zhibi:zhibi@127.0.0.1:5433/postgres"
    url = f"postgresql+psycopg://zhibi:zhibi@127.0.0.1:5433/{name}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    engine = sa.create_engine(url)
    try:
        command.upgrade(config, "0012")
        legacy = sa.MetaData()
        legacy.reflect(bind=engine)
        book_id, node_id, volume_id, unit_id = (uuid.uuid4() for _ in range(4))
        with engine.begin() as connection:
            insert_legacy_row(
                connection,
                legacy.tables["books"],
                id=book_id,
                title="第二包旧书迁移验收",
                concept={"title": "旧书", "protagonist_hook": "找回妹妹"},
                spine={"theme": "信任"},
                settings={"volume_approval": False},
                status="writing",
            )
            insert_legacy_row(
                connection,
                legacy.tables["story_nodes"],
                id=node_id,
                book_id=book_id,
                position=1,
                kind="milestone",
                title="作者钉死的节点",
                status="pinned",
                origin="author",
                event="不许改的事件",
                updated_by_volume=1,
            )
            insert_legacy_row(
                connection,
                legacy.tables["characters"],
                book_id=book_id,
                name="林岚",
                aliases=["小岚"],
                notes="作者备注",
                is_alive=True,
                goal="找到妹妹",
            )
            insert_legacy_row(
                connection,
                legacy.tables["volumes"],
                id=volume_id,
                book_id=book_id,
                index=1,
                title="入城",
                status="approved",
                target_node_id=node_id,
            )
            insert_legacy_row(
                connection,
                legacy.tables["plot_units"],
                id=unit_id,
                book_id=book_id,
                volume_id=volume_id,
                index=1,
                title="接案",
                chapter_count=5,
            )
            insert_legacy_row(
                connection,
                legacy.tables["chapters"],
                book_id=book_id,
                volume_id=volume_id,
                unit_id=unit_id,
                index=1,
                title="失踪",
                content="不可改动的作者正文。\n门外的雨还在下。",
                outline={"goal": "找信"},
                status="final",
            )
            snapshot = old_rows(connection, legacy)
        command.upgrade(config, "0013")
        assert_new_columns(engine, legacy)
        with engine.connect() as connection:
            assert old_rows(connection, legacy) == snapshot
            current = sa.MetaData()
            current.reflect(bind=connection)
            # 直接 SQL INSERT 省略新列，确认 server_default 对新行同样有效。
            fresh_id = uuid.uuid4()
            insert_legacy_row(connection, legacy.tables["books"], id=fresh_id, title="默认值校验书")
            fresh = connection.execute(
                sa.select(current.tables["books"].c.protagonist, current.tables["books"].c.world).where(
                    current.tables["books"].c.id == fresh_id
                )
            ).one()
            assert tuple(fresh) == ({}, {})
            for table, fields in NEW_COLUMNS.items():
                if table == "books":
                    continue
                values = dict(snapshot[table][0])
                values["id"], values["book_id"] = uuid.uuid4(), fresh_id
                if table == "plot_units":
                    values["index"] = 2
                connection.execute(legacy.tables[table].insert().values(**values))
                inserted = connection.execute(
                    sa.select(*(current.tables[table].c[field] for field in fields)).where(
                        current.tables[table].c.id == values["id"]
                    )
                ).one()
                assert tuple(inserted) == tuple(fields.values())
            connection.rollback()
        command.downgrade(config, "0012")
        for table in NEW_COLUMNS:
            assert {column["name"] for column in sa.inspect(engine).get_columns(table)} == set(
                legacy.tables[table].columns.keys()
            )
        with engine.connect() as connection:
            assert old_rows(connection, legacy) == snapshot
        command.upgrade(config, "0013")
        assert_new_columns(engine, legacy)
        with engine.connect() as connection:
            assert old_rows(connection, legacy) == snapshot
    finally:
        engine.dispose()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
