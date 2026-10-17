"""设定库接口的输入与输出结构。"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def validate_fields(value: list[str]) -> list[str]:
    if any(not field.strip() for field in value) or len(set(value)) != len(value):
        raise ValueError("字段名不能为空或重复")
    return value


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    style: Literal["card", "paragraph"]
    fields: list[str] = []
    hint: str = ""

    @field_validator("fields")
    @classmethod
    def unique_fields(cls, value):
        return validate_fields(value)


class CategoryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(None, min_length=1, max_length=40)
    fields: list[str] | None = None
    hint: str | None = None
    position: int | None = None
    style: str | None = None

    @field_validator("style")
    @classmethod
    def no_style_changes(cls, value):
        raise ValueError("类别的样式建好后不能改")

    @field_validator("name", "fields", "hint", "position")
    @classmethod
    def no_null(cls, value):
        if value is None:
            raise ValueError("类别字段不能为空值")
        return value

    @field_validator("fields")
    @classmethod
    def unique_fields(cls, value):
        return validate_fields(value)


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    book_id: uuid.UUID
    key: str
    name: str
    style: str
    fields: list[str]
    hint: str
    position: int
    created_at: datetime
    updated_at: datetime


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    book_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    version: int
    snapshot: dict
    source: str
    note: str
    created_at: datetime


class CandidateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    book_id: uuid.UUID
    target_type: str
    target_id: uuid.UUID
    path: str
    base: str
    options: list[dict]
    chosen: int | None
    created_at: datetime


class CandidateChoose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int = Field(ge=0, strict=True)


class SuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    book_id: uuid.UUID
    kind: str
    target_type: str | None
    target_id: uuid.UUID | None
    title: str
    payload: dict
    origin: dict
    status: str
    created_at: datetime
    resolved_at: datetime | None
