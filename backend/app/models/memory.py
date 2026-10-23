"""Author-owned memories live outside book snapshots and graph checkpoints."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.models.base import Base, Timestamps


class Memory(Timestamps, Base):
    __tablename__ = "memories"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    book_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20), default="writing", server_default="writing")
    summary: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="你加的", server_default="你加的")
    scope: Mapped[str] = mapped_column(String(10), default="always", server_default="always")
    chapter_index: Mapped[int | None] = mapped_column(Integer)
    volume_index: Mapped[int | None] = mapped_column(Integer)
    message_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("meeting_messages.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    # Internal compatibility for writing callers; neither alias reads the retired table.
    text = synonym("detail")
    seq = synonym("id")

    def __init__(self, **values):
        detail = values.get("detail", values.get("text", ""))
        values.setdefault("summary", detail[:40] + ("……" if len(detail) > 40 else ""))
        super().__init__(**values)
