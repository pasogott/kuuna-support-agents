from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolInvocation(BaseModel):
    """A requested local tool execution."""

    model_config = ConfigDict(extra="forbid")

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float | None = Field(default=None, ge=0)


class RunnerInput(BaseModel):
    """Validated runtime-agent input payload.

    When ``image_ref`` is set, the service runs ``docker run`` against that image
    (the per-version template build artifact) instead of hosting the model call
    in-process.
    """

    model_config = ConfigDict(extra="forbid")

    trace_id: str | None = None
    system_prompt: str | None = None
    user_prompt: str
    context: dict[str, Any] = Field(default_factory=dict)
    model_path: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    tool_requests: list[ToolInvocation] = Field(default_factory=list)
    image_ref: str | None = None


class ModelAttempt(BaseModel):
    """One placeholder model attempt within the failover chain."""

    model_config = ConfigDict(extra="forbid")

    model: str
    success: bool
    error: str | None = None


class ToolExecutionResult(BaseModel):
    """Normalized tool execution result."""

    model_config = ConfigDict(extra="forbid")

    name: str
    ok: bool
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    duration_ms: int = 0


class RuntimeAgentResult(BaseModel):
    """Final runner output."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    prompt: str
    system_prompt: str
    user_prompt: str
    context_block: str | None = None
    model_used: str | None = None
    attempts: list[ModelAttempt] = Field(default_factory=list)
    response_text: str | None = None
    tool_results: list[ToolExecutionResult] = Field(default_factory=list)
    error: str | None = None
    execution: "ContainerExecution | None" = None


class ContainerExecution(BaseModel):
    """Execution metadata for docker-run based runners."""

    model_config = ConfigDict(extra="forbid")

    image_ref: str
    container_name: str
    exit_code: int | None = None
    duration_ms: int
    stdout_tail: str = ""
    stderr_tail: str = ""
    timed_out: bool = False
    limits: dict[str, Any] = Field(default_factory=dict)
