"""全书地图：关键节点、人物锚点与信息差的唯一事实来源。"""

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk


class StoryNode(UUIDPk, Timestamps, Base):
    __tablename__ = "story_nodes"

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(100), default="", server_default="")
    event: Mapped[str] = mapped_column(Text, default="", server_default="")
    prerequisite: Mapped[str] = mapped_column(Text, default="", server_default="")
    consequence: Mapped[str] = mapped_column(Text, default="", server_default="")
    volume: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="pencil", server_default="pencil")
    origin: Mapped[str] = mapped_column(String(10), default="ai", server_default="ai")
    editor_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    techniques: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")


class NodeAnchor(UUIDPk, Timestamps, Base):
    __tablename__ = "node_anchors"

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("story_nodes.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    note: Mapped[str] = mapped_column(Text, default="", server_default="")


class Secret(UUIDPk, Timestamps, Base):
    __tablename__ = "secrets"
    __table_args__ = (UniqueConstraint("book_id", "seq"),)

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(100), default="", server_default="")
    truth: Mapped[str] = mapped_column(Text, default="", server_default="")
    knowers: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    reader_knows: Mapped[str | None] = mapped_column(String(10))
    reveal_plan: Mapped[str] = mapped_column(Text, default="", server_default="")
    node_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("story_nodes.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), default="hidden", server_default="hidden")
    created_chapter: Mapped[int | None] = mapped_column(Integer)
