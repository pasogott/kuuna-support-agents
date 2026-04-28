from __future__ import annotations


def extract_allowed_tools(tools_config: object) -> list[str]:
    if not isinstance(tools_config, dict):
        return []

    candidates: list[str] = []

    for key in ("allowed_tools", "allowedTools"):
        raw = tools_config.get(key)
        if isinstance(raw, list):
            candidates.extend(item for item in raw if isinstance(item, str))

    raw_tools = tools_config.get("tools")
    if isinstance(raw_tools, list):
        for item in raw_tools:
            if isinstance(item, str):
                candidates.append(item)
            elif isinstance(item, dict):
                name = item.get("name")
                enabled = item.get("enabled", True)
                if isinstance(name, str) and name and enabled is not False:
                    candidates.append(name)

    normalized: list[str] = []
    for candidate in candidates:
        value = candidate.strip().lower()
        if value and value not in normalized:
            normalized.append(value)
    return normalized
