from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters.ashby import fetch_ashby_job_board
from .adapters.company_site import crawl_company_site_source
from .adapters.greenhouse import fetch_greenhouse_board
from .adapters.html_fallback import parse_generic_html_file, parse_generic_html_url
from .adapters.jsonld import parse_jobposting_from_file, parse_jobposting_from_url
from .adapters.lever import fetch_lever_postings
from .io_utils import read_json, write_json, write_jsonl
from .schema_validation import validate_many

STANDARD_SOURCE_KEYS = {"name", "type", "kind", "enabled", "config"}


def run_source_registry(
    config_path: str | Path,
    out_dir: str | Path,
    *,
    continue_on_error: bool = False,
    report_path: str | Path | None = None,
) -> dict[str, Any]:
    config_path = Path(config_path)
    payload = read_json(config_path)
    sources = payload.get("sources", []) if isinstance(payload, dict) else None
    if not isinstance(sources, list):
        raise ValueError("Source config must contain a top-level 'sources' list")

    config_dir = config_path.parent
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = Path(report_path) if report_path is not None else out_dir / "source-registry-report.json"

    summary: dict[str, Any] = {
        "config_path": str(config_path),
        "out_dir": str(out_dir),
        "report_path": str(report_path),
        "status": "running",
        "generated_at": _now_iso(),
        "sources_total": len(sources),
        "sources_seen": 0,
        "sources_processed": 0,
        "sources_succeeded": 0,
        "sources_failed": 0,
        "sources_skipped": 0,
        "records_seen": 0,
        "records_written": 0,
        "output_files": [],
        "results": [],
    }

    _write_report(summary, report_path)

    for source in sources:
        if not isinstance(source, dict):
            message = "Source entries must be objects"
            result = {
                "name": "<invalid>",
                "type": None,
                "kind": None,
                "enabled": False,
                "status": "error",
                "seen": 0,
                "succeeded": 0,
                "failed": 1,
                "skipped": 0,
                "records": 0,
                "output_files": [],
                "error": message,
            }
            summary["results"].append(result)
            _apply_source_result(summary, result)
            if not continue_on_error:
                summary["status"] = "error"
                _write_report(summary, report_path)
                raise ValueError(message)
            _write_report(summary, report_path)
            continue

        normalized = _normalize_source_entry(source, config_dir)
        result = _run_one_source(normalized, out_dir)

        summary["results"].append(result)
        _apply_source_result(summary, result)
        if result["status"] == "error" and not continue_on_error:
            summary["status"] = "error"
            _write_report(summary, report_path)
            raise RuntimeError(f"Source {result['name']} failed: {result['error']}")
        _write_report(summary, report_path)

    summary["status"] = "error" if summary["sources_failed"] else "ok"
    _write_report(summary, report_path)

    return summary


