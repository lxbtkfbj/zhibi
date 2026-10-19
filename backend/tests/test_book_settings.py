"""Settings, exact compiled prose, live flow controls and the unique requirement ledger."""

import importlib.util
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from redis.asyncio import Redis

from app.book_settings import compile_rules, default_settings, merge_settings, strictness_text
from app.config import get_settings
from app.graphs.book_setup import intake_node, live_state, requirements
from app.graphs.write_book import (
    blocking_issues,
    judge_node,
    judge_pitches_node,
    plan_volume_node,
    route_volume_audit,
    trial_gate_node,
    volume_gate_node,
)
from app.main import create_app
from app.models import AuthorRequirement, Book, Chapter, Job, MeetingMessage, Volume
from app.services import jobs
from app.services.writing_context import chapter_words, requirements_of


@pytest.mark.parametrize(
    ("settings", "line"),
    [
        (
            {"title_style": "short"},
            "书名：2-6 个字的经典短书名，像《逆天邪神》《斗破苍穹》，不要用「主标题：副标题」的长书名。",
        ),
        (
            {"title_style": "tomato"},
            "书名：番茄式长书名，「主题：一句话卖点」的格式，例如《苟道邪尊：平时低调发育，战时越境秒杀》。",
        ),
        ({"title_style": "custom", "title_custom": "就叫归途"}, "书名：就叫归途"),
        ({"person": "first"}, "人称：全书用第一人称（「我」）叙述。"),
        ({"person": "second"}, "人称：全书用第二人称（「你」）叙述。"),
        ({"person": "third"}, "人称：全书用第三人称叙述。"),
        ({"intimacy": "heart"}, "亲密戏：只写心动、暧昧和情感拉扯，不写亲吻以上的身体接触。"),
        ({"intimacy": "fade"}, "亲密戏：可以写亲吻和拥抱，再进一步就一笔带过，不写露骨描写。"),
        ({"intimacy": "custom", "intimacy_custom": "牵手即可"}, "亲密戏：牵手即可"),
        ({"chapter_words": 2800}, "每章约 2800 字。"),
        ({"other_rules": "规则一\n\n 规则二 "}, "规则一\n-  规则二 "),
    ],
)
def test_compile_exact_options(settings, line):
    assert compile_rules(settings, title=True) == "【这本书的写作规矩】\n- " + line


def test_title_rule_only_when_naming_a_book():
    # 书有了名字以后，写正文、审稿、排大纲都不再带书名规矩；只有起书名（新建页起草、以前的开书流程）才带
    settings = {"title_style": "short", "person": "third"}
    assert compile_rules(settings) == "【这本书的写作规矩】\n- 人称：全书用第三人称叙述。"
    assert compile_rules(settings, title=True).count("书名：") == 1


@pytest.mark.parametrize(
    "settings",
    [
        None,
        {},
        {"title_style": "chief"},
        {"title_style": "custom"},
        {"intimacy": "custom", "intimacy_custom": " "},
        {"chapter_words": None},
    ],
)
def test_compile_omissions(settings):
    assert compile_rules(settings) == ""


def test_effort_presets_and_strictness():
    for name, expected in [
        ("quick", (1, 1, False, "lenient")),
        ("balanced", (2, 2, True, "standard")),
        ("premium", (3, 3, True, "strict")),
    ]:
        values = merge_settings({}, {"effort_preset": name})
        assert tuple(values[k] for k in ("max_rewrites", "pitches", "volume_audit", "review_strictness")) == expected
    assert merge_settings({}, {"max_rewrites": 0})["effort_preset"] == "custom"
    assert strictness_text("standard") == ""
    assert (
        strictness_text("lenient")
        == "审稿尺度：宽松。只有章纲关键内容缺失、人物严重崩坏、逻辑硬伤才判退，其余问题记下即可。"
    )
    assert strictness_text("strict") == "审稿尺度：严格。出现一条中等问题就判退，文字层面的明显毛病也要指出。"


