from __future__ import annotations

import argparse
import json
import os
from pprint import pprint
from pathlib import Path
from typing import Any

from . import db
from .adapters.ashby import save_ashby_job_board
from .adapters.greenhouse import save_greenhouse_board
from .adapters.html_fallback import parse_generic_html_file, parse_generic_html_url, save_html_records
from .adapters.jsonld import parse_jobposting_from_file, parse_jobposting_from_url, save_jobposting_records
from .adapters.lever import save_lever_postings
from .build_graph import build_public_graph
from .config import DEFAULT_COMPANY_ALIASES, DEFAULT_DB, DEFAULT_PUBLIC_DIR, DEFAULT_RAW_DIR, DEFAULT_SKILL_TAXONOMY, ROOT
from .enrich import enrich_jobs
from .normalize import import_raw_inputs, normalize_all
from .observability import start_run
from .source_registry import run_source_registry
from ..web.build_site import build_site

PIPELINE_STAGE_ORDER = [
    "fetch_sources",
    "import_raw",
    "normalize",
    "enrich",
    "build_graph",
    "build_site",
]

def main() -> None:
    parser = argparse.ArgumentParser(description="Recruitment graph pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db_p = subparsers.add_parser("init-db", help="Create SQLite tables")
    init_db_p.add_argument("--db", default=str(DEFAULT_DB))

    fg_p = subparsers.add_parser("fetch-greenhouse", help="Fetch one Greenhouse board into JSONL")
    fg_p.add_argument("--board", required=True)
    fg_p.add_argument("--out", required=True)

    fl_p = subparsers.add_parser("fetch-lever", help="Fetch one Lever account into JSONL")
    fl_p.add_argument("--account", required=True)
    fl_p.add_argument("--out", required=True)

    fa_p = subparsers.add_parser("fetch-ashby", help="Fetch one Ashby job board into JSONL")
    fa_p.add_argument("--job-board", required=True)
    fa_p.add_argument("--out", required=True)
    fa_p.add_argument("--include-compensation", action="store_true")

    fs_p = subparsers.add_parser("fetch-sources", help="Run a config-driven source registry into JSONL files")
    fs_p.add_argument("--config", required=True)
    fs_p.add_argument("--out-dir", default=str(DEFAULT_RAW_DIR))
    fs_p.add_argument("--report")
    fs_p.add_argument("--continue-on-error", action="store_true")
    fs_p.add_argument("--db", default=str(DEFAULT_DB))
    _add_observability_args(fs_p)

    pj_p = subparsers.add_parser("parse-jsonld", help="Extract JobPosting JSON-LD into JSONL")
    source_group = pj_p.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--html-file")
    source_group.add_argument("--url")
    pj_p.add_argument("--out", required=True)

    ph_p = subparsers.add_parser("parse-html", help="Extract a generic HTML job page into JSONL")
    html_group = ph_p.add_mutually_exclusive_group(required=True)
    html_group.add_argument("--html-file")
    html_group.add_argument("--url")
    ph_p.add_argument("--company-name", default="Unknown company")
    ph_p.add_argument("--out", required=True)

    ir_p = subparsers.add_parser("import-raw", help="Import raw JSON/JSONL files into SQLite")
    ir_p.add_argument("--input", required=True)
    ir_p.add_argument("--db", default=str(DEFAULT_DB))
    _add_observability_args(ir_p)

    norm_p = subparsers.add_parser("normalize", help="Normalize raw jobs into truth tables")
    norm_p.add_argument("--db", default=str(DEFAULT_DB))
    norm_p.add_argument("--company-aliases", default=str(DEFAULT_COMPANY_ALIASES))
    _add_observability_args(norm_p)

    enrich_p = subparsers.add_parser("enrich", help="Heuristic skill extraction and metadata enrichment")
    enrich_p.add_argument("--db", default=str(DEFAULT_DB))
    enrich_p.add_argument("--skill-taxonomy", default=str(DEFAULT_SKILL_TAXONOMY))
    enrich_p.add_argument("--limit", type=int)
    enrich_p.add_argument("--force", action="store_true")
    enrich_p.add_argument("--provider", help="heuristic | openai-compatible | env")
    enrich_p.add_argument("--provider-config-file", help="Path to JSON provider config")
    enrich_p.add_argument("--provider-config-json", help="Inline JSON object for provider config")
    enrich_p.add_argument("--provider-model")
    enrich_p.add_argument("--provider-base-url")
    enrich_p.add_argument("--provider-endpoint")
    enrich_p.add_argument("--provider-api-key")
    enrich_p.add_argument("--cache-path")
    enrich_p.add_argument("--no-cache", action="store_true")
    _add_observability_args(enrich_p)

    graph_p = subparsers.add_parser("build-graph", help="Build public JSON outputs")
    graph_p.add_argument("--db", default=str(DEFAULT_DB))
    graph_p.add_argument("--out", default=str(DEFAULT_PUBLIC_DIR))
    _add_observability_args(graph_p)

    site_p = subparsers.add_parser("build-site", help="Build the static site from public JSON outputs")
    site_p.add_argument("--data-dir", required=True)
    site_p.add_argument("--out", required=True)
    site_p.add_argument("--site-dir")
    site_p.add_argument("--db", default=str(DEFAULT_DB))
    _add_observability_args(site_p)

    run_p = subparsers.add_parser("run-pipeline", help="Run fetch, import, normalize, enrich, build-graph, and build-site as one orchestrated run")
    run_p.add_argument("--config", help="Source registry config file")
    run_p.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR))
    run_p.add_argument("--import-input", action="append", default=[], help="Additional raw JSON/JSONL input path. Can be repeated.")
    run_p.add_argument("--db", default=str(DEFAULT_DB))
    run_p.add_argument("--company-aliases", default=str(DEFAULT_COMPANY_ALIASES))
    run_p.add_argument("--skill-taxonomy", default=str(DEFAULT_SKILL_TAXONOMY))
    run_p.add_argument("--public-dir", default=str(DEFAULT_PUBLIC_DIR))
    run_p.add_argument("--site-out", default=str(ROOT / "dist"))
    run_p.add_argument("--site-dir")
    run_p.add_argument("--continue-on-error", action="store_true")
    run_p.add_argument("--provider", help="heuristic | openai-compatible | env")
    run_p.add_argument("--provider-config-file", help="Path to JSON provider config")
    run_p.add_argument("--provider-config-json", help="Inline JSON object for provider config")
    run_p.add_argument("--provider-model")
    run_p.add_argument("--provider-base-url")
    run_p.add_argument("--provider-endpoint")
    run_p.add_argument("--provider-api-key")
    run_p.add_argument("--cache-path")
    run_p.add_argument("--no-cache", action="store_true")
    run_p.add_argument("--from-stage", choices=PIPELINE_STAGE_ORDER)
    run_p.add_argument("--to-stage", choices=PIPELINE_STAGE_ORDER)
    run_p.add_argument("--resume-run-id")
    run_p.add_argument("--skip-fetch", action="store_true")
    run_p.add_argument("--skip-build-site", action="store_true")
    _add_observability_args(run_p)

    args = parser.parse_args()

    if args.command == "init-db":
        db.init_db(args.db)
        print(f"Initialized database at {args.db}")
        return

    if args.command == "fetch-greenhouse":
        count = save_greenhouse_board(args.board, args.out)
        print(f"Wrote {count} raw jobs to {args.out}")
        return

    if args.command == "fetch-lever":
        count = save_lever_postings(args.account, args.out)
        print(f"Wrote {count} raw jobs to {args.out}")
        return

    if args.command == "fetch-ashby":
        count = save_ashby_job_board(args.job_board, args.out, include_compensation=args.include_compensation)
        print(f"Wrote {count} raw jobs to {args.out}")
        return

    if args.command == "fetch-sources":
        run = _start_observed_run(args)
        stage = "fetch_sources"
        run.stage_start(stage, {"config": args.config, "out_dir": args.out_dir})
        try:
            result = run_source_registry(
                args.config,
                args.out_dir,
                continue_on_error=args.continue_on_error,
                report_path=args.report,
            )
            _record_source_results(run, stage, result)
            stage_status = _registry_stage_status(result)
            run.stage_end(stage, stage_status, result)
            _log_stage_to_db(args.db, stage, stage_status, _stage_details(run, result))
            run.finish("ok" if stage_status == "ok" else "error")
            pprint(result)
        except Exception as exc:
            _handle_stage_failure(run, args.db, stage, exc, {"config": args.config, "out_dir": args.out_dir})
            raise
        return

    if args.command == "parse-jsonld":
        records = parse_jobposting_from_file(args.html_file) if args.html_file else parse_jobposting_from_url(args.url)
        count = save_jobposting_records(records, args.out)
        print(f"Wrote {count} raw jobs to {args.out}")
        return

    if args.command == "parse-html":
        records = (
            parse_generic_html_file(args.html_file, company_name=args.company_name)
            if args.html_file
            else parse_generic_html_url(args.url, company_name=args.company_name)
        )
        count = save_html_records(records, args.out)
        print(f"Wrote {count} raw jobs to {args.out}")
        return

    if args.command == "import-raw":
        run = _start_observed_run(args)
        stage = "import_raw"
        run.stage_start(stage, {"input": args.input, "db": args.db})
        try:
            db.init_db(args.db)
            count = import_raw_inputs(
                args.db,
                args.input,
                run_id=run.run_id,
                observability=_observability_details(run),
            )
            result = {"records_inserted": count, "input_path": args.input, "db": args.db}
            run.stage_end(stage, "ok", result)
            run.add_artifact("sqlite", args.db, stage=stage)
            run.finish("ok")
            print(f"Imported {count} raw jobs into {args.db}")
        except Exception as exc:
            _handle_stage_failure(run, args.db, stage, exc, {"input": args.input, "db": args.db})
            raise
        return

    if args.command == "normalize":
        run = _start_observed_run(args)
        stage = "normalize"
        run.stage_start(stage, {"db": args.db, "company_aliases": args.company_aliases})
        try:
            db.init_db(args.db)
            result = normalize_all(
                args.db,
                args.company_aliases,
                run_id=run.run_id,
                observability=_observability_details(run),
            )
            run.stage_end(stage, "ok", result)
            run.add_artifact("sqlite", args.db, stage=stage)
            run.finish("ok")
            pprint(result)
        except Exception as exc:
            _handle_stage_failure(run, args.db, stage, exc, {"db": args.db, "company_aliases": args.company_aliases})
            raise
        return

    if args.command == "enrich":
        run = _start_observed_run(args)
        stage = "enrich"
        provider_config = _provider_config_from_args(args)
        run.stage_start(stage, {"db": args.db, "provider": _requested_provider_name(args, provider_config)})
        try:
            result = enrich_jobs(
                args.db,
                args.skill_taxonomy,
                limit=args.limit,
                force=args.force,
                provider=args.provider,
                provider_config=provider_config,
                cache_path=args.cache_path,
                use_cache=not args.no_cache,
                run_id=run.run_id,
                observability=_observability_details(run),
            )
            run.stage_end(stage, "ok", result)
            run.add_artifact("sqlite", args.db, stage=stage)
            run.finish("ok")
            pprint(result)
        except Exception as exc:
            run.fail(exc, stage=stage, details={"db": args.db, "provider": args.provider})
            run.stage_end(stage, "error", {"db": args.db, "provider": args.provider})
            run.finish("error")
            raise
        return

    if args.command == "build-graph":
        run = _start_observed_run(args)
        stage = "build_graph"
        run.stage_start(stage, {"db": args.db, "out_dir": args.out})
        try:
            result = build_public_graph(
                args.db,
                args.out,
                run_id=run.run_id,
                observability=_observability_details(run),
            )
            run.stage_end(stage, "ok", result)
            run.add_artifact("public_json", args.out, stage=stage)
            run.finish("ok")
            pprint(result)
        except Exception as exc:
            _handle_stage_failure(run, args.db, stage, exc, {"db": args.db, "out_dir": args.out})
            raise
        return

    if args.command == "build-site":
        run = _start_observed_run(args)
        stage = "build_site"
        run.stage_start(stage, {"data_dir": args.data_dir, "out_dir": args.out})
        try:
            build_site(args.data_dir, args.out, site_dir=args.site_dir)
            result = {"data_dir": args.data_dir, "out_dir": args.out, "site_dir": args.site_dir}
            run.stage_end(stage, "ok", result)
            _log_stage_to_db(args.db, stage, "ok", _stage_details(run, result))
            run.add_artifact("site_dist", args.out, stage=stage)
            run.finish("ok")
            print(f"Built static site into {args.out}")
        except Exception as exc:
            _handle_stage_failure(run, args.db, stage, exc, {"data_dir": args.data_dir, "out_dir": args.out})
            raise
        return

    if args.command == "run-pipeline":
        _run_pipeline_command(args)
        return


