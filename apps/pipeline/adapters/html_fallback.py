from __future__ import annotations

import re
import urllib.request
from pathlib import Path

from .base import RawJob
from ..io_utils import write_jsonl
from ..schema_validation import validate_many

TITLE_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
LOCATION_PATTERNS = [
    re.compile(r"location[:\s]+([A-Za-z0-9,\- ]+)", re.IGNORECASE),
    re.compile(r"based in ([A-Za-z0-9,\- ]+)", re.IGNORECASE),
]

def parse_generic_job_html(html: str, source_url: str, company_name: str = "Unknown company") -> list[RawJob]:
    title = _match_first(TITLE_H1_RE, html) or _match_first(TITLE_TAG_RE, html) or "Untitled role"
    text = _strip_html(html)
    location = None
    for pattern in LOCATION_PATTERNS:
        match = pattern.search(text)
        if match:
            location = match.group(1).strip()
            break
    return [
        RawJob(
            source_type="html",
            source_url=source_url,
            title=title,
            company_name=company_name,
            location_text=location,
            description_html=html,
            description_text=text,
            fetched_at=RawJob.now_iso(),
        )
    ]

def parse_generic_html_file(html_file: str | Path, source_url: str | None = None, company_name: str = "Unknown company") -> list[RawJob]:
    path = Path(html_file)
    html = path.read_text(encoding="utf-8")
    return parse_generic_job_html(html, source_url or path.as_uri(), company_name=company_name)

def parse_generic_html_url(url: str, company_name: str = "Unknown company", timeout: int = 30) -> list[RawJob]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        html = response.read().decode("utf-8", errors="replace")
    return parse_generic_job_html(html, url, company_name=company_name)

def save_html_records(records: list[RawJob], out_path: str) -> int:
    payloads = [record.to_dict() for record in records]
    validate_many("raw_job", payloads, context="html records")
    write_jsonl(out_path, payloads)
    return len(records)

def _match_first(pattern: re.Pattern[str], html: str) -> str | None:
    match = pattern.search(html)
    if not match:
        return None
    return _strip_html(match.group(1))

def _strip_html(value: str) -> str:
    text = TAG_RE.sub(" ", value or "")
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()