@pytest.mark.parametrize(
    ("strictness", "verdict", "count"),
    [
        ("lenient", "pass", 2),
        ("lenient", "revise", 2),
        ("standard", "pass", 1),
        ("standard", "revise", 3),
        ("strict", "pass", 4),
        ("strict", "revise", 4),
    ],
)
def test_blocking_scales(strictness, verdict, count):
    issues = [{"severity": level, "problem": level, "suggestion": "改"} for level in ("high", "medium", "low")]
    assert len(blocking_issues({"verdict": verdict, "issues": issues}, {"issues": issues}, strictness)) == count


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(jobs, "enqueue", lambda *args: None)
    app = create_app()
    app.state.redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.redis.aclose()


async def fixture_book(sessionmaker, settings=None, kind="book_setup"):
    async with sessionmaker() as session:
        book = Book(idea="一个寻找故乡的少年", settings={**default_settings(), **(settings or {})})
        session.add(book)
        await session.flush()
        job = Job(book_id=book.id, kind=kind, status="running", thread_id=str(uuid.uuid4()))
        session.add(job)
        await session.commit()
        return book.id, job.id


def runtime(sessionmaker, book_id, job_id):
    return SimpleNamespace(
        context=SimpleNamespace(
            sessionmaker=sessionmaker,
            book_id=book_id,
            job_id=job_id,
            check_cancel=AsyncMock(),
            emit=SimpleNamespace(status=AsyncMock(), say=AsyncMock(), artifact=AsyncMock()),
            llm=SimpleNamespace(),
            redis=SimpleNamespace(xadd=AsyncMock()),
        )
    )


async def test_defaults_are_copied_and_validated(client):
    response = await client.put(
        "/api/settings/new-book-defaults", json={"title_style": "tomato", "effort_preset": "quick"}
    )
    assert response.status_code == 200
    assert response.json()["settings"]["pitches"] == 1
    created = (await client.post("/api/books", json={"idea": "一个穿越到异界的少年"})).json()
    book_id = created["book"]["id"]
    await client.put("/api/settings/new-book-defaults", json={"title_style": "short"})
    values = (await client.get(f"/api/books/{book_id}/settings")).json()
    assert values["settings"]["title_style"] == "tomato"
    # 书名规矩只在起书名时带：新书默认的预览里有，已经建好的书没有
    assert "番茄式长书名" not in values["rules_text"]
    assert "经典短书名" in (await client.get("/api/settings/new-book-defaults")).json()["rules_text"]
    for body in ({"pitches": 5}, {"max_rewrites": -1}, {"person": "custom"}, {"volume_audit": None}, {"unknown": 1}):
        assert (await client.patch(f"/api/books/{book_id}/settings", json=body)).status_code == 422


async def test_requirements_crud_and_deleted_checkpoint_never_returns(client, sessionmaker):
    book_id, job_id = await fixture_book(sessionmaker)
    url = f"/api/books/{book_id}/requirements"
    first = (await client.post(url, json={"text": "不能忘记的旧要求"})).json()
    assert first["source"] == "manual"
    duplicate = (await client.post(url, json={"text": "不能忘记的旧要求"})).json()
    assert duplicate["id"] == first["id"]
    assert len((await client.get(url)).json()) == 1
    assert (await client.patch(f"/api/requirements/{first['id']}", json={"text": "改后的要求"})).status_code == 200
    d = runtime(sessionmaker, book_id, job_id).context
    state = {"brief": ["不能忘记的旧要求"], "notes": ["改后的要求"]}
    assert "改后的要求" in requirements(await live_state(state, d))
    await client.delete(f"/api/requirements/{first['id']}")
    assert "要求" not in requirements(await live_state(state, d))
    async with sessionmaker() as session:
        book = await session.get(Book, book_id)
        assert "改后的要求" not in await requirements_of(book, session)
    assert (await client.patch(f"/api/requirements/{first['id']}", json={"text": "重生"})).status_code == 404


