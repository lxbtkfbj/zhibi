"""全局手册及不可变的逐次保存。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps


class Handbook(Timestamps, Base):
    __tablename__ = "handbooks"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    source: Mapped[str] = mapped_column(String(10))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    name: Mapped[str | None] = mapped_column(Text)
    when: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    system_hash: Mapped[str | None] = mapped_column(String(64))
    saved: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class HandbookSave(Base):
    __tablename__ = "handbook_saves"

    key: Mapped[str] = mapped_column(ForeignKey("handbooks.key", ondelete="CASCADE"), primary_key=True)
    saved: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    when: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(20))
    restore_saved: Mapped[int | None] = mapped_column(Integer)
    follows_system: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
