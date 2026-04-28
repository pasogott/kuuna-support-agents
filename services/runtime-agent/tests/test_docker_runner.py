# ruff: noqa: E402
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from docker_runner import is_safe_image_ref, run_template_client_image
from prompt_builder import build_prompt
from result_schema import RunnerInput


def test_is_safe_image_ref() -> None:
    assert is_safe_image_ref("repo.io/foo/bar:1.2.3")
    assert is_safe_image_ref("repo/runtime@sha256:abcdef0123456789")
    assert not is_safe_image_ref("")
    assert not is_safe_image_ref("bad`image")
    assert not is_safe_image_ref("x" * 600)


def test_run_template_client_image_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            [],
            0,
            stdout=b'{"success": true, "response_text": "hello from container", "model_used": "gpt-4.1-mini"}\n',
            stderr=b"",
        )

    monkeypatch.setattr("docker_runner.subprocess.run", fake_run)

    request = RunnerInput(
        user_prompt="u",
        system_prompt="s",
        model_path=["gpt-4.1-mini"],
        image_ref="kuuna/template-test:local",
    )
    prompt = build_prompt(
        system_prompt=request.system_prompt,
        user_prompt=request.user_prompt,
        context=request.context,
    )
    result = run_template_client_image(request=request, prompt=prompt)

    assert result.success is True
    assert result.response_text == "hello from container"
    assert result.model_used == "gpt-4.1-mini"


def test_run_template_client_image_rejects_unsafe_ref() -> None:
    request = RunnerInput(
        user_prompt="u",
        system_prompt="s",
        model_path=["gpt-4.1-mini"],
        image_ref="bad;rm -rf /",
    )
    prompt = build_prompt(
        system_prompt=request.system_prompt,
        user_prompt=request.user_prompt,
        context=request.context,
    )
    result = run_template_client_image(request=request, prompt=prompt)

    assert result.success is False
    assert result.error is not None
    assert "unsafe" in (result.error or "").lower()