async def test_setting_change_creates_note_and_is_consumed(client, sessionmaker):
    book_id, job_id = await fixture_book(sessionmaker)
    response = await client.patch(f"/api/books/{book_id}/settings", json={"title_style": "tomato"})
    assert response.status_code == 200
    async with sessionmaker() as session:
        message = await session.scalar(sa.select(MeetingMessage).where(MeetingMessage.job_id == job_id))
        assert message.kind == "note" and "番茄长书名" in message.content
    out = await intake_node({"queue": ["concept"]}, runtime(sessionmaker, book_id, job_id))
    assert out["notes_seen"] == message.id
    assert "番茄长书名" in out["notes"][0]
    # Settings notifications are transient instructions, not irrevocable ledger requirements.
    assert (await client.get(f"/api/books/{book_id}/requirements")).json() == []


async def test_style_reference_can_change_while_editorial_works(client, sessionmaker):
    # 文风参考只给写手看、编辑部不会去改：编辑部干活时也能改，从下一章起照新的写；别的照样等编辑部停下
    book_id, _ = await fixture_book(sessionmaker, kind="write_book")
    response = await client.patch(f"/api/books/{book_id}", json={"style_reference": "短句，多对话。"})
    assert response.status_code == 200, response.text
    assert response.json()["style_reference"] == "短句，多对话。"
    assert (await client.patch(f"/api/books/{book_id}", json={"title": "新名字"})).status_code == 409


async def test_writing_settings_change_is_group_system_message(client, sessionmaker):
    book_id, job_id = await fixture_book(sessionmaker, kind="write_book")
    await client.patch(f"/api/books/{book_id}/settings", json={"chapter_words": 2200})
    async with sessionmaker() as session:
        message = await session.scalar(sa.select(MeetingMessage).where(MeetingMessage.job_id == job_id))
        assert message.speaker == "system" and not (message.payload or {}).get("thread")
        assert message.content == "作者修改了本书设置：每章字数：2200"
        book = await session.get(Book, book_id)
        book.concept = {"chapter_words": 1000}
        assert chapter_words(book) == 2200


@pytest.mark.parametrize("recipient", [None, "chief", "lorekeeper", "writer", "reviewer"])
async def test_note_sources_and_deleted_pending_note(client, sessionmaker, recipient):
    book_id, job_id = await fixture_book(sessionmaker)
    await client.post(f"/api/books/{book_id}/notes", json={"content": "记下：只属于当前清单", "to": recipient})
    rows = (await client.get(f"/api/books/{book_id}/requirements")).json()
    if recipient:
        assert rows == []  # 任务6：私聊永远不再自动记要求。
    else:
        assert rows[0]["text"] == "记下：只属于当前清单"
        assert rows[0]["source"] == "note"
        await client.delete(f"/api/requirements/{rows[0]['id']}")
    result = await intake_node({"queue": ["concept"]}, runtime(sessionmaker, book_id, job_id))
    assert not result.get("notes")


async def test_zero_rewrites_and_disabled_gates(sessionmaker):
    book_id, job_id = await fixture_book(
        sessionmaker, {"max_rewrites": 0, "volume_audit": False, "volume_approval": False, "trial_read": False}
    )
    rt = runtime(sessionmaker, book_id, job_id)
    async with sessionmaker() as session:
        chapter = Chapter(book_id=book_id, index=1, title="第一章")
        volume = Volume(book_id=book_id, index=1, title="第一卷", status="detailed")
        session.add_all([chapter, volume])
        await session.commit()
    result = await judge_node(
        {
            "chapter_id": str(chapter.id),
            "review": {"verdict": "revise", "issues": [{"severity": "high", "problem": "不合格", "suggestion": "改"}]},
        },
        rt,
    )
    assert result["step"] == "chapter_gate"
    assert await route_volume_audit({}, rt) == "save_volume"
    assert await trial_gate_node({}, rt) == {}
    result = await volume_gate_node({"volume_id": str(volume.id), "volume_index": 1}, rt)
    assert result.goto == "dispatch"
    assert "按设置自动批准" in rt.context.emit.say.call_args.args[1]
    async with sessionmaker() as session:
        assert (await session.get(Volume, volume.id)).status == "approved"
        assert (await session.get(Chapter, chapter.id)).attempts == 0


