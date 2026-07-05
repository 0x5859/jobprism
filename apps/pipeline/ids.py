from __future__ import annotations

import hashlib
import re
import unicodedata

def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "unknown"

def short_hash(value: str, length: int = 12) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]

def company_id_from_name(name: str) -> str:
    return f"company:{slugify(name)}"

def skill_id_from_label(label: str) -> str:
    return f"skill:{slugify(label)}"

def job_id(company_id: str, external_id: str | None, fallback_payload: str) -> str:
    company_slug = company_id.split(":", 1)[1]
    stable = slugify(external_id) if external_id else short_hash(fallback_payload)
    return f"job:{company_slug}:{stable}"

def edge_id(source: str, edge_type: str, target: str) -> str:
    stable = short_hash(f"{source}|{edge_type}|{target}")
    return f"edge:{edge_type.lower()}:{stable}"
