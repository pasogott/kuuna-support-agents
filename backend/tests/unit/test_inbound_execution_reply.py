from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import kuuna_backend.jobs.ingest as ingest_jobs
from kuuna_backend.db.models import (
    AgentInstance,
    BindingStatus,
    GroupBinding,
    GroupTemplate,
    Message,
    MessageEventType,
    MessageVersion,
    OutboundIntent,
    RuntimeStatus,
    RuntimeMode,
    TemplateBuild,
    TemplateBuildStatus,
    TemplateVersion,
    TemplateVersionStatus,
)


def _seed_active_binding(
    db: Session,
    *,
    provider_group_id: str,
    tools_config: dict[str, object],
) -> tuple[str, str]:
    template = GroupTemplate(key=f"tpl-{provider_group_id}", display_name="Template")
    db.add(template)
    db.flush()

    template_version = TemplateVersion(
        template_id=template.id,
        version_no=1,
        status=TemplateVersionStatus.PUBLISHED,
        system_prompt="You are a support assistant.",
        model_config={"model": "gpt-4.1-mini"},
        tools_config=tools_config,
        egress_policy={},
    )
    db.add(template_version)
    db.flush()

    db.add(
        TemplateBuild(
            template_id=template.id,
            template_version_id=template_version.id,
            status=TemplateBuildStatus.SUCCEEDED,
            image_ref="test/client-template:unit",
            image_tag="test/client-template:unit",
            build_inputs={},
            logs_ref=None,
        )
    )
    db.flush()

    binding = GroupBinding(
        provider_group_id=provider_group_id,
        template_version_id=template_version.id,
        status=BindingStatus.ACTIVE,
    )
    db.add(binding)
    db.flush()

    agent_instance = AgentInstance(
        group_binding_id=binding.id,
        runtime_mode=RuntimeMode.ON_DEMAND,
        status=RuntimeStatus.HEALTHY,
    )
    db.add(agent_instance)
    db.flush()

    message = Message(
        provider_group_id=provider_group_id,
        provider_message_id="msg-001",
        sender_provider_user_id="user-1",
        latest_version_no=1,
    )
    db.add(message)
    db.flush()

    message_version = MessageVersion(
        message_id=message.id,
        version_no=1,
        event_type=MessageEventType.CREATED,
        is_deleted=False,
        text_content="/tool uppercase hallo welt",
        raw_event={},
        occurred_at=datetime.now(timezone.utc),
    )
    db.add(message_version)
    db.commit()

    return str(message.id), str(agent_instance.id)


def test_process_inbound_message_job_executes_enabled_tool_command(
    test_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    provider_group_id = "group-tool@g.us"

    with test_session_factory() as db:
        message_id, agent_instance_id = _seed_active_binding(
            db,
            provider_group_id=provider_group_id,
            tools_config={"allowed_tools": ["uppercase"]},
        )

    monkeypatch.setattr(ingest_jobs, "get_db_session", lambda: test_session_factory())
    monkeypatch.setattr(ingest_jobs, "enqueue_outbound_dispatch", lambda _: "job-outbound")

    ingest_jobs.process_inbound_message_job(
        message_id=message_id,
        provider_group_id=provider_group_id,
        reason="mention",
        trace_id="trace-tool-1",
    )

    with test_session_factory() as db:
        outbound_intent = db.scalar(
            select(OutboundIntent)
            .where(OutboundIntent.provider_group_id == provider_group_id)
            .order_by(OutboundIntent.created_at.desc())
            .limit(1)
        )

    assert outbound_intent is not None
    payload = outbound_intent.payload
    assert "HALLO WELT" in str(payload.get("text"))

    metadata = payload.get("metadata")
    assert isinstance(metadata, dict)
    assert metadata.get("agent_instance_id") == agent_instance_id
    assert metadata.get("allowed_tools") == ["uppercase"]


def test_process_inbound_message_job_fallback_reply_contains_context_hint(
    test_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    provider_group_id = "group-fallback@g.us"

    with test_session_factory() as db:
        message_id, _ = _seed_active_binding(
            db,
            provider_group_id=provider_group_id,
            tools_config={},
        )

        latest = db.scalar(
            select(MessageVersion)
            .join(Message, Message.id == MessageVersion.message_id)
            .where(
                Message.id == UUID(message_id),
                MessageVersion.version_no == 1,
            )
            .limit(1)
        )
        assert latest is not None
        latest.text_content = "Kannst du mir bei einer Rechnung helfen?"
        db.commit()

    monkeypatch.setattr(ingest_jobs, "get_db_session", lambda: test_session_factory())
    monkeypatch.setattr(ingest_jobs, "enqueue_outbound_dispatch", lambda _: "job-outbound")
    monkeypatch.setattr(ingest_jobs, "is_openai_configured", lambda: False)
    monkeypatch.setattr(ingest_jobs, "_run_via_runtime_agent", lambda **kwargs: None)

    ingest_jobs.process_inbound_message_job(
        message_id=message_id,
        provider_group_id=provider_group_id,
        reason="mention",
        trace_id="trace-fallback-1",
    )

    with test_session_factory() as db:
        outbound_intent = db.scalar(
            select(OutboundIntent)
            .where(OutboundIntent.provider_group_id == provider_group_id)
            .order_by(OutboundIntent.created_at.desc())
            .limit(1)
        )

    assert outbound_intent is not None
    payload = outbound_intent.payload
    text = str(payload.get("text"))
    assert "Danke für deine Nachricht." in text

    metadata = payload.get("metadata")
    assert isinstance(metadata, dict)
    retrieval_refs = metadata.get("retrieval_refs")
    assert isinstance(retrieval_refs, list)