async def test_one_pitch_does_not_call_direction_or_judgement_llm(sessionmaker, monkeypatch):
    book_id, job_id = await fixture_book(sessionmaker, {"pitches": 1})
    rt = runtime(sessionmaker, book_id, job_id)
    from app.graphs import write_book

    monkeypatch.setattr(write_book, "_volume_context", AsyncMock(return_value=(SimpleNamespace(index=2), None, {})))
    directions = AsyncMock(side_effect=AssertionError("one pitch must not request competitive directions"))
    monkeypatch.setattr(write_book.editorial, "volume_directions", directions)
    planned = await plan_volume_node({"volume_id": str(uuid.uuid4())}, rt)
    assert len(planned["directions"]) == 1
    result = await judge_pitches_node({"pitches": [{"pitch": 1, "plan": {"units": []}}]}, rt)
    assert result["chosen_pitch"] == 1
    directions.assert_not_called()


async def test_trial_and_volume_sources(sessionmaker, monkeypatch):
    from app.graphs import write_book

    book_id, job_id = await fixture_book(sessionmaker)
    rt = runtime(sessionmaker, book_id, job_id)
    monkeypatch.setattr(write_book, "interrupt", lambda _: {"action": "revise", "feedback": "卷纲的意见"})
    await volume_gate_node({"volume_index": 2}, rt)
    monkeypatch.setattr(write_book, "interrupt", lambda _: {"action": "revise", "feedback": "试读的意见"})
    await trial_gate_node({}, rt)
    async with sessionmaker() as session:
        rows = (await session.scalars(sa.select(AuthorRequirement).where(AuthorRequirement.book_id == book_id))).all()
    assert {row.text: row.source for row in rows} == {
        "卷纲的意见": "volume:2",
        "试读的意见": "trial",
    }


async def test_three_finished_chapters_do_not_trigger_disabled_trial(sessionmaker):
    from app.graphs.write_book import decide

    book_id, _ = await fixture_book(sessionmaker, {"trial_read": False})
    async with sessionmaker() as session:
        session.add_all([Chapter(book_id=book_id, index=i, title=str(i), status="final") for i in range(1, 4)])
        await session.flush()
        result = await decide(session, book_id, {"until": "count", "written": 3, "target": 3})
        assert result["step"] == "done"


async def test_pre_upgrade_checkpoint_is_imported_once_then_deletion_wins(client, sessionmaker):
    book_id, job_id = await fixture_book(sessionmaker)
    d = runtime(sessionmaker, book_id, job_id).context
    old_state = {"brief": ["升级前已经回答但没落库"], "notes": ["（作者对设定师说）升级前私聊"]}
    rendered = requirements(await live_state(old_state, d))
    assert "升级前已经回答但没落库" in rendered and "升级前私聊" in rendered
    rows = (await client.get(f"/api/books/{book_id}/requirements")).json()
    assert {r["text"]: r["source"] for r in rows} == {
        "升级前已经回答但没落库": "answer",
        "升级前私聊": "private:lorekeeper",
    }
    for row in rows:
        await client.delete(f"/api/requirements/{row['id']}")
    assert "升级前" not in requirements(await live_state(old_state, d))
    assert (await client.get(f"/api/books/{book_id}/requirements")).json() == []


async def test_delete_before_first_legacy_resume_does_not_resurrect(client, sessionmaker):
    book_id, job_id = await fixture_book(sessionmaker)
    row = (await client.post(f"/api/books/{book_id}/requirements", json={"text": "不要复活"})).json()
    await client.delete(f"/api/requirements/{row['id']}")
    current = await live_state(
        {"brief": ["不要复活"], "notes": ["不要复活"]}, runtime(sessionmaker, book_id, job_id).context
    )
    assert "不要复活" not in requirements(current)


