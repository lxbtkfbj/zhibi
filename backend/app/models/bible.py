"""设定库：人物、关系、世界观、伏笔。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk


class Character(UUIDPk, Timestamps, Base):
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("book_id", "name"),)

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    aliases: Mapped[list] = mapped_column(JSONB, default=list)
    # 主角 / 配角 / 反派 / 龙套 等（2026-10-19 起页面上不显示，改成置顶；旧值留着）
    role_type: Mapped[str] = mapped_column(String(30), default="配角")
    # 置顶：排在角色目录最上面（后置顶的在上），编辑部每写一章都带上他的卡
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gender: Mapped[str] = mapped_column(String(20), default="")
    age: Mapped[str] = mapped_column(String(50), default="")
    appearance: Mapped[str] = mapped_column(Text, default="")
    personality: Mapped[str] = mapped_column(Text, default="")
    background: Mapped[str] = mapped_column(Text, default="")
    abilities: Mapped[str] = mapped_column(Text, default="")
    goal: Mapped[str] = mapped_column(Text, default="")
    # 此刻想要什么
    want: Mapped[str] = mapped_column(Text, default="", server_default="")
    # 随剧情变化的当前状态
    location: Mapped[str] = mapped_column(Text, default="")
    condition: Mapped[str] = mapped_column(Text, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    is_alive: Mapped[bool] = mapped_column(Boolean, default=True)
    first_appearance_chapter: Mapped[int | None] = mapped_column(Integer)
    one_line: Mapped[str] = mapped_column(Text, default="", server_default="")
    relation: Mapped[str] = mapped_column(Text, default="", server_default="")
    status: Mapped[str] = mapped_column(String(10), default="must", server_default="must")
    tags: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    source: Mapped[str] = mapped_column(String(20), default="ai", server_default="ai")
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 没有专门一列的栏目：所属、软肋、成长与结局、实力与地位，和作者自己加的栏目；键是栏目名
    extra: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


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
    # 内置类别中文名，或 custom:<key>；自建类别的 key 最长 40 字符。
    category: Mapped[str] = mapped_column(String(47), default="特殊规则")
    name: Mapped[str] = mapped_column(String(100))
    content: Mapped[str] = mapped_column(Text, default="")
    style: Mapped[str] = mapped_column(String(10), default="paragraph", server_default="paragraph")
    status: Mapped[str] = mapped_column(String(10), default="must", server_default="must")
    tags: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    one_line: Mapped[str] = mapped_column(Text, default="", server_default="")
    aliases: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    fields: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    levels: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("world_entries.id", ondelete="SET NULL"))
    secret_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("secrets.id", ondelete="SET NULL"))
    locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    source: Mapped[str] = mapped_column(String(20), default="ai", server_default="ai")
    position: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_chapter: Mapped[int | None] = mapped_column(Integer)


class Foreshadowing(UUIDPk, Timestamps, Base):
    """伏笔台账：每条伏笔有编号（F1、F2……）、跨度、计划埋下与回收的位置，写作时更新状态。"""

    __tablename__ = "foreshadowings"

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    # 书内编号，提示词里写作 F{seq}
    seq: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(10), default="伏笔", server_default="伏笔")
    node_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("story_nodes.id", ondelete="SET NULL"))
    description: Mapped[str] = mapped_column(Text)
    # 短（一个单元内收）/ 中（一卷内收）/ 长（跨卷）
    span: Mapped[str] = mapped_column(String(10), default="中")
    plant_plan: Mapped[str] = mapped_column(Text, default="")
    payoff_plan: Mapped[str] = mapped_column(Text, default="")
    plant_volume: Mapped[int | None] = mapped_column(Integer)
    payoff_volume: Mapped[int | None] = mapped_column(Integer)
    # planned / planted / resolved / abandoned
    status: Mapped[str] = mapped_column(String(20), default="planned")
    planted_chapter: Mapped[int | None] = mapped_column(Integer)
    # 埋下之后在哪些章节提醒过读者
    hint_chapters: Mapped[list] = mapped_column(JSONB, default=list)
    resolved_chapter: Mapped[int | None] = mapped_column(Integer)
