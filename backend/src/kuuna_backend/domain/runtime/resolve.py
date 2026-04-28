from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from kuuna_backend.db.models import (
    AgentInstance,
    BindingStatus,
    GroupBinding,
    TemplateBuild,
    TemplateBuildStatus,
    TemplateVersion,
)


class RuntimeResolutionError(Exception):
    """Base error for runtime target resolution."""


class NoBindingError(RuntimeResolutionError):
    """Raised when no active binding exists for a provider group."""


class InactiveBindingError(RuntimeResolutionError):
    """Raised when a binding exists but is not active (optional path)."""


class NoSuccessfulBuildError(RuntimeResolutionError):
    """Raised when a binding exists but no successful build artifact exists yet."""


@dataclass(frozen=True, slots=True)
class ResolvedRuntimeTarget:
    provider_group_id: str
    binding_id: UUID
    agent_instance_id: UUID | None
    template_version_id: UUID
    template_build_id: UUID | None
    image_ref: str | None


def resolve_runtime_target(
    db: Session,
    *,
    provider_group_id: str,
    require_successful_build: bool = False,
) -> ResolvedRuntimeTarget:
    """Resolve the runtime target for a group.

    Inbound execution requires a succeeded ``template_builds`` row with a
    non-empty ``image_ref`` when ``require_successful_build`` is true (the
    default path used by the inbound worker).
    """

    binding_row = db.execute(
        select(GroupBinding, AgentInstance, TemplateVersion)
        .join(TemplateVersion, TemplateVersion.id == GroupBinding.template_version_id)
        .outerjoin(AgentInstance, AgentInstance.group_binding_id == GroupBinding.id)
        .where(
            GroupBinding.provider_group_id == provider_group_id,
            GroupBinding.status == BindingStatus.ACTIVE,
        )
        .limit(1)
    ).one_or_none()

    if binding_row is None:
        raise NoBindingError

    binding, agent_instance, template_version = binding_row

    # Latest succeeded build (if any).
    build = db.execute(
        select(TemplateBuild)
        .where(
            TemplateBuild.template_version_id == template_version.id,
            TemplateBuild.status == TemplateBuildStatus.SUCCEEDED,
        )
        .order_by(TemplateBuild.created_at.desc(), TemplateBuild.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    if require_successful_build and build is None:
        raise NoSuccessfulBuildError

    if require_successful_build and build is not None:
        ref = (build.image_ref or "").strip()
        if not ref:
            raise NoSuccessfulBuildError

    return ResolvedRuntimeTarget(
        provider_group_id=provider_group_id,
        binding_id=binding.id,
        agent_instance_id=agent_instance.id if agent_instance is not None else None,
        template_version_id=template_version.id,
        template_build_id=build.id if build is not None else None,
        image_ref=build.image_ref if build is not None else None,
    )

