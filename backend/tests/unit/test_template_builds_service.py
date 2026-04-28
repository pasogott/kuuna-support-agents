from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kuuna_backend.db.models import (
    GroupTemplate,
    TemplateBuild,
    TemplateBuildStatus,
    TemplateVersion,
    TemplateVersionStatus,
)
from kuuna_backend.domain.template_builds.service import (
    QueueTemplateBuildInput,
    TemplateBuildValidationError,
    queue_template_build,
)


def _published_version(db: Session) -> TemplateVersion:
    template = GroupTemplate(key="build-test", display_name="build-test")
    db.add(template)
    db.flush()

    version = TemplateVersion(
        template_id=template.id,
        version_no=1,
        status=TemplateVersionStatus.PUBLISHED,
        system_prompt="prompt",
        model_config={},
        tools_config={"allowed_tools": ["echo"]},
        egress_policy={},
    )
    db.add(version)
    db.commit()
    db.refresh(version)
    return version


def test_queue_build_requires_published_version(test_session_factory: sessionmaker[Session]) -> None:
    with test_session_factory() as db:
        template = GroupTemplate(key="draft-only", display_name="draft-only")
        db.add(template)
        db.flush()

        draft = TemplateVersion(
            template_id=template.id,
            version_no=1,
            status=TemplateVersionStatus.DRAFT,
            system_prompt="prompt",
            model_config={},
            tools_config={},
            egress_policy={},
        )
        db.add(draft)
        db.commit()
        db.refresh(draft)

        with pytest.raises(TemplateBuildValidationError):
            queue_template_build(
                db,
                actor_user_id=UUID("00000000-0000-0000-0000-000000000001"),
                template_id=template.id,
                version_id=draft.id,
                payload=QueueTemplateBuildInput(base_image="python:3.12-slim-bookworm"),
            )


def test_queue_build_creates_row_and_enqueues(
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    enqueued: list[str] = []

    def _fake_enqueue(build_id: str) -> str:
        enqueued.append(build_id)
        return "job"

    monkeypatch.setattr("kuuna_backend.domain.template_builds.service.enqueue_template_build", _fake_enqueue)

    with test_session_factory() as db:
        version = _published_version(db)

        build = queue_template_build(
            db,
            actor_user_id=UUID("00000000-0000-0000-0000-000000000002"),
            template_id=version.template_id,
            version_id=version.id,
            payload=QueueTemplateBuildInput(base_image="python:3.12-slim-bookworm"),
        )

        assert build.status == TemplateBuildStatus.QUEUED
        assert enqueued == [str(build.id)]

        persisted = db.get(TemplateBuild, build.id)
        assert persisted is not None


def test_queue_build_rejects_bad_base_image(test_session_factory: sessionmaker[Session]) -> None:
    with test_session_factory() as db:
        version = _published_version(db)

        with pytest.raises(TemplateBuildValidationError):
            queue_template_build(
                db,
                actor_user_id=UUID("00000000-0000-0000-0000-000000000003"),
                template_id=version.template_id,
                version_id=version.id,
                payload=QueueTemplateBuildInput(base_image="bad image"),
            )
