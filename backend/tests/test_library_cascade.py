"""第三包任务 2：连带建议、作者改名、前文替换和章节回退。"""

import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.main import create_app
from app.models import (
    Book,
    Chapter,
    Character,
    Job,
    MeetingMessage,
    PlotUnit,
    SettingCandidate,
    SettingCategory,
    SettingSuggestion,
    SettingVersion,
    StoryNode,
    Volume,
    WorldEntry,
)
from app.services.library_cascade import generate_cascade_suggestions, iter_text_paths
from app.services.versions import apply_snapshot, snapshot_of


@pytest.fixture
async def client():
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        await app.state.redis.aclose()


async def fixture_book(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="连带建议", status="ready", concept={"story": "灵海是故事起点。"})
        session.add(book)
        await session.flush()
        ladder = WorldEntry(
            book_id=book.id,
            name="境界",
            category="等级体系",
            style="ladder",
            content="灵海之上还有路。",
            levels=[{"name": "灵渊", "text": "灵海深处。"}],
        )
        place = WorldEntry(book_id=book.id, name="城池", category="世界与地图", content="灵海修士驻守。", locked=True)
        card = WorldEntry(
            book_id=book.id,
            name="怪物",
            category="特殊规则",
            fields=[{"name": "弱点", "value": "灵海之力。"}],
        )
        character = Character(book_id=book.id, name="楚风", abilities="灵海修为", want="突破灵海", location="灵海边")
        node = StoryNode(
            book_id=book.id, position=1, kind="milestone", segment={"title": "灵海篇", "text": "走过灵海。"}
        )
        volume = Volume(book_id=book.id, index=1, title="初遇", summary="闯过灵海。")
        session.add_all([ladder, place, card, character, node, volume])
        await session.flush()
        unit = PlotUnit(book_id=book.id, volume_id=volume.id, index=1, title="破境", summary="跨入灵海。")
        content = "开头" + "前" * 20 + "灵海" + "后" * 20 + "灵海。灵海，灵海。"
        final = Chapter(
            book_id=book.id,
            index=1,
            title="第一章",
            content=content,
            word_count=len(content),
            status="final",
            summary="摘要不动",
        )
        draft = Chapter(book_id=book.id, index=2, title="未定稿", content="灵海", status="drafting")
        session.add_all([unit, final, draft])
        await session.commit()
        return book.id, ladder.id, final.id, content


async def test_cascade_scans_every_supported_path_skips_source_and_runtime_and_deduplicates(sessionmaker):
    book_id, ladder_id, _, content = await fixture_book(sessionmaker)
    async with sessionmaker() as session:
        ladder = await session.get(WorldEntry, ladder_id)
        rows = await generate_cascade_suggestions(
            session, book_id, ladder, "levels.0.name", [{"old": "灵海", "new": "灵渊"}]
        )
        targets = {(row.target_type, row.payload.get("path")) for row in rows}
        assert targets == {
            ("entry", "content"),
            ("entry", "fields.弱点"),
            ("entry", "levels.0.text"),
            ("character", "abilities"),
            ("concept", "story"),
            ("segment", "title"),
            ("segment", "text"),
            ("volume", "summary"),
            ("unit", "summary"),
            (None, None),
        }
        assert not any(row.payload.get("path") in {"want", "location", "condition", "is_alive"} for row in rows)
        assert sum(row.title.endswith("（已锁）") for row in rows) == 1
        written = next(row for row in rows if row.kind == "written")
        assert written.title == "『灵海』在第 1 章的正文里出现过，要不要把前文也一起换成『灵渊』？"
        assert written.payload["chapters"] == [1]
        assert written.payload["matches"][0]["count"] == 4
        contexts = written.payload["matches"][0]["contexts"]
        assert len(contexts) == 3 and contexts[0] == "前" * 15 + "灵海" + "后" * 15
        assert all(piece in content for piece in contexts)
        assert (
            await generate_cascade_suggestions(
                session, book_id, ladder, "levels.0.name", [{"old": "灵海", "new": "灵渊"}]
            )
            == []
        )
        assert (await session.get(Book, book_id)).concept["story"] == "灵海是故事起点。"


