import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk


class Job(UUIDPk, Timestamps, Base):
    """后台任务。写作使用 LangGraph 线程，拆书按章上的记录恢复。"""

    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "ix_jobs_one_active_teardown",
            "book_id",
            unique=True,
            postgresql_where=text("kind = 'teardown' AND status IN ('queued', 'running')"),
        ),
    )

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    # book_setup / write_book / rewrite_chapter / outline_expand / teardown
    kind: Mapped[str] = mapped_column(String(30))
    # queued / running / waiting_author / succeeded / failed / cancelled
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    thread_id: Mapped[str] = mapped_column(String(100))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    # 等待作者拍板时的内容（来自 LangGraph interrupt）
    pending: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str] = mapped_column(Text, default="")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MeetingMessage(Base):
    """会议室发言。自增 id 同时作为 SSE 事件 id，用于断线补齐。"""

    __tablename__ = "meeting_messages"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    # chief / lorekeeper / writer / reviewer / author / system
    speaker: Mapped[str] = mapped_column(String(20))
    # speech / artifact / status / decision / error
    kind: Mapped[str] = mapped_column(String(20), default="speech")
    content: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
