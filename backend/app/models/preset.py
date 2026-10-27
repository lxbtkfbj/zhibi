"""作者的全局预设与逐次保存；系统预设从随程序发布的资源读取。"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk


class Preset(UUIDPk, Timestamps, Base):
    __tablename__ = "presets"

    kind: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(200))
    based_on: Mapped[dict] = mapped_column(JSONB, default=dict)
    blocks: Mapped[list] = mapped_column(JSONB, default=list)
    saved: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class PresetSave(UUIDPk, Base):
    __tablename__ = "preset_saves"
    __table_args__ = (UniqueConstraint("preset_id", "saved"),)

    preset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("presets.id", ondelete="CASCADE"), index=True)
    saved: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    blocks: Mapped[list] = mapped_column(JSONB, default=list)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
