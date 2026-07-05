from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "packages" / "schema"
SCHEMA_FILES = {
    "raw_job": "raw-job.schema.json",
    "job": "job.schema.json",
    "company": "company.schema.json",
    "skill": "skill.schema.json",
    "graph_node": "graph-node.schema.json",
    "graph_edge": "graph-edge.schema.json",
    "summary": "summary.schema.json",
    "graph_full": "graph-full.schema.json",
    "company_jobs": "company-jobs.schema.json",
    "skill_jobs": "skill-jobs.schema.json",
    "job_skills": "job-skills.schema.json",
    "company_skill_stats": "company-skill-stats.schema.json",
    "job_neighbors": "job-neighbors.schema.json",
    "search_index": "search-index.schema.json",
}


class SchemaValidationError(ValueError):
    pass


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    try:
        filename = SCHEMA_FILES[name]
    except KeyError as exc:
        raise KeyError(f"Unknown schema name: {name}") from exc
    path = SCHEMA_DIR / filename
    return json.loads(path.read_text(encoding="utf-8"))


def validate_record(name: str, payload: dict[str, Any], *, context: str | None = None) -> None:
    validate_payload(name, payload, context=context)


def validate_many(name: str, payloads: list[dict[str, Any]], *, context: str | None = None) -> None:
    for index, payload in enumerate(payloads):
        item_context = f"{context}[{index}]" if context else f"{name}[{index}]"
        validate_payload(name, payload, context=item_context)


def validate_payload(name: str, payload: Any, *, context: str | None = None) -> None:
    errors: list[str] = []
    _validate(payload, load_schema(name), path="$", errors=errors)
    if errors:
        prefix = f"{context}: " if context else ""
        raise SchemaValidationError(prefix + "; ".join(errors))


def _validate(value: Any, schema: dict[str, Any], *, path: str, errors: list[str]) -> None:
    expected = schema.get("type")
    if expected is not None and not _matches_type(value, expected):
        errors.append(f"{path} expected {_type_label(expected)}, got {type(value).__name__}")
        return

    if isinstance(expected, list) and value is None:
        return

    if schema.get("type") == "object" or (isinstance(expected, list) and isinstance(value, dict)):
        _validate_object(value, schema, path=path, errors=errors)
        return

    if schema.get("type") == "array" or (isinstance(expected, list) and isinstance(value, list)):
        _validate_array(value, schema, path=path, errors=errors)


def _validate_object(value: Any, schema: dict[str, Any], *, path: str, errors: list[str]) -> None:
    if not isinstance(value, dict):
        return
    required = schema.get("required", [])
    for key in required:
        if key not in value:
            errors.append(f"{path}.{key} is required")
    properties = schema.get("properties", {})
    additional_schema = schema.get("additionalProperties")
    for key, item in value.items():
        if key not in properties:
            if additional_schema is False:
                errors.append(f"{path}.{key} is not allowed")
            elif isinstance(additional_schema, dict):
                _validate(item, additional_schema, path=f"{path}.{key}", errors=errors)
            continue
        _validate(item, properties[key], path=f"{path}.{key}", errors=errors)


def _validate_array(value: Any, schema: dict[str, Any], *, path: str, errors: list[str]) -> None:
    if not isinstance(value, list):
        return
    item_schema = schema.get("items")
    if not isinstance(item_schema, dict):
        return
    for index, item in enumerate(value):
        _validate(item, item_schema, path=f"{path}[{index}]", errors=errors)


def _matches_type(value: Any, expected: str | list[str]) -> bool:
    if isinstance(expected, list):
        return any(_matches_type(value, item) for item in expected)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def _type_label(expected: str | list[str]) -> str:
    if isinstance(expected, list):
        return " | ".join(expected)
    return expected
