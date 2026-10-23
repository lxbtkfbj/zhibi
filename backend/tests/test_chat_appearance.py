"""拍板气泡只补存未出现在消息正文里的作者原话，不改变排队行为。"""

import copy
import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import select

from app.api.jobs import _queue_setup_response
from app.config import get_settings
from app.models import Book, ChatConversation, Job, MeetingMessage
from app.services import jobs


@pytest.mark.parametrize(
    "content,feedback,stored",
    [
        ("确认「定调」。", "以后每章都留悬念\n人物不要自言自语。", True),
        ("批准这一卷的卷纲，开写。", "这一卷打斗多一点", True),
        ("出三个故事方向", "雨夜守灯", True),
        ("这一卷打斗多一点", "这一卷打斗多一点", False),
        ("这一卷打斗多一点\n「结尾」改成：找到同伴", "这一卷打斗多一点", False),
        ("确认「定调」。", "", False),
        ("确认「定调」。", " \n ", False),
        ("确认「定调」。", None, False),
    ],
)
async def test_queue_only_adds_missing_author_feedback(sessionmaker, monkeypatch, content, feedback, stored):
    queued = []
    monkeypatch.setattr(jobs, "enqueue", lambda jid, resume: queued.append((jid, resume)))
    resume = {"action": "confirm", "feedback": feedback, "flips": [], "nested": {"untouched": True}}
    original = copy.deepcopy(resume)
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        async with sessionmaker() as session:
            book = Book(title="拍板气泡合成书")
            session.add(book)
            await session.flush()
            job = Job(book_id=book.id, kind="book_setup", status="waiting_author", thread_id=str(uuid.uuid4()))
            session.add(job)
            await session.commit()
            result = await _queue_setup_response(session, redis, job, content, resume)
            assert result.status == "queued"
            message = await session.scalar(select(MeetingMessage).where(MeetingMessage.book_id == book.id))
            assert message.content == content
            assert message.speaker == "author" and message.kind == "decision" and message.job_id == job.id
            conv = await session.get(ChatConversation, uuid.UUID(message.payload["conv"]))
            assert conv.book_id == book.id
            assert message.payload == {
                "conv": str(conv.id),
                "requirement_saved": True,
                **({"author_feedback": feedback} if stored else {}),
            }
            assert queued == [(job.id, {**original, "requirement_saved": True})]
            assert resume == original
    finally:
        await redis.aclose()
