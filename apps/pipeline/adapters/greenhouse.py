from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .base import RawJob
from ..io_utils import fetch_json, write_jsonl
from ..schema_validation import validate_many

GREENHOUSE_BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"

def fetch_greenhouse_board(board: str, timeout: int = 30) -> list[RawJob]:
    url = GREENHOUSE_BOARD_URL.format(board=urllib.parse.quote(board))
    payload = fetch_json(url, timeout=timeout)

    jobs: list[RawJob] = []
    for job in payload.get("jobs", []):
        content = job.get("content") or ""
        metadata = {
            "absolute_url": job.get("absolute_url"),
            "internal_job_id": job.get("internal_job_id"),
            "updated_at": job.get("updated_at"),
            "departments": job.get("departments", []),
            "offices": job.get("offices", []),
        }
        location = None
        offices = metadata["offices"]
        if offices:
            names = [office.get("name") for office in offices if office.get("name")]
            location = ", ".join(names) if names else None

        jobs.append(
            RawJob(
                source_type="greenhouse",
                source_url=job.get("absolute_url") or url,
                external_job_id=str(job.get("id")) if job.get("id") is not None else None,
                title=job.get("title") or "Untitled role",
                company_name=board,
                location_text=location,
                posted_at=job.get("updated_at"),
                description_html=content,
                description_text=_strip_html(content),
                fetched_at=RawJob.now_iso(),
                json_payload=job,
                metadata=metadata,
            )
        )
    return jobs

def save_greenhouse_board(board: str, out_path: str) -> int:
    jobs = [job.to_dict() for job in fetch_greenhouse_board(board)]
    validate_many("raw_job", jobs, context=f"greenhouse[{board}]")
    write_jsonl(out_path, jobs)
    return len(jobs)

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
