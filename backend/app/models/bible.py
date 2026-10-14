"""设定库：人物、关系、世界观、伏笔。"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk


class Character(UUIDPk, Timestamps, Base):
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("book_id", "name"),)

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    aliases: Mapped[list] = mapped_column(JSONB, default=list)
    # 主角 / 配角 / 反派 / 龙套 等
    role_type: Mapped[str] = mapped_column(String(30), default="配角")
    gender: Mapped[str] = mapped_column(String(20), default="")
    age: Mapped[str] = mapped_column(String(50), default="")
    appearance: Mapped[str] = mapped_column(Text, default="")
    personality: Mapped[str] = mapped_column(Text, default="")
    background: Mapped[str] = mapped_column(Text, default="")
    abilities: Mapped[str] = mapped_column(Text, default="")
    goal: Mapped[str] = mapped_column(Text, default="")
    # 随剧情变化的当前状态
    location: Mapped[str] = mapped_column(Text, default="")
    condition: Mapped[str] = mapped_column(Text, default="")
    # 此人知道的秘密 / 隐藏的秘密
    secrets: Mapped[list] = mapped_column(JSONB, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_alive: Mapped[bool] = mapped_column(Boolean, default=True)
    first_appearance_chapter: Mapped[int | None] = mapped_column(Integer)


class Relationship(UUIDPk, Timestamps, Base):
    __tablename__ = "relationships"

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))
    target_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(Text, default="")
    since_chapter: Mapped[int | None] = mapped_column(Integer)


class WorldEntry(UUIDPk, Timestamps, Base):
    __tablename__ = "world_entries"

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    # 地理 / 势力 / 力量体系 / 历史 / 物品 / 规则 / 其他
    category: Mapped[str] = mapped_column(String(30), default="其他")
    name: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text, default="")


class Foreshadowing(UUIDPk, Timestamps, Base):
    __tablename__ = "foreshadowings"

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    description: Mapped[str] = mapped_column(Text)
    plant_plan: Mapped[str] = mapped_column(Text, default="")
    payoff_plan: Mapped[str] = mapped_column(Text, default="")
    # planned / planted / resolved / abandoned
    status: Mapped[str] = mapped_column(String(20), default="planned")
    planted_chapter: Mapped[int | None] = mapped_column(Integer)
    resolved_chapter: Mapped[int | None] = mapped_column(Integer)
