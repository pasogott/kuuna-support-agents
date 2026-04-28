from __future__ import annotations

import json
import logging
import re
import subprocess
from uuid import UUID

from sqlalchemy.orm import Session

from kuuna_backend.config.settings import get_settings
from kuuna_backend.db.models import GroupTemplate, TemplateBuild, TemplateBuildStatus, TemplateVersion
from kuuna_backend.domain.audit.service import append_audit_event
from kuuna_backend.integrations.postgres import get_db_session

logger = logging.getLogger(__name__)

_TAG_SAFE_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")


def process_template_build_job(build_id: str) -> None:
    db = get_db_session()
    try:
        try:
            build_uuid = UUID(build_id)
        except ValueError:
            logger.error("template_build_invalid_build_id", extra={"build_id": build_id})
            return

        build = db.get(TemplateBuild, build_uuid)
        if build is None:
            logger.error("template_build_not_found", extra={"build_id": build_id})
            return

        template = db.get(GroupTemplate, build.template_id)
        version = db.get(TemplateVersion, build.template_version_id)
        if template is None or version is None:
            _mark_failed(db, build, error="missing template/version rows")
            return

        build.status = TemplateBuildStatus.RUNNING
        db.commit()

        settings = get_settings()
        docker = settings.docker_cli_path
        context_path = settings.template_build_context_path

        build_inputs = build.build_inputs if isinstance(build.build_inputs, dict) else {}
        base_image = str(build_inputs.get("base_image") or "").strip()
        if not base_image:
            _mark_failed(db, build, error="missing base_image in build_inputs")
            return

        image_tag = _build_image_tag(template_key=template.key, build_id=build.id)

        build_cmd = [
            docker,
            "build",
            "-f",
            "Dockerfile",
            "--build-arg",
            f"BASE_IMAGE={base_image}",
            "--build-arg",
            f"KUUNA_TEMPLATE_KEY={template.key}",
            "--build-arg",
            f"KUUNA_TEMPLATE_VERSION_ID={version.id}",
            "-t",
            image_tag,
            context_path,
        ]

        completed = subprocess.run(
            build_cmd,
            check=False,
            capture_output=True,
            text=True,
        )

        logs = {
            "command": build_cmd,
            "returncode": completed.returncode,
            "stdout_tail": _tail(completed.stdout, 4000),
            "stderr_tail": _tail(completed.stderr, 4000),
        }
        build.logs_ref = json.dumps(logs, separators=(",", ":"))

        if completed.returncode != 0:
            _mark_failed(db, build, error=f"docker build failed (exit {completed.returncode})")
            return

        inspect = subprocess.run(
            [docker, "image", "inspect", "--format", "{{json .RepoDigests}}", image_tag],
            check=False,
            capture_output=True,
            text=True,
        )
        digests: list[str] = []
        if inspect.returncode == 0 and inspect.stdout.strip():
            try:
                parsed = json.loads(inspect.stdout.strip())
                if isinstance(parsed, list):
                    digests = [item for item in parsed if isinstance(item, str) and item]
            except json.JSONDecodeError:
                digests = []

        image_ref = digests[0] if digests else image_tag

        build.status = TemplateBuildStatus.SUCCEEDED
        build.image_ref = image_ref[:512]
        build.image_tag = image_tag[:255]

        append_audit_event(
            db,
            actor_user_id=None,
            event_type="template_build.succeeded",
            entity_type="template_build",
            entity_id=str(build.id),
            payload={
                "template_id": str(template.id),
                "template_version_id": str(version.id),
                "image_ref": build.image_ref,
            },
        )

        db.commit()
    except Exception:
        db.rollback()
        logger.exception("template_build_job_failed", extra={"build_id": build_id})
        raise
    finally:
        db.close()


def _mark_failed(db: Session, build: TemplateBuild, *, error: str) -> None:
    build.status = TemplateBuildStatus.FAILED
    build.image_ref = None

    append_audit_event(
        db,
        actor_user_id=None,
        event_type="template_build.failed",
        entity_type="template_build",
        entity_id=str(build.id),
        payload={"error": error},
    )

    db.commit()


def _tail(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return f"…{value[-max_len:]}"


def _build_image_tag(*, template_key: str, build_id: UUID) -> str:
    safe_key = _TAG_SAFE_PATTERN.sub("-", template_key).strip("-").lower() or "template"
    short = str(build_id).replace("-", "")[:12]
    return f"kuuna/template-{safe_key}:build-{short}"
