import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.book_settings import default_settings
from app.models.base import Base, Timestamps, UUIDPk

if TYPE_CHECKING:
    from app.models.settings import AuthorRequirement


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
    # 主角卡：起点、驱动力、金手指、软肋与在乎的人
    protagonist: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # 世界与地图：规则、详细地图、第一段的对手、远处的影子与核心谜团
    world: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # 主线骨架：核心矛盾、主题、主角成长弧；关键节点以 story_nodes 为准
    spine: Mapped[dict] = mapped_column(JSONB, default=dict)
    setup_progress: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    # 这本书每一类设定有哪几栏：{类别: {facts: [{key, label}], sections: [{key, label}]}}；没存的按默认
    card_layouts: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    settings: Mapped[dict] = mapped_column(JSONB, default=default_settings)
    author_requirements: Mapped[list["AuthorRequirement"]] = relationship(
        back_populates="book",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="(AuthorRequirement.created_at, AuthorRequirement.id)",
    )

    @property
    def requirements(self) -> list[str]:
        """Compatibility view only; the table is the sole source of requirements."""
        return [item.text for item in self.author_requirements]

    @requirements.setter
    def requirements(self, values: list[str]) -> None:
        from app.models.settings import AuthorRequirement

        self.author_requirements = [AuthorRequirement(text=text, source="legacy") for text in dict.fromkeys(values)]

    # 新书写完前 3 章后的试读是否已经做过
    trial_read_done: Mapped[bool] = mapped_column(Boolean, default=False)
    # setting_up / awaiting_approval / ready / writing / completed
    status: Mapped[str] = mapped_column(String(30), default="setting_up")

    volumes: Mapped[list["Volume"]] = relationship(
        back_populates="book", cascade="all, delete-orphan", order_by="Volume.index"
    )


class StoryThread(UUIDPk, Timestamps, Base):
    """线索：主线、每位女主的感情线、反派线、谜团线、成长线……每条线拆成落在各卷的节拍。"""

    __tablename__ = "story_threads"
    __table_args__ = (UniqueConstraint("book_id", "name"),)

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(100))
    # 主线 / 感情线 / 反派线 / 谜团线 / 成长线 / 其他
    kind: Mapped[str] = mapped_column(String(20), default="其他")
    summary: Mapped[str] = mapped_column(Text, default="")
    characters: Mapped[list] = mapped_column(JSONB, default=list)
    # [{volume, beat}]：这条线在第几卷走到哪一步
    beats: Mapped[list] = mapped_column(JSONB, default=list)


class Volume(UUIDPk, Timestamps, Base):
    __tablename__ = "volumes"
    __table_args__ = (UniqueConstraint("book_id", "index"),)

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    # 本卷的舞台：地图、地点
    stage: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    goal: Mapped[str] = mapped_column(Text, default="")
    locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # 这一卷想做成什么、卷首处境
    want: Mapped[str] = mapped_column(Text, default="", server_default="")
    pressure: Mapped[str] = mapped_column(Text, default="", server_default="")
    # 本卷高潮、主要对手、主角境界从哪到哪
    climax: Mapped[str] = mapped_column(Text, default="")
    antagonist: Mapped[str] = mapped_column(Text, default="")
    power_range: Mapped[str] = mapped_column(Text, default="")
    # [{thread, beat}]：本卷推进哪些线索
    thread_beats: Mapped[list] = mapped_column(JSONB, default=list)
    # 本卷新登场的重要人物（姓名与身份）
    new_characters: Mapped[list] = mapped_column(JSONB, default=list)
    # 本卷预计章数（拆剧情单元之前的规划）
    chapter_count: Mapped[int] = mapped_column(Integer, default=0)
    target_node_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("story_nodes.id", ondelete="SET NULL"))
    reaches_node: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    editor_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    techniques: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # planned：只有总纲卡片；detailed：已拆单元待拍板；approved：作者已批准；done：已写完
    status: Mapped[str] = mapped_column(String(20), default="planned")
    # 一卷写完后设定师写的卷回顾，供后面各卷的规划和写作回顾前情
    recap: Mapped[str] = mapped_column(Text, default="")

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
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    goal: Mapped[str] = mapped_column(Text, default="")
    conflict: Mapped[str] = mapped_column(Text, default="")
    climax: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str] = mapped_column(Text, default="")
    # 核心循环在这个单元怎么转一圈
    loop: Mapped[str] = mapped_column(Text, default="", server_default="")
    key_events: Mapped[list] = mapped_column(JSONB, default=list)
    # [{thread, beat}]：本单元推进哪些线索
    thread_beats: Mapped[list] = mapped_column(JSONB, default=list)
    # [{ref, action, detail}]：本单元对伏笔台账的动作（ref 如 F3；action 埋下 / 提醒 / 回收）
    foreshadow_actions: Mapped[list] = mapped_column(JSONB, default=list)
    # 本单元用到的套路（核心套路在前）与高潮的破局手法，统计全书用了几次、防止重复
    tropes: Mapped[list] = mapped_column(JSONB, default=list)
    resolution: Mapped[str] = mapped_column(Text, default="")
    reveals: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    editor_note: Mapped[str] = mapped_column(Text, default="", server_default="")
    techniques: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    plan_issues: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # planned：还没出章纲；outlined：章纲已出；done：本单元写完
    status: Mapped[str] = mapped_column(String(20), default="planned")
    # 单元写完后设定师写的单元回顾
    recap: Mapped[str] = mapped_column(Text, default="")

    volume: Mapped[Volume] = relationship(back_populates="units")
    chapters: Mapped[list["Chapter"]] = relationship(order_by="Chapter.index", viewonly=True)


class Chapter(UUIDPk, Timestamps, Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("book_id", "index"),)

    book_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"), index=True)
    volume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("volumes.id", ondelete="SET NULL"))
    unit_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("plot_units.id", ondelete="SET NULL"), index=True)
    # 全书章号，从 1 开始
    index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200), default="")
    # 章纲：目标、场景、冲突、爽点、结尾钩子、出场人物、伏笔动作
    outline: Mapped[dict] = mapped_column(JSONB, default=dict)
    content: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    # 定稿后设定师写的本章摘要，供后面的章节回顾前情
    summary: Mapped[str] = mapped_column(Text, default="")
    # 最近一轮审稿与设定检查的结果
    review: Mapped[dict] = mapped_column(JSONB, default=dict)
    # 写之前设定师为这一章备的资料：人物、设定条目、要回顾的前文、注意事项
    materials: Mapped[dict] = mapped_column(JSONB, default=dict)
    # 定稿时这一章对设定库和伏笔台账做的改动（改之前的值），重写这一章时据此撤销
    bible_changes: Mapped[dict] = mapped_column(JSONB, default=dict)
    # 本章重写过几次
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # generated / imported
    source: Mapped[str] = mapped_column(String(20), default="generated")
    # planned：只有章纲；drafting：写作与审稿中；final：已定稿
    status: Mapped[str] = mapped_column(String(20), default="planned")


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
