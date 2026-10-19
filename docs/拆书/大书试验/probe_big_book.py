"""第 14.7 节第 2 条：一千多章的书导入以后，新书页打开要调的几个接口、存一档各要多久。

不用模型。在预览库里造一本拆完的样子的书（章都挂在单元下、每章有章纲和摘要、正文是真书的），
在进程里直接调接口计时。别对作者的 zhibi 库跑。在 backend 下运行：
    set ZHIBI_DATABASE_URL=postgresql+psycopg://zhibi:zhibi@127.0.0.1:5433/<预览库>
    uv run --no-sync python probe_big_book.py <prep_chapters.py 出的全书 json> <倍数，1 就是原书> [unassigned]
unassigned：章都不挂单元（第一批「只导入不拆」的样子）。
"""

import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, "E:/Codex/zhibi/backend")
sys.stdout.reconfigure(encoding="utf-8")
assert "zhibi_" in os.environ.get("ZHIBI_DATABASE_URL", "") and not os.environ["ZHIBI_DATABASE_URL"].endswith("/zhibi"), "只对预览库跑"

import httpx  # noqa: E402

from app.db import get_sessionmaker  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Book, Chapter, PlotUnit, Volume  # noqa: E402

UNIT = 7
VOLUME = 100


async def build(source: Path, times: int, unassigned: bool) -> uuid.UUID:
    rows = json.loads(source.read_text(encoding="utf-8"))["chapters"] * times
    async with get_sessionmaker()() as session:
        book = Book(title=f"大书试验 {len(rows)} 章", source="imported", status="writing", concept={"pitch": "大书试验"})
        session.add(book)
        await session.flush()
        volume = unit = None
        for n, row in enumerate(rows, start=1):
            if not unassigned and (n - 1) % VOLUME == 0:
                volume = Volume(book_id=book.id, index=(n - 1) // VOLUME + 1, title=f"第 {(n - 1) // VOLUME + 1} 卷", summary="这一卷想做成什么；被什么挡着；卷末高潮；卷末变成什么" * 2, status="done")
                session.add(volume)
                await session.flush()
            if not unassigned and (n - 1) % UNIT == 0:
                unit = PlotUnit(volume_id=volume.id, book_id=book.id, index=(n - 1) // UNIT + 1, title=f"单元 {(n - 1) // UNIT + 1}", chapter_count=UNIT, summary="什么事找上门；怎么应对；叫好的那一下；拿到什么" * 3, status="done")
                session.add(unit)
                await session.flush()
            text = row["text"]
            session.add(Chapter(
                book_id=book.id, volume_id=None if unassigned else volume.id, unit_id=None if unassigned else unit.id,
                index=n, title=row["title"], content=text, word_count=len(text), status="final", source="imported",
                summary=text[:180],
                outline=None if unassigned else {"goal": text[:36], "scenes": [text[40:62], text[70:92], text[100:122]], "cool_point": "智取：" + text[130:166], "hook": "期待：" + text[170:196]},
            ))
            if n % 200 == 0:
                await session.flush()
        await session.commit()
        return book.id


async def timed(client: httpx.AsyncClient, method: str, url: str, **kwargs) -> None:
    started = time.monotonic()
    response = await client.request(method, url, **kwargs)
    seconds = time.monotonic() - started
    print(f"  {method:4} {url.split('?')[0].replace(str(BOOK), '{书}'):40} {seconds:6.2f} 秒  {len(response.content) / 1024:8.0f} KB  {response.status_code}")


async def main() -> None:
    global BOOK
    source, times = Path(sys.argv[1]), int(sys.argv[2])
    unassigned = len(sys.argv) > 3 and sys.argv[3] == "unassigned"
    started = time.monotonic()
    BOOK = await build(source, times, unassigned)
    print(f"造书 {time.monotonic() - started:.1f} 秒，书 {BOOK}")
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://probe/api", timeout=600) as client:
        print("新书页打开时拉的：")
        for url in (f"/books/{BOOK}", f"/books/{BOOK}/library", f"/books/{BOOK}/outline-tree", f"/books/{BOOK}/bible",
                    f"/books/{BOOK}/chapters?with_outline=true", f"/books/{BOOK}/outline", "/books"):
            await timed(client, "GET", url)
        print("再拉一遍（看第二次）：")
        await timed(client, "GET", f"/books/{BOOK}/outline-tree")
        await timed(client, "GET", f"/books/{BOOK}/chapters?with_outline=true")
        print("读一章：")
        await timed(client, "GET", f"/books/{BOOK}/chapters/{300 if times else 1}")
        print("存档：")
        await timed(client, "POST", f"/books/{BOOK}/saves", json={"label": "第一档"})
        await timed(client, "PATCH", f"/books/{BOOK}/chapters/5", json={"summary": "改了一下摘要"})
        await timed(client, "POST", f"/books/{BOOK}/saves", json={"label": "改了一章摘要"})
        await timed(client, "POST", f"/books/{BOOK}/saves", json={"auto": True})
        await timed(client, "GET", f"/books/{BOOK}/saves")


if __name__ == "__main__":
    asyncio.run(main())
