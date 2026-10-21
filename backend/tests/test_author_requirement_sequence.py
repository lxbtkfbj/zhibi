"""要求的先后由数据库自增号决定；迁移只给旧行补号，不改作者内容。"""

import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import psycopg
import sqlalchemy as sa
from alembic.config import Config
from psycopg import sql
from sqlalchemy.dialects.postgresql import JSONB

from alembic import command
from app.models import AppSetting, AuthorRequirement, Book
from app.services.requirements import add_requirement, list_requirements


@contextmanager
def legacy_database(migration_database_urls):
    """另建随机库，所有连接仍只使用调用方指定的隔离测试实例。"""
    name = f"zhibi_requirement_sequence_test_{uuid.uuid4().hex}"
    admin_url, url = migration_database_urls(name)
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    engine = sa.create_engine(url)
    try:
        command.upgrade(config, "0025")
        metadata = sa.MetaData()
        metadata.reflect(bind=engine)
        yield config, engine, metadata
    finally:
        engine.dispose()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def insert_legacy_row(connection, table, **values):
    """只按旧表反射定义补齐必填值，避免已更新的 ORM 偷带 seq。"""
    for column in table.columns:
        if column.name in values or column.nullable or column.server_default is not None:
            continue
        if isinstance(column.type, sa.Uuid):
            values[column.name] = uuid.uuid4()
        elif isinstance(column.type, JSONB):
            values[column.name] = {}
        elif isinstance(column.type, sa.Boolean):
            values[column.name] = False
        elif isinstance(column.type, sa.Integer):
            values[column.name] = 0
        elif isinstance(column.type, sa.DateTime):
            values[column.name] = datetime(2020, 1, 1, tzinfo=UTC)
        else:
            values[column.name] = ""
    connection.execute(table.insert().values(**values))


def legacy_rows(connection, metadata):
    return {
        name: [
            dict(row)
            for row in connection.execute(
                sa.select(metadata.tables[name]).order_by(metadata.tables[name].c.id)
            ).mappings()
        ]
        for name in ("books", "author_requirements")
    } | {
        "app_settings": [
            dict(row)
            for row in connection.execute(
                sa.select(metadata.tables["app_settings"]).order_by(metadata.tables["app_settings"].c.key)
            ).mappings()
        ]
    }


def assert_sequence_schema(engine):
    inspector = sa.inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("author_requirements")}
    column = columns["seq"]
    assert isinstance(column["type"], sa.Integer)
    assert column["nullable"] is False
    assert column["identity"]["always"] is False
    assert any(index["column_names"] == ["seq"] for index in inspector.get_indexes("author_requirements"))
    with engine.connect() as connection:
        values = list(connection.scalars(sa.text("SELECT seq FROM author_requirements ORDER BY seq")))
        assert all(isinstance(value, int) and value > 0 for value in values)
        assert len(values) == len(set(values))
        return connection.scalar(sa.text("SELECT pg_get_serial_sequence('author_requirements', 'seq')"))


def assert_old_order_and_next_value(engine, metadata, expected, snapshot):
    with engine.connect() as connection:
        assert legacy_rows(connection, metadata) == snapshot
        for book_id, ids in expected.items():
            assert (
                list(
                    connection.scalars(
                        sa.text("SELECT id FROM author_requirements WHERE book_id = :book_id ORDER BY seq"),
                        {"book_id": book_id},
                    )
                )
                == ids
            )
        maximum = connection.scalar(sa.text("SELECT max(seq) FROM author_requirements"))
        fresh_id = uuid.uuid4()
        insert_legacy_row(
            connection,
            metadata.tables["author_requirements"],
            id=fresh_id,
            book_id=next(iter(expected)),
            text="迁移后新增，不传 seq",
            source="manual",
        )
        assert (
            connection.scalar(sa.text("SELECT seq FROM author_requirements WHERE id = :id"), {"id": fresh_id})
            == maximum + 1
        )
        connection.rollback()


