from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from kuuna_backend.db.models import (
    GroupTemplate,
    TemplateBuild,
    TemplateBuildStatus,
    TemplateVersion,
    TemplateVersionStatus,
)
from kuuna_backend.domain.audit.service import append_audit_event
from kuuna_backend.domain.templates.tools import extract_allowed_tools
from kuuna_backend.jobs.queue import enqueue_template_build


class TemplateBuildServiceError(Exception):
    """Base error for template build operations."""


class TemplateBuildNotFoundError(TemplateBuildServiceError):
    pass


class TemplateBuildValidationError(TemplateBuildServiceError):
    pass


_BASE_IMAGE_PATTERN = re.compile(r"^[a-zA-Z0-9._/:@-]+$")


def _validate_base_image(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise TemplateBuildValidationError("base_image is required")
    if len(normalized) > 255:
        raise TemplateBuildValidationError("base_image is too long")
    if not _BASE_IMAGE_PATTERN.match(normalized):
        raise TemplateBuildValidationError("base_image contains invalid characters")
    return normalized


@dataclass(frozen=True, slots=True)
class QueueTemplateBuildInput:
    base_image: str
    allowed_tools_override: list[str] | None = None


def queue_template_build(
    db: Session,
    *,
    actor_user_id: UUID,
    template_id: UUID,
    version_id: UUID,
    payload: QueueTemplateBuildInput,
) -> TemplateBuild:
    template = db.get(GroupTemplate, template_id)
    if template is None:
        raise TemplateBuildValidationError("template not found")

    version = db.get(TemplateVersion, version_id)
    if version is None or version.template_id != template_id:
        raise TemplateBuildValidationError("template version not found")

    if version.status != TemplateVersionStatus.PUBLISHED:
        raise TemplateBuildValidationError("only published template versions can be built")

    base_image = _validate_base_image(payload.base_image)

    allowed_tools = (
        [tool.strip().lower() for tool in payload.allowed_tools_override if tool.strip()]
        if payload.allowed_tools_override is not None
        else extract_allowed_tools(version.tools_config)
    )

    build_inputs: dict[str, Any] = {
        "base_image": base_image,
        "allowed_tools": allowed_tools,
        "egress_policy": version.egress_policy,
        "tools_config": version.tools_config,
        "model_config": version.model_config,
    }

    build = TemplateBuild(
        template_id=template_id,
        template_version_id=version_id,
        status=TemplateBuildStatus.QUEUED,
        build_inputs=build_inputs,
    )
    db.add(build)
    db.flush()

    append_audit_event(
        db,
        actor_user_id=actor_user_id,
        event_type="template_build.queued",
        entity_type="template_build",
        entity_id=str(build.id),
        payload={
            "template_id": str(template_id),
            "template_version_id": str(version_id),
        },
    )

    db.commit()
    db.refresh(build)

    enqueue_template_build(str(build.id))
    return build


def list_template_builds_for_version(
    db: Session,
    *,
    template_id: UUID,
    version_id: UUID,
) -> list[TemplateBuild]:
    version = db.get(TemplateVersion, version_id)
    if version is None or version.template_id != template_id:
        raise TemplateBuildValidationError("template version not found")

    return list(
        db.scalars(
            select(TemplateBuild)
            .where(TemplateBuild.template_version_id == version_id)
            .order_by(TemplateBuild.created_at.desc(), TemplateBuild.id.desc())
        ).all()
    )


def get_template_build(db: Session, *, build_id: UUID) -> TemplateBuild:
    build = db.get(TemplateBuild, build_id)
    if build is None:
        raise TemplateBuildNotFoundError("template build not found")
    return build
