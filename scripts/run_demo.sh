#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_PATH="$ROOT_DIR/data/recruit_graph.sqlite3"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
REPORTS_DIR="$ROOT_DIR/reports"
LOGS_DIR="$ROOT_DIR/logs"
TMP_CONFIG="$(mktemp "$ROOT_DIR/data/demo-sources.XXXXXX.json")"

rm -f "$DB_PATH"
find "$ROOT_DIR/data/raw" -mindepth 1 ! -name '.gitkeep' -exec rm -rf {} +
rm -f "$ROOT_DIR"/data/public/*.json || true
rm -rf "$ROOT_DIR/dist"

mkdir -p "$ROOT_DIR/data/raw" "$ROOT_DIR/data/public"
mkdir -p "$REPORTS_DIR" "$LOGS_DIR"

cat > "$TMP_CONFIG" <<EOF
{
  "sources": [
    {
      "name": "sample-jsonld-fixture",
      "type": "jsonld",
      "enabled": true,
      "config": {
        "html_file": "$ROOT_DIR/sample-data/raw_html/sample_job_posting.html"
      }
    },
    {
      "name": "sample-html-fixture",
      "type": "html",
      "enabled": true,
      "config": {
        "html_file": "$ROOT_DIR/sample-data/raw_html/sample_html_fallback.html",
        "company_name": "Fallback Labs"
      }
    }
  ]
}
EOF

python -m apps.pipeline.cli run-pipeline \
  --config "$TMP_CONFIG" \
  --raw-dir "$ROOT_DIR/data/raw" \
  --import-input "$ROOT_DIR/sample-data/input" \
  --db "$DB_PATH" \
  --company-aliases "$ROOT_DIR/config/company_aliases.json" \
  --skill-taxonomy "$ROOT_DIR/config/skill_taxonomy.json" \
  --public-dir "$ROOT_DIR/data/public" \
  --site-out "$ROOT_DIR/dist" \
  --run-id "$RUN_ID" \
  --reports-dir "$REPORTS_DIR" \
  --logs-dir "$LOGS_DIR"

rm -f "$TMP_CONFIG"

echo
echo "Demo completed."
echo "Run ID: $RUN_ID"
echo "Public outputs written to $ROOT_DIR/data/public"
echo "Static site written to $ROOT_DIR/dist"
echo "Report written to $REPORTS_DIR/$RUN_ID-run.json"
echo "Log written to $LOGS_DIR/pipeline-$RUN_ID.log"