@pytest.mark.parametrize("thread", [None, "lorekeeper"])
async def test_deleted_legacy_pending_note_cannot_resurrect(client, sessionmaker, thread):
    from app.services.requirements import ingest_notes

    book_id, job_id = await fixture_book(sessionmaker)
    legacy = "（作者对设定师说）旧插话" if thread else "旧插话"
    row = (await client.post(f"/api/books/{book_id}/requirements", json={"text": legacy})).json()
    payload = {"thread": thread} if thread else None
    async with sessionmaker() as session:
        message = MeetingMessage(
            book_id=book_id, job_id=job_id, speaker="author", kind="note", content="旧插话", payload=payload
        )
        session.add(message)
        await session.commit()
    await client.delete(f"/api/requirements/{row['id']}")
    result = await intake_node({"queue": ["concept"]}, runtime(sessionmaker, book_id, job_id))
    assert not result.get("notes")
    async with sessionmaker() as session:
        await ingest_notes(session, book_id, [(message.id, "旧插话", payload)])
        await session.commit()
        message = await session.get(MeetingMessage, message.id)
        assert message.payload["requirement_saved"] is True
    assert (await client.get(f"/api/books/{book_id}/requirements")).json() == []


async def test_delete_invalidates_author_feedback_but_preserves_reviewer_instructions(client, sessionmaker):
    book_id, job_id = await fixture_book(sessionmaker)
    row = (await client.post(f"/api/books/{book_id}/requirements", json={"text": "让主角永远失败"})).json()
    await client.delete(f"/api/requirements/{row['id']}")
    current = await live_state(
        {
            "requirements_ledger_ready": True,
            "feedback": "让主角永远失败",
            "feedback_sources": ["让主角永远失败"],
            "instructions": {"concept": "审稿要求修复逻辑。改成失意者的故事。", "world": "审稿要求修复人物年龄矛盾。"},
            "instruction_sources": {"concept": ["让主角永远失败"]},
            "instruction_fallbacks": {"concept": "审稿要求修复逻辑。"},
        },
        runtime(sessionmaker, book_id, job_id).context,
    )
    assert current["feedback"] == ""
    assert current["feedback_sources"] == []
    assert current["instructions"] == {"concept": "审稿要求修复逻辑。", "world": "审稿要求修复人物年龄矛盾。"}


@pytest.mark.parametrize("kind", ["trial_read", "volume_review"])
async def test_decision_feedback_is_saved_once_even_if_worker_replays_after_delete(
    client, sessionmaker, monkeypatch, kind
):
    from app.graphs import write_book

    book_id, job_id = await fixture_book(sessionmaker, kind="write_book")
    async with sessionmaker() as session:
        job = await session.get(Job, job_id)
        job.status, job.pending = "waiting_author", {"kind": kind, "volume": 2}
        await session.commit()
    queued = []
    monkeypatch.setattr(jobs, "enqueue", lambda _, payload: queued.append(payload))
    response = await client.post(
        f"/api/jobs/{job_id}/decision", json={"action": "revise", "feedback": "已经删去的意见"}
    )
    assert response.status_code == 200
    rows = (await client.get(f"/api/books/{book_id}/requirements")).json()
    assert rows[0]["source"] == ("trial" if kind == "trial_read" else "volume:2")
    await client.delete(f"/api/requirements/{rows[0]['id']}")
    monkeypatch.setattr(write_book, "interrupt", lambda _: queued[0])
    gate = trial_gate_node if kind == "trial_read" else volume_gate_node
    await gate({"volume_index": 2}, runtime(sessionmaker, book_id, job_id))
    assert (await client.get(f"/api/books/{book_id}/requirements")).json() == []


