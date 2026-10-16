"""写作接入：信息差只做增量写入，重写只撤销本章且不抹掉作者与后文数据。"""

import httpx
from sqlalchemy import select

from app.agents.schemas import ChapterDigest
from app.main import app
from app.models import Book, Chapter, Character, Foreshadowing, Secret, StoryNode
from app.services.setup_store import load_nodes
from app.services.writing_store import apply_digest, reopen_chapter, revert_chapter


async def _story(session):
    book, other = Book(title="信息差测试"), Book(title="不能串书")
    session.add_all([book, other])
    await session.flush()
    chapter = Chapter(book_id=book.id, index=3, title="揭晓")
    secret = Secret(
        book_id=book.id,
        seq=2,
        title="真实身份",
        truth="林岚是旧王之子。",
        knowers=[{"name": "林岚", "since_chapter": None, "how": "开书时"}],
        reader_knows="知道",
    )
    foreign_secret = Secret(book_id=other.id, seq=5, title="另一部书", truth="不能更改")
    session.add_all(
        [
            chapter,
            secret,
            foreign_secret,
            *(Character(book_id=book.id, name=name) for name in ("林岚", "柳如烟", "赵无极")),
            Character(book_id=other.id, name="外书人物"),
        ]
    )
    await session.flush()
    return book, chapter, secret, foreign_secret


def _digest(**values):
    return ChapterDigest(summary="本章揭开身份。", remark="已记录。", **values)


async def test_digest_filters_names_refs_logs_exact_before_after_and_numbers(sessionmaker):
    async with sessionmaker() as session:
        book, chapter, secret, foreign = await _story(session)
        counts = await apply_digest(
            session,
            book.id,
            chapter,
            _digest(
                secret_updates=[
                    {
                        "ref": "S2",
                        "learned_by": [" 林岚 ", "柳如烟", "柳如烟", "不存在", "外书人物"],
                        "how": "亲眼看到",
                    },
                    {"ref": "S2", "learned_by": ["赵无极"], "public": True, "how": "当众坦白"},
                    {"ref": "S5", "learned_by": ["林岚"], "public": True},
                    {"ref": "F2", "public": True},
                ],
                new_characters=[{"name": "新人物"}],
                new_secrets=[
                    {
                        "title": "密道的入口",
                        "truth": "北墙之后有一条密道。",
                        "knowers": ["柳如烟", "柳如烟", "新人物", "外书人物"],
                        "reader_knows": "部分",
                    }
                ],
            ),
        )
        assert counts["secrets_updated"] == counts["secrets_created"] == 1
        assert secret.status == "public"
        assert secret.knowers == [
            {"name": "林岚", "since_chapter": None, "how": "开书时"},
            {"name": "柳如烟", "since_chapter": 3, "how": "亲眼看到"},
            {"name": "赵无极", "since_chapter": 3, "how": "当众坦白"},
        ]
        assert foreign.status == "hidden" and foreign.knowers == []
        log = chapter.bible_changes
        assert log["secrets"] == [
            {
                "seq": 2,
                "before": {"knowers": [{"name": "林岚", "since_chapter": None, "how": "开书时"}], "status": "hidden"},
                "after": {"knowers": secret.knowers, "status": "public"},
            }
        ]
        assert log["created_secrets"] == [3]
        created = await session.scalar(select(Secret).where(Secret.book_id == book.id, Secret.seq == 3))
        assert created.created_chapter == 3 and created.reader_knows == "部分" and created.status == "hidden"
        assert created.knowers == [
            {"name": "柳如烟", "since_chapter": 3, "how": "本章"},
            {"name": "新人物", "since_chapter": 3, "how": "本章"},
        ]


async def test_reopen_latest_removes_learners_and_created_secrets(sessionmaker):
    async with sessionmaker() as session:
        book, chapter, secret, _ = await _story(session)
        await apply_digest(
            session,
            book.id,
            chapter,
            _digest(
                secret_updates=[{"ref": "S2", "learned_by": ["柳如烟"], "public": True, "how": "亲见"}],
                new_secrets=[
                    {"title": "新秘密", "truth": "重要的新真相", "knowers": ["林岚"], "reader_knows": "不知道"}
                ],
            ),
        )
        counts = await reopen_chapter(session, book.id, chapter)
        assert counts["secrets"] == counts["removed_secrets"] == 1
        assert secret.status == "hidden"
        assert secret.knowers == [{"name": "林岚", "since_chapter": None, "how": "开书时"}]
        assert list(await session.scalars(select(Secret.seq).where(Secret.book_id == book.id))) == [2]
        assert chapter.status == "drafting" and chapter.bible_changes == {}
        assert not any((await revert_chapter(session, book.id, chapter)).values())


async def test_revert_preserves_later_and_author_knowers_and_changed_status(sessionmaker):
    async with sessionmaker() as session:
        book, chapter, secret, _ = await _story(session)
        await apply_digest(
            session,
            book.id,
            chapter,
            _digest(secret_updates=[{"ref": "S2", "learned_by": ["柳如烟", "赵无极"], "public": True, "how": "亲见"}]),
        )
        secret.knowers = [
            secret.knowers[0],
            {"name": "柳如烟", "since_chapter": 3, "how": "作者修正后的获知方式"},
            {"name": "赵无极", "since_chapter": 4, "how": "后文才得知"},
            {"name": "新旁观者", "since_chapter": 5, "how": "作者添加"},
        ]
        secret.status = "hidden"
        original = list(secret.knowers)
        await revert_chapter(session, book.id, chapter)
        assert secret.knowers == original and secret.status == "hidden"


