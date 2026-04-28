# ruff: noqa: E402
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from result_schema import RunnerInput, RuntimeAgentResult, ToolInvocation
from runner import run_agent


def test_run_agent_delegates_to_docker_when_image_ref_set(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[RunnerInput] = []

    def fake_run_template_client_image(*, request: RunnerInput, prompt) -> RuntimeAgentResult:
        calls.append(request)
        return RuntimeAgentResult(
            success=True,
            prompt=prompt.full_prompt,
            system_prompt=prompt.system_message,
            user_prompt=prompt.user_message,
            context_block=prompt.context_message,
            model_used="from-docker",
            response_text="delegated",
        )

    monkeypatch.setattr("runner.run_template_client_image", fake_run_template_client_image)

    request = RunnerInput(
        system_prompt="sys",
        user_prompt="user",
        context={"k": "v"},
        model_path=["gpt-4.1-mini"],
        allowed_tools=[],
        image_ref="kuuna/template-x:build-abc",
    )
    result = run_agent(request)

    assert len(calls) == 1
    assert calls[0].image_ref == "kuuna/template-x:build-abc"
    assert result.success is True
    assert result.response_text == "delegated"
    assert result.model_used == "from-docker"


def test_run_agent_happy_path_with_failover_and_tool_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    request = RunnerInput(
        system_prompt="You are a concise support runtime.",
        user_prompt="Summarize the ticket and use the tool output.",
        context={"ticket_id": "T-100", "priority": "high"},
        model_path=["local-fail-model", "local-ok-model", "unused-model"],
        allowed_tools=["echo"],
        tool_requests=[
            ToolInvocation(
                name="echo",
                arguments={"text": "tool-ok"},
                timeout_seconds=0.5,
            )
        ],
    )

    result = run_agent(request)

    assert result.success is True
    assert result.model_used == "local-ok-model"
    assert [attempt.model for attempt in result.attempts] == [
        "local-fail-model",
        "local-ok-model",
    ]
    assert result.attempts[0].success is False
    assert result.attempts[1].success is True
    assert "## System" in result.prompt
    assert "## Context" in result.prompt
    assert "ticket_id: T-100" in result.prompt
    assert result.tool_results[0].ok is True
    assert result.tool_results[0].stdout == "tool-ok"
    assert result.response_text is not None
    assert "Tool results:" in result.response_text
    assert "tool-ok" in result.response_text


def test_run_agent_openai_path_with_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    call_count = {"value": 0}

    def fake_chat_completion(*, model_name: str, messages, tools):
        call_count["value"] += 1
        if call_count["value"] == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "tool-call-1",
                        "type": "function",
                        "function": {
                            "name": "uppercase",
                            "arguments": '{"text":"hello"}',
                        },
                    }
                ],
            }

        return {"content": f"Final from {model_name}"}

    monkeypatch.setattr("runner._chat_completion", fake_chat_completion)

    request = RunnerInput(
        system_prompt="You are a concise support runtime.",
        user_prompt="Please uppercase hello.",
        context={"ticket_id": "T-101"},
        model_path=["gpt-4.1-mini"],
        allowed_tools=["uppercase"],
        tool_requests=[],
    )

    result = run_agent(request)

    assert result.success is True
    assert result.model_used == "gpt-4.1-mini"
    assert result.response_text == "Final from gpt-4.1-mini"
    assert len(result.tool_results) == 1
    assert result.tool_results[0].name == "uppercase"
    assert result.tool_results[0].stdout == "HELLO"
