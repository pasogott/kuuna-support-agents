from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from kuuna_backend.api.deps import get_db
from kuuna_backend.api.schemas.internal import (
    MediaReconcileRequest,
    MediaReconcileResponse,
    MediaReconcileSnapshot,
)
from kuuna_backend.api.schemas.internal_template_builds import (
    InternalTemplateBuildCreateRequest,
    InternalTemplateBuildListResponse,
    InternalTemplateBuildResponse,
)
from kuuna_backend.api.schemas.internal_runtime_runs import (
    InternalRuntimeRunListResponse,
    InternalRuntimeRunResponse,
)
from kuuna_backend.config.settings import get_settings
from kuuna_backend.domain.template_builds.service import (
    QueueTemplateBuildInput,
    TemplateBuildNotFoundError,
    TemplateBuildServiceError,
    TemplateBuildValidationError,
    get_template_build,
    list_template_builds_for_version,
    queue_template_build,
)
from sqlalchemy import select

from kuuna_backend.db.models import RuntimeRun
from kuuna_backend.jobs.media_processing import (
    cleanup_bogus_failed_assets,
    enqueue_failed_media_assets_for_retry,
    enqueue_pending_media_assets,
    get_media_reconcile_snapshot,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


def _require_internal_token(token: str | None) -> None:
    settings = get_settings()
    expected = settings.internal_ops_token

    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="internal ops token not configured",
        )

    if token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid internal ops token",
        )


@router.post(
    "/media/reconcile",
    response_model=MediaReconcileResponse,
    status_code=status.HTTP_200_OK,
)
def reconcile_media_assets(
    request: MediaReconcileRequest,
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> MediaReconcileResponse:
    _require_internal_token(x_internal_token)

    before = get_media_reconcile_snapshot(request.provider_group_id)

    actions = {
        "cleaned_bogus": 0,
        "enqueued_pending": 0,
        "retried_failed": 0,
    }

    if not request.dry_run:
        if request.cleanup_bogus:
            actions["cleaned_bogus"] = cleanup_bogus_failed_assets(
                limit=request.limit,
                provider_group_id=request.provider_group_id,
            )

        if request.enqueue_pending:
            actions["enqueued_pending"] = enqueue_pending_media_assets(
                limit=request.limit,
                provider_group_id=request.provider_group_id,
            )

        if request.retry_failed:
            actions["retried_failed"] = enqueue_failed_media_assets_for_retry(
                limit=request.limit,
                provider_group_id=request.provider_group_id,
            )

    after = get_media_reconcile_snapshot(request.provider_group_id)

    logger.info(
        "internal_media_reconcile",
        extra={
            "provider_group_id": request.provider_group_id,
            "dry_run": request.dry_run,
            **actions,
            "before": before,
            "after": after,
        },
    )

    message = (
        "dry-run completed"
        if request.dry_run
        else "reconcile jobs enqueued and cleanup applied"
    )

    return MediaReconcileResponse(
        provider_group_id=request.provider_group_id,
        dry_run=request.dry_run,
        before=MediaReconcileSnapshot(**before),
        after=MediaReconcileSnapshot(**after),
        actions=actions,
        message=message,
    )


@router.get(
    "/templates/{template_id}/versions/{version_id}/builds",
    response_model=InternalTemplateBuildListResponse,
    status_code=status.HTTP_200_OK,
)
def internal_list_template_builds(
    template_id: UUID,
    version_id: UUID,
    db: Session = Depends(get_db),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> InternalTemplateBuildListResponse:
    _require_internal_token(x_internal_token)

    try:
        builds = list_template_builds_for_version(db, template_id=template_id, version_id=version_id)
    except TemplateBuildValidationError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return InternalTemplateBuildListResponse(
        items=[InternalTemplateBuildResponse.model_validate(b) for b in builds]
    )


@router.post(
    "/templates/{template_id}/versions/{version_id}/builds",
    response_model=InternalTemplateBuildResponse,
    status_code=status.HTTP_201_CREATED,
)
def internal_queue_template_build(
    template_id: UUID,
    version_id: UUID,
    payload: InternalTemplateBuildCreateRequest,
    db: Session = Depends(get_db),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> InternalTemplateBuildResponse:
    _require_internal_token(x_internal_token)

    try:
        build = queue_template_build(
            db,
            actor_user_id=payload.actor_user_id,
            template_id=template_id,
            version_id=version_id,
            payload=QueueTemplateBuildInput(
                base_image=payload.base_image,
                allowed_tools_override=payload.allowed_tools,
            ),
        )
    except TemplateBuildValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except TemplateBuildServiceError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    return InternalTemplateBuildResponse.model_validate(build)


@router.get(
    "/template-builds/{build_id}",
    response_model=InternalTemplateBuildResponse,
    status_code=status.HTTP_200_OK,
)
def internal_get_template_build(
    build_id: UUID,
    db: Session = Depends(get_db),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> InternalTemplateBuildResponse:
    _require_internal_token(x_internal_token)

    try:
        build = get_template_build(db, build_id=build_id)
    except TemplateBuildNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return InternalTemplateBuildResponse.model_validate(build)


@router.get(
    "/runtime-runs",
    response_model=InternalRuntimeRunListResponse,
    status_code=status.HTTP_200_OK,
)
def internal_list_runtime_runs(
    provider_group_id: str | None = None,
    message_id: UUID | None = None,
    template_version_id: UUID | None = None,
    binding_id: UUID | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> InternalRuntimeRunListResponse:
    _require_internal_token(x_internal_token)

    stmt = select(RuntimeRun).order_by(RuntimeRun.started_at.desc(), RuntimeRun.id.desc())
    if provider_group_id:
        stmt = stmt.where(RuntimeRun.provider_group_id == provider_group_id)
    if message_id:
        stmt = stmt.where(RuntimeRun.message_id == message_id)
    if template_version_id:
        stmt = stmt.where(RuntimeRun.template_version_id == template_version_id)
    if binding_id:
        stmt = stmt.where(RuntimeRun.binding_id == binding_id)

    limit = max(1, min(int(limit), 200))
    runs = list(db.scalars(stmt.limit(limit)))

    return InternalRuntimeRunListResponse(items=[InternalRuntimeRunResponse.model_validate(r) for r in runs])


@router.get(
    "/runtime-runs/{run_id}",
    response_model=InternalRuntimeRunResponse,
    status_code=status.HTTP_200_OK,
)
def internal_get_runtime_run(
    run_id: UUID,
    db: Session = Depends(get_db),
    x_internal_token: str | None = Header(default=None, alias="X-Internal-Token"),
) -> InternalRuntimeRunResponse:
    _require_internal_token(x_internal_token)

    run = db.get(RuntimeRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="runtime run not found")

    return InternalRuntimeRunResponse.model_validate(run)
