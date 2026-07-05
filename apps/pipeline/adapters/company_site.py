from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .base import RawJob
from ..io_utils import iter_jsonl

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BUNDLE_SCRIPT = ROOT / "includes" / "company_site_crawler_bundle" / "company_site_crawler.py"


def crawl_company_site_source(
    *,
    source: str,
    output_path: str | Path,
    report_path: str | Path | None = None,
    script_path: str | Path | None = None,
    python_bin: str | Path | None = None,
    list_url: str | None = None,
    max_jobs: int | None = None,
    timeout_ms: int = 45_000,
    delay_seconds: float = 1.0,
    headful: bool = False,
    log_level: str = "INFO",
) -> tuple[list[RawJob], str | None]:
    script = _resolve_script_path(script_path)
    python = _resolve_python_bin(script, python_bin)
    output_path = Path(output_path)
    report_path_obj = Path(report_path) if report_path else None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path_obj:
        report_path_obj.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(python),
        str(script),
        "--source",
        str(source),
        "--output",
        str(output_path),
        "--timeout-ms",
        str(int(timeout_ms)),
        "--delay-seconds",
        str(float(delay_seconds)),
        "--log-level",
        str(log_level),
    ]
    if report_path_obj:
        cmd.extend(["--report", str(report_path_obj)])
    if list_url:
        cmd.extend(["--list-url", str(list_url)])
    if max_jobs is not None:
        cmd.extend(["--max-jobs", str(int(max_jobs))])
    if headful:
        cmd.append("--headful")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part).strip()
        raise RuntimeError(f"company_site crawler failed: {detail or 'unknown error'}")

    records = [RawJob(**payload) for payload in iter_jsonl(output_path)]
    resolved_report = str(report_path_obj) if report_path_obj and report_path_obj.exists() else None
    return records, resolved_report


def _resolve_script_path(script_path: str | Path | None) -> Path:
    path = Path(script_path) if script_path else DEFAULT_BUNDLE_SCRIPT
    if not path.exists():
        raise FileNotFoundError(f"company_site crawler script not found: {path}")
    return path


def _resolve_python_bin(script_path: Path, python_bin: str | Path | None) -> Path:
    if python_bin:
        path = Path(python_bin)
        if not path.exists():
            raise FileNotFoundError(f"company_site crawler python not found: {path}")
        return path

    sibling_venv = script_path.parent / ".venv" / "bin" / "python"
    if sibling_venv.exists():
        return sibling_venv
    return Path(sys.executable)
