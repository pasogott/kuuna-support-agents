from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select

from kuuna_backend.db.models import (
    AgentInstance,
    BindingStatus,
    GroupBinding,
    Message,
    MessageVersion,
    RuntimeStatus,
    RuntimeRun,
    RuntimeRunStatus,
    TemplateVersion,
)
from kuuna_backend.domain.runtime.resolve import (
    NoBindingError,
    NoSuccessfulBuildError,
    resolve_runtime_target,
)
from kuuna_backend.domain.outbound.service import create_outbound_intent, mark_outbound_intent_failed
from kuuna_backend.domain.audit.service import append_audit_event
from kuuna_backend.domain.retrieval import RetrievalHit, retrieve_context
from kuuna_backend.domain.templates.tools import extract_allowed_tools
from kuuna_backend.integrations.openai import (
    OpenAIIntegrationError,
    create_chat_completion,
    is_openai_configured,
)
from kuuna_backend.integrations.postgres import get_db_session
from kuuna_backend.jobs.queue import enqueue_outbound_dispatch

logger = logging.getLogger(__name__)

_INBOUND_CONFIRMATION_TEXT = "Danke, wir haben deine Nachricht erhalten."
_DEFAULT_SYSTEM_PROMPT = (
    "Du bist ein hilfreicher Support-Agent für eine WhatsApp-Gruppe. "
    "Antworte präzise, freundlich und mit klaren nächsten Schritten."
)
_DEFAULT_MODEL = "gpt-4.1-mini"
_DEFAULT_RUNTIME_AGENT_BASE_URL = "http://runtime-agent:8100"
_DEFAULT_RUNTIME_AGENT_TIMEOUT_SECONDS = 12.0
_PROVIDER_TOKENS = {"openai", "anthropic", "google", "azure-openai"}
_TOOL_COMMAND_PATTERN = re.compile(r"^\s*/tool\s+([a-zA-Z0-9_-]+)(?:\s+(.*))?$")

ToolHandler = Callable[[str], str]


@dataclass(slots=True)
class AgentReply:
    text: str
    model_path: list[str]
    retrieval_refs: list[dict[str, object]]
    allowed_tools: list[str]
    runtime_execution: dict[str, object] | None = None


def _tool_echo(value: str) -> str:
    return value or "(leer)"


def _tool_uppercase(value: str) -> str:
    return value.upper()


LOCAL_TOOL_HANDLERS: dict[str, ToolHandler] = {
    "echo": _tool_echo,
    "uppercase": _tool_uppercase,
}


