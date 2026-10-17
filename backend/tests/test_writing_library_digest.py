"""第三包逐章设定提取与撤销：别名去重、类别配置、作者修改及后文保护。"""

import uuid

import pytest
from sqlalchemy import select

from app.agents.schemas import ChapterDigest
from app.models import Book, Chapter, Character, SettingCategory, SettingSuggestion, SettingVersion, WorldEntry
from app.services.writing_store import apply_digest, revert_chapter


def digest(**values):
    return ChapterDigest(summary="本章发生的事。", remark="已记录。", **values)


async def setup(session):
    book = Book(title="逐章设定测试")
    session.add(book)
    await session.flush()
    chapter = Chapter(book_id=book.id, index=3, title="入坊市")
    session.add(chapter)
    await session.flush()
    return book, chapter


async def test_digest_new_entries_category_fallback_alias_dedupe_and_exact_conflict_origin(sessionmaker):
    async with sessionmaker() as session:
        book, chapter = await setup(session)
        session.add_all(
            [
                Character(book_id=book.id, name="楚风", aliases=["楚小子"]),
                WorldEntry(
                    book_id=book.id, category="世界与地图", name="旧坊市", aliases=["老市集"], content="作者旧内容"
                ),
                SettingCategory(book_id=book.id, key="ghost", name="厉鬼", style="paragraph"),
            ]
        )
        await session.flush()
        result = await apply_digest(
            session,
            book.id,
            chapter,
            digest(
                new_characters=[
                    {"name": "新掌柜", "role_type": "班底", "background": "看守坊市。另有秘密。"},
                    {"name": "楚小子"},
                ],
                new_entries=[
                    {"category": category, "name": name, "one_line": "一条说明", "content": "细节"}
                    for category, name in [
                        ("世界与地图", "坊市"),
                        ("不认识的类别", "灵钱"),
                        ("厉鬼", "灯鬼"),
                        ("特殊规则", "老市集"),
                        ("特殊规则", "楚小子"),
                        ("特殊规则", "新掌柜"),
                        ("特殊规则", "坊市"),
                    ]
                ],
                conflicts=["设定库用灵石，正文写了金币。"],
            ),
        )
        assert result["new_entries"] == 3 and result["conflicts"] == 1 and result["characters_created"] == 1
        entries = {
            row.name: row for row in await session.scalars(select(WorldEntry).where(WorldEntry.book_id == book.id))
        }
        assert entries["坊市"].category == "世界与地图" and entries["坊市"].parent_id is None
        assert entries["灵钱"].category == "特殊规则" and entries["灯鬼"].category == "custom:ghost"
        assert entries["旧坊市"].content == "作者旧内容"
        for name in ("坊市", "灵钱", "灯鬼"):
            row = entries[name]
            assert row.source == "writing" and row.status == "one" and row.created_chapter == 3
            assert row.one_line == "一条说明" and row.content == "细节"
        person = await session.scalar(select(Character).where(Character.name == "新掌柜"))
        assert person.source == "writing" and person.status == "one" and person.one_line == "看守坊市。"
        suggestion = await session.scalar(select(SettingSuggestion).where(SettingSuggestion.book_id == book.id))
        assert suggestion.title == "第 3 章：设定库用灵石，正文写了金币。"
        assert suggestion.kind == "review" and suggestion.payload == {"op": "note"}
        assert suggestion.origin == {"target_type": "chapter", "target_id": str(chapter.id), "chapter": 3}
        log = chapter.bible_changes
        assert log["created_suggestions"] == [str(suggestion.id)]
        assert len(log["created_entries"]) == 3 and all(
            item["snapshot"]["source"] == "writing" for item in log["created_entries"]
        )
        versions = list(await session.scalars(select(SettingVersion).where(SettingVersion.target_type == "entry")))
        assert len(versions) == 3 and all(row.source == "writing" for row in versions)


async def test_revert_new_entries_only_if_snapshot_unchanged_and_only_pending_suggestions(sessionmaker):
    async with sessionmaker() as session:
        book, chapter = await setup(session)
        await apply_digest(
            session,
            book.id,
            chapter,
            digest(
                new_entries=[
                    {"category": "世界与地图", "name": name, "one_line": "原句"}
                    for name in ("原样", "作者改过", "作者锁住")
                ],
                conflicts=["未处理", "接受了", "不用了"],
            ),
        )
        entries = {row.name: row for row in await session.scalars(select(WorldEntry))}
        entries["作者改过"].content = "作者补充"
        entries["作者锁住"].locked = True
        suggestions = {row.title: row for row in await session.scalars(select(SettingSuggestion))}
        suggestions["第 3 章：接受了"].status = "accepted"
        suggestions["第 3 章：不用了"].status = "ignored"
        await session.flush()
        out = await revert_chapter(session, book.id, chapter)
        assert out["removed_entries"] == 1 and out["removed_suggestions"] == 1
        assert {row.name for row in await session.scalars(select(WorldEntry))} == {"作者改过", "作者锁住"}
        assert {row.status for row in await session.scalars(select(SettingSuggestion))} == {"accepted", "ignored"}
        assert chapter.bible_changes == {}


@pytest.mark.parametrize("later", [False, True])
async def test_digest_rewrite_respects_later_final_and_is_idempotent_for_entries(sessionmaker, later):
    async with sessionmaker() as session:
        book, chapter = await setup(session)
        content = digest(
            new_entries=[{"category": "势力划分", "name": "灯会", "one_line": "掌灯人组成"}], conflicts=["称呼不一致"]
        )
        await apply_digest(session, book.id, chapter, content)
        original = uuid.UUID(chapter.bible_changes["created_entries"][0]["id"])
        if later:
            session.add(Chapter(book_id=book.id, index=4, status="final", content="后来用到了灯会"))
            await session.flush()
        await apply_digest(session, book.id, chapter, content)
        entries = list(await session.scalars(select(WorldEntry)))
        assert len(entries) == 1 and (entries[0].id == original) == later
        assert len(list(await session.scalars(select(SettingSuggestion)))) == 1
        if later:
            assert chapter.bible_changes["created_entries"] == []
        else:
            assert len(chapter.bible_changes["created_entries"]) == 1
