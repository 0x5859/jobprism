from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .base import RawJob
from ..io_utils import fetch_json, write_jsonl
from ..schema_validation import validate_many

LEVER_POSTINGS_URL = "https://api.lever.co/v0/postings/{account}"


def fetch_lever_postings(account: str, timeout: int = 30) -> list[RawJob]:
    url = LEVER_POSTINGS_URL.format(account=urllib.parse.quote(account))
    payload = fetch_json(url, timeout=timeout)

    postings = _iter_postings(payload)
    jobs: list[RawJob] = []
    for posting in postings:
        title = (
            posting.get("text")
            or posting.get("title")
            or posting.get("jobTitle")
            or "Untitled role"
        )
        description_html = (
            posting.get("descriptionHtml")
            or posting.get("description")
            or posting.get("content")
            or ""
        )
        description_text = (
            posting.get("descriptionPlain")
            or posting.get("descriptionText")
            or _strip_html(description_html)
        )
        categories = posting.get("categories") or {}
        metadata = {
            "hosted_url": posting.get("hostedUrl"),
            "apply_url": posting.get("applyUrl"),
            "created_at": posting.get("createdAt"),
            "updated_at": posting.get("updatedAt"),
            "categories": categories,
            "state": posting.get("state"),
            "workplace_type": posting.get("workplaceType"),
            "additional": {
                key: value
                for key, value in posting.items()
                if key
                not in {
                    "text",
                    "title",
                    "jobTitle",
                    "descriptionHtml",
                    "description",
                    "content",
                    "descriptionPlain",
                    "descriptionText",
                    "categories",
                    "hostedUrl",
                    "applyUrl",
                    "createdAt",
                    "updatedAt",
                    "state",
                    "workplaceType",
                }
            },
        }
        location = _format_location(categories)
        jobs.append(
            RawJob(
                source_type="lever",
                source_url=posting.get("hostedUrl") or posting.get("applyUrl") or url,
                external_job_id=_stringify_id(posting.get("id") or posting.get("leverId")),
                title=title,
                company_name=account,
                location_text=location,
                employment_type=_normalize_employment_type(categories.get("commitment") or posting.get("employmentType")),
                posted_at=_epoch_to_iso(posting.get("createdAt") or posting.get("updatedAt")),
                description_html=description_html,
                description_text=description_text,
                fetched_at=RawJob.now_iso(),
                json_payload=posting,
                metadata=metadata,
            )
        )
    return jobs


def save_lever_postings(account: str, out_path: str) -> int:
    jobs = [job.to_dict() for job in fetch_lever_postings(account)]
    validate_many("raw_job", jobs, context=f"lever[{account}]")
    write_jsonl(out_path, jobs)
    return len(jobs)


def _iter_postings(payload: Any) -> list[dict[str, Any]]:
    postings: list[dict[str, Any]] = []
    stack: list[Any] = [payload]

    while stack:
        current = stack.pop()
        if isinstance(current, list):
            stack.extend(reversed(current))
            continue
        if not isinstance(current, dict):
            continue
        if _looks_like_posting(current):
            postings.append(current)
            continue
        for key in ("postings", "jobs", "items", "data", "results"):
            value = current.get(key)
            if value is not None:
                stack.append(value)

    return postings


def _looks_like_posting(value: dict[str, Any]) -> bool:
    return any(key in value for key in ("text", "title", "hostedUrl", "applyUrl", "description"))


def _format_location(categories: dict[str, Any]) -> str | None:
    value = categories.get("location")
    if not value:
        return None
    if isinstance(value, dict):
        parts = [value.get("name"), value.get("city"), value.get("state"), value.get("country")]
        return ", ".join([part for part in parts if part]) or None
    return str(value)


def _normalize_employment_type(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    mapping = {
        "full time": "full-time",
        "fulltime": "full-time",
        "part time": "part-time",
        "parttime": "part-time",
        "contract": "contract",
        "intern": "internship",
        "internship": "internship",
        "temporary": "temporary",
        "temp": "temporary",
    }
    return mapping.get(text, text)


def _stringify_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _epoch_to_iso(value: Any) -> str | None:
    """Lever timestamps are millisecond unix epochs; the raw_job schema wants ISO strings."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        from datetime import datetime, timezone

        seconds = float(value) / 1000.0 if value > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _strip_html(value: str) -> str:
    text = value or ""
    text = text.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
    chunks: list[str] = []
    current: list[str] = []
    in_tag = False
    for ch in text:
        if ch == "<":
            in_tag = True
            if current:
                chunks.append("".join(current))
                current = []
            continue
        if ch == ">":
            in_tag = False
            continue
        if not in_tag:
            current.append(ch)
    if current:
        chunks.append("".join(current))
    return " ".join(" ".join(chunks).split())