def process_inbound_message_job(
    message_id: str,
    provider_group_id: str,
    reason: str | None = None,
    trace_id: str | None = None,
) -> None:
    db = get_db_session()
    message_uuid: UUID | None = None

    try:
        try:
            message_uuid = UUID(message_id)
        except ValueError:
            logger.error(
                "inbound_execution_invalid_message_id",
                extra={
                    "trace_id": trace_id,
                    "message_id": message_id,
                    "provider_group_id": provider_group_id,
                    "reason": reason,
                },
            )
            return

        message = db.execute(
            select(Message)
            .where(
                Message.id == message_uuid,
                Message.provider_group_id == provider_group_id,
            )
            .limit(1)
        ).scalar_one_or_none()
        if message is None:
            logger.warning(
                "inbound_execution_message_not_found",
                extra={
                    "trace_id": trace_id,
                    "message_id": message_id,
                    "provider_group_id": provider_group_id,
                    "reason": reason,
                },
            )
            return

        try:
            resolved = resolve_runtime_target(
                db,
                provider_group_id=provider_group_id,
                require_successful_build=True,
            )
        except NoBindingError:
            logger.info(
                "inbound_execution_skipped_unbound_group",
                extra={
                    "trace_id": trace_id,
                    "message_id": message_id,
                    "provider_group_id": provider_group_id,
                    "reason": reason,
                },
            )
            return
        except NoSuccessfulBuildError:
            logger.error(
                "inbound_execution_skipped_no_successful_template_build",
                extra={
                    "trace_id": trace_id,
                    "message_id": message_id,
                    "provider_group_id": provider_group_id,
                    "reason": reason,
                },
            )
            return

        binding = db.get(GroupBinding, resolved.binding_id)
        template_version = db.get(TemplateVersion, resolved.template_version_id)
        agent_instance = (
            db.get(AgentInstance, resolved.agent_instance_id)
            if resolved.agent_instance_id is not None
            else None
        )
        if binding is None or template_version is None:
            logger.error(
                "inbound_execution_resolution_inconsistent",
                extra={
                    "trace_id": trace_id,
                    "message_id": message_id,
                    "provider_group_id": provider_group_id,
                    "binding_id": str(resolved.binding_id),
                    "template_version_id": str(resolved.template_version_id),
                    "reason": reason,
                },
            )
            return

        if agent_instance is None:
            logger.error(
                "inbound_execution_missing_agent_instance",
                extra={
                    "trace_id": trace_id,
                    "message_id": message_id,
                    "provider_group_id": provider_group_id,
                    "binding_id": str(binding.id),
                    "reason": reason,
                },
            )
            return

        if agent_instance.status == RuntimeStatus.STOPPED:
            logger.warning(
                "inbound_execution_agent_stopped",
                extra={
                    "trace_id": trace_id,
                    "message_id": message_id,
                    "provider_group_id": provider_group_id,
                    "binding_id": str(binding.id),
                    "agent_instance_id": str(agent_instance.id),
                    "reason": reason,
                },
            )
            return

        latest_message_version = db.execute(
            select(MessageVersion)
            .where(
                MessageVersion.message_id == message.id,
                MessageVersion.version_no == message.latest_version_no,
            )
            .limit(1)
        ).scalar_one_or_none()
        user_text = _extract_user_text(latest_message_version)

        if not resolved.image_ref:
            logger.error(
                "inbound_execution_missing_image_ref_after_resolution",
                extra={
                    "trace_id": trace_id,
                    "message_id": message_id,
                    "provider_group_id": provider_group_id,
                    "template_build_id": str(resolved.template_build_id)
                    if resolved.template_build_id
                    else None,
                    "reason": reason,
                },
            )
            return

        agent_reply = _generate_agent_reply(
            db=db,
            provider_group_id=provider_group_id,
            user_text=user_text,
            template_version=template_version,
            trace_id=trace_id,
            image_ref=resolved.image_ref,
            message_id=message.id,
            binding_id=binding.id,
            template_build_id=resolved.template_build_id,
        )

        outbound_intent = create_outbound_intent(
            db,
            provider_group_id=provider_group_id,
            payload={
                "trace_id": trace_id or str(uuid4()),
                "provider_group_id": provider_group_id,
                "reply_to_provider_message_id": message.provider_message_id,
                "text": agent_reply.text,
                "metadata": {
                    "agent_instance_id": agent_instance.id,
                    "binding_id": str(binding.id),
                    "template_version_id": str(template_version.id),
                    "template_build_id": (
                        str(resolved.template_build_id)
                        if resolved.template_build_id is not None
                        else None
                    ),
                    "image_ref": resolved.image_ref,
                    "runtime_run_id": (
                        str(agent_reply.runtime_execution.get("runtime_run_id"))
                        if isinstance(agent_reply.runtime_execution, dict)
                        and isinstance(agent_reply.runtime_execution.get("runtime_run_id"), str)
                        and agent_reply.runtime_execution.get("runtime_run_id")
                        else None
                    ),
                    "model_path": agent_reply.model_path,
                    "retrieval_refs": agent_reply.retrieval_refs,
                    "allowed_tools": agent_reply.allowed_tools,
                    "runtime_execution": agent_reply.runtime_execution,
                },
            },
        )

        try:
            enqueue_outbound_dispatch(str(outbound_intent.outbound_intent_id))
        except Exception as exc:
            mark_outbound_intent_failed(
                db,
                outbound_intent.outbound_intent_id,
                error_code="inbound_execution_dispatch_enqueue_failed",
                error_message=str(exc),
            )
            logger.exception(
                "inbound_execution_dispatch_enqueue_failed",
                extra={
                    "trace_id": trace_id,
                    "message_id": message_id,
                    "provider_group_id": provider_group_id,
                    "binding_id": str(binding.id),
                    "agent_instance_id": str(agent_instance.id),
                    "outbound_intent_id": str(outbound_intent.outbound_intent_id),
                    "reason": reason,
                },
            )
            return

        logger.info(
            "inbound_execution_outbound_intent_enqueued",
            extra={
                "trace_id": trace_id,
                "message_id": message_id,
                "provider_group_id": provider_group_id,
                "binding_id": str(binding.id),
                "agent_instance_id": str(agent_instance.id),
                "outbound_intent_id": str(outbound_intent.outbound_intent_id),
                "model_path": agent_reply.model_path,
                "retrieval_refs_count": len(agent_reply.retrieval_refs),
                "reason": reason,
            },
        )
    except Exception:
        db.rollback()
        logger.exception(
            "inbound_execution_failed",
            extra={
                "trace_id": trace_id,
                "message_id": message_id,
                "provider_group_id": provider_group_id,
                "reason": reason,
            },
        )
        raise
    finally:
        db.close()


