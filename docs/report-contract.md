# Run Report Contract

This document describes the JSON written by the current pipeline run reporter at `reports/<run_id>-run.json`.

## Top-Level Fields

- `report_version` string. Current value: `"1.0"`.
- `run_id` string. The run identifier used in the report filename.
- `run_name` string. Usually `"pipeline"`.
- `started_at` string. ISO-8601 UTC timestamp.
- `ended_at` string or `null`. Present after the run finishes.
- `duration_ms` integer or `null`. Milliseconds between `started_at` and `ended_at`.
- `status` string. Final run status, currently `ok`, `error`, or `running`.
- `report_path` string. Absolute path to the JSON report file.
- `log_path` string. Absolute path to the run log file.
- `traceback_path` string. Absolute path to the traceback file for failures.
- `details` object. Free-form run details.
- `stages` array. Stage records for the run.
- `sources` array. Source records collected by the source registry stage.
- `artifacts` array. Artifact records produced by stages.
- `events` array. Run events emitted during execution.
- `errors` array. Error records captured during execution.

## Optional Details

`details` may contain run-specific data. The current implementation writes:

- `resume_run_id` when a run is resumed
- `from_stage`
- `to_stage`
- `requested_stages`
- `effective_stage_plan`
- `skipped_stages`

## Stage Records

Each item in `stages` has:

- `name` string.
- `status` string. Current stage statuses are `ok`, `error`, and `skipped`. During execution a stage may temporarily be `running`.
- `started_at` string. ISO-8601 UTC timestamp.
- `ended_at` string or `null`.
- `duration_ms` integer or `null`.
- `details` object. Stage-specific details.

`skipped` is used when the pipeline intentionally does not run a stage. `error` is used when a stage fails. `ok` is used when a stage completes successfully.

`stages[]` may contain the same `name` more than once. The current pipeline records `import_raw` once per input batch, so repeated stage names are valid and expected.

## Source Records

Each item in `sources` is a source-registry summary record. The current payload is implementation-defined, but it is persisted as-is in the run report.

## Artifact Records

Each item in `artifacts` has:

- `name` string.
- `path` string.
- `stage` string or `null`.
- `metadata` object.

## Event Records

Each item in `events` has:

- `kind` string.
- `timestamp` string. ISO-8601 UTC timestamp.
- `details` object.

The current implementation emits run lifecycle events such as `run_start`, `run_resume`, `resume_from`, `pipeline_plan`, and `run_end`.

## Error Records

Each item in `errors` has:

- `stage` string or `null`.
- `message` string.
- `traceback_path` string or `null`.
- `details` object.

Failures write the traceback to `traceback_path` and add a corresponding error record to the report.
