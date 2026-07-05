from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

from .base import RawJob
from ..io_utils import fetch_json, write_jsonl
from ..schema_validation import validate_many

ASHBY_JOB_BOARD_URL = "https://api.ashbyhq.com/posting-api/job-board/{job_board}"


def fetch_ashby_job_board(job_board: str, include_compensation: bool = False, timeout: int = 30) -> list[RawJob]:
    query = {"includeCompensation": "true" if include_compensation else "false"}
    url = f"{ASHBY_JOB_BOARD_URL.format(job_board=urllib.parse.quote(job_board))}?{urllib.parse.urlencode(query)}"
    payload = fetch_json(url, timeout=timeout)

    meta = payload.get("meta") or {}
    jobs: list[RawJob] = []
    for job in payload.get("jobs", []):
        description_html = job.get("descriptionHtml") or ""
        description_text = job.get("descriptionPlain") or _strip_html(description_html)
        address = (job.get("address") or {}).get("postalAddress") or {}
        secondary_locations = job.get("secondaryLocations") or []
        location = _format_location(job.get("location"), address, secondary_locations)
        metadata = {
            "api_version": payload.get("apiVersion"),
            "organization_id": meta.get("id") or job.get("organizationId"),
            "organization_name": meta.get("name") or job.get("organizationName") or job_board,
            "organization_link": meta.get("link"),
            "job_board_link": meta.get("jobBoardLink"),
            "job_url": job.get("jobUrl"),
            "apply_url": job.get("applyUrl"),
            "department": job.get("department"),
            "team": job.get("team"),
            "is_listed": job.get("isListed"),
            "is_remote": job.get("isRemote"),
            "workplace_type": job.get("workplaceType"),
            "published_at": job.get("publishedAt"),
            "employment_type": job.get("employmentType"),
            "address": job.get("address"),
            "secondary_locations": secondary_locations,
            "compensation": job.get("compensation"),
        }
        jobs.append(
            RawJob(
                source_type="ashby",
                source_url=job.get("jobUrl") or meta.get("jobBoardLink") or job.get("applyUrl") or url,
                external_job_id=_stringify_id(job.get("id")),
                title=job.get("title") or "Untitled role",
                company_name=meta.get("name") or job.get("organizationName") or job_board,
                location_text=location,
                employment_type=_normalize_employment_type(job.get("employmentType")),
                posted_at=job.get("publishedAt"),
                description_html=description_html,
                description_text=description_text,
                fetched_at=RawJob.now_iso(),
                json_payload=job,
                metadata=metadata,
            )
        )
    return jobs


def save_ashby_job_board(job_board: str, out_path: str, include_compensation: bool = False) -> int:
    jobs = [job.to_dict() for job in fetch_ashby_job_board(job_board, include_compensation=include_compensation)]
    validate_many("raw_job", jobs, context=f"ashby[{job_board}]")
    write_jsonl(out_path, jobs)
    return len(jobs)


def _format_location(primary: str | None, address: dict[str, Any], secondary_locations: list[dict[str, Any]]) -> str | None:
    candidates: list[str] = []
    if primary:
        candidates.append(primary)
    parts = [address.get("addressLocality"), address.get("addressRegion"), address.get("addressCountry")]
    primary_address = ", ".join([part for part in parts if part])
    if primary_address and primary_address not in candidates:
        candidates.append(primary_address)
    for location in secondary_locations:
        secondary = location.get("location")
        if secondary and secondary not in candidates:
            candidates.append(str(secondary))
    return ", ".join(candidates) if candidates else None


def _normalize_employment_type(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip().lower()
    mapping = {
        "fulltime": "full-time",
        "parttime": "part-time",
        "intern": "internship",
        "contract": "contract",
        "temporary": "temporary",
    }
    return mapping.get(text, text)


def _stringify_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


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