async def test_written_accept_saves_each_chapter_then_reverts_without_touching_runtime(client, sessionmaker):
    book_id, ladder_id, chapter_id, content = await fixture_book(sessionmaker)
    async with sessionmaker() as session:
        rows = await generate_cascade_suggestions(
            session,
            book_id,
            await session.get(WorldEntry, ladder_id),
            "levels.0.name",
            [{"old": "灵海", "new": "灵渊深境"}],
        )
        suggestion_id = next(row.id for row in rows if row.kind == "written")
        # 写作时仍能接受前文建议；不能动正在写的第 2 章。
        session.add(Job(book_id=book_id, kind="write_chapters", status="running", thread_id="busy"))
        await session.commit()
    response = await client.post(f"/api/suggestions/{suggestion_id}/accept")
    assert response.status_code == 200, response.text
    versions_path = f"/api/books/{book_id}/versions?target_type=chapter&target_id={chapter_id}"
    versions = (await client.get(versions_path)).json()
    assert len(versions) == 2
    assert versions[-1]["snapshot"] == {"title": "第一章", "content": content}
    async with sessionmaker() as session:
        chapter = await session.get(Chapter, chapter_id)
        assert chapter.content == content.replace("灵海", "灵渊深境")
        assert chapter.word_count == len(chapter.content)
        assert chapter.summary == "摘要不动" and chapter.status == "final"
        assert (
            await session.scalar(select(Chapter).where(Chapter.book_id == book_id, Chapter.index == 2))
        ).content == "灵海"
    response = await client.post(f"/api/versions/{versions[-1]['id']}/revert")
    assert response.status_code == 200 and response.json()["content"] == content
    async with sessionmaker() as session:
        chapter = await session.get(Chapter, chapter_id)
        assert chapter.word_count == len(content) and chapter.summary == "摘要不动"


@pytest.mark.parametrize("bad_chapter", ["missing", "drafting", "stale"])
async def test_written_replacement_is_atomic_and_rejects_changed_chapters(client, sessionmaker, bad_chapter):
    async with sessionmaker() as session:
        book = Book(title="保护前文")
        session.add(book)
        await session.flush()
        one = Chapter(book_id=book.id, index=1, title="首章", content="灵海", status="final")
        session.add(one)
        if bad_chapter != "missing":
            session.add(
                Chapter(
                    book_id=book.id,
                    index=2,
                    title="次章",
                    content="已重写" if bad_chapter == "stale" else "灵海",
                    status="drafting" if bad_chapter == "drafting" else "final",
                )
            )
        suggestion = SettingSuggestion(
            book_id=book.id,
            kind="written",
            title="换前文",
            payload={"op": "replace_in_chapters", "old": "灵海", "new": "灵渊", "chapters": [1, 2]},
        )
        session.add(suggestion)
        await session.commit()
        one_id, suggestion_id = one.id, suggestion.id
    assert (await client.post(f"/api/suggestions/{suggestion_id}/accept")).status_code == 409
    async with sessionmaker() as session:
        assert (await session.get(Chapter, one_id)).content == "灵海"
        assert list(await session.scalars(select(SettingVersion))) == []
        assert (await session.get(SettingSuggestion, suggestion_id)).status == "pending"


