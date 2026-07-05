from __future__ import annotations

import json
import re
from typing import Any

CODE_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE | re.DOTALL)


def coerce_json_object(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return _unwrap_known_wrappers(content)
    if isinstance(content, list):
        if len(content) == 1 and isinstance(content[0], dict):
            return _unwrap_known_wrappers(content[0])
        raise ValueError("Provider returned a JSON array where an object was expected")
    if not isinstance(content, str):
        raise ValueError("Provider returned non-string content")

    text = _strip_code_fences(content)
    payload = _loads_json(text)
    if payload is None:
        payload = _extract_json_substring(text)
    if payload is None:
        raise ValueError("Provider did not return valid JSON")
    if isinstance(payload, dict):
        return _unwrap_known_wrappers(payload)
    if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict):
        return _unwrap_known_wrappers(payload[0])
    raise ValueError("Provider JSON payload must be an object")


def coerce_any_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [value]
    return [item for item in value if item is not None]


def coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return [str(value).strip()] if str(value).strip() else []
    return [str(item).strip() for item in value if str(item).strip()]


def _strip_code_fences(text: str) -> str:
    return CODE_FENCE_RE.sub("", text).strip()


def _loads_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _extract_json_substring(text: str) -> Any | None:
    candidates = []
    first_object = text.find("{")
    last_object = text.rfind("}")
    if first_object != -1 and last_object != -1 and last_object > first_object:
        candidates.append(text[first_object:last_object + 1])
    first_array = text.find("[")
    last_array = text.rfind("]")
    if first_array != -1 and last_array != -1 and last_array > first_array:
        candidates.append(text[first_array:last_array + 1])

    for candidate in candidates:
        payload = _loads_json(candidate)
        if payload is not None:
            return payload
    return None


def _unwrap_known_wrappers(payload: dict[str, Any]) -> dict[str, Any]:
    current: Any = payload
    while isinstance(current, dict):
        if any(key in current for key in ("summary", "role_family", "skills", "confidence")):
            return current
        for wrapper_key in ("result", "data", "payload", "output", "response"):
            nested = current.get(wrapper_key)
            if isinstance(nested, dict):
                current = nested
                break
        else:
            return current
    return payload
