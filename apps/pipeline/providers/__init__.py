from __future__ import annotations

from typing import Any

from .base import EnrichmentProvider, EnrichmentResult, SkillSuggestion
from .heuristic import HeuristicEnrichmentProvider, load_taxonomy
from .openai_compatible import OpenAICompatibleEnrichmentProvider


def build_enrichment_provider(
    spec: str | EnrichmentProvider | None,
    *,
    provider_config: dict[str, Any] | None = None,
    taxonomy: list[dict[str, Any]] | None = None,
) -> EnrichmentProvider:
    if _looks_like_provider(spec):
        return spec

    config = dict(provider_config or {})
    taxonomy = taxonomy or []
    kind = _coerce_kind(spec, config)

    if kind in {"env", "auto"}:
        env_provider = load_provider_from_env(provider_config=config, taxonomy=taxonomy)
        if env_provider is not None:
            return env_provider
        kind = "heuristic"

    if kind in {"heuristic", "default", "local"}:
        return HeuristicEnrichmentProvider(taxonomy)

    if kind in {"openai", "openai-compatible", "chat-completions"}:
        return OpenAICompatibleEnrichmentProvider(
            api_key=config.get("api_key") or config.get("token"),
            model=config.get("model", "gpt-4.1-mini"),
            base_url=config.get("base_url", "https://api.openai.com"),
            endpoint=config.get("endpoint", "/v1/chat/completions"),
            request_timeout=float(config.get("timeout", config.get("request_timeout", 60))),
            strict_json=_coerce_bool(config.get("strict_json"), default=True),
            max_retries=int(config.get("max_retries", config.get("retries", 2))),
            retry_backoff_seconds=float(config.get("retry_backoff_seconds", 1.0)),
            retry_max_backoff_seconds=float(config.get("retry_max_backoff_seconds", 8.0)),
            retry_status_codes=_coerce_status_codes(config.get("retry_status_codes")),
        )

    raise ValueError(f"Unsupported enrichment provider: {spec!r}")


def load_provider_from_env(
    *,
    provider_config: dict[str, Any] | None = None,
    taxonomy: list[dict[str, Any]] | None = None,
) -> EnrichmentProvider | None:
    import os

    kind = os.getenv("JOBVISUALIZER_ENRICH_PROVIDER")
    if not kind:
        return None

    merged_config = dict(provider_config or {})
    for key, env_key in {
        "api_key": "JOBVISUALIZER_ENRICH_API_KEY",
        "model": "JOBVISUALIZER_ENRICH_MODEL",
        "base_url": "JOBVISUALIZER_ENRICH_BASE_URL",
        "endpoint": "JOBVISUALIZER_ENRICH_ENDPOINT",
        "timeout": "JOBVISUALIZER_ENRICH_TIMEOUT",
        "max_retries": "JOBVISUALIZER_ENRICH_MAX_RETRIES",
        "retry_backoff_seconds": "JOBVISUALIZER_ENRICH_RETRY_BACKOFF_SECONDS",
        "retry_max_backoff_seconds": "JOBVISUALIZER_ENRICH_RETRY_MAX_BACKOFF_SECONDS",
    }.items():
        if key not in merged_config and os.getenv(env_key):
            merged_config[key] = os.getenv(env_key)

    resolved_kind = str(merged_config.get("kind") or merged_config.get("provider") or kind).strip().lower()
    if resolved_kind in {"env", "auto"}:
        resolved_kind = "heuristic"
    return build_enrichment_provider(resolved_kind, provider_config=merged_config, taxonomy=taxonomy)


def _coerce_kind(spec: str | EnrichmentProvider | None, config: dict[str, Any]) -> str:
    value = spec if isinstance(spec, str) else config.get("kind") or config.get("provider") or "heuristic"
    return str(value).strip().lower().replace("_", "-")


def _looks_like_provider(value: Any) -> bool:
    return hasattr(value, "enrich") and callable(getattr(value, "enrich", None)) and hasattr(value, "name")


def provider_cache_signature(provider: EnrichmentProvider, taxonomy_hash: str) -> str:
    key = getattr(provider, "cache_key", None)
    if callable(key):
        signature = key()
    else:
        signature = key
    if not signature:
        signature = provider.name
    return f"{signature}:{taxonomy_hash}"


def _coerce_status_codes(value: Any) -> list[int]:
    if value is None:
        return [429, 500, 502, 503, 504]
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        items = [value]
    codes: list[int] = []
    for item in items:
        try:
            codes.append(int(item))
        except (TypeError, ValueError):
            continue
    return codes or [429, 500, 502, 503, 504]


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