async def test_chapter_revert_cannot_overwrite_an_active_rewrite(client, sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="重写保护")
        session.add(book)
        await session.flush()
        chapter = Chapter(book_id=book.id, index=1, title="重写稿", content="正在重写", status="drafting")
        session.add(chapter)
        await session.flush()
        version = SettingVersion(
            book_id=book.id,
            target_type="chapter",
            target_id=chapter.id,
            version=1,
            snapshot={"title": "原稿", "content": "灵海"},
            source="suggestion",
        )
        session.add(version)
        await session.commit()
        chapter_id, version_id = chapter.id, version.id
    assert (await client.post(f"/api/versions/{version_id}/revert")).status_code == 409
    async with sessionmaker() as session:
        assert (await session.get(Chapter, chapter_id)).content == "正在重写"


async def test_author_names_aliases_levels_generate_but_long_text_does_not(client, sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="作者改名")
        session.add(book)
        await session.flush()
        entry = WorldEntry(
            book_id=book.id,
            name="旧名",
            category="等级体系",
            style="ladder",
            aliases=["旧别称"],
            levels=[{"name": "灵海", "text": "介绍"}],
        )
        person = Character(book_id=book.id, name="旧人名", aliases=["旧绰号"])
        other = WorldEntry(
            book_id=book.id, name="被提到", category="特殊规则", content="旧名、旧别称、灵海、旧人名、旧绰号。"
        )
        session.add_all([entry, person, other])
        await session.commit()
        book_id, entry_id, person_id = book.id, entry.id, person.id
    response = await client.patch(f"/api/world-entries/{entry_id}", json={"content": "灵海改成灵渊。"})
    assert response.status_code == 200, response.text
    assert (await client.get(f"/api/books/{book_id}/suggestions")).json() == []
    response = await client.patch(
        f"/api/world-entries/{entry_id}",
        json={"name": "新名", "aliases": ["新别称"], "levels": [{"name": "灵渊", "text": "介绍"}]},
    )
    assert response.status_code == 200, response.text
    response = await client.patch(f"/api/characters/{person_id}", json={"name": "新人名", "aliases": ["新绰号"]})
    assert response.status_code == 200, response.text
    rows = (await client.get(f"/api/books/{book_id}/suggestions")).json()
    assert {(row["payload"]["old"], row["payload"]["new"]) for row in rows} == {
        ("旧名", "新名"),
        ("旧别称", "新别称"),
        ("灵海", "灵渊"),
        ("旧人名", "新人名"),
        ("旧绰号", "新绰号"),
    }
    assert (await client.patch(f"/api/world-entries/{entry_id}", json={"name": "新名"})).status_code == 200
    assert len((await client.get(f"/api/books/{book_id}/suggestions")).json()) == len(rows)


async def test_choose_option_uses_its_rename_and_only_suggests_one_line_while_busy(client, sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="选候选", status="writing")
        session.add(book)
        await session.flush()
        entry = WorldEntry(
            book_id=book.id, name="境界", category="特殊规则", content="灵海的介绍。", one_line="原来的话"
        )
        other = Character(book_id=book.id, name="楚风", abilities="灵海修为")
        session.add_all([entry, other])
        await session.flush()
        candidate = SettingCandidate(
            book_id=book.id,
            target_type="entry",
            target_id=entry.id,
            path="content",
            base=entry.content,
            options=[
                {"text": "稳妥", "renamed": []},
                {"text": "灵渊的介绍。", "renamed": [{"old": "灵海", "new": "灵渊"}], "one_line": "新的话"},
            ],
        )
        session.add_all([candidate, Job(book_id=book.id, kind="write_chapters", status="running", thread_id="writing")])
        await session.commit()
        candidate_id, book_id = candidate.id, book.id
    response = await client.post(f"/api/candidates/{candidate_id}/choose", json={"index": 1})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["target"]["content"] == "灵渊的介绍。" and body["target"]["one_line"] == "原来的话"
    assert {row["payload"]["op"] for row in body["suggestions"]} == {"replace_text", "set_field"}
    one_line = next(row for row in body["suggestions"] if row["payload"]["op"] == "set_field")
    assert one_line["title"] == "『境界』的一段话改了，一句话要不要跟着换成：新的话"
    assert (await client.post(f"/api/suggestions/{one_line['id']}/accept")).status_code == 200
    async with sessionmaker() as session:
        message = await session.scalar(select(MeetingMessage).where(MeetingMessage.book_id == book_id))
        assert message.job_id is None and message.speaker == "lorekeeper" and "你选的写法" in message.content


