from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .schema_validation import validate_record

def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db(db_path: str | Path) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS raw_jobs (
                raw_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL,
                source_url TEXT NOT NULL,
                external_job_id TEXT,
                title TEXT NOT NULL,
                company_name TEXT NOT NULL,
                location_text TEXT,
                employment_type TEXT,
                posted_at TEXT,
                description_text TEXT,
                description_html TEXT,
                json_payload TEXT,
                metadata_json TEXT,
                fetched_at TEXT NOT NULL,
                canonical_source_key TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_raw_jobs_canonical_source_key
              ON raw_jobs(canonical_source_key);

            CREATE TABLE IF NOT EXISTS companies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                website TEXT,
                industry TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL REFERENCES companies(id),
                external_id TEXT,
                source_type TEXT NOT NULL,
                source_url TEXT NOT NULL,
                title TEXT NOT NULL,
                title_normalized TEXT NOT NULL,
                location_text TEXT,
                remote_mode TEXT,
                employment_type TEXT,
                posted_at TEXT,
                description_raw TEXT NOT NULL DEFAULT '',
                description_text TEXT NOT NULL DEFAULT '',
                description_hash TEXT NOT NULL,
                dedupe_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                raw_payload_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_external_source
              ON jobs(company_id, source_type, external_id)
              WHERE external_id IS NOT NULL;

            CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint
              ON jobs(dedupe_fingerprint);

            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                normalized_label TEXT NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]',
                parent_id TEXT,
                category TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_enrichment (
                job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                summary TEXT,
                role_family TEXT,
                seniority TEXT,
                remote_mode_inferred TEXT,
                salary_text TEXT,
                responsibilities_json TEXT NOT NULL DEFAULT '[]',
                qualifications_json TEXT NOT NULL DEFAULT '[]',
                evidence_json TEXT NOT NULL DEFAULT '[]',
                confidence REAL,
                model_name TEXT,
                prompt_version TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_skill_edges (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                skill_id TEXT NOT NULL REFERENCES skills(id),
                edge_type TEXT NOT NULL,
                weight REAL,
                confidence REAL,
                provenance TEXT,
                evidence_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(job_id, skill_id, edge_type)
            );

            CREATE TABLE IF NOT EXISTS run_log (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )
        _ensure_run_log_column(conn, "run_id", "TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_run_log_run_id ON run_log(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_run_log_stage ON run_log(stage)")

def insert_raw_jobs(conn: sqlite3.Connection, raw_jobs: Iterable[dict[str, Any]]) -> int:
    rows = []
    existing_keys = {
        row[0]
        for row in conn.execute(
            "SELECT canonical_source_key FROM raw_jobs WHERE canonical_source_key IS NOT NULL"
        ).fetchall()
        if row[0]
    }
    pending_keys: set[str] = set()
    for job in raw_jobs:
        validate_record("raw_job", job, context=f"raw_job[{job.get('source_url') or job.get('title') or 'unknown'}]")
        canonical_key = _canonical_source_key(job)
        if canonical_key in existing_keys or canonical_key in pending_keys:
            continue
        rows.append(
            (
                job["source_type"],
                job["source_url"],
                job.get("external_job_id"),
                job["title"],
                job["company_name"],
                job.get("location_text"),
                job.get("employment_type"),
                job.get("posted_at"),
                job.get("description_text"),
                job.get("description_html"),
                _json(job.get("json_payload")),
                _json(job.get("metadata") or {}),
                job["fetched_at"],
                canonical_key,
            )
        )
        pending_keys.add(canonical_key)
    if not rows:
        return 0
    conn.executemany(
        """
        INSERT INTO raw_jobs (
            source_type, source_url, external_job_id, title, company_name, location_text,
            employment_type, posted_at, description_text, description_html, json_payload,
            metadata_json, fetched_at, canonical_source_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    return len(rows)

def upsert_company(
    conn: sqlite3.Connection,
    *,
    company_id: str,
    name: str,
    aliases: list[str] | None = None,
    website: str | None = None,
    industry: str | None = None,
    metadata: dict[str, Any] | None = None,
    now_iso: str,
) -> None:
    aliases = aliases or []
    metadata = metadata or {}
    validate_record(
        "company",
        {
            "id": company_id,
            "name": name,
            "aliases": sorted(set(aliases)),
            "website": website,
            "industry": industry,
            "metadata": metadata,
        },
        context=f"company[{company_id}]",
    )
    conn.execute(
        """
        INSERT INTO companies (id, name, aliases_json, website, industry, metadata_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name,
            aliases_json=excluded.aliases_json,
            website=COALESCE(excluded.website, companies.website),
            industry=COALESCE(excluded.industry, companies.industry),
            metadata_json=excluded.metadata_json,
            updated_at=excluded.updated_at
        """,
        (
            company_id,
            name,
            _json(sorted(set(aliases))),
            website,
            industry,
            _json(metadata),
            now_iso,
            now_iso,
        ),
    )

def upsert_job(conn: sqlite3.Connection, job: dict[str, Any], now_iso: str) -> str:
    validate_record("job", job, context=f"job[{job.get('id', 'unknown')}]")
    existing = None
    if job.get("external_id"):
        existing = conn.execute(
            """
            SELECT id FROM jobs
            WHERE company_id = ? AND source_type = ? AND external_id = ?
            """,
            (job["company_id"], job["source_type"], job["external_id"]),
        ).fetchone()
    if existing is None:
        existing = conn.execute(
            "SELECT id FROM jobs WHERE dedupe_fingerprint = ?",
            (job["dedupe_fingerprint"],),
        ).fetchone()

    if existing:
        job_identifier = existing["id"]
        conn.execute(
            """
            UPDATE jobs SET
                company_id = ?,
                external_id = ?,
                source_type = ?,
                source_url = ?,
                title = ?,
                title_normalized = ?,
                location_text = ?,
                remote_mode = ?,
                employment_type = ?,
                posted_at = ?,
                description_raw = ?,
                description_text = ?,
                description_hash = ?,
                dedupe_fingerprint = ?,
                status = ?,
                raw_payload_json = ?,
                metadata_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                job["company_id"],
                job.get("external_id"),
                job["source_type"],
                job["source_url"],
                job["title"],
                job["title_normalized"],
                job.get("location_text"),
                job.get("remote_mode"),
                job.get("employment_type"),
                job.get("posted_at"),
                job.get("description_raw") or "",
                job.get("description_text") or "",
                job["description_hash"],
                job["dedupe_fingerprint"],
                job.get("status", "active"),
                _json(job.get("raw_payload") or {}),
                _json(job.get("metadata") or {}),
                now_iso,
                job_identifier,
            ),
        )
        return job_identifier

    conn.execute(
        """
        INSERT INTO jobs (
            id, company_id, external_id, source_type, source_url, title, title_normalized,
            location_text, remote_mode, employment_type, posted_at, description_raw,
            description_text, description_hash, dedupe_fingerprint, status, raw_payload_json,
            metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job["id"],
            job["company_id"],
            job.get("external_id"),
            job["source_type"],
            job["source_url"],
            job["title"],
            job["title_normalized"],
            job.get("location_text"),
            job.get("remote_mode"),
            job.get("employment_type"),
            job.get("posted_at"),
            job.get("description_raw") or "",
            job.get("description_text") or "",
            job["description_hash"],
            job["dedupe_fingerprint"],
            job.get("status", "active"),
            _json(job.get("raw_payload") or {}),
            _json(job.get("metadata") or {}),
            now_iso,
            now_iso,
        ),
    )
    return job["id"]

def upsert_skill(
    conn: sqlite3.Connection,
    *,
    skill_id: str,
    label: str,
    normalized_label: str,
    aliases: list[str] | None,
    parent_id: str | None,
    category: str | None,
    metadata: dict[str, Any] | None,
    now_iso: str,
) -> None:
    validate_record(
        "skill",
        {
            "id": skill_id,
            "label": label,
            "normalized_label": normalized_label,
            "aliases": aliases or [],
            "parent_id": parent_id,
            "category": category,
            "metadata": metadata or {},
        },
        context=f"skill[{skill_id}]",
    )
    conn.execute(
        """
        INSERT INTO skills (
            id, label, normalized_label, aliases_json, parent_id, category,
            metadata_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            label = excluded.label,
            normalized_label = excluded.normalized_label,
            aliases_json = excluded.aliases_json,
            parent_id = COALESCE(excluded.parent_id, skills.parent_id),
            category = COALESCE(excluded.category, skills.category),
            metadata_json = excluded.metadata_json,
            updated_at = excluded.updated_at
        """,
        (
            skill_id,
            label,
            normalized_label,
            _json(aliases or []),
            parent_id,
            category,
            _json(metadata or {}),
            now_iso,
            now_iso,
        ),
    )

def upsert_enrichment(conn: sqlite3.Connection, enrichment: dict[str, Any], now_iso: str) -> None:
    conn.execute(
        """
        INSERT INTO job_enrichment (
            job_id, summary, role_family, seniority, remote_mode_inferred, salary_text,
            responsibilities_json, qualifications_json, evidence_json, confidence,
            model_name, prompt_version, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id) DO UPDATE SET
            summary = excluded.summary,
            role_family = excluded.role_family,
            seniority = excluded.seniority,
            remote_mode_inferred = excluded.remote_mode_inferred,
            salary_text = excluded.salary_text,
            responsibilities_json = excluded.responsibilities_json,
            qualifications_json = excluded.qualifications_json,
            evidence_json = excluded.evidence_json,
            confidence = excluded.confidence,
            model_name = excluded.model_name,
            prompt_version = excluded.prompt_version,
            updated_at = excluded.updated_at
        """,
        (
            enrichment["job_id"],
            enrichment.get("summary"),
            enrichment.get("role_family"),
            enrichment.get("seniority"),
            enrichment.get("remote_mode_inferred"),
            enrichment.get("salary_text"),
            _json(enrichment.get("responsibilities") or []),
            _json(enrichment.get("qualifications") or []),
            _json(enrichment.get("evidence") or []),
            enrichment.get("confidence"),
            enrichment.get("model_name"),
            enrichment.get("prompt_version"),
            now_iso,
            now_iso,
        ),
    )

def upsert_job_skill_edge(conn: sqlite3.Connection, edge: dict[str, Any], now_iso: str) -> None:
    conn.execute(
        """
        INSERT INTO job_skill_edges (
            id, job_id, skill_id, edge_type, weight, confidence, provenance, evidence_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(job_id, skill_id, edge_type) DO UPDATE SET
            weight = excluded.weight,
            confidence = excluded.confidence,
            provenance = excluded.provenance,
            evidence_json = excluded.evidence_json,
            updated_at = excluded.updated_at
        """,
        (
            edge["id"],
            edge["job_id"],
            edge["skill_id"],
            edge["edge_type"],
            edge.get("weight"),
            edge.get("confidence"),
            edge.get("provenance"),
            _json(edge.get("evidence") or []),
            now_iso,
            now_iso,
        ),
    )

def log_run(
    conn: sqlite3.Connection,
    stage: str,
    status: str,
    details: dict[str, Any],
    now_iso: str,
    *,
    run_id: str | None = None,
) -> None:
    columns = _table_columns(conn, "run_log")
    if "run_id" in columns:
        conn.execute(
            "INSERT INTO run_log (run_id, stage, status, details_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (run_id, stage, status, _json(details), now_iso),
        )
        return
    conn.execute(
        "INSERT INTO run_log (stage, status, details_json, created_at) VALUES (?, ?, ?, ?)",
        (stage, status, _json(details), now_iso),
    )

def fetch_all(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    return conn.execute(query, params).fetchall()

def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)

def _canonical_source_key(job: dict[str, Any]) -> str:
    external_id = job.get("external_job_id")
    if external_id:
        return f"{job['source_type']}::{job['company_name']}::{external_id}"
    return f"{job['source_type']}::{job['source_url']}"


def _ensure_run_log_column(conn: sqlite3.Connection, name: str, definition: str) -> None:
    columns = _table_columns(conn, "run_log")
    if name in columns:
        return
    conn.execute(f"ALTER TABLE run_log ADD COLUMN {name} {definition}")


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}