async def test_revert_earlier_keeps_created_secret_and_later_knowledge(sessionmaker):
    async with sessionmaker() as session:
        book, chapter, secret, _ = await _story(session)
        new_secret = {"title": "古城的钥匙", "truth": "钥匙在井底", "knowers": ["柳如烟"], "reader_knows": "知道"}
        digest = _digest(
            secret_updates=[{"ref": "S2", "learned_by": ["柳如烟"], "how": "本章看到"}],
            new_secrets=[new_secret],
        )
        await apply_digest(session, book.id, chapter, digest)
        later = Chapter(book_id=book.id, index=4, title="后续")
        session.add(later)
        await session.flush()
        await apply_digest(
            session,
            book.id,
            later,
            _digest(
                secret_updates=[
                    {"ref": "S2", "learned_by": ["赵无极"], "public": True, "how": "后文得知"},
                    {"ref": "S3", "learned_by": ["林岚"], "how": "后文得知"},
                ]
            ),
        )
        await reopen_chapter(session, book.id, chapter)
        assert secret.status == "public"
        assert [item["name"] for item in secret.knowers] == ["林岚", "赵无极"]
        created = await session.scalar(select(Secret).where(Secret.book_id == book.id, Secret.seq == 3))
        assert created is not None and len(created.knowers) == 2
        counts = await apply_digest(session, book.id, chapter, digest)
        assert counts["secrets_created"] == 0
        assert len(list(await session.scalars(select(Secret).where(Secret.book_id == book.id)))) == 2
        assert secret.status == "public" and {item["name"] for item in secret.knowers} == {"林岚", "柳如烟", "赵无极"}


async def test_revert_keeps_new_secret_edited_by_author(sessionmaker):
    async with sessionmaker() as session:
        book, chapter, _, _ = await _story(session)
        await apply_digest(
            session,
            book.id,
            chapter,
            _digest(new_secrets=[{"title": "新秘密", "truth": "重要的新真相", "reader_knows": "知道"}]),
        )
        created = await session.scalar(select(Secret).where(Secret.book_id == book.id, Secret.seq == 3))
        created.truth = "作者亲手修改的真相，不随重写丢失。"
        counts = await revert_chapter(session, book.id, chapter)
        assert counts["removed_secrets"] == 0
        assert await session.get(Secret, created.id) is created
        assert created.truth == "作者亲手修改的真相，不随重写丢失。"


async def test_old_digest_and_change_log_remain_compatible(sessionmaker):
    async with sessionmaker() as session:
        book, chapter, secret, _ = await _story(session)
        chapter.bible_changes = {"characters": [], "created": [], "foreshadowings": []}
        result = await apply_digest(session, book.id, chapter, _digest())
        assert result["secrets_updated"] == result["secrets_created"] == 0
        assert chapter.status == "final" and secret.status == "hidden"


async def test_digest_rejects_wrong_prefix_and_noncanonical_refs(sessionmaker):
    async with sessionmaker() as session:
        book, chapter, secret, _ = await _story(session)
        foreshadow = Foreshadowing(book_id=book.id, seq=1, kind="伏笔", description="伏笔")
        expectation = Foreshadowing(book_id=book.id, seq=3, kind="期待", description="期待")
        session.add_all([foreshadow, expectation])
        await session.flush()
        result = await apply_digest(
            session,
            book.id,
            chapter,
            _digest(
                foreshadow_updates=[
                    {"ref": ref, "action": "回收"} for ref in ["E1", "F3", "前缀F1", "E3后缀", "F01", "E03"]
                ],
                secret_updates=[
                    {"ref": ref, "learned_by": ["柳如烟"], "public": True}
                    for ref in ["F2", "E2", "前缀S2", "S2后缀", "S02", "2", "S0", "S-2"]
                ],
            ),
        )
        assert result["foreshadowings"] == result["secrets_updated"] == 0
        assert foreshadow.status == expectation.status == "planned"
        assert secret.status == "hidden" and len(secret.knowers) == 1
        assert chapter.bible_changes["foreshadowings"] == chapter.bible_changes["secrets"] == []
        # 首尾空格和小写可以规范化，但种类前缀与完整编号必须一致。
        result = await apply_digest(
            session,
            book.id,
            chapter,
            _digest(
                foreshadow_updates=[{"ref": ref, "action": "埋下"} for ref in [" f1 ", " e3 "]],
                secret_updates=[{"ref": " s2 ", "learned_by": ["柳如烟"]}],
            ),
        )
        assert result["foreshadowings"] == 2 and result["secrets_updated"] == 1


async def test_node_updated_by_volume_is_readable_through_api_and_snapshots(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="卷纲节点")
        session.add(book)
        await session.flush()
        node = StoryNode(book_id=book.id, kind="milestone", position=1, title="进入古城", updated_by_volume=2)
        session.add(node)
        await session.commit()
        assert (await load_nodes(session, book.id))[0]["updated_by_volume"] == 2
        book_id = book.id
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/books/{book_id}/nodes")
    assert response.status_code == 200
    assert response.json()[0]["updated_by_volume"] == 2
