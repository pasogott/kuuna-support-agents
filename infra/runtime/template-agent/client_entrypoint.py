#!/usr/bin/env python3
"""Template client image: read one JSON object from stdin, write one JSON line to stdout.

The parent ``runtime-agent`` invokes ``docker run`` against this image and passes
the same prompt bundle the in-process runner would use (OpenAI chat completion).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_TIMEOUT = 60.0


def _normalize_model(name: str) -> str:
    normalized = name.strip()
    for prefix in ("openai/", "openai:"):
        if normalized.startswith(prefix):
            return normalized[len(prefix) :]
    return normalized


def _pick_model(model_path: list[Any]) -> str:
    for item in model_path:
        if isinstance(item, str) and item.strip():
            return _normalize_model(item)
    return "gpt-4.1-mini"


def _extract_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"].strip())
        return "\n".join(p for p in parts if p).strip()
    return ""


def main() -> None:
    result: dict[str, Any] = {"success": False, "error": "uninitialized"}
    try:
        raw = sys.stdin.buffer.read()
        data = json.loads(raw.decode("utf-8"))
        system_prompt = str(data.get("system_prompt") or "")
        user_prompt = str(data.get("user_prompt") or "")
        model_path = data.get("model_path") if isinstance(data.get("model_path"), list) else []
        model_name = _pick_model(model_path)

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            result = {"success": False, "error": "OPENAI_API_KEY not set in container"}
            return

        base = os.getenv("OPENAI_BASE_URL", _DEFAULT_OPENAI_BASE_URL).rstrip("/")
        raw_timeout = os.getenv("OPENAI_TIMEOUT_SECONDS", "").strip()
        try:
            timeout = float(raw_timeout) if raw_timeout else _DEFAULT_TIMEOUT
        except ValueError:
            timeout = _DEFAULT_TIMEOUT

        body: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }

        response = httpx.post(
            f"{base}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("OpenAI returned no choices")

        message_payload = choices[0].get("message")
        if not isinstance(message_payload, dict):
            raise RuntimeError("OpenAI returned malformed message")

        text = _extract_text(message_payload)
        if not text:
            raise RuntimeError("OpenAI returned empty assistant content")

        result = {"success": True, "response_text": text, "model_used": model_name}
    except Exception as exc:
        result = {"success": False, "error": str(exc)}
    finally:
        sys.stdout.write(json.dumps(result) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
