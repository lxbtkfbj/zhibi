"""会议室消息：写入 PostgreSQL（可回放），同时推到 Redis Stream（实时推送给网页）。"""

import json
import uuid
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Job, MeetingMessage

STREAM_MAXLEN = 2000

SPEAKER_NAMES = {
    "chief": "主编",
    "lorekeeper": "设定师",
    "writer": "写手",
    "reviewer": "审稿",
    "author": "作者",
    "system": "系统",
}


def stream_key(book_id: uuid.UUID | str) -> str:
    return f"zhibi:events:{book_id}"


def message_dict(m: MeetingMessage) -> dict[str, Any]:
    return {
        "id": m.id,
        "book_id": str(m.book_id),
        "job_id": str(m.job_id) if m.job_id else None,
        "speaker": m.speaker,
        "speaker_name": SPEAKER_NAMES.get(m.speaker, m.speaker),
        "kind": m.kind,
        "content": m.content,
        "payload": m.payload,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


def job_dict(job: Job) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "book_id": str(job.book_id),
        "kind": job.kind,
        "status": job.status,
        "pending": job.pending,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


async def publish(redis: Redis, book_id: uuid.UUID | str, event: str, data: dict[str, Any]) -> None:
    await redis.xadd(
        stream_key(book_id),
        {"event": event, "data": json.dumps(data, ensure_ascii=False)},
        maxlen=STREAM_MAXLEN,
        approximate=True,
    )


async def post_message(
    session: AsyncSession,
    redis: Redis,
    *,
    book_id: uuid.UUID,
    job_id: uuid.UUID | None,
    speaker: str,
    kind: str,
    content: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = MeetingMessage(
        book_id=book_id, job_id=job_id, speaker=speaker, kind=kind, content=content, payload=payload
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    data = message_dict(message)
    await publish(redis, book_id, "message", data)
    return data


class Emitter:
    """编辑部节点用来发言的小工具，绑定到某本书的某个任务。"""

    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], redis: Redis, book_id: uuid.UUID, job_id: uuid.UUID
    ) -> None:
        self.sessionmaker = sessionmaker
        self.redis = redis
        self.book_id = book_id
        self.job_id = job_id

    async def say(self, speaker: str, content: str, *, kind: str = "speech", payload: dict | None = None) -> None:
        async with self.sessionmaker() as session:
            await post_message(
                session,
                self.redis,
                book_id=self.book_id,
                job_id=self.job_id,
                speaker=speaker,
                kind=kind,
                content=content,
                payload=payload,
            )

    async def status(self, speaker: str, content: str) -> None:
        await self.say(speaker, content, kind="status")

    async def artifact(self, speaker: str, title: str, payload: dict) -> None:
        await self.say(speaker, title, kind="artifact", payload=payload)
