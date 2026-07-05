from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

@dataclass
class RawJob:
    source_type: str
    source_url: str
    title: str
    company_name: str
    fetched_at: str
    external_job_id: str | None = None
    location_text: str | None = None
    employment_type: str | None = None
    posted_at: str | None = None
    description_text: str | None = None
    description_html: str | None = None
    json_payload: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def now_iso(cls) -> str:
        return datetime.now(timezone.utc).isoformat()
