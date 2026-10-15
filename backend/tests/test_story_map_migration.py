"""用随机命名的隔离数据库执行真实旧数据 upgrade / downgrade，不读取作者数据库。"""

import uuid

import psycopg
import sqlalchemy as sa
from alembic.config import Config
from sqlalchemy.dialects.postgresql import JSONB

from alembic import command


def _insert(connection, table, **values):
    """补全 0001 中无 server_default 的历史必填列，测试夹具不依赖当前 ORM。"""
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


def test_story_map_upgrade_and_downgrade():
    name = f"zhibi_story_map_test_{uuid.uuid4().hex}"
    assert name.startswith("zhibi_story_map_test_") and name.replace("_", "").isalnum()
    admin_url = "postgresql://zhibi:zhibi@127.0.0.1:5433/zhibi"
    url = f"postgresql+psycopg://zhibi:zhibi@127.0.0.1:5433/{name}"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", url)
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    engine = sa.create_engine(url)
    try:
        command.upgrade(config, "0010")
        metadata = sa.MetaData()
        metadata.reflect(bind=engine)
        book_id, setup_id, character_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        with engine.begin() as connection:
            _insert(
                connection,
                metadata.tables["books"],
                id=book_id,
                title="迁移测试书",
                source="new",
                status="writing",
                concept={"title": "迁移测试书"},
                spine={
                    "core_conflict": "身份冲突",
                    "theme": "初心",
                    "protagonist_arc": "担当",
                    "opening": "入城",
                    "ending": "回家",
                    "milestones": [
                        {"index": 2, "title": "离城", "event": "离开", "change": "新地图", "volume": 3},
                        {"index": 1, "title": "亮牌", "event": "对质", "change": "洗冤", "volume": 2},
                    ],
                },
            )
            _insert(
                connection,
                metadata.tables["books"],
                id=setup_id,
                title="待开书",
                source="new",
                status="setting_up",
                concept={},
                spine={},
            )
            _insert(
                connection,
                metadata.tables["characters"],
                id=character_id,
                book_id=book_id,
                name="林岚",
                is_alive=True,
                aliases=["小岚"],
                notes="作者备注",
                secrets=["血脉传承的真相。", "", "  ", "一封未寄出的信"],
            )
            for index in range(1, 5):
                _insert(
                    connection,
                    metadata.tables["volumes"],
                    book_id=book_id,
                    index=index,
                    title=f"卷{index}",
                    status="approved",
                )
            _insert(
                connection,
                metadata.tables["foreshadowings"],
                book_id=book_id,
                description="旧玉佩",
                seq=1,
                span="长",
                status="planted",
                planted_chapter=1,
            )
            for index in range(1, 4):
                _insert(
                    connection,
                    metadata.tables["chapters"],
                    book_id=book_id,
                    index=index,
                    title=f"章{index}",
                    status="final",
                    content=f"不可改动的正文{index}",
                    outline={},
                    materials={},
                    bible_changes={},
                    review={},
                )
        command.upgrade(config, "head")
        metadata = sa.MetaData()
        metadata.reflect(bind=engine)
        with engine.connect() as connection:
            nodes = list(
                connection.execute(
                    sa.select(metadata.tables["story_nodes"])
                    .where(metadata.tables["story_nodes"].c.book_id == book_id)
                    .order_by(metadata.tables["story_nodes"].c.position)
                ).mappings()
            )
            assert [node["title"] for node in nodes] == ["开篇", "亮牌", "离城", "结局"]
            assert [node["position"] for node in nodes] == [1, 2, 3, 4]
            assert nodes[1]["consequence"] == "洗冤"
            assert all(node["status"] == "pencil" and node["origin"] == "ai" for node in nodes)
            volumes = list(
                connection.execute(
                    sa.select(metadata.tables["volumes"]).order_by(metadata.tables["volumes"].c.index)
                ).mappings()
            )
            assert [volume["target_node_id"] for volume in volumes] == [
                nodes[1]["id"],
                nodes[1]["id"],
                nodes[2]["id"],
                nodes[3]["id"],
            ]
            assert [volume["reaches_node"] for volume in volumes] == [False, True, True, True]
            secrets = list(
                connection.execute(
                    sa.select(metadata.tables["secrets"]).order_by(metadata.tables["secrets"].c.seq)
                ).mappings()
            )
            assert [item["seq"] for item in secrets] == [1, 2]
            assert secrets[0]["truth"] == "血脉传承的真相。"
            assert secrets[0]["title"] == "血脉传承的真相"
            assert secrets[0]["knowers"] == [{"name": "林岚", "since_chapter": None, "how": "开书设定"}]
            assert all(item["reader_knows"] is None for item in secrets)
            assert "secrets" not in metadata.tables["characters"].c
            books = {row["id"]: row for row in connection.execute(sa.select(metadata.tables["books"])).mappings()}
            assert books[book_id]["spine"] == {"core_conflict": "身份冲突", "theme": "初心", "protagonist_arc": "担当"}
            assert books[book_id]["setup_progress"]["pieces"] == {
                piece: "confirmed" for piece in ("concept", "nodes", "cast", "fill", "first_volume")
            }
            assert books[setup_id]["setup_progress"] == {}
            ledger = connection.execute(sa.select(metadata.tables["foreshadowings"])).mappings().one()
            assert ledger["kind"] == "伏笔" and ledger["status"] == "planted" and ledger["planted_chapter"] == 1
        command.downgrade(config, "0010")
        metadata = sa.MetaData()
        metadata.reflect(bind=engine)
        assert not {"story_nodes", "node_anchors", "secrets"} & set(metadata.tables)
        with engine.connect() as connection:
            book = (
                connection.execute(sa.select(metadata.tables["books"]).where(metadata.tables["books"].c.id == book_id))
                .mappings()
                .one()
            )
            assert book["spine"]["opening"] == "入城" and book["spine"]["ending"] == "回家"
            assert [item["title"] for item in book["spine"]["milestones"]] == ["亮牌", "离城"]
            character = connection.execute(sa.select(metadata.tables["characters"])).mappings().one()
            assert character["secrets"] == ["血脉传承的真相。", "一封未寄出的信"]
            assert character["aliases"] == ["小岚"] and character["notes"] == "作者备注"
            chapters = list(
                connection.execute(
                    sa.select(metadata.tables["chapters"]).order_by(metadata.tables["chapters"].c.index)
                ).mappings()
            )
            assert [chapter["content"] for chapter in chapters] == [f"不可改动的正文{index}" for index in range(1, 4)]
        # 还原后能再次升级，避免 downgrade 仅表面成功。
        command.upgrade(config, "head")
    finally:
        engine.dispose()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
