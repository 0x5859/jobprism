from __future__ import annotations

import json
import logging
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS_DIR = ROOT / "reports"
DEFAULT_LOGS_DIR = ROOT / "logs"
REPORT_VERSION = "1.0"


def new_run_id(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.strftime("%Y%m%dT%H%M%SZ")


def default_report_path(run_id: str, reports_dir: str | Path | None = None) -> Path:
    base = Path(reports_dir) if reports_dir is not None else DEFAULT_REPORTS_DIR
    return base / f"{run_id}-run.json"


def default_log_path(run_name: str, run_id: str, logs_dir: str | Path | None = None) -> Path:
    base = Path(logs_dir) if logs_dir is not None else DEFAULT_LOGS_DIR
    return base / f"{run_name}-{run_id}.log"


def default_traceback_path(run_name: str, run_id: str, logs_dir: str | Path | None = None) -> Path:
    base = Path(logs_dir) if logs_dir is not None else DEFAULT_LOGS_DIR
    return base / f"{run_name}-{run_id}.traceback.txt"


@dataclass(slots=True)
class StageEvent:
    name: str
    status: str
    started_at: str
    ended_at: str | None = None
    duration_ms: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RunArtifact:
    name: str
    path: str
    stage: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RunError:
    stage: str | None
    message: str
    traceback_path: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class ObservabilityRun:
    def __init__(
        self,
        *,
        run_name: str = "pipeline",
        run_id: str | None = None,
        reports_dir: str | Path | None = None,
        logs_dir: str | Path | None = None,
    ) -> None:
        self.run_name = run_name
        self.run_id = run_id or new_run_id()
        self.reports_dir = Path(reports_dir) if reports_dir is not None else DEFAULT_REPORTS_DIR
        self.logs_dir = Path(logs_dir) if logs_dir is not None else DEFAULT_LOGS_DIR
        self.report_path = default_report_path(self.run_id, self.reports_dir)
        self.log_path = default_log_path(self.run_name, self.run_id, self.logs_dir)
        self.traceback_path = default_traceback_path(self.run_name, self.run_id, self.logs_dir)
        existing = self._load_existing_report()
        self.started_at = existing.get("started_at") if existing else _now_iso()
        self.ended_at = existing.get("ended_at") if existing else None
        self.status = existing.get("status", "running") if existing else "running"
        self.stages = [self._stage_from_dict(item) for item in existing.get("stages", [])] if existing else []
        self.artifacts = [self._artifact_from_dict(item) for item in existing.get("artifacts", [])] if existing else []
        self.sources = list(existing.get("sources", [])) if existing else []
        self.events = list(existing.get("events", [])) if existing else []
        self.errors = [self._error_from_dict(item) for item in existing.get("errors", [])] if existing else []
        self._closed = False
        self._logger = self._build_logger()
        self._report = existing or self._initial_report()
        self._report["details"] = dict(self._report.get("details", {}))
        self.status = "running"
        self.ended_at = None
        self._sync_report()
        self.add_event(
            "run_resume" if existing else "run_start",
            {"run_name": self.run_name, "report_path": str(self.report_path), "log_path": str(self.log_path)},
        )

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    def stage_start(self, name: str, details: dict[str, Any] | None = None) -> StageEvent:
        event = StageEvent(name=name, status="running", started_at=_now_iso(), details=dict(details or {}))
        self.stages.append(event)
        self.log_event("stage_start", {"stage": name, **event.details})
        self._sync_report()
        return event

    def stage_end(self, name: str, status: str = "ok", details: dict[str, Any] | None = None) -> StageEvent:
        event = self._find_or_create_stage(name)
        event.status = status
        event.ended_at = _now_iso()
        event.duration_ms = _duration_ms(event.started_at, event.ended_at)
        if details:
            event.details.update(details)
        self.log_event("stage_end", {"stage": name, "status": status, **(details or {})})
        self._sync_report()
        return event

    def stage_skip(self, name: str, details: dict[str, Any] | None = None) -> StageEvent:
        now = _now_iso()
        event = StageEvent(
            name=name,
            status="skipped",
            started_at=now,
            ended_at=now,
            duration_ms=0,
            details=dict(details or {}),
        )
        self.stages.append(event)
        self.log_event("stage_skip", {"stage": name, **event.details})
        self._sync_report()
        return event

    def record_source(self, name: str, status: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        record = {
            "name": name,
            "status": status,
            "details": dict(details or {}),
            "recorded_at": _now_iso(),
        }
        self.sources.append(record)
        self.log_event("source", record)
        self._sync_report()
        return record

    def add_artifact(self, name: str, path: str | Path, stage: str | None = None, metadata: dict[str, Any] | None = None) -> RunArtifact:
        artifact = RunArtifact(name=name, path=str(path), stage=stage, metadata=dict(metadata or {}))
        self.artifacts.append(artifact)
        self.log_event("artifact", {"name": name, "path": str(path), "stage": stage, **artifact.metadata})
        self._sync_report()
        return artifact

    def add_event(self, kind: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        event = {"kind": kind, "details": dict(details or {}), "timestamp": _now_iso()}
        self.events.append(event)
        self.log_event(kind, event["details"])
        self._sync_report()
        return event

    def fail(
        self,
        exc: BaseException,
        *,
        stage: str | None = None,
        message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> RunError:
        self.status = "error"
        self.ended_at = self.ended_at or _now_iso()
        traceback_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.traceback_path.parent.mkdir(parents=True, exist_ok=True)
        self.traceback_path.write_text(traceback_text, encoding="utf-8")
        error = RunError(
            stage=stage,
            message=message or str(exc),
            traceback_path=str(self.traceback_path),
            details=dict(details or {}),
        )
        self.errors.append(error)
        self.log_event(
            "error",
            {
                "stage": stage,
                "message": error.message,
                "traceback_path": str(self.traceback_path),
                **error.details,
            },
            level=logging.ERROR,
        )
        self._sync_report()
        return error

    def finish(self, status: str = "ok", details: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._closed:
            self.status = status
            self.ended_at = self.ended_at or _now_iso()
            if details:
                self._report["details"].update(details)
            self.add_event("run_end", {"status": self.status, **(details or {})})
            self._sync_report()
            self._closed = True
            for handler in list(self._logger.handlers):
                self._logger.removeHandler(handler)
                handler.close()
        return self.report

    @property
    def report(self) -> dict[str, Any]:
        return self._report

    @contextmanager
    def stage(self, name: str, details: dict[str, Any] | None = None) -> Iterator["ObservabilityRun"]:
        self.stage_start(name, details)
        try:
            yield self
        except BaseException as exc:
            self.fail(exc, stage=name)
            self.stage_end(name, status="error")
            raise
        else:
            self.stage_end(name, status="ok")

    def wrap(self, name: str, fn, *args, **kwargs):
        with self.stage(name):
            return fn(*args, **kwargs)

    def log_event(self, kind: str, details: dict[str, Any] | None = None, *, level: int = logging.INFO) -> None:
        payload = json.dumps(details or {}, ensure_ascii=False, sort_keys=True)
        self._logger.log(level, "%s %s", kind, payload)

    def _build_logger(self) -> logging.Logger:
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        logger = logging.getLogger(f"jobvisualizer.observability.{self.run_id}")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        handler = logging.FileHandler(self.log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        return logger

    def _initial_report(self) -> dict[str, Any]:
        return {
            "report_version": REPORT_VERSION,
            "run_id": self.run_id,
            "run_name": self.run_name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": None,
            "status": self.status,
            "report_path": str(self.report_path),
            "log_path": str(self.log_path),
            "traceback_path": str(self.traceback_path),
            "details": {},
            "stages": [],
            "sources": [],
            "artifacts": [],
            "events": [],
            "errors": [],
        }

    def _load_existing_report(self) -> dict[str, Any] | None:
        if not self.report_path.exists():
            return None
        try:
            payload = json.loads(self.report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("run_id") != self.run_id:
            return None
        return payload

    def _sync_report(self) -> None:
        self._report["report_version"] = self._report.get("report_version") or REPORT_VERSION
        self._report["ended_at"] = self.ended_at
        self._report["duration_ms"] = _duration_ms(self.started_at, self.ended_at)
        self._report["status"] = self.status
        self._report["stages"] = [self._stage_to_dict(stage) for stage in self.stages]
        self._report["sources"] = list(self.sources)
        self._report["artifacts"] = [self._artifact_to_dict(item) for item in self.artifacts]
        self._report["events"] = list(self.events)
        self._report["errors"] = [self._error_to_dict(item) for item in self.errors]
        self._flush_report()

    def _flush_report(self) -> None:
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(json.dumps(self._report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _find_or_create_stage(self, name: str) -> StageEvent:
        for stage in reversed(self.stages):
            if stage.name == name and stage.ended_at is None:
                return stage
        event = StageEvent(name=name, status="running", started_at=_now_iso())
        self.stages.append(event)
        return event

    @staticmethod
    def _stage_to_dict(stage: StageEvent) -> dict[str, Any]:
        return {
            "name": stage.name,
            "status": stage.status,
            "started_at": stage.started_at,
            "ended_at": stage.ended_at,
            "duration_ms": stage.duration_ms if stage.duration_ms is not None else _duration_ms(stage.started_at, stage.ended_at),
            "details": dict(stage.details),
        }

    @staticmethod
    def _stage_from_dict(stage: dict[str, Any]) -> StageEvent:
        return StageEvent(
            name=str(stage.get("name", "unknown")),
            status=str(stage.get("status", "unknown")),
            started_at=str(stage.get("started_at", _now_iso())),
            ended_at=stage.get("ended_at"),
            duration_ms=_coerce_int(stage.get("duration_ms"))
            if stage.get("duration_ms") is not None
            else _duration_ms(str(stage.get("started_at", _now_iso())), stage.get("ended_at")),
            details=dict(stage.get("details", {})),
        )

    @staticmethod
    def _artifact_to_dict(artifact: RunArtifact) -> dict[str, Any]:
        return {
            "name": artifact.name,
            "path": artifact.path,
            "stage": artifact.stage,
            "metadata": dict(artifact.metadata),
        }

    @staticmethod
    def _artifact_from_dict(artifact: dict[str, Any]) -> RunArtifact:
        return RunArtifact(
            name=str(artifact.get("name", "artifact")),
            path=str(artifact.get("path", "")),
            stage=artifact.get("stage"),
            metadata=dict(artifact.get("metadata", {})),
        )

    @staticmethod
    def _error_to_dict(error: RunError) -> dict[str, Any]:
        return {
            "stage": error.stage,
            "message": error.message,
            "traceback_path": error.traceback_path,
            "details": dict(error.details),
        }

    @staticmethod
    def _error_from_dict(error: dict[str, Any]) -> RunError:
        return RunError(
            stage=error.get("stage"),
            message=str(error.get("message", "")),
            traceback_path=error.get("traceback_path"),
            details=dict(error.get("details", {})),
        )


def start_run(
    run_name: str = "pipeline",
    *,
    run_id: str | None = None,
    reports_dir: str | Path | None = None,
    logs_dir: str | Path | None = None,
) -> ObservabilityRun:
    return ObservabilityRun(run_name=run_name, run_id=run_id, reports_dir=reports_dir, logs_dir=logs_dir)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_ms(started_at: str | None, ended_at: str | None) -> int | None:
    if not started_at or not ended_at:
        return None
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(ended_at)
    except ValueError:
        return None
    delta = end - start
    return max(0, int(delta.total_seconds() * 1000))


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
