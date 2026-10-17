import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk

if TYPE_CHECKING:
    from app.models.book import Book


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)


class AuthorRequirement(UUIDPk, Timestamps, Base):
    __tablename__ = "author_requirements"

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(100), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    scope: Mapped[str] = mapped_column(String(10), default="always", server_default="always")
    chapter_index: Mapped[int | None] = mapped_column(Integer)
    volume_index: Mapped[int | None] = mapped_column(Integer)
    message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("meeting_messages.id", ondelete="SET NULL"))
    book: Mapped["Book"] = relationship(back_populates="author_requirements")


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