async def test_choose_rolls_back_target_versions_and_suggestions_when_message_cannot_save(
    client, sessionmaker, monkeypatch
):
    from app.api import library

    async def fail_to_save(*args, **kwargs):
        raise IntegrityError("insert message", {}, Exception("消息保存失败"))

    monkeypatch.setattr(library, "post_message", fail_to_save)
    async with sessionmaker() as session:
        book = Book(title="同事务保护")
        session.add(book)
        await session.flush()
        entry = WorldEntry(book_id=book.id, category="特殊规则", name="境界", content="原文")
        session.add(entry)
        await session.flush()
        candidate = SettingCandidate(
            book_id=book.id,
            target_type="entry",
            target_id=entry.id,
            path="content",
            base="原文",
            options=[{"text": "新文", "one_line": "新的概括"}],
        )
        session.add(candidate)
        await session.commit()
        candidate_id, entry_id = candidate.id, entry.id
    response = await client.post(f"/api/candidates/{candidate_id}/choose", json={"index": 0})
    assert response.status_code == 409, response.text
    async with sessionmaker() as session:
        assert (await session.get(WorldEntry, entry_id)).content == "原文"
        assert (await session.get(SettingCandidate, candidate_id)).chosen is None
        assert list(await session.scalars(select(SettingVersion))) == []
        assert list(await session.scalars(select(SettingSuggestion))) == []


@pytest.mark.parametrize(("style", "expected"), [("卡片", "card"), ("段落", "paragraph")])
async def test_create_category_suggestion_maps_chinese_style(client, sessionmaker, style, expected):
    async with sessionmaker() as session:
        book = Book(title="自建类别")
        session.add(book)
        await session.flush()
        suggestion = SettingSuggestion(
            book_id=book.id,
            kind="fill_gap",
            title="建一个自建类别",
            payload={
                "op": "create_category",
                "category": {
                    "name": "厉鬼",
                    "style": style,
                    "fields": ["弱点"] if expected == "card" else [],
                    "hint": "说明来历",
                },
            },
        )
        session.add(suggestion)
        await session.commit()
        suggestion_id = suggestion.id
    response = await client.post(f"/api/suggestions/{suggestion_id}/accept")
    assert response.status_code == 200, response.text
    async with sessionmaker() as session:
        category = await session.scalar(select(SettingCategory))
        assert category.name == "厉鬼" and category.style == expected and category.hint == "说明来历"


def test_chapter_snapshots_only_restore_title_content_and_recount():
    chapter = Chapter(
        id=uuid.uuid4(), title="标题", content="原 文\n正文", status="final", summary="摘要", word_count=999
    )
    assert snapshot_of(chapter) == {"title": "标题", "content": "原 文\n正文"}
    apply_snapshot(chapter, {"title": "退回标题", "content": "新 文"})
    assert chapter.word_count == 2 and chapter.summary == "摘要" and chapter.status == "final"
    with pytest.raises(ValueError, match="不可编辑"):
        apply_snapshot(chapter, {"content": "不该改", "status": "planned"})
    with pytest.raises(ValueError, match="必须是文字"):
        apply_snapshot(chapter, {"title": None})
    assert chapter.title == "退回标题" and chapter.content == "新 文"


def test_searchable_character_paths_exclude_runtime():
    character = Character(name="楚风", aliases=["小楚"], abilities="灵海", want="灵海", location="灵海")
    paths = dict(iter_text_paths(character))
    assert paths["name"] == "楚风" and paths["abilities"] == "灵海"
    assert not {"aliases", "want", "location", "condition", "is_alive"}.intersection(paths)
