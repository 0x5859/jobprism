from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db
from .ids import company_id_from_name, job_id, short_hash, slugify
from .io_utils import iter_input_paths, iter_jsonl, read_json

REMOTE_PATTERNS = {
    "remote": re.compile(r"\bremote\b", re.IGNORECASE),
    "hybrid": re.compile(r"\bhybrid\b", re.IGNORECASE),
    "onsite": re.compile(r"\b(on[- ]?site|onsite)\b", re.IGNORECASE),
}

EMPLOYMENT_PATTERNS = {
    "full-time": re.compile(r"\bfull[- ]?time\b", re.IGNORECASE),
    "part-time": re.compile(r"\bpart[- ]?time\b", re.IGNORECASE),
    "contract": re.compile(r"\bcontract(or)?\b", re.IGNORECASE),
    "internship": re.compile(r"\bintern(ship)?\b", re.IGNORECASE),
}

def import_raw_inputs(
    db_path: str | Path,
    input_path: str | Path,
    *,
    run_id: str | None = None,
    observability: dict[str, Any] | None = None,
) -> int:
    records: list[dict[str, Any]] = []
    for path in iter_input_paths(input_path):
        if path.suffix.lower() == ".jsonl":
            records.extend(iter_jsonl(path))
        elif path.suffix.lower() == ".json":
            payload = read_json(path)
            if isinstance(payload, list):
                records.extend(payload)
            elif isinstance(payload, dict):
                records.append(payload)
            else:
                raise ValueError(f"Unsupported JSON payload in {path}")
    with db.connect(db_path) as conn:
        count = db.insert_raw_jobs(conn, records)
        db.log_run(
            conn,
            "import_raw",
            "ok",
            {
                "input_path": str(input_path),
                "records_seen": len(records),
                "records_inserted": count,
                "records_skipped": len(records) - count,
                **(observability or {}),
            },
            _now_iso(),
            run_id=run_id,
        )
        conn.commit()
    return count

def normalize_all(
    db_path: str | Path,
    company_aliases_path: str | Path,
    *,
    run_id: str | None = None,
    observability: dict[str, Any] | None = None,
) -> dict[str, int]:
    aliases = _load_company_aliases(company_aliases_path)
    with db.connect(db_path) as conn:
        raw_rows = db.fetch_all(
            conn,
            """
            SELECT raw_id, source_type, source_url, external_job_id, title, company_name, location_text,
                   employment_type, posted_at, description_text, description_html, json_payload,
                   metadata_json, fetched_at
            FROM raw_jobs
            ORDER BY raw_id ASC
            """
        )

        company_upserts = 0
        job_upserts = 0

        for row in raw_rows:
            normalized_company_name, company_identifier = _normalize_company(row["company_name"], aliases)
            now_iso = _now_iso()

            db.upsert_company(
                conn,
                company_id=company_identifier,
                name=normalized_company_name,
                aliases=[row["company_name"]] if row["company_name"] != normalized_company_name else [],
                now_iso=now_iso,
            )
            company_upserts += 1

            raw_payload = json.loads(row["json_payload"]) if row["json_payload"] else {}
            metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
            description_raw = row["description_html"] or row["description_text"] or ""
            description_text = _normalize_text(row["description_text"] or row["description_html"] or "")
            title_normalized = _normalize_title(row["title"])
            remote_mode = _infer_remote_mode(row["location_text"], description_text)
            employment_type = row["employment_type"] or _infer_employment_type(description_text)
            description_hash = hashlib.sha256(description_text.encode("utf-8")).hexdigest()
            dedupe_fingerprint = _dedupe_fingerprint(
                normalized_company_name,
                row["title"],
                row["location_text"],
                description_text,
            )

            normalized_job = {
                "id": job_id(
                    company_identifier,
                    row["external_job_id"],
                    fallback_payload=f"{normalized_company_name}|{row['title']}|{description_hash}",
                ),
                "company_id": company_identifier,
                "external_id": row["external_job_id"],
                "title": row["title"],
                "title_normalized": title_normalized,
                "location_text": row["location_text"],
                "remote_mode": remote_mode,
                "employment_type": employment_type,
                "posted_at": row["posted_at"],
                "source_type": row["source_type"],
                "source_url": row["source_url"],
                "description_raw": description_raw,
                "description_text": description_text,
                "description_hash": description_hash,
                "dedupe_fingerprint": dedupe_fingerprint,
                "status": "active",
                "raw_payload": raw_payload,
                "metadata": metadata,
            }

            db.upsert_job(conn, normalized_job, now_iso=now_iso)
            job_upserts += 1

        db.log_run(
            conn,
            "normalize",
            "ok",
            {
                "raw_rows": len(raw_rows),
                "companies_upserted": company_upserts,
                "jobs_upserted": job_upserts,
                **(observability or {}),
            },
            _now_iso(),
            run_id=run_id,
        )
        conn.commit()

    return {
        "raw_rows": len(raw_rows),
        "companies_upserted": company_upserts,
        "jobs_upserted": job_upserts,
    }

def _load_company_aliases(path: str | Path) -> dict[str, Any]:
    if not Path(path).exists():
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))

def _normalize_company(company_name: str, aliases: dict[str, Any]) -> tuple[str, str]:
    normalized = company_name.strip()
    key = normalized.lower()
    mapping = aliases.get(key)
    if isinstance(mapping, str):
        company_identifier = mapping
        return normalized, company_identifier
    if isinstance(mapping, dict):
        company_identifier = mapping["id"]
        canonical_name = mapping.get("name") or normalized
        return canonical_name, company_identifier
    company_identifier = company_id_from_name(normalized)
    return normalized, company_identifier

def _normalize_title(title: str) -> str:
    title = title.strip().lower()
    title = re.sub(r"[^a-z0-9]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title

def _normalize_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def _infer_remote_mode(location_text: str | None, description_text: str) -> str | None:
    text = " ".join(filter(None, [location_text or "", description_text]))
    for label, pattern in REMOTE_PATTERNS.items():
        if pattern.search(text):
            return label
    return None

def _infer_employment_type(description_text: str) -> str | None:
    for label, pattern in EMPLOYMENT_PATTERNS.items():
        if pattern.search(description_text):
            return label
    return None

def _dedupe_fingerprint(company_name: str, title: str, location_text: str | None, description_text: str) -> str:
    top_words = " ".join(sorted(set(_keywords(description_text)))[:12])
    payload = "|".join(
        [
            slugify(company_name),
            slugify(title),
            slugify(location_text or ""),
            short_hash(top_words),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def _keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9+\-]{1,}", text.lower())
    stop = {"the", "and", "with", "for", "you", "our", "will", "this", "that", "are", "job", "role"}
    return [token for token in tokens if token not in stop][:100]

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
