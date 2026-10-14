import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPk


class Book(UUIDPk, Timestamps, Base):
    __tablename__ = "books"

    title: Mapped[str] = mapped_column(String(200), default="未命名")
    # new：从点子开新书；imported：导入已有小说
    source: Mapped[str] = mapped_column(String(20), default="new")
    idea: Mapped[str] = mapped_column(Text, default="")
    style_reference: Mapped[str] = mapped_column(Text, default="")
    genre: Mapped[str] = mapped_column(String(100), default="")
    # 主编定下的概念：卖点、主角钩子、基调等
    concept: Mapped[dict] = mapped_column(JSONB, default=dict)
    # setting_up / awaiting_approval / ready / writing
    status: Mapped[str] = mapped_column(String(30), default="setting_up")

    volumes: Mapped[list["Volume"]] = relationship(
        back_populates="book", cascade="all, delete-orphan", order_by="Volume.index"
    )


class Volume(UUIDPk, Timestamps, Base):
    __tablename__ = "volumes"
    __table_args__ = (UniqueConstraint("book_id", "index"),)

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    goal: Mapped[str] = mapped_column(Text, default="")
    # planned：只有概要；detailed：已拆剧情单元；approved：作者已批准
    status: Mapped[str] = mapped_column(String(20), default="planned")

    book: Mapped[Book] = relationship(back_populates="volumes")
    units: Mapped[list["PlotUnit"]] = relationship(
        back_populates="volume", cascade="all, delete-orphan", order_by="PlotUnit.index"
    )


class PlotUnit(UUIDPk, Timestamps, Base):
    """剧情单元：一卷拆成若干段，每段 5–15 章。"""

    __tablename__ = "plot_units"
    __table_args__ = (UniqueConstraint("volume_id", "index"),)

    volume_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("volumes.id", ondelete="CASCADE"), index=True)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    chapter_count: Mapped[int] = mapped_column(Integer, default=8)
    goal: Mapped[str] = mapped_column(Text, default="")
    conflict: Mapped[str] = mapped_column(Text, default="")
    climax: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(Text, default="")
    key_events: Mapped[list] = mapped_column(JSONB, default=list)

    volume: Mapped[Volume] = relationship(back_populates="units")


class Chapter(UUIDPk, Timestamps, Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("book_id", "index"),)

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    volume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("volumes.id", ondelete="SET NULL"))
    unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plot_units.id", ondelete="SET NULL"))
    index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    # generated / imported
    source: Mapped[str] = mapped_column(String(20), default="generated")
    # draft / final
    status: Mapped[str] = mapped_column(String(20), default="draft")


class DraftVersion(UUIDPk, Base):
    """开书方案的历史版本（每轮 AI 生成或作者修改后存一份快照）。"""

    __tablename__ = "draft_versions"

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    round: Mapped[int] = mapped_column(Integer, default=0)
    # ai / author
    source: Mapped[str] = mapped_column(String(20), default="ai")
    note: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