def _extract_user_text(latest_message_version: MessageVersion | None) -> str:
    if latest_message_version is None or latest_message_version.is_deleted:
        return ""
    return (latest_message_version.text_content or "").strip()


def _generate_agent_reply(
    *,
    db,
    provider_group_id: str,
    user_text: str,
    template_version: TemplateVersion,
    trace_id: str | None,
    image_ref: str,
    message_id: UUID,
    binding_id: UUID,
    template_build_id: UUID | None,
) -> AgentReply:
    allowed_tools = extract_allowed_tools(template_version.tools_config)
    model_candidates = _extract_model_candidates(template_version.model_config)

    retrieval_hits: list[RetrievalHit] = []
    if user_text:
        retrieval_hits = retrieve_context(
            db,
            provider_group_id=provider_group_id,
            query=user_text,
            limit=8,
        )
    retrieval_refs = _build_retrieval_refs(retrieval_hits)

    tool_reply = _maybe_execute_tool_command(user_text=user_text, allowed_tools=allowed_tools)
    if tool_reply is not None:
        return AgentReply(
            text=tool_reply,
            model_path=[],
            retrieval_refs=retrieval_refs,
            allowed_tools=allowed_tools,
        )

    if not user_text:
        return AgentReply(
            text=_INBOUND_CONFIRMATION_TEXT,
            model_path=model_candidates[:1],
            retrieval_refs=retrieval_refs,
            allowed_tools=allowed_tools,
        )

    assembled_system_prompt = _build_system_prompt(
        template_system_prompt=template_version.system_prompt,
        allowed_tools=allowed_tools,
    )
    assembled_user_prompt = _build_user_prompt(user_text=user_text, retrieval_hits=retrieval_hits)

    run = RuntimeRun(
        provider_group_id=provider_group_id,
        message_id=message_id,
        binding_id=binding_id,
        template_version_id=template_version.id,
        template_build_id=template_build_id,
        image_ref=image_ref,
        status=RuntimeRunStatus.STARTED,
        execution={
            "trace_id": trace_id,
            "requested": {
                "model_path": model_candidates,
                "allowed_tools": allowed_tools,
            },
        },
    )
    db.add(run)
    db.flush()

    runtime_result = _run_via_runtime_agent(
        trace_id=trace_id,
        provider_group_id=provider_group_id,
        system_prompt=assembled_system_prompt,
        user_prompt=assembled_user_prompt,
        model_path=model_candidates,
        allowed_tools=allowed_tools,
        retrieval_refs=retrieval_refs,
        image_ref=image_ref,
    )
    if runtime_result is not None:
        execution = runtime_result.get("execution")
        if isinstance(execution, dict):
            run.execution = {**(run.execution or {}), **execution}

        run.finished_at = datetime.now(UTC)
        run.duration_ms = (
            int(execution.get("duration_ms"))
            if isinstance(execution, dict) and isinstance(execution.get("duration_ms"), int)
            else run.duration_ms
        )

        if runtime_result.get("success") is True:
            run.status = RuntimeRunStatus.SUCCEEDED
            run.error = None
        else:
            timed_out = bool(execution.get("timed_out")) if isinstance(execution, dict) else False
            run.status = RuntimeRunStatus.TIMEOUT if timed_out else RuntimeRunStatus.FAILED
            run.error = str(runtime_result.get("audit_payload", {}).get("error") or runtime_result.get("error") or "")

        append_audit_event(
            db,
            actor_user_id=None,
            event_type="runtime.execution",
            entity_type="message",
            entity_id=str(message_id),
            payload={
                **(runtime_result.get("audit_payload", {}) if isinstance(runtime_result.get("audit_payload"), dict) else {}),
                "runtime_run_id": str(run.id),
                "binding_id": str(binding_id),
                "template_version_id": str(template_version.id),
                "template_build_id": str(template_build_id) if template_build_id else None,
                "image_ref": image_ref,
                "status": run.status.value,
                "duration_ms": run.duration_ms,
            },
        )

    if runtime_result is not None and runtime_result.get("success") is True:
        response_text = str(runtime_result.get("response_text") or "").strip()
        runtime_model_path = runtime_result.get("model_path") or []
        execution_out = runtime_result.get("execution")
        execution_with_id = (
            {**execution_out, "runtime_run_id": str(run.id)}
            if isinstance(execution_out, dict)
            else {"runtime_run_id": str(run.id)}
        )
        return AgentReply(
            text=response_text,
            model_path=runtime_model_path,
            retrieval_refs=retrieval_refs,
            allowed_tools=allowed_tools,
            runtime_execution=execution_with_id,
        )

    if is_openai_configured():
        attempted_models: list[str] = []
        for model_name in model_candidates:
            attempted_models.append(model_name)
            try:
                response_text = create_chat_completion(
                    model=model_name,
                    system_prompt=assembled_system_prompt,
                    user_prompt=assembled_user_prompt,
                )
                if response_text.strip():
                    return AgentReply(
                        text=response_text.strip(),
                        model_path=attempted_models,
                        retrieval_refs=retrieval_refs,
                        allowed_tools=allowed_tools,
                    )
            except OpenAIIntegrationError as exc:
                logger.warning(
                    "inbound_execution_model_failed",
                    extra={
                        "trace_id": trace_id,
                        "provider_group_id": provider_group_id,
                        "model": model_name,
                        "error": str(exc),
                    },
                )

    return AgentReply(
        text=_build_fallback_reply(user_text=user_text, retrieval_hits=retrieval_hits),
        model_path=model_candidates[:1],
        retrieval_refs=retrieval_refs,
        allowed_tools=allowed_tools,
    )


