from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from typing import Any

from .base import EnrichmentResult, SkillSuggestion
from .json_utils import coerce_any_list, coerce_json_object, coerce_string_list


class OpenAICompatibleEnrichmentProvider:
    name = "openai-compatible"

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        base_url: str,
        endpoint: str,
        request_timeout: float = 60.0,
        strict_json: bool = True,
        max_retries: int = 2,
        retry_backoff_seconds: float = 1.0,
        retry_max_backoff_seconds: float = 8.0,
        retry_status_codes: list[int] | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        self.request_timeout = request_timeout
        self.timeout = request_timeout
        self.strict_json = strict_json
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.retry_max_backoff_seconds = max(self.retry_backoff_seconds, float(retry_max_backoff_seconds))
        self.retry_status_codes = retry_status_codes or [429, 500, 502, 503, 504]

    def cache_key(self) -> str:
        return "|".join(
            [
                self.name,
                self.model,
                self.base_url,
                self.endpoint,
                str(self.request_timeout),
                str(self.strict_json),
                str(self.max_retries),
                str(self.retry_backoff_seconds),
                str(self.retry_max_backoff_seconds),
                ",".join(str(code) for code in self.retry_status_codes),
            ]
        )

    def enrich(self, job: dict[str, Any], taxonomy: list[dict[str, Any]]) -> EnrichmentResult:
        if not self.api_key:
            raise ValueError("OpenAI-compatible enrichment requires an API key")

        request_body = self._build_request(job, taxonomy)
        response_payload = self._request_json(request_body)
        content = self._extract_content(response_payload)
        data = coerce_json_object(content)
        return self._normalize_result(job, data)

    def _request_json(self, request_body: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{self.endpoint}",
            data=payload,
            method="POST",
            headers=self._headers(),
        )

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.request_timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:  # pragma: no cover - depends on remote API
                body = exc.read().decode("utf-8", errors="replace")
                last_error = RuntimeError(f"OpenAI-compatible provider error: {exc.code} {exc.reason}: {body}")
                if not self._should_retry_http_status(exc.code) or attempt >= self.max_retries:
                    raise last_error from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
                last_error = RuntimeError(f"OpenAI-compatible provider request failed: {exc}")
                if attempt >= self.max_retries:
                    raise last_error from exc

            self._sleep_backoff(attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI-compatible provider request failed")

    def _build_request(self, job: dict[str, Any], taxonomy: list[dict[str, Any]]) -> dict[str, Any]:
        prompt = self._prompt(job, taxonomy)
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "Return only valid JSON matching the requested schema. Do not include markdown or commentary.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
        }
        if self.strict_json:
            body["response_format"] = {"type": "json_object"}
        return body

    def _prompt(self, job: dict[str, Any], taxonomy: list[dict[str, Any]]) -> str:
        compact_taxonomy = [
            {
                "id": item["skill_id"],
                "label": item["label"],
                "aliases": item.get("aliases", [])[:5],
                "parent_id": item.get("parent_id"),
                "category": item.get("category"),
            }
            for item in taxonomy[:250]
        ]
        return json.dumps(
            {
                "task": "Extract structured enrichment data for a job posting.",
                "job": {
                    "id": job["id"],
                    "title": job.get("title"),
                    "company_name": job.get("company_name"),
                    "location_text": job.get("location_text"),
                    "description_text": job.get("description_text"),
                    "source_url": job.get("source_url"),
                    "remote_mode": job.get("remote_mode"),
                    "employment_type": job.get("employment_type"),
                    "description_hash": job.get("description_hash"),
                },
                "taxonomy": compact_taxonomy,
                "required_output_shape": {
                    "summary": "string or null",
                    "role_family": "string or null",
                    "seniority": "string or null",
                    "remote_mode_inferred": "string or null",
                    "salary_text": "string or null",
                    "responsibilities": ["string"],
                    "qualifications": ["string"],
                    "evidence": ["string|object"],
                    "confidence": "number between 0 and 1",
                    "skills": [
                        {
                            "skill_id": "string",
                            "label": "string",
                            "normalized_label": "string",
                            "aliases": ["string"],
                            "parent_id": "string or null",
                            "category": "string or null",
                            "edge_type": "REQUIRES or PREFERS",
                            "weight": "number",
                            "confidence": "number between 0 and 1",
                            "evidence": ["string|object"],
                            "provenance": "string",
                        }
                    ],
                },
                "rules": [
                    "Only use skills from the provided taxonomy when possible.",
                    "Prefer concise evidence snippets copied from the job description.",
                    "Preserve evidence quotes or spans when available.",
                    "Return JSON only.",
                ],
            },
            ensure_ascii=False,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _extract_content(self, payload: dict[str, Any]) -> Any:
        if "choices" in payload and payload["choices"]:
            message = payload["choices"][0].get("message", {})
            content = message.get("content")
            if isinstance(content, list):
                pieces: list[str] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") in {"output_text", "text"}:
                        text = item.get("text")
                        if text:
                            pieces.append(str(text))
                if pieces:
                    return "".join(pieces)
            return content
        if "output_text" in payload:
            return payload["output_text"]
        if "output" in payload:
            return self._extract_from_output(payload["output"])
        raise ValueError("Unsupported response shape from OpenAI-compatible provider")

    def _extract_from_output(self, output: list[dict[str, Any]]) -> Any:
        chunks: list[str] = []
        for item in output:
            for content in item.get("content", []):
                if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                    text = content.get("text")
                    if text:
                        chunks.append(str(text))
        if chunks:
            return "".join(chunks)
        raise ValueError("Could not extract text from provider response")

    def _normalize_result(self, job: dict[str, Any], data: dict[str, Any]) -> EnrichmentResult:
        skills = []
        for item in data.get("skills", []):
            if not isinstance(item, dict):
                continue
            skills.append(
                SkillSuggestion(
                    skill_id=str(item.get("skill_id", "")).strip(),
                    label=str(item.get("label", "")).strip(),
                    normalized_label=str(item.get("normalized_label") or item.get("label") or "").strip().lower(),
                    aliases=coerce_string_list(item.get("aliases")),
                    parent_id=_as_optional_str(item.get("parent_id")),
                    category=_as_optional_str(item.get("category")),
                    edge_type=str(item.get("edge_type") or "REQUIRES").upper(),
                    weight=_float_or_default(item.get("weight"), 1.0),
                    confidence=_clamp_confidence(item.get("confidence")),
                    evidence=coerce_any_list(item.get("evidence") or item.get("evidence_quotes") or item.get("source_spans")),
                    provenance=str(item.get("provenance") or self.name),
                )
            )

        evidence = coerce_any_list(
            data.get("evidence")
            or data.get("evidence_quotes")
            or data.get("source_spans")
        )

        return EnrichmentResult(
            job_id=job["id"],
            summary=_as_optional_str(data.get("summary")),
            role_family=_as_optional_str(data.get("role_family")),
            seniority=_as_optional_str(data.get("seniority")),
            remote_mode_inferred=_as_optional_str(data.get("remote_mode_inferred")),
            salary_text=_as_optional_str(data.get("salary_text")),
            responsibilities=coerce_any_list(data.get("responsibilities")),
            qualifications=coerce_any_list(data.get("qualifications")),
            evidence=evidence,
            confidence=_clamp_confidence(data.get("confidence")),
            model_name=self.model,
            prompt_version="openai-compatible-v2",
            skills=skills,
        )

    def _should_retry_http_status(self, status_code: int) -> bool:
        return status_code in self.retry_status_codes

    def _sleep_backoff(self, attempt: int) -> None:
        delay = min(self.retry_max_backoff_seconds, self.retry_backoff_seconds * (2**attempt))
        delay += random.uniform(0, min(0.2, delay * 0.25))
        time.sleep(delay)


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clamp_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return 0.0
    if number > 1:
        return 1.0
    return number


def _float_or_default(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
