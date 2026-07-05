from __future__ import annotations

import argparse
import shutil
from pathlib import Path

def build_site(data_dir: str | Path, out_dir: str | Path, site_dir: str | Path | None = None) -> None:
    data_dir = Path(data_dir)
    out_dir = Path(out_dir)
    site_dir = Path(site_dir) if site_dir else Path(__file__).resolve().parent / "site"

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    shutil.copytree(site_dir, out_dir, dirs_exist_ok=True)
    target_data = out_dir / "data"
    target_data.mkdir(parents=True, exist_ok=True)

    for path in data_dir.glob("*.json"):
        shutil.copy2(path, target_data / path.name)

def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static demo site")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--site-dir")
    args = parser.parse_args()
    build_site(args.data_dir, args.out, site_dir=args.site_dir)

if __name__ == "__main__":
    main()
