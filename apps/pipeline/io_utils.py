from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Iterator

# Some job-board APIs (Ashby) reject the default Python-urllib user agent.
# Identify honestly as this project rather than spoofing a browser.
HTTP_USER_AGENT = "JobVisualizer/1.0 (public job-board aggregator)"

def fetch_json(url: str, timeout: int = 30) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": HTTP_USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))

def write_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def iter_jsonl(path: str | Path) -> Iterator[dict]:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        yield json.loads(line)

def write_jsonl(path: str | Path, records: Iterable[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

def iter_input_paths(input_path: str | Path) -> list[Path]:
    path = Path(input_path)
    if path.is_dir():
        return sorted(
            p for p in path.rglob("*")
            if p.is_file()
            and p.suffix.lower() in {".json", ".jsonl"}
            and p.name != "source-registry-report.json"
            and not p.name.endswith(".report.json")
        )
    return [path]
