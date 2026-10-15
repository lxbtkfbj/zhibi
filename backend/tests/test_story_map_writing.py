"""第一包过渡期间，旧写作产出仍可安全使用新的共用台账。"""

from sqlalchemy import select

from app.agents.schemas import ChapterDigest, ForeshadowUpdate
from app.models import Book, Chapter, Foreshadowing, Volume
from app.services.writing_store import apply_digest, revert_chapter, save_volume_plan


async def test_old_volume_revision_keeps_author_expectations(sessionmaker):
    async with sessionmaker() as session:
        book = Book(idea="测试")
        session.add(book)
        await session.flush()
        volume = Volume(book_id=book.id, index=1, title="第一卷")
        session.add(volume)
        session.add_all(
            [
                Foreshadowing(book_id=book.id, seq=1, kind="期待", span="中", plant_volume=1, description="大比将至"),
                Foreshadowing(book_id=book.id, seq=2, kind="伏笔", span="中", plant_volume=1, description="旧伏笔"),
            ]
        )
        await session.flush()
        await save_volume_plan(session, book.id, volume, [], [], replace_new=True)
        ledger = list(await session.scalars(select(Foreshadowing).where(Foreshadowing.book_id == book.id)))
        assert [(f.seq, f.kind, f.description) for f in ledger] == [(1, "期待", "大比将至")]


async def test_expectation_digest_and_revert_share_seq_logic(sessionmaker):
    async with sessionmaker() as session:
        book = Book(idea="测试")
        session.add(book)
        await session.flush()
        expectation = Foreshadowing(book_id=book.id, seq=8, kind="期待", description="三年之约", span="长")
        chapter = Chapter(book_id=book.id, index=1, title="立约")
        session.add_all([expectation, chapter])
        await session.flush()
        result = await apply_digest(
            session,
            book.id,
            chapter,
            ChapterDigest(
                summary="主角立下约定。",
                remark="已记录",
                foreshadow_updates=[ForeshadowUpdate(ref="E8", action="埋下")],
            ),
        )
        assert result["foreshadowings"] == 1
        assert expectation.kind == "期待" and expectation.status == "planted" and expectation.planted_chapter == 1
        assert chapter.bible_changes["foreshadowings"][0]["seq"] == 8
        await revert_chapter(session, book.id, chapter)
        assert expectation.status == "planned" and expectation.planted_chapter is None and expectation.kind == "期待"
