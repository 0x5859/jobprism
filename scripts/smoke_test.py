from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
result = subprocess.run(["bash", str(ROOT / "scripts" / "run_demo.sh")], cwd=ROOT, capture_output=True, text=True)
print(result.stdout)
if result.returncode != 0:
    print(result.stderr)
    raise SystemExit(result.returncode)

summary_path = ROOT / "data" / "public" / "summary.json"
summary = json.loads(summary_path.read_text(encoding="utf-8"))
counts = summary["counts"]
assert counts["companies"] >= 3
assert counts["jobs"] >= 4
assert counts["skills"] >= 5
print("Smoke test passed with counts:", counts)
