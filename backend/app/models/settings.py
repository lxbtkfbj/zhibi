import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)


class AuthorRequirement(UUIDPk, Timestamps, Base):
    __tablename__ = "author_requirements"

    seq: Mapped[int] = mapped_column(Integer, Identity(), index=True)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    scope: Mapped[str] = mapped_column(String(10), default="always", server_default="always")
    chapter_index: Mapped[int | None] = mapped_column(Integer)
    volume_index: Mapped[int | None] = mapped_column(Integer)
    message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("meeting_messages.id", ondelete="SET NULL"))


class ChatThread(UUIDPk, Base):
    __tablename__ = "chat_threads"
    __table_args__ = (UniqueConstraint("book_id", "thread"),)

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    thread: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    summarized_until: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    reset_after: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChatConversation(UUIDPk, Base):
    """群聊里的一段对话：每段只带自己的记录和摘要。消息的 payload.conv 记着属于哪一段（私聊不分段）。"""

    __tablename__ = "chat_conversations"

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    # 按作者在这一段说的第一句话起名；还没说话的是空的
    title: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    # 最近一次在这一段说话（或者刚开这一段）：最近的那一段就是「现在聊的」
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    summarized_until: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    # 作者归档了这一段：不再算「现在聊的」，以前的对话里收在最下面；在这一段再说话就自动取消归档
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
