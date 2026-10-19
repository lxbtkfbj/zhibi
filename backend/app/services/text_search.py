"""原文搜索：网页和群聊共用，不把整本正文传回 Python。"""

from sqlalchemy import func, select

from app.models import Chapter


async def search_original(session, book_id, word: str) -> dict:
    at = func.strpos(Chapter.content, word)
    condition = (Chapter.book_id == book_id, at > 0)
    total = await session.scalar(select(func.count()).select_from(Chapter).where(*condition))
    times = (func.length(Chapter.content) - func.length(func.replace(Chapter.content, word, ""))) / len(word)
    start = func.greatest(at - 60, 1)
    rows = await session.execute(
        select(
            Chapter.index,
            Chapter.title,
            times.label("times"),
            func.substr(Chapter.content, start, at - start + len(word) + 60).label("near"),
        )
        .where(*condition)
        .order_by(Chapter.index)
        .limit(200)
    )
    return {
        "word": word,
        "chapters": int(total or 0),
        "results": [
            {
                "index": row.index,
                "title": row.title,
                "times": int(row.times),
                "near": row.near.replace("\r", " ").replace("\n", " "),
            }
            for row in rows
        ],
    }
