from __future__ import annotations

import json
import logging
import os
from typing import Any, Mapping

import httpx

from docker_runner import run_template_client_image
from failover import iter_model_path
from logging_utils import configure_json_logging
from prompt_builder import PromptAssembly, build_prompt
from result_schema import ModelAttempt, RunnerInput, RuntimeAgentResult, ToolExecutionResult, ToolInvocation
from tool_executor import LOCAL_TOOLS, execute_tool_call, execute_tool_calls

FAILURE_MARKERS = ("fail", "down", "error", "unavailable")
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_TIMEOUT_SECONDS = 30.0
MAX_TOOL_ROUNDS = 4
logger = logging.getLogger(__name__)


def _call_placeholder_model(model_name: str, prompt: PromptAssembly) -> str:
    normalized_name = model_name.lower()
    if any(marker in normalized_name for marker in FAILURE_MARKERS):
        raise RuntimeError(f"placeholder model unavailable: {model_name}")

    response_lines = [
        f"[{model_name}] Processed request.",
        f"User: {prompt.user_message}",
    ]
    if prompt.context_message is not None:
        response_lines.append("Context: attached")
    return "\n".join(response_lines)


def _openai_api_key() -> str | None:
    value = os.getenv("OPENAI_API_KEY", "").strip()
    return value or None


def _openai_base_url() -> str:
    return os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL).rstrip("/")


def _openai_timeout_seconds() -> float:
    raw_value = os.getenv("OPENAI_TIMEOUT_SECONDS", "").strip()
    if not raw_value:
        return DEFAULT_OPENAI_TIMEOUT_SECONDS

    try:
        return float(raw_value)
    except ValueError:
        return DEFAULT_OPENAI_TIMEOUT_SECONDS


def _normalize_model_name(model_name: str) -> str:
    normalized = model_name.strip()
    if not normalized:
        return normalized

    for prefix in ("openai/", "openai:"):
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]

    return normalized


def _openai_tools(allowed_tools: list[str]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []

    for tool_name in allowed_tools:
        if tool_name not in LOCAL_TOOLS:
            continue

        if tool_name == "echo":
            parameters = {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Text to echo back."}},
                "required": ["text"],
            }
            description = "Return the provided text unchanged."
        elif tool_name == "uppercase":
            parameters = {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Text to transform."}},
                "required": ["text"],
            }
            description = "Convert the provided text to uppercase."
        elif tool_name == "context_lookup":
            parameters = {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Context key to read from runtime context.",
                    }
                },
                "required": ["key"],
            }
            description = "Lookup one key from runtime context."
        else:  # pragma: no cover - defensive path for future local tools
            continue

        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": description,
                    "parameters": parameters,
                },
            }
        )

    return tools


def _extract_message_text(message_payload: dict[str, Any]) -> str:
    content = message_payload.get("content")
    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"].strip())
        return "\n".join(part for part in parts if part).strip()

    return ""