def _extract_model_candidates(model_config: object) -> list[str]:
    if not isinstance(model_config, dict):
        return [_DEFAULT_MODEL]

    raw_candidates: list[str] = []

    for key in (
        "failover_chain",
        "failoverChain",
        "model_chain",
        "modelChain",
        "models",
        "model_path",
    ):
        value = model_config.get(key)
        if isinstance(value, list):
            raw_candidates.extend(item for item in value if isinstance(item, str))

    for key in ("model", "model_name", "modelName", "model_id", "modelId"):
        value = model_config.get(key)
        if isinstance(value, str):
            raw_candidates.append(value)

    nested_model = model_config.get("model")
    if isinstance(nested_model, dict):
        provider = nested_model.get("provider")
        model_name = nested_model.get("model_name") or nested_model.get("model")
        if isinstance(provider, str) and isinstance(model_name, str):
            raw_candidates.append(f"{provider}/{model_name}")

    normalized: list[str] = []
    for candidate in raw_candidates:
        normalized_candidate = _normalize_model_candidate(candidate)
        if normalized_candidate and normalized_candidate not in normalized:
            normalized.append(normalized_candidate)

    return normalized or [_DEFAULT_MODEL]


def _normalize_model_candidate(candidate: str) -> str:
    normalized = candidate.strip()
    if not normalized:
        return ""

    lowered = normalized.lower()
    if lowered in _PROVIDER_TOKENS:
        return ""

    if "/" in normalized:
        provider, model_name = normalized.split("/", 1)
        if provider.strip().lower() in _PROVIDER_TOKENS:
            return model_name.strip()

    return normalized


