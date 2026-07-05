from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..ids import skill_id_from_label
from .base import EnrichmentResult, SkillSuggestion

SECTION_PATTERNS = {
    # English (\b for word boundaries) OR Chinese (no word boundary needed for CJK).
    "preferred": re.compile(
        r"\b(preferred|nice to have|bonus|plus)\b"
        r"|(加分项|优先考虑|优先|更佳|有加分|附加要求|有以下经验者优先)",
        re.IGNORECASE,
    ),
    "required": re.compile(
        r"\b(required|must have|minimum qualifications|you have|basic qualifications)\b"
        r"|(任职资格|任职要求|岗位要求|岗位描述|应聘要求|招聘要求|工作要求|具备能力|基本要求|必备技能|必备条件|要求|资格要求)",
        re.IGNORECASE,
    ),
    "responsibilities": re.compile(
        r"\b(responsibilities|what you.ll do|what you will do|in this role)\b"
        r"|(岗位职责|工作职责|职位职责|工作内容|岗位内容|主要职责|职责描述|你将负责|工作描述)",
        re.IGNORECASE,
    ),
    "qualifications": re.compile(
        r"\b(qualifications|requirements|what you bring)\b"
        r"|(任职资格|任职要求|岗位要求|职位要求|资格要求|应聘要求|招聘要求|工作要求|要求)",
        re.IGNORECASE,
    ),
}

ROLE_FAMILY_PATTERNS = [
    ("hardware", re.compile(
        r"\b(fpga|rtl|verilog|systemverilog|asic|timing|silicon)\b"
        r"|(嵌入式|硬件工程师|芯片|集成电路|射频|模拟电路|数字电路)",
        re.IGNORECASE,
    )),
    ("photonics", re.compile(
        r"\b(photonics|optical|pic|silicon photonics)\b"
        r"|(光子|光电|光通信|硅光)",
        re.IGNORECASE,
    )),
    ("machine-learning", re.compile(
        r"\b(machine learning|deep learning|llm|model)\b"
        r"|(机器学习|深度学习|大模型|大语言模型|算法工程师|算法研究员|nlp|自然语言|计算机视觉|多模态|推荐系统|搜索算法|强化学习)",
        re.IGNORECASE,
    )),
    ("data", re.compile(
        r"\b(sql|analytics|warehouse|etl|data engineer)\b"
        r"|(数据工程|数据分析|数据开发|数据仓库|数据科学|数据挖掘|大数据|商业分析|bi)",
        re.IGNORECASE,
    )),
    ("software", re.compile(
        r"\b(python|c\+\+|java|backend|frontend|full stack)\b"
        r"|(后端|后台|服务端|前端|全栈|web开发|微服务|分布式|高并发|移动端|客户端|android|ios|游戏开发|测试开发|qa|devops|运维|安全|sre)",
        re.IGNORECASE,
    )),
]

SENIORITY_PATTERNS = [
    ("intern", re.compile(
        r"\bintern(ship)?\b"
        r"|(实习生|实习)",
        re.IGNORECASE,
    )),
    ("entry", re.compile(
        r"\b(junior|entry[ -]level)\b"
        r"|(应届|校招|校园招聘|初级|入门)",
        re.IGNORECASE,
    )),
    ("staff", re.compile(r"\bstaff\b", re.IGNORECASE)),
    ("principal", re.compile(
        r"\bprincipal\b"
        r"|(首席|主任工程师)",
        re.IGNORECASE,
    )),
    ("senior", re.compile(
        r"\bsenior\b"
        r"|(高级|资深|专家|架构师)",
        re.IGNORECASE,
    )),
    ("lead", re.compile(
        r"\blead\b"
        r"|(主管|组长|技术负责人|leader)",
        re.IGNORECASE,
    )),
    ("manager", re.compile(
        r"\bmanager\b"
        r"|(经理|主管|总监)",
        re.IGNORECASE,
    )),
]

# Used by `_contains_term` to choose the right boundary strategy.
_CJK_RE = re.compile(r"[一-鿿]")

SALARY_RE = re.compile(
    r"(?P<salary>(?:\$|USD\s*)?\d{2,3}(?:[,\d]{0,6})\s*(?:-|to)\s*(?:\$|USD\s*)?\d{2,3}(?:[,\d]{0,6}))",
    re.IGNORECASE,
)


