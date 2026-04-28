from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from kuuna_backend.db.models import (
    Message,
    OutboundIntent,
    Role,
    RoleName,
    TemplateBuild,
    TemplateBuildStatus,
    TemplateVersion,
    User,
    UserRole,
)
from kuuna_backend.domain.auth.service import hash_password
from kuuna_backend.jobs import ingest as ingest_jobs
import kuuna_backend.domain.messages.ingest as ingest_domain


def _seed_owner(db: Session) -> None:
    owner = User(
        email="owner-e2e@example.com",
        password_hash=hash_password("OwnerSecure123!"),
        must_change_password=False,
        is_active=True,
    )
    db.add(owner)
    db.flush()

    role_owner = db.scalar(select(Role).where(Role.name == RoleName.OWNER))
    if role_owner is None:
        role_owner = Role(name=RoleName.OWNER)
        db.add(role_owner)
        db.flush()

    db.add(UserRole(user_id=owner.id, role_id=role_owner.id))
    db.commit()


def test_e2e_smoke_login_bind_ingest_route_reply_trace(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    with test_session_factory() as db:
        _seed_owner(db)

    # Keep smoke deterministic and fast: no real queue/network dispatch.
    monkeypatch.setattr(ingest_domain, "enqueue_media_processing", lambda *args, **kwargs: "job-media")
    monkeypatch.setattr(ingest_domain, "enqueue_inbound_execution", lambda *args, **kwargs: "job-inbound")
    monkeypatch.setattr(ingest_jobs, "enqueue_outbound_dispatch", lambda *args, **kwargs: "job-outbound")
    monkeypatch.setattr(ingest_jobs, "get_db_session", lambda: test_session_factory())
    monkeypatch.setattr(
        ingest_jobs,
        "_run_via_runtime_agent",
        lambda **kwargs: {
            "success": True,
            "response_text": "E2E smoke compiled reply",
            "model_path": ["gpt-4.1-mini"],
            "execution": {"image_ref": str(kwargs.get("image_ref") or ""), "duration_ms": 1},
            "audit_payload": {"success": True},
        },
    )

    login_response = client.post(
        "/auth/login",
        json={"email": "owner-e2e@example.com", "password": "OwnerSecure123!"},
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    template_response = client.post(
        "/templates",
        json={"key": "e2e-smoke-template", "display_name": "E2E Smoke Template"},
        headers=headers,
    )
    assert template_response.status_code == 201
    template_id = template_response.json()["id"]

    version_response = client.post(
        f"/templates/{template_id}/versions",
        json={
            "system_prompt": "You are a concise support assistant.",
            "model_settings": {"model": "gpt-4.1-mini"},
            "tools_config": {},
            "egress_policy": {},
        },
        headers=headers,
    )
    assert version_response.status_code == 201
    version_id = version_response.json()["id"]

    publish_response = client.post(
        f"/templates/{template_id}/versions/{version_id}/publish",
        headers=headers,
    )
    assert publish_response.status_code == 200

    provider_group_id = "e2e-smoke-group@g.us"
    binding_response = client.post(
        "/bindings",
        json={
            "provider_group_id": provider_group_id,
            "template_version_id": version_id,
        },
        headers=headers,
    )
    assert binding_response.status_code == 201
    assert binding_response.json()["status"] == "active"

    with test_session_factory() as db:
        tv = db.get(TemplateVersion, UUID(version_id))
        assert tv is not None
        db.add(
            TemplateBuild(
                template_id=tv.template_id,
                template_version_id=tv.id,
                status=TemplateBuildStatus.SUCCEEDED,
                image_ref="test/e2e-client-template:smoke",
                image_tag="test/e2e-client-template:smoke",
                build_inputs={},
                logs_ref=None,
            )
        )
        db.commit()

    trace_id = str(uuid4())
    provider_message_id = "e2e-msg-001"
    inbound_payload = {
        "trace_id": trace_id,
        "provider": "whatsapp-neonize",
        "provider_group_id": provider_group_id,
        "provider_message_id": provider_message_id,
        "sender_provider_user_id": "user-1",
        "event_type": "message_created",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "message": {
            "text": "@agent help me",
            "reply_to_provider_message_id": None,
            "mentions": ["agent"],
            "media": [],
        },
        "raw_event": {
            "provider_payload": {"kind": "MessageEv", "message_id": provider_message_id},
            "raw_flags": {"from_me": False},
        },
    }

    ingest_response = client.post("/gateway/inbound", json=inbound_payload)
    assert ingest_response.status_code == 202

    with test_session_factory() as db:
        message = db.scalar(
            select(Message).where(
                Message.provider_group_id == provider_group_id,
                Message.provider_message_id == provider_message_id,
            )
        )
        assert message is not None
        message_id = str(message.id)

    ingest_jobs.process_inbound_message_job(
        message_id=message_id,
        provider_group_id=provider_group_id,
        reason="mention",
        trace_id=trace_id,
    )

    with test_session_factory() as db:
        outbound_intent = db.scalar(
            select(OutboundIntent)
            .where(OutboundIntent.provider_group_id == provider_group_id)
            .order_by(OutboundIntent.created_at.desc())
            .limit(1)
        )
        assert outbound_intent is not None

    trace_response = client.get(f"/audit/trace/message/{provider_group_id}/{provider_message_id}", headers=headers)
    assert trace_response.status_code == 200

    trace_payload = trace_response.json()
    assert trace_payload["provider_group_id"] == provider_group_id
    assert trace_payload["provider_message_id"] == provider_message_id
    assert trace_payload["ingest"] is not None
    assert len(trace_payload["versions"]) >= 1
    assert len(trace_payload["outbound"]) >= 1

    outbound_trace = trace_payload["outbound"][0]
    assert outbound_trace["trace_id"] == trace_id
    assert outbound_trace["payload"]["reply_to_provider_message_id"] == provider_message_id
