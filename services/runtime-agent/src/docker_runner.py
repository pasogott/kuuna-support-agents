from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from typing import Any
from uuid import uuid4

from prompt_builder import PromptAssembly
from result_schema import ContainerExecution, ModelAttempt, RuntimeAgentResult, RunnerInput

logger = logging.getLogger(__name__)

# Conservative allowlist: image refs are docker image names, digests, or repo paths.
_IMAGE_REF_RE = re.compile(r"^[a-zA-Z0-9._/@:+-]+$")


def is_safe_image_ref(value: str) -> bool:
    stripped = value.strip()
    if not stripped or len(stripped) > 512:
        return False
    return bool(_IMAGE_REF_RE.fullmatch(stripped))


def _docker_bin() -> str:
    return (os.getenv("DOCKER_CLI_PATH", "docker") or "docker").strip() or "docker"


def _docker_timeout_seconds() -> float:
    raw = os.getenv("RUNTIME_AGENT_DOCKER_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 120.0
    try:
        return float(raw)
    except ValueError:
        return 120.0


def _docker_limits() -> dict[str, str]:
    limits: dict[str, str] = {}

    mem = os.getenv("RUNTIME_AGENT_DOCKER_MEMORY", "").strip()
    if mem:
        limits["memory"] = mem

    cpus = os.getenv("RUNTIME_AGENT_DOCKER_CPUS", "").strip()
    if cpus:
        limits["cpus"] = cpus

    pids = os.getenv("RUNTIME_AGENT_DOCKER_PIDS_LIMIT", "").strip()
    if pids:
        limits["pids_limit"] = pids

    network = os.getenv("RUNTIME_AGENT_DOCKER_NETWORK", "").strip() or "none"
    limits["network"] = network

    readonly = os.getenv("RUNTIME_AGENT_DOCKER_READONLY", "").strip().lower()
    limits["readonly"] = "true" if readonly in ("", "1", "true", "yes", "on") else "false"

    return limits


def run_template_client_image(*, request: RunnerInput, prompt: PromptAssembly) -> RuntimeAgentResult:
    """Execute the published template image via `docker run` (Issue #4 hardened)."""

    image_ref = (request.image_ref or "").strip()
    if not is_safe_image_ref(image_ref):
        return RuntimeAgentResult(
            success=False,
            prompt=prompt.full_prompt,
            system_prompt=prompt.system_message,
            user_prompt=prompt.user_message,
            context_block=prompt.context_message,
            attempts=[],
            error="invalid or unsafe image_ref",
        )

    limits = _docker_limits()
    container_name = f"kuuna-run-{(request.trace_id or 'no-trace')[:12]}-{uuid4().hex[:8]}"

    stdin_payload: dict[str, Any] = {
        "trace_id": request.trace_id,
        "system_prompt": prompt.system_message,
        "user_prompt": prompt.user_message,
        "model_path": list(request.model_path),
        "allowed_tools": list(request.allowed_tools),
        "context": dict(request.context),
    }

    cmd: list[str] = [
        _docker_bin(),
        "run",
        "--rm",
        "-i",
        "--name",
        container_name,
        "--network",
        limits["network"],
    ]

    if limits.get("readonly") == "true":
        cmd.append("--read-only")
        cmd += ["--tmpfs", "/tmp:rw,nosuid,nodev,size=64m"]

    if limits.get("memory"):
        cmd += ["--memory", limits["memory"]]
    if limits.get("cpus"):
        cmd += ["--cpus", limits["cpus"]]
    if limits.get("pids_limit"):
        cmd += ["--pids-limit", limits["pids_limit"]]

    cmd += ["--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    cmd.append(image_ref)

    started = time.monotonic()

    try:
        completed = subprocess.run(
            cmd,
            input=json.dumps(stdin_payload).encode("utf-8"),
            capture_output=True,
            timeout=_docker_timeout_seconds(),
            check=False,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        try:
            subprocess.run(
                [_docker_bin(), "rm", "-f", container_name],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except Exception:  # pragma: no cover
            pass

        duration_ms = int((time.monotonic() - started) * 1000)
        logger.warning(
            "runtime_agent_docker_run_timeout",
            extra={"trace_id": request.trace_id, "image_ref": image_ref},
        )
        return RuntimeAgentResult(
            success=False,
            prompt=prompt.full_prompt,
            system_prompt=prompt.system_message,
            user_prompt=prompt.user_message,
            context_block=prompt.context_message,
            attempts=[],
            error="docker run timed out",
            execution=ContainerExecution(
                image_ref=image_ref,
                container_name=container_name,
                exit_code=None,
                duration_ms=duration_ms,
                stdout_tail="",
                stderr_tail="",
                timed_out=True,
                limits=limits,
            ),
        )
    except Exception as exc:  # pragma: no cover - subprocess setup
        logger.exception(
            "runtime_agent_docker_run_failed",
            extra={"trace_id": request.trace_id, "image_ref": image_ref},
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        return RuntimeAgentResult(
            success=False,
            prompt=prompt.full_prompt,
            system_prompt=prompt.system_message,
            user_prompt=prompt.user_message,
            context_block=prompt.context_message,
            attempts=[],
            error=f"docker run failed: {exc}",
            execution=ContainerExecution(
                image_ref=image_ref,
                container_name=container_name,
                exit_code=None,
                duration_ms=duration_ms,
                stdout_tail="",
                stderr_tail="",
                timed_out=False,
                limits=limits,
            ),
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    stdout_tail = (completed.stdout or b"").decode("utf-8", errors="replace")[-4000:].strip()
    stderr_tail = (completed.stderr or b"").decode("utf-8", errors="replace")[-4000:].strip()

    if completed.returncode != 0:
        logger.warning(
            "runtime_agent_docker_run_nonzero",
            extra={
                "trace_id": request.trace_id,
                "image_ref": image_ref,
                "returncode": completed.returncode,
                "stderr_tail": stderr_tail,
            },
        )
        return RuntimeAgentResult(
            success=False,
            prompt=prompt.full_prompt,
            system_prompt=prompt.system_message,
            user_prompt=prompt.user_message,
            context_block=prompt.context_message,
            attempts=[],
            error=f"docker exit {completed.returncode}: {stderr_tail or '(no stderr)'}",
            execution=ContainerExecution(
                image_ref=image_ref,
                container_name=container_name,
                exit_code=completed.returncode,
                duration_ms=duration_ms,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                timed_out=False,
                limits=limits,
            ),
        )

    raw_out = stdout_tail
    if not raw_out:
        return RuntimeAgentResult(
            success=False,
            prompt=prompt.full_prompt,
            system_prompt=prompt.system_message,
            user_prompt=prompt.user_message,
            context_block=prompt.context_message,
            attempts=[],
            error="client container produced empty stdout",
            execution=ContainerExecution(
                image_ref=image_ref,
                container_name=container_name,
                exit_code=completed.returncode,
                duration_ms=duration_ms,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                timed_out=False,
                limits=limits,
            ),
        )

    try:
        payload = json.loads(raw_out.splitlines()[-1])
    except json.JSONDecodeError as exc:
        return RuntimeAgentResult(
            success=False,
            prompt=prompt.full_prompt,
            system_prompt=prompt.system_message,
            user_prompt=prompt.user_message,
            context_block=prompt.context_message,
            attempts=[],
            error=f"invalid JSON from client container: {exc}",
            execution=ContainerExecution(
                image_ref=image_ref,
                container_name=container_name,
                exit_code=completed.returncode,
                duration_ms=duration_ms,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                timed_out=False,
                limits=limits,
            ),
        )

    if not isinstance(payload, dict):
        return RuntimeAgentResult(
            success=False,
            prompt=prompt.full_prompt,
            system_prompt=prompt.system_message,
            user_prompt=prompt.user_message,
            context_block=prompt.context_message,
            attempts=[],
            error="client container JSON was not an object",
            execution=ContainerExecution(
                image_ref=image_ref,
                container_name=container_name,
                exit_code=completed.returncode,
                duration_ms=duration_ms,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                timed_out=False,
                limits=limits,
            ),
        )

    if not bool(payload.get("success")):
        return RuntimeAgentResult(
            success=False,
            prompt=prompt.full_prompt,
            system_prompt=prompt.system_message,
            user_prompt=prompt.user_message,
            context_block=prompt.context_message,
            attempts=[],
            error=str(payload.get("error") or "client container reported failure"),
            execution=ContainerExecution(
                image_ref=image_ref,
                container_name=container_name,
                exit_code=completed.returncode,
                duration_ms=duration_ms,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                timed_out=False,
                limits=limits,
            ),
        )

    response_text = str(payload.get("response_text") or "").strip()
    if not response_text:
        return RuntimeAgentResult(
            success=False,
            prompt=prompt.full_prompt,
            system_prompt=prompt.system_message,
            user_prompt=prompt.user_message,
            context_block=prompt.context_message,
            attempts=[],
            error="client container returned empty response_text",
            execution=ContainerExecution(
                image_ref=image_ref,
                container_name=container_name,
                exit_code=completed.returncode,
                duration_ms=duration_ms,
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                timed_out=False,
                limits=limits,
            ),
        )

    model_used = payload.get("model_used")
    model_name = model_used if isinstance(model_used, str) and model_used else None
    attempts: list[ModelAttempt] = []
    if model_name:
        attempts.append(ModelAttempt(model=model_name, success=True))

    return RuntimeAgentResult(
        success=True,
        prompt=prompt.full_prompt,
        system_prompt=prompt.system_message,
        user_prompt=prompt.user_message,
        context_block=prompt.context_message,
        model_used=model_name,
        attempts=attempts,
        response_text=response_text,
        tool_results=[],
        execution=ContainerExecution(
            image_ref=image_ref,
            container_name=container_name,
            exit_code=completed.returncode,
            duration_ms=duration_ms,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            timed_out=False,
            limits=limits,
        ),
    )
