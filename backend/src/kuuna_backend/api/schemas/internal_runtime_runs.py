from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from kuuna_backend.db.models import RuntimeRunStatus


class InternalRuntimeRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    provider_group_id: str
    message_id: UUID | None
    binding_id: UUID
    template_version_id: UUID
    template_build_id: UUID | None
    image_ref: str
    status: RuntimeRunStatus
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    error: str | None
    execution: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class InternalRuntimeRunListResponse(BaseModel):
    items: list[InternalRuntimeRunResponse]