def _run_pipeline_command(args: argparse.Namespace) -> None:
    run = _start_observed_run(args)
    db.init_db(args.db)
    stage_plan = _pipeline_stage_plan(args)
    run.report["details"].update(
        {
            "from_stage": args.from_stage or PIPELINE_STAGE_ORDER[0],
            "to_stage": args.to_stage or PIPELINE_STAGE_ORDER[-1],
            "requested_stages": _requested_stage_names(args),
            "effective_stage_plan": stage_plan,
            "skipped_stages": [],
        }
    )
    if args.resume_run_id:
        run.report["details"]["resume_run_id"] = args.resume_run_id
        run.add_event("resume_from", {"resume_run_id": args.resume_run_id})
    run.add_event("pipeline_plan", stage_plan)

    import_inputs = [str(Path(path)) for path in args.import_input]
    if args.config and stage_plan["import_raw"]["run"]:
        import_inputs.append(str(Path(args.raw_dir)))

    if stage_plan["fetch_sources"]["run"] and not args.config:
        raise ValueError("run-pipeline needs --config when fetch_sources will run")
    if stage_plan["import_raw"]["run"] and not import_inputs:
        raise ValueError("run-pipeline needs --config or --import-input when import_raw will run")

    provider_config = _provider_config_from_args(args)

    if stage_plan["fetch_sources"]["run"]:
        stage = "fetch_sources"
        run.stage_start(stage, {"config": args.config, "out_dir": args.raw_dir})
        try:
            source_report_path = run.report_path.with_name(f"{run.run_id}-source-registry.json")
            fetch_result = run_source_registry(
                args.config,
                args.raw_dir,
                continue_on_error=args.continue_on_error,
                report_path=source_report_path,
            )
            _record_source_results(run, stage, fetch_result)
            stage_status = _registry_stage_status(fetch_result)
            run.stage_end(stage, stage_status, fetch_result)
            _log_stage_to_db(args.db, stage, stage_status, _stage_details(run, fetch_result))
        except Exception as exc:
            _handle_stage_failure(run, args.db, stage, exc, {"config": args.config, "out_dir": args.raw_dir})
            raise
    else:
        _record_skipped_stage(
            run,
            args.db,
            "fetch_sources",
            {
                "reason": stage_plan["fetch_sources"]["reason"],
                "config": args.config,
                "out_dir": args.raw_dir,
            },
        )

    if stage_plan["import_raw"]["run"]:
        for input_path in import_inputs:
            stage = "import_raw"
            run.stage_start(stage, {"input": input_path, "db": args.db})
            try:
                count = import_raw_inputs(
                    args.db,
                    input_path,
                    run_id=run.run_id,
                    observability=_observability_details(run),
                )
                result = {"records_inserted": count, "input_path": input_path, "db": args.db}
                run.stage_end(stage, "ok", result)
                run.add_artifact("sqlite", args.db, stage=stage, metadata={"input_path": input_path})
            except Exception as exc:
                _handle_stage_failure(run, args.db, stage, exc, {"input": input_path, "db": args.db})
                raise
    else:
        _record_skipped_stage(
            run,
            args.db,
            "import_raw",
            {
                "reason": stage_plan["import_raw"]["reason"],
                "inputs": import_inputs,
                "db": args.db,
            },
        )

    stage = "normalize"
    if stage_plan[stage]["run"]:
        run.stage_start(stage, {"db": args.db, "company_aliases": args.company_aliases})
        try:
            normalize_result = normalize_all(
                args.db,
                args.company_aliases,
                run_id=run.run_id,
                observability=_observability_details(run),
            )
            run.stage_end(stage, "ok", normalize_result)
            run.add_artifact("sqlite", args.db, stage=stage)
        except Exception as exc:
            _handle_stage_failure(run, args.db, stage, exc, {"db": args.db, "company_aliases": args.company_aliases})
            raise
    else:
        _record_skipped_stage(
            run,
            args.db,
            stage,
            {"reason": stage_plan[stage]["reason"], "db": args.db, "company_aliases": args.company_aliases},
        )

    stage = "enrich"
    if stage_plan[stage]["run"]:
        run.stage_start(stage, {"db": args.db, "provider": _requested_provider_name(args, provider_config)})
        try:
            enrich_result = enrich_jobs(
                args.db,
                args.skill_taxonomy,
                provider=args.provider,
                provider_config=provider_config,
                cache_path=args.cache_path,
                use_cache=not args.no_cache,
                run_id=run.run_id,
                observability=_observability_details(run),
            )
            run.stage_end(stage, "ok", enrich_result)
            run.add_artifact("sqlite", args.db, stage=stage)
        except Exception as exc:
            run.fail(exc, stage=stage, details={"db": args.db, "provider": args.provider})
            run.stage_end(stage, "error", {"db": args.db, "provider": args.provider})
            run.finish("error")
            raise
    else:
        _record_skipped_stage(
            run,
            args.db,
            stage,
            {"reason": stage_plan[stage]["reason"], "db": args.db, "provider": _requested_provider_name(args, provider_config)},
        )

    stage = "build_graph"
    if stage_plan[stage]["run"]:
        run.stage_start(stage, {"db": args.db, "out_dir": args.public_dir})
        try:
            graph_result = build_public_graph(
                args.db,
                args.public_dir,
                run_id=run.run_id,
                observability=_observability_details(run),
            )
            run.stage_end(stage, "ok", graph_result)
            run.add_artifact("public_json", args.public_dir, stage=stage)
        except Exception as exc:
            _handle_stage_failure(run, args.db, stage, exc, {"db": args.db, "out_dir": args.public_dir})
            raise
    else:
        _record_skipped_stage(
            run,
            args.db,
            stage,
            {"reason": stage_plan[stage]["reason"], "db": args.db, "out_dir": args.public_dir},
        )

    stage = "build_site"
    if stage_plan[stage]["run"]:
        run.stage_start(stage, {"data_dir": args.public_dir, "out_dir": args.site_out})
        try:
            build_site(args.public_dir, args.site_out, site_dir=args.site_dir)
            site_result = {"data_dir": args.public_dir, "out_dir": args.site_out, "site_dir": args.site_dir}
            run.stage_end(stage, "ok", site_result)
            _log_stage_to_db(args.db, stage, "ok", _stage_details(run, site_result))
            run.add_artifact("site_dist", args.site_out, stage=stage)
        except Exception as exc:
            _handle_stage_failure(run, args.db, stage, exc, {"data_dir": args.public_dir, "out_dir": args.site_out})
            raise
    else:
        _record_skipped_stage(
            run,
            args.db,
            stage,
            {"reason": stage_plan[stage]["reason"], "data_dir": args.public_dir, "out_dir": args.site_out},
        )

    run.report["details"]["skipped_stages"] = [stage["name"] for stage in run.report.get("stages", []) if stage.get("status") == "skipped"]
    final_status = "error" if any(stage.get("status") == "error" for stage in run.report.get("stages", [])) else "ok"
    run.finish(final_status)
    pprint(
        {
            "run_id": run.run_id,
            "report_path": str(run.report_path),
            "log_path": str(run.log_path),
            "traceback_path": str(run.traceback_path),
            "status": final_status,
            "stage_count": len(run.report.get("stages", [])),
        }
    )


