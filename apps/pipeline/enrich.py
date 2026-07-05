from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db
from .enrichment_cache import EnrichmentCache, compute_taxonomy_hash, provider_signature
from .ids import edge_id
from .providers import (
    EnrichmentProvider,
    build_enrichment_provider,
    load_provider_from_env,
)
from .providers.base import EnrichmentResult
from .providers.heuristic import HeuristicEnrichmentProvider
from .providers.heuristic import load_taxonomy


def enrich_jobs(
    db_path: str | Path,
    skill_taxonomy_path: str | Path,
    limit: int | None = None,
    force: bool = False,
    provider: str | EnrichmentProvider | None = None,
    provider_config: dict[str, Any] | None = None,
    cache_path: str | Path | None = None,
    use_cache: bool = True,
    run_id: str | None = None,
    observability: dict[str, Any] | None = None,
) -> dict[str, int]:
    taxonomy = load_taxonomy(skill_taxonomy_path)
    taxonomy_hash = compute_taxonomy_hash(taxonomy)
    enrichment_provider = _resolve_provider(provider, provider_config, taxonomy)
    provider_sig = provider_signature(enrichment_provider)
    provider_name = _canonical_provider_name(enrichment_provider.name)
    cache = _resolve_cache(cache_path, provider_config, use_cache)
    processed = 0
    edges_created = 0
    skills_upserted = 0
    cache_hits = 0
    cache_misses = 0
    cache_writes = 0

    with db.connect(db_path) as conn, (cache if cache is not None else nullcontext()):
        try:
            query = """
                SELECT j.id, j.title, j.location_text, j.remote_mode, j.description_text,
                       j.company_id, j.external_id, j.source_type, j.source_url,
                       j.employment_type, j.posted_at, j.description_raw, j.description_hash,
                       j.dedupe_fingerprint, j.status, j.metadata_json, c.name AS company_name
                FROM jobs j
                LEFT JOIN job_enrichment e ON e.job_id = j.id
                LEFT JOIN companies c ON c.id = j.company_id
            """
            params: tuple[Any, ...] = ()
            if not force:
                query += " WHERE e.job_id IS NULL"
            query += " ORDER BY j.id ASC"
            if limit is not None:
                query += " LIMIT ?"
                params = (limit,)
            rows = db.fetch_all(conn, query, params)

            for row in rows:
                now_iso = _now_iso()
                job = dict(row)
                job["metadata"] = _loads(row["metadata_json"])
                job_description_hash = row["description_hash"] or ""

                result = None
                cache_key = None
                if cache and job_description_hash:
                    cache_key = cache.make_key(
                        description_hash=job_description_hash,
                        provider_signature=provider_sig,
                        taxonomy_hash=taxonomy_hash,
                    )
                    result = cache.get(cache_key)
                    if result is not None:
                        cache_hits += 1
                        result.job_id = row["id"]

                if result is None:
                    cache_misses += 1
                    result = enrichment_provider.enrich(job, taxonomy)
                    _validate_result(result)
                    result.job_id = row["id"]
                    if cache and cache_key:
                        cache.set(
                            cache_key,
                            result,
                            description_hash=job_description_hash,
                            provider_name=enrichment_provider.name,
                            provider_signature=provider_sig,
                            taxonomy_hash=taxonomy_hash,
                        )
                        cache_writes += 1
                else:
                    _validate_result(result)

                for skill in result.skills:
                    if not skill.skill_id or not skill.label:
                        continue
                    db.upsert_skill(
                        conn,
                        skill_id=skill.skill_id,
                        label=skill.label,
                        normalized_label=skill.normalized_label,
                        aliases=skill.aliases,
                        parent_id=skill.parent_id,
                        category=skill.category,
                        metadata={"source": skill.provenance},
                        now_iso=now_iso,
                    )
                    skills_upserted += 1

                    edge = {
                        "id": edge_id(row["id"], skill.edge_type, skill.skill_id),
                        "job_id": row["id"],
                        "skill_id": skill.skill_id,
                        "edge_type": skill.edge_type,
                        "weight": skill.weight,
                        "confidence": skill.confidence,
                        "provenance": skill.provenance,
                        "evidence": skill.evidence,
                    }
                    db.upsert_job_skill_edge(conn, edge, now_iso=now_iso)
                    edges_created += 1

                db.upsert_enrichment(conn, result.to_db_payload(job_id=row["id"]), now_iso=now_iso)
                processed += 1

            db.log_run(
                conn,
                "enrich",
                "ok",
                {
                    "jobs_processed": processed,
                    "skills_upserted": skills_upserted,
                    "edges_upserted": edges_created,
                    "provider": provider_name,
                    "provider_signature": provider_sig,
                    "taxonomy_hash": taxonomy_hash,
                    "cache_hits": cache_hits,
                    "cache_misses": cache_misses,
                    "cache_writes": cache_writes,
                    "cache_enabled": bool(cache is not None),
                    **(observability or {}),
                },
                _now_iso(),
                run_id=run_id,
            )
            conn.commit()
        except Exception as exc:
            db.log_run(
                conn,
                "enrich",
                "error",
                {
                    "provider": provider_name,
                    "provider_signature": provider_sig,
                    "taxonomy_hash": taxonomy_hash,
                    "error": str(exc),
                    **(observability or {}),
                },
                _now_iso(),
                run_id=run_id,
            )
            conn.commit()
            raise

    return {
        "jobs_processed": processed,
        "skills_upserted": skills_upserted,
        "edges_upserted": edges_created,
        "provider": provider_name,
        "provider_signature": provider_sig,
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "cache_writes": cache_writes,
    }


def _resolve_provider(
    provider: str | EnrichmentProvider | None,
    provider_config: dict[str, Any] | None,
    taxonomy: list[dict[str, Any]],
) -> EnrichmentProvider:
    if _looks_like_provider(provider):
        return provider

    if provider_config and any(key in provider_config for key in ("kind", "provider", "api_key", "token", "model", "base_url", "endpoint")):
        return build_enrichment_provider(None, provider_config=provider_config, taxonomy=taxonomy)

    if provider is None:
        env_provider = load_provider_from_env(provider_config=provider_config, taxonomy=taxonomy)
        if env_provider is not None:
            return env_provider
        return HeuristicEnrichmentProvider(taxonomy)

    return build_enrichment_provider(provider, provider_config=provider_config, taxonomy=taxonomy)


def _resolve_cache(
    cache_path: str | Path | None,
    provider_config: dict[str, Any] | None,
    use_cache: bool,
) -> EnrichmentCache | None:
    if not use_cache:
        return None
    resolved_path = cache_path or (provider_config or {}).get("cache_path")
    cache_enabled = _coerce_bool((provider_config or {}).get("cache_enabled"), default=True)
    if not cache_enabled:
        return None
    return EnrichmentCache(resolved_path)


def _validate_result(result: EnrichmentResult) -> None:
    if not result.job_id:
        raise ValueError("Enrichment result must include job_id")
    if not isinstance(result.evidence, list):
        raise TypeError("Enrichment result evidence must be a list")
    if not isinstance(result.skills, list):
        raise TypeError("Enrichment result skills must be a list")


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _looks_like_provider(value: Any) -> bool:
    return hasattr(value, "enrich") and callable(getattr(value, "enrich", None)) and hasattr(value, "name")


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _canonical_provider_name(value: str) -> str:
    return str(value).strip().lower().replace("-", "_")