def test_sequence_migration_preserves_each_books_legacy_order_and_all_old_fields(migration_database_urls):
    with legacy_database(migration_database_urls) as (config, engine, metadata):
        requirements = metadata.tables["author_requirements"]
        defaults = {
            column["name"]: column["default"] for column in sa.inspect(engine).get_columns("author_requirements")
        }
        book_ids = [uuid.UUID(int=100 + index) for index in range(3)]
        with engine.begin() as connection:
            for index, book_id in enumerate(book_ids):
                insert_legacy_row(connection, metadata.tables["books"], id=book_id, title=f"保留旧要求 {index}")
                timestamp = datetime(2022 + index, 1, 1, tzinfo=UTC)
                # 插入顺序既不是时间顺序，也不是 UUID 顺序；同一时间必须保留旧 id 次序。
                for suffix, offset, source, scope in (
                    (3, 2, "private:writer", "volume"),
                    (2, 0, "answer", "always"),
                    (1, 0, "manual", "chapter"),
                ):
                    insert_legacy_row(
                        connection,
                        requirements,
                        id=uuid.UUID(int=1000 + index * 10 + suffix),
                        book_id=book_id,
                        text=f"原文保留 {index}/{suffix}：换行\n不改来源与范围。",
                        source=source,
                        created_at=timestamp + timedelta(days=offset),
                        updated_at=timestamp + timedelta(days=10 + suffix),
                        scope=scope,
                        chapter_index=7 if scope == "chapter" else None,
                        volume_index=3 if scope == "volume" else None,
                        message_id=None,
                    )
                connection.execute(
                    metadata.tables["app_settings"]
                    .insert()
                    .values(key=f"requirement_tombstones:{book_id}", value={"texts": [f"不许复活的旧要求 {index}"]})
                )
            expected = {
                book_id: list(
                    connection.scalars(
                        sa.select(requirements.c.id)
                        .where(requirements.c.book_id == book_id)
                        .order_by(requirements.c.created_at, requirements.c.id)
                    )
                )
                for book_id in book_ids
            }
            snapshot = legacy_rows(connection, metadata)

        command.upgrade(config, "0026")
        sequence_name = assert_sequence_schema(engine)
        assert sequence_name is not None
        assert_old_order_and_next_value(engine, metadata, expected, snapshot)

        command.downgrade(config, "0025")
        columns = {column["name"]: column for column in sa.inspect(engine).get_columns("author_requirements")}
        assert set(columns) == set(requirements.c.keys())
        assert {name: column["default"] for name, column in columns.items()} == defaults
        assert not any(
            "seq" in index["column_names"] for index in sa.inspect(engine).get_indexes("author_requirements")
        )
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT to_regclass(:name)"), {"name": sequence_name}) is None
            assert legacy_rows(connection, metadata) == snapshot

        command.upgrade(config, "0026")
        assert_sequence_schema(engine)
        assert_old_order_and_next_value(engine, metadata, expected, snapshot)


def test_sequence_migration_on_empty_ledger_starts_at_one(migration_database_urls):
    with legacy_database(migration_database_urls) as (config, engine, metadata):
        command.upgrade(config, "0026")
        assert_sequence_schema(engine)
        book_id, requirement_id = uuid.uuid4(), uuid.uuid4()
        with engine.begin() as connection:
            insert_legacy_row(connection, metadata.tables["books"], id=book_id, title="空旧库升级")
            insert_legacy_row(
                connection,
                metadata.tables["author_requirements"],
                id=requirement_id,
                book_id=book_id,
                text="升级后的第一条要求",
                source="manual",
            )
            assert connection.scalar(sa.text("SELECT seq FROM author_requirements")) == 1


async def test_requirements_keep_insertion_order_when_wall_clock_moves_backwards(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="时钟回跳不改变要求先后")
        session.add(book)
        await session.commit()
        first = await add_requirement(session, book.id, "先加的要求", source="answer")
        await session.commit()
        first.created_at = datetime(2099, 1, 1, tzinfo=UTC)
        await session.commit()
        second = await add_requirement(session, book.id, "后加的要求", source="note")
        await session.commit()
        book_id, expected = book.id, [first.id, second.id]
        assert first.created_at > second.created_at
        assert first.seq < second.seq

    # 不借用已有 relationship 缓存，分别检查现行服务查询和重新加载的兼容视图。
    async with sessionmaker() as session:
        rows = await list_requirements(session, book_id)
        assert [row.id for row in rows] == expected
        assert [row.text for row in rows] == ["先加的要求", "后加的要求"]
        book = await session.get(Book, book_id)
        assert [row.id for row in book.author_requirements] == expected
        assert book.requirements == ["先加的要求", "后加的要求"]


async def test_equal_timestamps_and_deduplication_do_not_change_existing_sequence(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="同时间与去重保持原序")
        session.add(book)
        await session.commit()
        first = await add_requirement(session, book.id, "保留第一条", source="manual")
        second = await add_requirement(session, book.id, "保留第二条", source="private:writer", scope="next_chapter")
        first.created_at = second.created_at = datetime(2020, 1, 1, tzinfo=UTC)
        await session.commit()
        book_id = book.id
        expected = [(first.id, first.seq, "manual"), (second.id, second.seq, "private:writer")]
        duplicate = await add_requirement(session, book.id, "  保留第一条  ", source="answer")
        await session.commit()
        assert duplicate.id == first.id
        assert duplicate.seq == first.seq
        assert duplicate.source == "manual"

    async with sessionmaker() as session:
        rows = await list_requirements(session, book_id)
        assert [(row.id, row.seq, row.source) for row in rows] == expected
        assert len(list(await session.scalars(sa.select(AuthorRequirement)))) == 2
        book = await session.get(Book, book_id)
        assert book.requirements == ["保留第一条", "保留第二条"]
        assert await session.get(AppSetting, f"requirement_tombstones:{book_id}") is None