class HeuristicEnrichmentProvider:
    name = "heuristic"
    cache_key = "heuristic"
    request_timeout = None

    def __init__(self, taxonomy: list[dict[str, Any]] | None = None) -> None:
        self.taxonomy = list(taxonomy or [])

    def enrich(self, job: dict[str, Any], taxonomy: list[dict[str, Any]] | None = None) -> EnrichmentResult:
        effective_taxonomy = taxonomy if taxonomy is not None else self.taxonomy
        description = job.get("description_text") or ""
        title = job.get("title") or ""
        role_family = _infer_role_family(title, description)
        seniority = _infer_seniority(title, description)
        salary_text = _extract_salary(description)
        responsibilities = _extract_bullets(description, "responsibilities")
        qualifications = _extract_bullets(description, "qualifications")
        summary = _extract_summary(description)

        skills = _match_skills(description, effective_taxonomy)
        evidence = _merge_evidence([skill.evidence for skill in skills])

        return EnrichmentResult(
            job_id=job["id"],
            summary=summary,
            role_family=role_family,
            seniority=seniority,
            remote_mode_inferred=job.get("remote_mode"),
            salary_text=salary_text,
            responsibilities=responsibilities,
            qualifications=qualifications,
            evidence=evidence[:20],
            confidence=0.55 if skills else 0.35,
            model_name=self.name,
            prompt_version="n/a",
            skills=skills,
        )


def load_taxonomy(path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = []
    for normalized_label, meta in payload.items():
        items.append(
            {
                "normalized_label": normalized_label,
                "skill_id": meta.get("id") or skill_id_from_label(normalized_label),
                "label": meta.get("label") or normalized_label.title(),
                "aliases": meta.get("aliases", []),
                "parent_id": meta.get("parent_id"),
                "category": meta.get("category"),
            }
        )
    return items


def _match_skills(description: str, taxonomy: list[dict[str, Any]]) -> list[SkillSuggestion]:
    sentences = _split_sentences(description)
    normalized_description = description.lower()
    matches: list[SkillSuggestion] = []
    seen: set[tuple[str, str]] = set()

    for skill in taxonomy:
        labels = [skill["normalized_label"], *skill.get("aliases", [])]
        evidence_sentences = [
            sentence.strip()
            for sentence in sentences
            if any(_contains_term(sentence.lower(), label.lower()) for label in labels)
        ]
        if not evidence_sentences:
            continue

        joined_evidence = " ".join(evidence_sentences)
        edge_type = "REQUIRES"
        confidence = 0.7
        if SECTION_PATTERNS["preferred"].search(joined_evidence):
            edge_type = "PREFERS"
            confidence = 0.6
        elif SECTION_PATTERNS["required"].search(joined_evidence) or _contains_term(normalized_description, skill["normalized_label"]):
            edge_type = "REQUIRES"
            confidence = 0.75

        key = (skill["skill_id"], edge_type)
        if key in seen:
            continue
        seen.add(key)
        matches.append(
            SkillSuggestion(
                skill_id=skill["skill_id"],
                label=skill["label"],
                normalized_label=skill["normalized_label"],
                aliases=list(skill.get("aliases", [])),
                parent_id=skill.get("parent_id"),
                category=skill.get("category"),
                edge_type=edge_type,
                weight=1.0 if edge_type == "REQUIRES" else 0.6,
                confidence=confidence,
                evidence=evidence_sentences[:5],
                provenance="heuristic+taxonomy",
            )
        )
    return matches


def _contains_term(text: str, term: str) -> bool:
    if not term:
        return False
    term_lower = term.lower()
    # CJK terms have no word boundaries — substring match is correct (and required)
    # because Chinese text isn't tokenized with whitespace.
    if _CJK_RE.search(term_lower):
        return term_lower in text.lower()
    pattern = r"\b" + re.escape(term_lower) + r"\b"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _split_sentences(description: str) -> list[str]:
    # Split on English (.!?) and Chinese (。！？；) terminators, with or without
    # following whitespace. Chinese punctuation lookahead does not require \s.
    parts = re.split(r"(?<=[\.\!\?])\s+|(?<=[。！？；])", description)
    return [part for part in parts if part]


def _infer_role_family(title: str, description: str) -> str | None:
    corpus = f"{title} {description}"
    for family, pattern in ROLE_FAMILY_PATTERNS:
        if pattern.search(corpus):
            return family
    return None


def _infer_seniority(title: str, description: str) -> str | None:
    corpus = f"{title} {description}"
    for level, pattern in SENIORITY_PATTERNS:
        if pattern.search(corpus):
            return level
    return None


def _extract_salary(description: str) -> str | None:
    match = SALARY_RE.search(description)
    if not match:
        return None
    return match.group("salary")


def _extract_summary(description: str, max_sentences: int = 2) -> str:
    sentences = [sentence.strip() for sentence in _split_sentences(description) if sentence.strip()]
    return " ".join(sentences[:max_sentences])


def _extract_bullets(description: str, section: str) -> list[str]:
    tokens = _split_sentences(description)
    if SECTION_PATTERNS[section].search(description):
        anchor_idx = None
        for idx, sentence in enumerate(tokens):
            if SECTION_PATTERNS[section].search(sentence):
                anchor_idx = idx
                break
        if anchor_idx is not None:
            return [token.strip(" -•·、") for token in tokens[anchor_idx + 1 : anchor_idx + 5] if token.strip()]
    return [token.strip(" -•·、") for token in tokens[:3] if token.strip()]


def _merge_evidence(groups: list[list[str]]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item not in merged:
                merged.append(item)
    return merged
