from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class SkillSuggestion:
    skill_id: str
    label: str
    normalized_label: str
    aliases: list[str] = field(default_factory=list)
    parent_id: str | None = None
    category: str | None = None
    edge_type: str = "REQUIRES"
    weight: float = 1.0
    confidence: float = 0.0
    evidence: list[Any] = field(default_factory=list)
    provenance: str = "heuristic"


@dataclass(slots=True)
class EnrichmentResult:
    job_id: str
    summary: str | None = None
    role_family: str | None = None
    seniority: str | None = None
    remote_mode_inferred: str | None = None
    salary_text: str | None = None
    responsibilities: list[Any] = field(default_factory=list)
    qualifications: list[Any] = field(default_factory=list)
    evidence: list[Any] = field(default_factory=list)
    confidence: float | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    skills: list[SkillSuggestion] = field(default_factory=list)

    def to_db_payload(self, *, job_id: str | None = None) -> dict[str, Any]:
        return {
            "job_id": job_id or self.job_id,
            "summary": self.summary,
            "role_family": self.role_family,
            "seniority": self.seniority,
            "remote_mode_inferred": self.remote_mode_inferred,
            "salary_text": self.salary_text,
            "responsibilities": list(self.responsibilities),
            "qualifications": list(self.qualifications),
            "evidence": list(self.evidence),
            "confidence": self.confidence,
            "model_name": self.model_name,
            "prompt_version": self.prompt_version,
        }

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["skills"] = [asdict(skill) for skill in self.skills]
        return data

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EnrichmentResult":
        skills: list[SkillSuggestion] = []
        for item in payload.get("skills", []):
            if not isinstance(item, dict):
                continue
            skills.append(
                SkillSuggestion(
                    skill_id=str(item.get("skill_id", "")).strip(),
                    label=str(item.get("label", "")).strip(),
                    normalized_label=str(item.get("normalized_label") or item.get("label") or "").strip().lower(),
                    aliases=_string_list(item.get("aliases")),
                    parent_id=_optional_str(item.get("parent_id")),
                    category=_optional_str(item.get("category")),
                    edge_type=str(item.get("edge_type") or "REQUIRES").upper(),
                    weight=_float_or_default(item.get("weight"), 1.0),
                    confidence=_float_or_default(item.get("confidence"), 0.0),
                    evidence=_any_list(item.get("evidence")),
                    provenance=str(item.get("provenance") or "heuristic"),
                )
            )

        return cls(
            job_id=str(payload.get("job_id", "")).strip(),
            summary=_optional_str(payload.get("summary")),
            role_family=_optional_str(payload.get("role_family")),
            seniority=_optional_str(payload.get("seniority")),
            remote_mode_inferred=_optional_str(payload.get("remote_mode_inferred")),
            salary_text=_optional_str(payload.get("salary_text")),
            responsibilities=_any_list(payload.get("responsibilities")),
            qualifications=_any_list(payload.get("qualifications")),
            evidence=_any_list(payload.get("evidence")),
            confidence=_float_or_none(payload.get("confidence")),
            model_name=_optional_str(payload.get("model_name")),
            prompt_version=_optional_str(payload.get("prompt_version")),
            skills=skills,
        )


@runtime_checkable
class EnrichmentProvider(Protocol):
    name: str

    def enrich(self, job: dict[str, Any], taxonomy: list[dict[str, Any]]) -> EnrichmentResult:
        raise NotImplementedError


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _any_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [item for item in value if item is not None]


def _float_or_default(value: Any, default: float) -> float:
    number = _float_or_none(value)
    return default if number is None else number


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