def _provider_config_from_args(args: argparse.Namespace) -> dict[str, Any] | None:
    config: dict[str, Any] = {}

    if args.provider_config_file:
        payload = json.loads(Path(args.provider_config_file).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Provider config file must contain a JSON object")
        config.update({str(key): value for key, value in payload.items()})

    if args.provider_config_json:
        payload = json.loads(args.provider_config_json)
        if not isinstance(payload, dict):
            raise ValueError("Inline provider config must be a JSON object")
        config.update({str(key): value for key, value in payload.items()})

    for field, value in (
        ("model", args.provider_model),
        ("base_url", args.provider_base_url),
        ("endpoint", args.provider_endpoint),
        ("api_key", args.provider_api_key),
    ):
        if value:
            config[field] = value

    return config or None


def _requested_provider_name(args: argparse.Namespace, provider_config: dict[str, Any] | None) -> str:
    for value in (
        getattr(args, "provider", None),
        (provider_config or {}).get("provider"),
        (provider_config or {}).get("kind"),
        os.getenv("JOBVISUALIZER_ENRICH_PROVIDER"),
    ):
        if value:
            return str(value).strip().lower().replace("-", "_")
    return "heuristic"


def _add_observability_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id")
    parser.add_argument("--reports-dir")
    parser.add_argument("--logs-dir")


def _start_observed_run(args: argparse.Namespace):
    return start_run(
        "pipeline",
        run_id=getattr(args, "run_id", None) or os.getenv("JOBVISUALIZER_RUN_ID"),
        reports_dir=getattr(args, "reports_dir", None),
        logs_dir=getattr(args, "logs_dir", None),
    )


def _stage_details(run, result: Any) -> dict[str, Any]:
    details = dict(result) if isinstance(result, dict) else {"result": result}
    for key, value in _observability_details(run).items():
        if key in details and details[key] != value:
            details[f"run_{key}"] = value
        else:
            details[key] = value
    return details


def _record_source_results(run, stage: str, fetch_result: dict[str, Any]) -> None:
    if fetch_result.get("report_path"):
        run.add_artifact("source_registry_report", fetch_result["report_path"], stage=stage)
    for item in fetch_result.get("results", []):
        run.record_source(item.get("name", "unknown"), item.get("status", "unknown"), item)
        output_files = _source_output_files(item)
        for path in output_files:
            run.add_artifact(item.get("name", "source"), path, stage=stage, metadata={"status": item.get("status")})


def _source_output_files(item: dict[str, Any]) -> list[str]:
    files = []
    if item.get("out_path"):
        files.append(str(item["out_path"]))
    for path in item.get("output_files", []) or []:
        files.append(str(path))
    return list(dict.fromkeys(files))


def _registry_stage_status(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "ok").strip().lower()
    return status if status in {"ok", "error"} else "ok"


def _pipeline_stage_plan(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    from_stage = args.from_stage or PIPELINE_STAGE_ORDER[0]
    to_stage = args.to_stage or PIPELINE_STAGE_ORDER[-1]
    from_index = PIPELINE_STAGE_ORDER.index(from_stage)
    to_index = PIPELINE_STAGE_ORDER.index(to_stage)
    if from_index > to_index:
        raise ValueError("--from-stage must not be after --to-stage")

    plan: dict[str, dict[str, Any]] = {}
    for index, stage in enumerate(PIPELINE_STAGE_ORDER):
        should_run = from_index <= index <= to_index
        reason = None
        if index < from_index:
            should_run = False
            reason = f"before_from_stage:{from_stage}"
        elif index > to_index:
            should_run = False
            reason = f"after_to_stage:{to_stage}"
        plan[stage] = {"run": should_run, "reason": reason}

    if args.skip_fetch:
        plan["fetch_sources"] = {"run": False, "reason": "skip_fetch"}
    elif not args.config and plan["fetch_sources"]["run"]:
        plan["fetch_sources"] = {"run": False, "reason": "no_config"}

    if args.skip_build_site:
        plan["build_site"] = {"run": False, "reason": "skip_build_site"}

    return plan


def _requested_stage_names(args: argparse.Namespace) -> list[str]:
    from_stage = args.from_stage or PIPELINE_STAGE_ORDER[0]
    to_stage = args.to_stage or PIPELINE_STAGE_ORDER[-1]
    from_index = PIPELINE_STAGE_ORDER.index(from_stage)
    to_index = PIPELINE_STAGE_ORDER.index(to_stage)
    if from_index > to_index:
        raise ValueError("--from-stage must not be after --to-stage")
    return PIPELINE_STAGE_ORDER[from_index : to_index + 1]


def _record_skipped_stage(run, db_path: str | Path | None, stage: str, details: dict[str, Any]) -> None:
    run.stage_skip(stage, details)
    _log_stage_to_db(db_path, stage, "skipped", _stage_details(run, details))


def _observability_details(run) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "report_path": str(run.report_path),
        "log_path": str(run.log_path),
        "traceback_path": str(run.traceback_path),
    }


def _log_stage_to_db(db_path: str | Path | None, stage: str, status: str, details: dict[str, Any]) -> None:
    if not db_path:
        return
    db.init_db(db_path)
    with db.connect(db_path) as conn:
        db.log_run(
            conn,
            stage,
            status,
            details,
            _now_iso(),
            run_id=str(details.get("run_id")) if details.get("run_id") else None,
        )
        conn.commit()


def _handle_stage_failure(run, db_path: str | Path | None, stage: str, exc: BaseException, details: dict[str, Any]) -> None:
    run.fail(exc, stage=stage, details=details)
    run.stage_end(stage, "error", details)
    _log_stage_to_db(
        db_path,
        stage,
        "error",
        {
            **details,
            "run_id": run.run_id,
            "report_path": str(run.report_path),
            "log_path": str(run.log_path),
            "traceback_path": str(run.traceback_path),
            "error": str(exc),
        },
    )
    run.finish("error")


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()

if __name__ == "__main__":
    main()
