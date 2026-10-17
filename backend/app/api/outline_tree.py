"""第三包大纲树的只读投影；保留第二包 segmentBands 的分篇和完成判断。"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, get_book
from app.models import Book, Chapter, PlotUnit, StoryNode, Volume

router = APIRouter(tags=["outline-tree"])


@router.get("/books/{book_id}/outline-tree")
async def outline_tree(book: Book = Depends(get_book), session: AsyncSession = SessionDep):
    nodes = list(
        await session.scalars(select(StoryNode).where(StoryNode.book_id == book.id).order_by(StoryNode.position))
    )
    volumes = list(await session.scalars(select(Volume).where(Volume.book_id == book.id).order_by(Volume.index)))
    units = list(await session.scalars(select(PlotUnit).where(PlotUnit.book_id == book.id).order_by(PlotUnit.index)))
    chapters = list(await session.scalars(select(Chapter).where(Chapter.book_id == book.id).order_by(Chapter.index)))
    by_volume = {volume.id: [unit for unit in units if unit.volume_id == volume.id] for volume in volumes}
    volume_chapters = {
        volume.id: [chapter for chapter in chapters if chapter.volume_id == volume.id] for volume in volumes
    }
    unit_chapters = {unit.id: [chapter for chapter in chapters if chapter.unit_id == unit.id] for unit in units}

    def volume_status(volume):
        own = volume_chapters[volume.id]
        planned = (
            sum(max(0, unit.chapter_count) for unit in by_volume[volume.id])
            if by_volume[volume.id]
            else max(0, volume.chapter_count)
        )
        # 与前端一致：done 不能掩盖重写中的草稿；已拆单元以单元章数为准。
        if all(chapter.status == "final" for chapter in own) and (
            volume.status == "done" or (planned > 0 and len(own) >= planned)
        ):
            return "done"
        if any(chapter.status in {"final", "drafting"} for chapter in own):
            return "writing"
        return "planned"

    def volume_out(volume):
        return {
            "id": volume.id,
            "index": volume.index,
            "title": volume.title,
            "summary": volume.summary,
            "chapter_count": volume.chapter_count,
            "status": volume_status(volume),
            "locked": volume.locked,
            "units": [
                {
                    "id": unit.id,
                    "index": unit.index,
                    "title": unit.title,
                    "summary": unit.summary,
                    "chapter_count": unit.chapter_count,
                    "status": unit.status,
                    "locked": unit.locked,
                    "chapters": [
                        {"index": chapter.index, "title": chapter.title, "status": chapter.status}
                        for chapter in unit_chapters[unit.id]
                    ],
                }
                for unit in by_volume[volume.id]
            ],
        }

    def arc_status(own, planned):
        if not planned:
            return "later"
        if own and all(volume_status(volume) == "done" for volume in own):
            return "done"
        if any(chapter.status in {"final", "drafting"} for volume in own for chapter in volume_chapters[volume.id]):
            return "writing"
        return "planned"

    segmented = any(node.segment is not None for node in nodes)
    ending = next((node for node in reversed(nodes) if node.kind == "ending"), None)
    arcs = []
    if segmented:
        for node in nodes:
            if node.kind == "opening":
                continue
            own = [volume for volume in volumes if volume.target_node_id == node.id]
            plan = node.segment
            arcs.append(
                {
                    "node_id": node.id,
                    "title": plan.get("title", node.title) if plan is not None else node.title,
                    "text": plan.get("text", "") if plan is not None else node.event,
                    "status": arc_status(own, plan is not None),
                    "locked": node.status == "pinned",
                    "planned": plan is not None,
                    "end": {"title": node.title, "event": node.event, "kind": node.kind},
                    "volumes": [volume_out(volume) for volume in own],
                }
            )
    else:
        arcs.append(
            {
                "node_id": None,
                "title": "全书",
                "text": "",
                "status": arc_status(volumes, True),
                "locked": False,
                "planned": True,
                "end": None,
                "volumes": [volume_out(volume) for volume in volumes],
            }
        )
    return {
        "arcs": arcs,
        "ending": {"node_id": ending.id, "title": ending.title, "event": ending.event} if ending else None,
        "segmented": segmented,
    }