def _chat_completion(
    *,
    model_name: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    api_key = _openai_api_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")

    body: dict[str, Any] = {
        "model": _normalize_model_name(model_name),
        "messages": messages,
        "temperature": 0.2,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"

    response = httpx.post(
        f"{_openai_base_url()}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=_openai_timeout_seconds(),
    )
    response.raise_for_status()

    payload = response.json()
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("openai returned no choices")

    message_payload = choices[0].get("message")
    if not isinstance(message_payload, dict):
        raise RuntimeError("openai returned malformed message payload")

    return message_payload


def _run_openai_agent(
    *,
    model_name: str,
    prompt: PromptAssembly,
    context: Mapping[str, Any],
    allowed_tools: list[str],
) -> tuple[str, list[ToolExecutionResult]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": prompt.system_message}]
    if prompt.context_message:
        messages.append({"role": "system", "content": prompt.context_message})
    messages.append({"role": "user", "content": prompt.user_message})

    tools = _openai_tools(allowed_tools)
    all_tool_results: list[ToolExecutionResult] = []

    for _ in range(MAX_TOOL_ROUNDS):
        assistant_message = _chat_completion(model_name=model_name, messages=messages, tools=tools)

        tool_calls = assistant_message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            messages.append({
                "role": "assistant",
                "content": assistant_message.get("content"),
                "tool_calls": tool_calls,
            })

            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    continue
                call_id = tool_call.get("id")
                function_payload = tool_call.get("function")
                if not isinstance(call_id, str) or not isinstance(function_payload, dict):
                    continue

                tool_name = function_payload.get("name")
                raw_arguments = function_payload.get("arguments")
                if not isinstance(tool_name, str):
                    continue

                parsed_arguments: dict[str, Any] = {}
                if isinstance(raw_arguments, str) and raw_arguments.strip():
                    try:
                        decoded = json.loads(raw_arguments)
                        if isinstance(decoded, dict):
                            parsed_arguments = decoded
                    except json.JSONDecodeError:
                        parsed_arguments = {}

                invocation = ToolInvocation(name=tool_name, arguments=parsed_arguments)
                result = execute_tool_call(invocation, allowed_tools=allowed_tools, context=context)
                all_tool_results.append(result)

                tool_content = result.stdout if result.ok else f"ERROR: {result.stderr}"
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_content,
                    }
                )
            continue

        response_text = _extract_message_text(assistant_message)
        if response_text:
            return response_text, all_tool_results

        raise RuntimeError("openai returned empty response")

    raise RuntimeError("max tool rounds reached without final response")


def run_agent(input_data: RunnerInput | dict[str, Any]) -> RuntimeAgentResult:
    """Run the runtime-agent with model failover and optional local tools."""

    configure_json_logging()

    request = input_data if isinstance(input_data, RunnerInput) else RunnerInput.model_validate(input_data)
    trace_id = request.trace_id

    logger.info(
        "runtime_agent_run_started",
        extra={
            "trace_id": trace_id,
            "model_candidates": len(request.model_path),
            "tool_requests": len(request.tool_requests),
            "context_items": len(request.context),
            "openai_configured": bool(_openai_api_key()),
        },
    )

    prompt = build_prompt(
        system_prompt=request.system_prompt,
        user_prompt=request.user_prompt,
        context=request.context,
    )

    if (request.image_ref or "").strip():
        logger.info(
            "runtime_agent_run_client_template_image",
            extra={"trace_id": trace_id, "image_ref": request.image_ref},
        )
        return run_template_client_image(request=request, prompt=prompt)

    attempts: list[ModelAttempt] = []
    model_used: str | None = None
    response_text: str | None = None
    last_error: str | None = None
    model_tool_results: list[ToolExecutionResult] = []

    for model_name in iter_model_path(request.model_path, max_hops=2):
        try:
            if _openai_api_key():
                response_text, model_tool_results = _run_openai_agent(
                    model_name=model_name,
                    prompt=prompt,
                    context=request.context,
                    allowed_tools=request.allowed_tools,
                )
            else:
                response_text = _call_placeholder_model(model_name=model_name, prompt=prompt)
                model_tool_results = []

            attempts.append(ModelAttempt(model=model_name, success=True))
            model_used = model_name
            break
        except Exception as exc:
            last_error = str(exc)
            attempts.append(ModelAttempt(model=model_name, success=False, error=last_error))

    if model_used is None:
        logger.warning(
            "runtime_agent_run_failed",
            extra={"trace_id": trace_id, "attempts": len(attempts), "error": last_error},
        )
        return RuntimeAgentResult(
            success=False,
            prompt=prompt.full_prompt,
            system_prompt=prompt.system_message,
            user_prompt=prompt.user_message,
            context_block=prompt.context_message,
            attempts=attempts,
            error=last_error or "no model candidates available",
        )

    requested_tool_results = execute_tool_calls(
        tool_calls=request.tool_requests,
        allowed_tools=request.allowed_tools,
        context=request.context,
    )

    tool_results = [*model_tool_results, *requested_tool_results]

    if requested_tool_results and response_text is not None:
        tool_summary_lines = []
        for result in requested_tool_results:
            if result.ok:
                tool_summary_lines.append(f"- {result.name}: {result.stdout}")
            else:
                tool_summary_lines.append(f"- {result.name} failed: {result.stderr}")
        response_text = f"{response_text}\n\nTool results:\n" + "\n".join(tool_summary_lines)

    logger.info(
        "runtime_agent_run_completed",
        extra={
            "trace_id": trace_id,
            "model_used": model_used,
            "attempts": len(attempts),
            "tool_result_count": len(tool_results),
        },
    )

    return RuntimeAgentResult(
        success=True,
        prompt=prompt.full_prompt,
        system_prompt=prompt.system_message,
        user_prompt=prompt.user_message,
        context_block=prompt.context_message,
        model_used=model_used,
        attempts=attempts,
        response_text=response_text,
        tool_results=tool_results,
    )