def _build_system_prompt(*, template_system_prompt: str | None, allowed_tools: list[str]) -> str:
    base_prompt = (template_system_prompt or _DEFAULT_SYSTEM_PROMPT).strip()
    if not allowed_tools:
        return base_prompt

    tools_block = ", ".join(allowed_tools)
    return f"{base_prompt}\n\nAktivierte Tools für diese Gruppe: {tools_block}."


def _build_user_prompt(*, user_text: str, retrieval_hits: list[RetrievalHit]) -> str:
    if not retrieval_hits:
        return user_text

    context_lines = ["Kontext aus Chat/Knowledge:"]
    for hit in retrieval_hits[:6]:
        scope = hit.source_scope
        snippet = hit.content.strip().replace("\n", " ")
        if len(snippet) > 220:
            snippet = f"{snippet[:220]}…"
        context_lines.append(f"- [{scope}] {snippet}")

    context_block = "\n".join(context_lines)
    return f"Nutzeranfrage:\n{user_text}\n\n{context_block}"


def _runtime_agent_base_url() -> str:
    return os.getenv("RUNTIME_AGENT_BASE_URL", _DEFAULT_RUNTIME_AGENT_BASE_URL).rstrip("/")


def _runtime_agent_timeout_seconds() -> float:
    raw_value = os.getenv("RUNTIME_AGENT_TIMEOUT_SECONDS")
    if not raw_value:
        return _DEFAULT_RUNTIME_AGENT_TIMEOUT_SECONDS

    try:
        return float(raw_value)
    except ValueError:
        return _DEFAULT_RUNTIME_AGENT_TIMEOUT_SECONDS


