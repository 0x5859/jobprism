from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .providers.base import EnrichmentResult


DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "enrichment_cache.sqlite3"


@dataclass(slots=True)
class CacheStats:
    hits: int = 0
    misses: int = 0
    writes: int = 0


class EnrichmentCache:
    def __init__(self, db_path: str | Path | None = None) -> None:
        self.path = Path(
            db_path
            or os.getenv("JOBVISUALIZER_ENRICH_CACHE_PATH")
            or DEFAULT_CACHE_PATH
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "EnrichmentCache":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self.close()
        return False

    def get(self, cache_key: str) -> EnrichmentResult | None:
        row = self._conn.execute(
            "SELECT result_json FROM enrichment_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row["result_json"])
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        return EnrichmentResult.from_dict(payload)

    def set(
        self,
        cache_key: str,
        result: EnrichmentResult,
        *,
        description_hash: str,
        provider_name: str,
        provider_signature: str,
        taxonomy_hash: str,
    ) -> None:
        payload = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)
        now_iso = _now_iso()
        self._conn.execute(
            """
            INSERT INTO enrichment_cache (
                cache_key, description_hash, provider_name, provider_signature,
                taxonomy_hash, result_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                description_hash = excluded.description_hash,
                provider_name = excluded.provider_name,
                provider_signature = excluded.provider_signature,
                taxonomy_hash = excluded.taxonomy_hash,
                result_json = excluded.result_json,
                updated_at = excluded.updated_at
            """,
            (
                cache_key,
                description_hash,
                provider_name,
                provider_signature,
                taxonomy_hash,
                payload,
                now_iso,
                now_iso,
            ),
        )
        self._conn.commit()

    def make_key(self, *, description_hash: str, provider_signature: str, taxonomy_hash: str) -> str:
        raw = "::".join([description_hash, provider_signature, taxonomy_hash])
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS enrichment_cache (
                cache_key TEXT PRIMARY KEY,
                description_hash TEXT NOT NULL,
                provider_name TEXT NOT NULL,
                provider_signature TEXT NOT NULL,
                taxonomy_hash TEXT NOT NULL,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_enrichment_cache_description_hash
              ON enrichment_cache(description_hash);
            """
        )


def compute_taxonomy_hash(taxonomy: list[dict[str, Any]]) -> str:
    payload = json.dumps(taxonomy, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def provider_signature(provider: Any) -> str:
    signature = getattr(provider, "cache_key", None)
    if callable(signature):
        value = signature()
        if value:
            return str(value)
    if isinstance(signature, str) and signature.strip():
        return signature.strip()
    return getattr(provider, "name", provider.__class__.__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
