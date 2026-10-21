"""导入小修：只用合成文本，保留原 5.1 样本与作者文件边界。"""

import pytest
from sqlalchemy import select

from app.models import Book, Chapter, Character, Volume
from app.services import teardown_digest, teardown_split


def chapter(number, *, named=True, volume=""):
    title = f" 章名{number}" if named else ""
    return f"{volume}第{number}章{title}\n" + f"这是第{number}章，少年望着山林走向远方。" * 40 + "\n"


@pytest.mark.parametrize("append", [False, True])
def test_volume_number_restart_keeps_all_ninety_chapters(append):
    text = "第一卷 少年\n" + "".join(chapter(n) for n in range(1, 61))
    # 不同的正文，避免与第一卷同号同名的章被精确去重。
    text += "第二卷 风起\n" + "".join(chapter(n).replace("少年", "少女") for n in range(1, 31))
    result = teardown_split.split(text.encode(), append=append)
    selected = teardown_split.selected_chapters(result)
    assert len(selected) == 90
    assert not any("像是混进来的别的书" in piece.flags for piece in result["chapters"])
    assert teardown_split.number_issues(selected) == ([], 0)


@pytest.mark.parametrize("count,foreign", [(1, True), (5, True), (6, False), (8, False)])
def test_foreign_chain_releases_the_whole_chain_at_six(count, foreign):
    text = chapter(300) + "".join(chapter(n) for n in range(1, count + 1)) + chapter(301)
    result = teardown_split.split(text.encode())
    assert all(("像是混进来的别的书" in piece.flags) is foreign for piece in result["chapters"][1:-1])
    assert len(teardown_split.selected_chapters(result)) == (2 if foreign else count + 2)


def test_single_foreign_chapter_still_excluded():
    result = teardown_split.split((chapter(1540) + chapter(1).replace("章名1", "外门弟子") + chapter(1541)).encode())
    preview = teardown_split.make_preview(result, "样本.txt", 100)
    assert [(item["title"], item["reason"]) for item in preview["excluded"]] == [("外门弟子", "像是混进来的别的书")]
    assert preview["number_issues"] == []


def test_bare_typo_and_true_gap_keep_twenty_chapters():
    numbers = [1, 2, 3, 4, 50, *range(6, 15), *range(17, 23)]
    result = teardown_split.split("".join(chapter(n, named=False) for n in numbers).encode())
    assert [piece.number for piece in result["chapters"]] == numbers
    assert len(teardown_split.selected_chapters(result)) == 20
    issues, total = teardown_split.number_issues(teardown_split.selected_chapters(result))
    assert total == 2
    assert [(issue["kind"], issue["expected"], issue["number"]) for issue in issues] == [
        ("打错了", 5, 50),
        ("跳了", 15, 17),
    ]


@pytest.mark.parametrize("following", ["第811章 后续", "第811章"])
def test_bare_body_line_followed_by_current_plus_one_stays_in_body(following):
    result = teardown_split.split((chapter(810) + "第1章\n" + following + "\n正文继续。").encode())
    assert [piece.number for piece in result["chapters"]] == [810, 811]
    assert "第1章" in result["chapters"][0].text
    assert teardown_split.make_preview(result, "样本.txt", 100)["ignored_heading_total"] == 1


@pytest.mark.parametrize("following", [18, 19])
def test_bare_true_gap_looks_at_named_or_bare_next_candidate(following):
    result = teardown_split.split((chapter(14) + chapter(17, named=False) + chapter(following)).encode())
    assert [piece.number for piece in result["chapters"]] == [14, 17, following]


async def test_appearance_lines_share_identity_rules_merge_and_skip_empty(sessionmaker):
    async with sessionmaker() as session:
        book = Book(title="合成书", source="teardown")
        other = Book(title="别书", source="teardown")
        session.add_all([book, other])
        await session.flush()
        volume = Volume(book_id=book.id, index=1, title="卷")
        person = Character(book_id=book.id, name="陈枭", aliases=["父亲", "旧名"])
        session.add_all([volume, person])
        await session.flush()
        records = {
            1: [
                {"name": "陈枭", "shown": "开门", "change": "醒来"},
                {"name": "父亲", "shown": "离开", "change": "动身"},
            ],
            2: [{"name": "别人", "was": "旧名", "shown": "", "change": "忆起往事"}],
            3: [{"name": "陌生人", "also_called": ["父亲"], "shown": "出现", "change": ""}],
            4: [{"name": "陈枭", "shown": "", "change": ""}],
            5: [{"name": "无关", "shown": "不应出现"}],
        }
        for index, people in records.items():
            session.add(
                Chapter(
                    book_id=book.id,
                    volume_id=volume.id,
                    index=index,
                    teardown={"read_version": 1, "read": {"people": people}},
                )
            )
        session.add(
            Chapter(
                book_id=book.id,
                volume_id=volume.id,
                index=6,
                teardown={"read": {"people": [{"name": "陈枭", "shown": "未读不算"}]}},
            )
        )
        await session.commit()
        result = await teardown_digest.appearances(session, book, person.id)
        assert result == {
            "chapters": [1, 2, 3, 4],
            "lines": [
                {"chapter": 1, "shown": "开门；离开", "change": "醒来；动身"},
                {"chapter": 2, "shown": "", "change": "忆起往事"},
                {"chapter": 3, "shown": "出现", "change": ""},
            ],
        }
        assert len(list(await session.scalars(select(Chapter).where(Chapter.book_id == book.id)))) == 6
