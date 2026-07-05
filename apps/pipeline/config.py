from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "recruit_graph.sqlite3"
DEFAULT_RAW_DIR = ROOT / "data" / "raw"
DEFAULT_PUBLIC_DIR = ROOT / "data" / "public"
DEFAULT_COMPANY_ALIASES = ROOT / "config" / "company_aliases.json"
DEFAULT_SKILL_TAXONOMY = ROOT / "config" / "skill_taxonomy.json"

@dataclass(frozen=True)
class PipelinePaths:
    root: Path = ROOT
    db: Path = DEFAULT_DB
    raw_dir: Path = DEFAULT_RAW_DIR
    public_dir: Path = DEFAULT_PUBLIC_DIR
    company_aliases: Path = DEFAULT_COMPANY_ALIASES
    skill_taxonomy: Path = DEFAULT_SKILL_TAXONOMY
