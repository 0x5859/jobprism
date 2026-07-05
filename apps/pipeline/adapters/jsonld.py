from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Any

from .base import RawJob
from ..io_utils import write_jsonl
from ..schema_validation import validate_many

JSONLD_SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)

def parse_jobposting_jsonld_from_html(html: str, source_url: str) -> list[RawJob]:
    jobs: list[RawJob] = []
    for raw_script in JSONLD_SCRIPT_RE.findall(html):
        raw_script = raw_script.strip()
        if not raw_script:
            continue
        try:
            payload = json.loads(raw_script)
        except json.JSONDecodeError:
            continue
        for obj in _expand_jsonld(payload):
            if obj.get("@type") != "JobPosting":
                continue
            jobs.append(_job_from_jobposting(obj, source_url))
    return jobs

def parse_jobposting_from_file(html_file: str | Path, source_url: str | None = None) -> list[RawJob]:
    path = Path(html_file)
    html = path.read_text(encoding="utf-8")
    return parse_jobposting_jsonld_from_html(html, source_url or path.as_uri())

def parse_jobposting_from_url(url: str, timeout: int = 30) -> list[RawJob]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="replace")
    return parse_jobposting_jsonld_from_html(html, url)

def save_jobposting_records(records: list[RawJob], out_path: str) -> int:
    payloads = [record.to_dict() for record in records]
    validate_many("raw_job", payloads, context="jsonld records")
    write_jsonl(out_path, payloads)
    return len(records)

def _expand_jsonld(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        items: list[dict[str, Any]] = []
        for item in payload:
            items.extend(_expand_jsonld(item))
        return items
    if isinstance(payload, dict):
        if "@graph" in payload and isinstance(payload["@graph"], list):
            return _expand_jsonld(payload["@graph"])
        return [payload]
    return []

def _job_from_jobposting(obj: dict[str, Any], source_url: str) -> RawJob:
    hiring_org = obj.get("hiringOrganization") or {}
    location = obj.get("jobLocation") or {}
    location_text = None
    if isinstance(location, list):
        location = location[0] if location else {}
    if isinstance(location, dict):
        address = location.get("address") or {}
        loc_parts = [
            address.get("addressLocality"),
            address.get("addressRegion"),
            address.get("addressCountry"),
        ]
        location_text = ", ".join([part for part in loc_parts if part]) or None

    description_html = obj.get("description") or ""
    description_text = _strip_html(description_html)
    identifier = obj.get("identifier")
    if isinstance(identifier, dict):
        external_id = identifier.get("value")
    else:
        external_id = None

    return RawJob(
        source_type="jsonld",
        source_url=obj.get("url") or source_url,
        external_job_id=str(external_id) if external_id else None,
        title=obj.get("title") or "Untitled role",
        company_name=(hiring_org.get("name") if isinstance(hiring_org, dict) else None) or "Unknown company",
        location_text=location_text,
        employment_type=obj.get("employmentType"),
        posted_at=obj.get("datePosted"),
        description_html=description_html,
        description_text=description_text,
        fetched_at=RawJob.now_iso(),
        json_payload=obj,
        metadata={
            "valid_through": obj.get("validThrough"),
            "direct_apply": obj.get("directApply"),
            "industry": obj.get("industry"),
        },
    )

def _strip_html(value: str) -> str:
    text = value or ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