def _run_via_runtime_agent(
    *,
    trace_id: str | None,
    provider_group_id: str,
    system_prompt: str,
    user_prompt: str,
    model_path: list[str],
    allowed_tools: list[str],
    retrieval_refs: list[dict[str, object]],
    image_ref: str,
) -> dict[str, object] | None:
    payload = {
        "trace_id": trace_id,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "context": {
            "provider_group_id": provider_group_id,
            "retrieval_refs": retrieval_refs,
        },
        "model_path": model_path,
        "allowed_tools": allowed_tools,
        "tool_requests": [],
        "image_ref": image_ref,
    }

    try:
        response = httpx.post(
            f"{_runtime_agent_base_url()}/run",
            json=payload,
            timeout=_runtime_agent_timeout_seconds(),
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning(
            "runtime_agent_request_failed",
            extra={
                "trace_id": trace_id,
                "provider_group_id": provider_group_id,
                "error": str(exc),
            },
        )
        return {
            "success": False,
            "response_text": None,
            "model_path": [],
            "execution": None,
            "audit_payload": {
                "trace_id": trace_id,
                "provider_group_id": provider_group_id,
                "image_ref": image_ref,
                "success": False,
                "error": str(exc),
            },
        }

    result_payload = response.json()
    execution = result_payload.get("execution") if isinstance(result_payload, dict) else None
    error_value = result_payload.get("error") if isinstance(result_payload, dict) else None

    if not bool(result_payload.get("success")):
        logger.warning(
            "runtime_agent_execution_unsuccessful",
            extra={
                "trace_id": trace_id,
                "provider_group_id": provider_group_id,
                "error": str(result_payload.get("error")),
            },
        )
        return {
            "success": False,
            "response_text": None,
            "model_path": [],
            "execution": execution if isinstance(execution, dict) else None,
            "audit_payload": {
                "trace_id": trace_id,
                "provider_group_id": provider_group_id,
                "image_ref": image_ref,
                "success": False,
                "error": str(error_value or "runtime-agent unsuccessful"),
                "execution": execution if isinstance(execution, dict) else None,
            },
        }

    response_text = str(result_payload.get("response_text") or "").strip()
    if not response_text:
        return {
            "success": False,
            "response_text": None,
            "model_path": [],
            "execution": execution if isinstance(execution, dict) else None,
            "audit_payload": {
                "trace_id": trace_id,
                "provider_group_id": provider_group_id,
                "image_ref": image_ref,
                "success": False,
                "error": "runtime-agent returned empty response_text",
                "execution": execution if isinstance(execution, dict) else None,
            },
        }

    attempts = result_payload.get("attempts")
    attempt_models: list[str] = []
    if isinstance(attempts, list):
        for attempt in attempts:
            if isinstance(attempt, dict):
                model_name = attempt.get("model")
                if isinstance(model_name, str) and model_name and model_name not in attempt_models:
                    attempt_models.append(model_name)

    if not attempt_models:
        model_used = result_payload.get("model_used")
        if isinstance(model_used, str) and model_used:
            attempt_models = [model_used]

    normalized_model_path = attempt_models or model_path[:1]

    return {
        "success": True,
        "response_text": response_text,
        "model_path": normalized_model_path,
        "execution": execution if isinstance(execution, dict) else None,
        "audit_payload": {
            "trace_id": trace_id,
            "provider_group_id": provider_group_id,
            "image_ref": image_ref,
            "success": True,
            "model_path": normalized_model_path,
            "execution": execution if isinstance(execution, dict) else None,
        },
    }


def _build_retrieval_refs(retrieval_hits: list[RetrievalHit]) -> list[dict[str, object]]:
    refs: list[dict[str, object]] = []
    for hit in retrieval_hits:
        ref: dict[str, object] = {
            "source_type": hit.source_type,
            "source_scope": hit.source_scope,
            "score": round(hit.score, 4),
        }

        if hit.provider_message_id is not None:
            ref["provider_message_id"] = hit.provider_message_id
        if hit.message_id is not None:
            ref["message_id"] = str(hit.message_id)
        if hit.message_version_id is not None:
            ref["message_version_id"] = str(hit.message_version_id)
        if hit.knowledge_version_id is not None:
            ref["knowledge_version_id"] = str(hit.knowledge_version_id)
        if hit.knowledge_doc_id is not None:
            ref["knowledge_doc_id"] = str(hit.knowledge_doc_id)
        if hit.knowledge_doc_title is not None:
            ref["knowledge_doc_title"] = hit.knowledge_doc_title
        if hit.chunk_no is not None:
            ref["chunk_no"] = hit.chunk_no

        refs.append(ref)

    return refs


def _maybe_execute_tool_command(*, user_text: str, allowed_tools: list[str]) -> str | None:
    if not user_text:
        return None

    match = _TOOL_COMMAND_PATTERN.match(user_text)
    if not match:
        return None

    tool_name = match.group(1).lower()
    tool_input = (match.group(2) or "").strip()

    if tool_name not in allowed_tools:
        return (
            f"Tool `{tool_name}` ist für diese Gruppe nicht freigeschaltet. "
            "Bitte wende dich an das Team für die Template-Konfiguration."
        )

    handler = LOCAL_TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return f"Tool `{tool_name}` ist konfiguriert, aber aktuell nicht implementiert."

    try:
        output = handler(tool_input)
    except Exception:
        return f"Tool `{tool_name}` konnte nicht ausgeführt werden."

    return f"Tool `{tool_name}` Ergebnis:\n{output}"


def _build_fallback_reply(*, user_text: str, retrieval_hits: list[RetrievalHit]) -> str:
    normalized_text = " ".join(user_text.split())
    if not normalized_text:
        return _INBOUND_CONFIRMATION_TEXT

    if len(normalized_text) > 240:
        normalized_text = f"{normalized_text[:240]}…"

    if retrieval_hits:
        return (
            "Danke für deine Nachricht. "
            f"Ich habe {len(retrieval_hits)} passende Kontexteinträge berücksichtigt.\n\n"
            f"Kurzantwort: {normalized_text}"
        )

    return f"Danke für deine Nachricht. Kurzantwort: {normalized_text}"


process_inbound_execution_job = process_inbound_message_job
