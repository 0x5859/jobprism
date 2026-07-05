#!/usr/bin/env bash
# Production site build: live job-board APIs + committed Chinese-crawl snapshots.
#
# This is what CI (.github/workflows/pages.yml) runs on every push and on the
# daily schedule. It differs from run_demo.sh in two ways:
#   1. Sources are the real public APIs in source-config.ci.json
#      (greenhouse/lever/ashby — stdlib urllib, no Playwright, no anti-bot).
#      A source that fails (API hiccup, renamed board) is recorded in the
#      source-registry report and skipped; the build continues.
#   2. Chinese company data (tencent/bytedance campus sites) cannot be crawled
#      from CI, so the pipeline imports the committed JSONL snapshots under
#      data/snapshots/. Refresh those locally with the crawler bundle:
#      see includes/company_site_crawler_bundle/README.md, then commit + push.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$(command -v python || command -v python3)}"
DB_PATH="$ROOT_DIR/data/recruit_graph.sqlite3"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
REPORTS_DIR="$ROOT_DIR/reports"
LOGS_DIR="$ROOT_DIR/logs"

rm -f "$DB_PATH"
find "$ROOT_DIR/data/raw" -mindepth 1 ! -name '.gitkeep' -exec rm -rf {} + 2>/dev/null || true
rm -f "$ROOT_DIR"/data/public/*.json || true
rm -rf "$ROOT_DIR/dist"

mkdir -p "$ROOT_DIR/data/raw" "$ROOT_DIR/data/public" "$REPORTS_DIR" "$LOGS_DIR"

"$PYTHON_BIN" -m apps.pipeline.cli run-pipeline \
  --config "$ROOT_DIR/source-config.ci.json" \
  --raw-dir "$ROOT_DIR/data/raw" \
  --import-input "$ROOT_DIR/data/snapshots" \
  --db "$DB_PATH" \
  --company-aliases "$ROOT_DIR/config/company_aliases.json" \
  --skill-taxonomy "$ROOT_DIR/config/skill_taxonomy.json" \
  --public-dir "$ROOT_DIR/data/public" \
  --site-out "$ROOT_DIR/dist" \
  --run-id "$RUN_ID" \
  --reports-dir "$REPORTS_DIR" \
  --logs-dir "$LOGS_DIR" \
  --continue-on-error

echo
echo "Production build completed."
echo "Run ID: $RUN_ID"
echo "Static site written to $ROOT_DIR/dist"
"$PYTHON_BIN" - "$ROOT_DIR/dist/data" <<'EOF'
import json, sys
from pathlib import Path
data_dir = Path(sys.argv[1])
jobs = json.loads((data_dir / "jobs.json").read_text())
companies = json.loads((data_dir / "companies.json").read_text())
print(f"Jobs: {len(jobs)} · Companies: {len(companies)}")
EOF