def _run_one_source(source: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    name = str(source.get("name") or source.get("type") or "source").strip()
    source_type = str(source.get("type") or "").strip().lower()
    enabled = bool(source.get("enabled", True))
    if not enabled:
        return {
            "name": name,
            "type": source_type,
            "kind": source_type,
            "enabled": False,
            "config": dict(source.get("config") or {}),
            "status": "skipped",
            "seen": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 1,
            "records": 0,
            "output_files": [],
            "reason": "disabled",
        }

    try:
        config = dict(source.get("config") or {})
        out_path = out_dir / f"{_slug(name)}.jsonl"

        if source_type == "company_site":
            report_path = Path(config["report_path"]) if config.get("report_path") else out_dir / f"{_slug(name)}.report.json"
            records, generated_report = crawl_company_site_source(
                source=_required(source_type, config, "source"),
                output_path=out_path,
                report_path=report_path,
                script_path=config.get("script_path"),
                python_bin=config.get("python_bin"),
                list_url=config.get("list_url"),
                max_jobs=config.get("max_jobs"),
                timeout_ms=int(config.get("timeout_ms", 45_000)),
                delay_seconds=float(config.get("delay_seconds", 1.0)),
                headful=bool(config.get("headful", False)),
                log_level=str(config.get("log_level", "INFO")),
            )
        else:
            records = _fetch_source_records(source_type, config)
            generated_report = None
            # API boards (greenhouse/lever/ashby) can carry hundreds of
            # postings; honor an optional cap so CI builds stay bounded.
            max_jobs = config.get("max_jobs")
            if max_jobs is not None:
                records = records[: int(max_jobs)]

        payloads = [record.to_dict() for record in records]
        validate_many("raw_job", payloads, context=f"source[{name}]")
        write_jsonl(out_path, payloads)
        output_files = [str(out_path)]
        if generated_report:
            output_files.append(str(generated_report))
        return {
            "name": name,
            "type": source_type,
            "kind": source_type,
            "enabled": True,
            "config": config,
            "status": "ok",
            "seen": len(payloads),
            "succeeded": len(payloads),
            "failed": 0,
            "skipped": 0,
            "records": len(payloads),
            "output_files": output_files,
            "out_path": str(out_path),
        }
    except Exception as exc:
        return {
            "name": name,
            "type": source_type,
            "kind": source_type,
            "enabled": enabled,
            "config": dict(source.get("config") or {}),
            "status": "error",
            "seen": 0,
            "succeeded": 0,
            "failed": 1,
            "skipped": 0,
            "records": 0,
            "output_files": [],
            "error": str(exc),
        }


def _normalize_source_entry(source: dict[str, Any], config_dir: Path) -> dict[str, Any]:
    source_type = str(source.get("type") or source.get("kind") or "").strip().lower()
    if not source_type:
        raise ValueError("Source config entry is missing 'type'")

    name = str(source.get("name") or source_type or "source").strip()
    enabled = bool(source.get("enabled", True))

    config = source.get("config")
    if config is None:
        config = {}
    elif not isinstance(config, dict):
        raise ValueError("Source config entry field 'config' must be an object")
    else:
        config = deepcopy(config)

    legacy_config = {key: value for key, value in source.items() if key not in STANDARD_SOURCE_KEYS}
    merged = {**legacy_config, **config}
    merged = _resolve_config_paths(merged, config_dir)
    return {
        "name": name,
        "type": source_type,
        "enabled": enabled,
        "config": merged,
    }


def _fetch_source_records(source_type: str, config: dict[str, Any]) -> list[Any]:
    if not source_type:
        raise ValueError("Source config entry is missing 'type'")

    if source_type == "greenhouse":
        board = _required(source_type, config, "board")
        return fetch_greenhouse_board(board, timeout=int(config.get("timeout", 30)))

    if source_type == "lever":
        account = _required(source_type, config, "account")
        return fetch_lever_postings(account, timeout=int(config.get("timeout", 30)))

    if source_type == "ashby":
        job_board = _required(source_type, config, "job_board")
        return fetch_ashby_job_board(
            job_board,
            include_compensation=bool(config.get("include_compensation", False)),
            timeout=int(config.get("timeout", 30)),
        )

    if source_type == "jsonld":
        if config.get("html_file"):
            return parse_jobposting_from_file(str(config["html_file"]), source_url=config.get("source_url") or config.get("url"))
        if config.get("url"):
            return parse_jobposting_from_url(str(config["url"]), timeout=int(config.get("timeout", 30)))
        raise ValueError("jsonld sources require 'url' or 'html_file'")

    if source_type == "html":
        company_name = str(config.get("company_name") or "Unknown company")
        if config.get("html_file"):
            return parse_generic_html_file(
                str(config["html_file"]),
                source_url=config.get("source_url") or config.get("url"),
                company_name=company_name,
            )
        if config.get("url"):
            return parse_generic_html_url(str(config["url"]), company_name=company_name, timeout=int(config.get("timeout", 30)))
        raise ValueError("html sources require 'url' or 'html_file'")

    raise ValueError(f"Unsupported source type: {source_type}")


def _required(source_type: str, source: dict[str, Any], field: str) -> str:
    value = source.get(field)
    if not value:
        raise ValueError(f"Source type '{source_type}' requires field '{field}'")
    return str(value)


def _resolve_config_paths(config: dict[str, Any], config_dir: Path) -> dict[str, Any]:
    resolved = dict(config)
    for key in ("html_file", "script_path", "python_bin", "report_path"):
        value = resolved.get(key)
        if not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = (config_dir / path).resolve()
        resolved[key] = str(path)
    return resolved


def _apply_source_result(summary: dict[str, Any], result: dict[str, Any]) -> None:
    summary["sources_seen"] += 1
    summary["records_seen"] += int(result.get("seen") or 0)
    summary["records_written"] += int(result.get("succeeded") or 0)
    summary["sources_processed"] += 1 if result.get("status") == "ok" else 0
    summary["sources_succeeded"] += 1 if result.get("status") == "ok" else 0
    summary["sources_failed"] += 1 if result.get("status") == "error" else 0
    summary["sources_skipped"] += 1 if result.get("status") == "skipped" else 0
    summary["output_files"].extend(result.get("output_files") or [])


def _write_report(summary: dict[str, Any], report_path: Path) -> None:
    write_json(report_path, summary)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "source"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
