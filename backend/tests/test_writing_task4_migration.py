"""迁移 0012 在隔离 schema 升降级，旧节点文字与作者状态原样保留。"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


async def test_node_updated_by_volume_upgrade_and_downgrade(sessionmaker):
    spec = importlib.util.spec_from_file_location(
        "node_volume_migration", Path("alembic/versions/0012_node_updated_by_volume.py")
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "0012" and migration.down_revision == "0011"
    async with sessionmaker() as session:
        connection = await session.connection()

        def migrate(sync_connection):
            sync_connection.execute(sa.text("CREATE SCHEMA task4_migration_test"))
            sync_connection.execute(sa.text("SET LOCAL search_path TO task4_migration_test"))
            sync_connection.execute(
                sa.text("CREATE TABLE story_nodes (id int PRIMARY KEY, title text, status text, origin text)")
            )
            sync_connection.execute(sa.text("INSERT INTO story_nodes VALUES (1, '作者的节点', 'pinned', 'author')"))
            migration.op = Operations(MigrationContext.configure(sync_connection))
            migration.upgrade()
            row = sync_connection.execute(sa.text("SELECT * FROM story_nodes")).one()
            assert tuple(row) == (1, "作者的节点", "pinned", "author", None)
            columns = {column["name"]: column for column in sa.inspect(sync_connection).get_columns("story_nodes")}
            assert columns["updated_by_volume"]["nullable"]
            sync_connection.execute(sa.text("UPDATE story_nodes SET updated_by_volume = 2"))
            assert sync_connection.scalar(sa.text("SELECT updated_by_volume FROM story_nodes")) == 2
            migration.downgrade()
            assert tuple(sync_connection.execute(sa.text("SELECT * FROM story_nodes")).one()) == (
                1,
                "作者的节点",
                "pinned",
                "author",
            )
            assert "updated_by_volume" not in {
                column["name"] for column in sa.inspect(sync_connection).get_columns("story_nodes")
            }
            migration.upgrade()
            assert sync_connection.scalar(sa.text("SELECT updated_by_volume FROM story_nodes")) is None

        await connection.run_sync(migrate)
        await session.rollback()
