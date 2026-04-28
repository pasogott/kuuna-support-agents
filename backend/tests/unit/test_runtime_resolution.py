from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from kuuna_backend.db.models import (
    AgentInstance,
    BindingStatus,
    GroupBinding,
    GroupTemplate,
    TemplateBuild,
    TemplateBuildStatus,
    TemplateVersion,
    TemplateVersionStatus,
)
from kuuna_backend.domain.runtime.resolve import NoBindingError, NoSuccessfulBuildError, resolve_runtime_target


def _create_published_template_version(db: Session, *, key: str) -> TemplateVersion:
    template = GroupTemplate(key=key, display_name=key)
    db.add(template)
    db.flush()

    version = TemplateVersion(
        template_id=template.id,
        version_no=1,
        status=TemplateVersionStatus.PUBLISHED,
        system_prompt="prompt",
        model_config={"provider": "openai", "model_name": "gpt-4.1-mini"},
        tools_config={"allowed_tools": ["echo"]},
        egress_policy={},
    )
    db.add(version)
    db.flush()
    return version


def test_resolve_runtime_target_no_binding(test_session_factory: sessionmaker[Session]) -> None:
    with test_session_factory() as db:
        with pytest.raises(NoBindingError):
            resolve_runtime_target(db, provider_group_id="missing@g.us")


def test_resolve_runtime_target_returns_binding_and_version_without_build(
    test_session_factory: sessionmaker[Session],
) -> None:
    with test_session_factory() as db:
        version = _create_published_template_version(db, key="rt-no-build")

        binding = GroupBinding(
            provider_group_id="group-a@g.us",
            template_version_id=version.id,
            status=BindingStatus.ACTIVE,
        )
        db.add(binding)
        db.flush()

        agent = AgentInstance(group_binding_id=binding.id)
        db.add(agent)
        db.commit()

        resolved = resolve_runtime_target(db, provider_group_id="group-a@g.us")
        assert resolved.binding_id == binding.id
        assert resolved.template_version_id == version.id
        assert resolved.agent_instance_id == agent.id
        assert resolved.template_build_id is None
        assert resolved.image_ref is None


def test_resolve_runtime_target_requires_successful_build(
    test_session_factory: sessionmaker[Session],
) -> None:
    with test_session_factory() as db:
        version = _create_published_template_version(db, key="rt-require-build")

        binding = GroupBinding(
            provider_group_id="group-b@g.us",
            template_version_id=version.id,
            status=BindingStatus.ACTIVE,
        )
        db.add(binding)
        db.flush()
        db.add(AgentInstance(group_binding_id=binding.id))
        db.commit()

        with pytest.raises(NoSuccessfulBuildError):
            resolve_runtime_target(db, provider_group_id="group-b@g.us", require_successful_build=True)


def test_resolve_runtime_target_picks_latest_succeeded_build(
    test_session_factory: sessionmaker[Session],
) -> None:
    with test_session_factory() as db:
        version = _create_published_template_version(db, key="rt-latest-build")

        binding = GroupBinding(
            provider_group_id="group-c@g.us",
            template_version_id=version.id,
            status=BindingStatus.ACTIVE,
        )
        db.add(binding)
        db.flush()
        db.add(AgentInstance(group_binding_id=binding.id))

        # Older succeeded
        t0 = datetime.now(UTC)
        older = TemplateBuild(
            template_id=version.template_id,
            template_version_id=version.id,
            status=TemplateBuildStatus.SUCCEEDED,
            image_ref="repo/runtime@sha256:old",
            image_tag="v1",
            build_inputs={},
            logs_ref=None,
            created_at=t0,
            updated_at=t0,
        )
        db.add(older)
        db.flush()

        # Newer failed (should not be picked)
        db.add(
            TemplateBuild(
                template_id=version.template_id,
                template_version_id=version.id,
                status=TemplateBuildStatus.FAILED,
                image_ref=None,
                image_tag=None,
                build_inputs={},
                logs_ref=None,
                created_at=t0 + timedelta(seconds=1),
                updated_at=t0 + timedelta(seconds=1),
            )
        )
        db.flush()

        # Newer succeeded
        newer = TemplateBuild(
            template_id=version.template_id,
            template_version_id=version.id,
            status=TemplateBuildStatus.SUCCEEDED,
            image_ref="repo/runtime@sha256:new",
            image_tag="v2",
            build_inputs={},
            logs_ref=None,
            created_at=t0 + timedelta(seconds=2),
            updated_at=t0 + timedelta(seconds=2),
        )
        db.add(newer)
        db.commit()

        resolved = resolve_runtime_target(db, provider_group_id="group-c@g.us", require_successful_build=True)
        assert resolved.template_build_id == newer.id
        assert resolved.image_ref == "repo/runtime@sha256:new"


def test_resolve_runtime_target_requires_non_empty_image_ref(
    test_session_factory: sessionmaker[Session],
) -> None:
    with test_session_factory() as db:
        version = _create_published_template_version(db, key="rt-empty-image-ref")

        binding = GroupBinding(
            provider_group_id="group-d@g.us",
            template_version_id=version.id,
            status=BindingStatus.ACTIVE,
        )
        db.add(binding)
        db.flush()
        db.add(AgentInstance(group_binding_id=binding.id))

        db.add(
            TemplateBuild(
                template_id=version.template_id,
                template_version_id=version.id,
                status=TemplateBuildStatus.SUCCEEDED,
                image_ref=None,
                image_tag="only-tag",
                build_inputs={},
                logs_ref=None,
            )
        )
        db.commit()

        with pytest.raises(NoSuccessfulBuildError):
            resolve_runtime_target(db, provider_group_id="group-d@g.us", require_successful_build=True)

