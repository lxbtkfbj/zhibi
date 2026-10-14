import uuid
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.llm.router import LLMRouter
from app.services.meeting import Emitter


class JobCancelled(Exception):
    pass


def cancel_key(job_id: uuid.UUID | str) -> str:
    return f"zhibi:cancel:{job_id}"


@dataclass
class GraphDeps:
    """注入到 LangGraph 节点的运行时依赖（不进入检查点）。"""

    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis
    llm: LLMRouter
    emit: Emitter
    book_id: uuid.UUID
    job_id: uuid.UUID

    async def check_cancel(self) -> None:
        if await self.redis.exists(cancel_key(self.job_id)):
            raise JobCancelled()