async def test_legacy_migration_preserves_text_time_and_drops_column(sessionmaker):
    spec = importlib.util.spec_from_file_location("settings_migration", Path("alembic/versions/0007_book_settings.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    async with sessionmaker() as session:
        connection = await session.connection()

        def migrate(sync_connection):
            sync_connection.execute(sa.text("CREATE SCHEMA settings_migration_test"))
            sync_connection.execute(sa.text("SET LOCAL search_path TO settings_migration_test"))
            sync_connection.execute(
                sa.text("CREATE TABLE books (id uuid PRIMARY KEY, requirements jsonb, updated_at timestamptz)")
            )
            book_id = uuid.uuid4()
            sync_connection.execute(
                sa.text('INSERT INTO books VALUES (:id, \'["旧要求","旧要求","另一条"]\', \'2025-01-02T03:04:05Z\')'),
                {"id": book_id},
            )
            module.op = Operations(MigrationContext.configure(sync_connection))
            module.upgrade()
            rows = sync_connection.execute(sa.text("SELECT text,source,created_at FROM author_requirements")).all()
            assert {r.text for r in rows} == {"旧要求", "另一条"}
            assert all(r.source == "legacy" and r.created_at.year == 2025 for r in rows)
            assert sync_connection.scalar(sa.text("SELECT settings->>'title_style' FROM books")) == "chief"
            assert (
                sync_connection.scalar(
                    sa.text(
                        "SELECT count(*) FROM information_schema.columns WHERE table_schema='settings_migration_test' AND table_name='books' AND column_name='requirements'"
                    )
                )
                == 0
            )
            module.downgrade()
            assert set(sync_connection.scalar(sa.text("SELECT requirements FROM books"))) == {"旧要求", "另一条"}

        await connection.run_sync(migrate)
        await session.rollback()


async def test_other_rules_migration_moves_each_line_into_requirements(sessionmaker):
    # 0021：「其他规矩」并进写作要求，每一行挪成一条一直有效的写作要求，已经有的不重复，设置里清空
    spec = importlib.util.spec_from_file_location(
        "rules_migration", Path("alembic/versions/0021_other_rules_to_requirements.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    async with sessionmaker() as session:
        connection = await session.connection()

        def migrate(sync_connection):
            sync_connection.execute(sa.text("CREATE SCHEMA rules_migration_test"))
            sync_connection.execute(sa.text("SET LOCAL search_path TO rules_migration_test"))
            sync_connection.execute(sa.text("CREATE TABLE books (id uuid PRIMARY KEY, settings jsonb)"))
            sync_connection.execute(
                sa.text(
                    "CREATE TABLE author_requirements (id uuid PRIMARY KEY, book_id uuid, text text, "
                    "source varchar(100), scope varchar(10) DEFAULT 'always', "
                    "created_at timestamptz DEFAULT clock_timestamp())"
                )
            )
            with_rules, without = uuid.uuid4(), uuid.uuid4()
            for book_id, rules in ((with_rules, "规矩一\n\n 规矩二 \n规矩一\n已经有的"), (without, "")):
                sync_connection.execute(
                    sa.text("INSERT INTO books VALUES (:id, CAST(:settings AS jsonb))"),
                    {"id": book_id, "settings": json.dumps({"person": "first", "other_rules": rules})},
                )
            sync_connection.execute(
                sa.text(
                    "INSERT INTO author_requirements (id, book_id, text, source) VALUES (:id, :book, '已经有的', 'note')"
                ),
                {"id": uuid.uuid4(), "book": with_rules},
            )
            module.op = Operations(MigrationContext.configure(sync_connection))
            module.upgrade()
            rows = sync_connection.execute(
                sa.text("SELECT text, source, scope FROM author_requirements ORDER BY created_at")
            ).all()
            assert [row.text for row in rows] == ["已经有的", "规矩一", "规矩二"]
            assert {(row.source, row.scope) for row in rows[1:]} == {("manual", "always")}
            settings = dict(sync_connection.execute(sa.text("SELECT id, settings FROM books")).all())
            assert settings[with_rules] == settings[without] == {"person": "first", "other_rules": ""}

        await connection.run_sync(migrate)
        await session.rollback()
