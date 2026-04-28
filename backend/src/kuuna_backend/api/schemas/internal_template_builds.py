from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from kuuna_backend.db.models import TemplateBuildStatus


class InternalTemplateBuildCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    actor_user_id: UUID
    base_image: str
    allowed_tools: list[str] | None = None


class InternalTemplateBuildResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    template_id: UUID
    template_version_id: UUID
    status: TemplateBuildStatus
    image_ref: str | None = None
    image_tag: str | None = None
    build_inputs: dict[str, Any]
    logs_ref: str | None = None
    created_at: datetime
    updated_at: datetime


class InternalTemplateBuildListResponse(BaseModel):
    items: list[InternalTemplateBuildResponse]
