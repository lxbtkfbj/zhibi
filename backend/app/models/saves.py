"""整本书的存档：照 git 的办法按内容存，同样的内容只存一份。"""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BookObject(Base):
    """一行书里的东西（或一张清单、一章的正文）：hash 是 data 规范化 JSON 的 sha256。"""

    __tablename__ = "book_objects"

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), primary_key=True)
    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    # row：表里的一行；manifest：一张表的清单 {行 id: hash}；text：一章的正文
    kind: Mapped[str] = mapped_column(String(10))
    data: Mapped[dict | list | str] = mapped_column(JSONB)


class BookSave(Base):
    """一档：每张表的清单 hash；只往后加，不删、不分叉。"""

    __tablename__ = "book_saves"
    __table_args__ = (Index("ix_book_saves_book", "book_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.clock_timestamp())
    # auto：编辑部动完书、作者手改后自动存；manual：作者自己存的；restore：回到了某一档
    kind: Mapped[str] = mapped_column(String(10), default="auto")
    # author / chief / lorekeeper / writer / reviewer / system
    actor: Mapped[str] = mapped_column(String(20), default="system")
    title: Mapped[str] = mapped_column(Text, default="")
    # 和上一档比改了哪些：{items: [...], more: n}
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    # {表名: 这张表清单的 hash}；books 直接是书那一行的 hash
    tree: Mapped[dict] = mapped_column(JSONB, default=dict)
    chapters_final: Mapped[int] = mapped_column(Integer, default=0)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("book_saves.id", ondelete="SET NULL"))
    restored_from: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("book_saves.id", ondelete="SET NULL"))
