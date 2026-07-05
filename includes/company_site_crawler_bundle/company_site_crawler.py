#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import re
import sys
import time
import traceback
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from bs4 import BeautifulSoup
from playwright.sync_api import Browser, BrowserContext, Page, Response, TimeoutError as PlaywrightTimeoutError, sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 "
    "CompanySiteCrawler/1.0"
)
CRAWLER_VERSION = "1.0.0"
DEFAULT_TIMEOUT_MS = 45_000
DEFAULT_DELAY_SECONDS = 1.0

TRACKING_QUERY_KEYS = {
    "external_referral_code",
    "referral_code",
    "recomid",
    "sourcejobid",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_content",
    "utm_term",
    "spread",
    "activity",
    "activitylink",
    "from",
}

NAV_TEXT_BLACKLIST = {
    "首页",
    "校园招聘",
    "社招官网",
    "全球招聘",
    "了解腾讯",
    "求职攻略",
    "招聘动态",
    "Apply",
    "Search now",
    "Jobs",
    "登录",
    "退出登录",
    "我的简历",
    "应聘进度",
    "账号绑定",
    "首页青云计划岗位投递招聘动态了解腾讯求职攻略",
}

KNOWN_EMPLOYMENT_TOKENS = {
    "实习",
    "应届实习",
    "日常实习",
    "校招",
    "校园招聘",
    "Graduate",
    "Intern",
    "Internship",
    "Regular",
    "Full Time",
    "Part Time",
    "Contract",
}

SECTION_HEADINGS = [
    "职位描述",
    "职位要求",
    "岗位描述",
    "岗位要求",
    "团队介绍",
    "加分项或注意事项",
    "加分项",
    "参加面试的城市",
    "招聘部门和工作地",
    "Job Description",
    "Responsibilities",
    "Qualifications",
    "Preferred Qualifications",
]

SECTION_END_MARKERS = [
    "相关职位",
    "推荐职位",
    "更多职位",
    "你可能还喜欢",
    "岗位已下架",
    "职位已下架",
    "立即投递",
    "关注腾讯招聘",
    "Apply",
    "Search now",
]

TITLE_KEYS = (
    "title",
    "name",
    "jobTitle",
    "positionTitle",
    "positionName",
    "jobName",
    "postName",
    "recruitPostName",
    "岗位名称",
    "职位名称",
)
ID_KEYS = (
    "id",
    "jobId",
    "positionId",
    "postId",
    "postid",
    "recruitPostId",
    "requisitionId",
)
URL_KEYS = (
    "url",
    "detailUrl",
    "detailURL",
    "positionUrl",
    "positionURL",
    "postUrl",
    "postURL",
    "link",
    "href",
)
LOCATION_KEYS = (
    "location",
    "locationName",
    "locationNames",
    "city",
    "cityName",
    "cityList",
    "workLocation",
    "workAddress",
    "工作地点",
    "工作地",
)
EMPLOYMENT_KEYS = (
    "employmentType",
    "jobType",
    "recruitType",
    "type",
    "positionType",
    "招募类型",
)
POSTED_KEYS = (
    "postedAt",
    "publishTime",
    "publishedAt",
    "发布日期",
    "发布时间",
    "createTime",
    "createdAt",
)
DESCRIPTION_TEXT_KEYS = (
    "description",
    "descriptionText",
    "jobDescription",
    "jobDesc",
    "岗位描述",
    "职位描述",
    "responsibilities",
    "requirement",
    "requirements",
    "qualifications",
    "content",
)
DESCRIPTION_HTML_KEYS = (
    "descriptionHtml",
    "descriptionHTML",
    "jobDescriptionHtml",
    "jobDescHtml",
    "contentHtml",
    "richText",
    "html",
)
TEAM_KEYS = (
    "team",
    "teamName",
    "业务线",
    "团队",
)
DEPARTMENT_KEYS = (
    "department",
    "departmentName",
    "bg",
    "bgName",
    "部门",
)

logger = logging.getLogger("company_site_crawler")


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
    json_payload: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        required = {
            "source_type": self.source_type,
            "source_url": self.source_url,
            "title": self.title,
            "company_name": self.company_name,
            "fetched_at": self.fetched_at,
        }
        missing = [name for name, value in required.items() if value in (None, "")]
        if missing:
            raise ValueError(f"RawJob 缺少必填字段: {', '.join(missing)}")
        if self.source_type != "company_site":
            raise ValueError("source_type 必须固定为 company_site")
        if not is_absolute_http_url(self.source_url):
            raise ValueError(f"source_url 不是合法的 http(s) URL: {self.source_url}")
        if self.posted_at and not looks_like_date(self.posted_at):
            raise ValueError(f"posted_at 不是规范日期字符串: {self.posted_at}")
        if not looks_like_datetime(self.fetched_at):
            raise ValueError(f"fetched_at 不是 ISO 时间戳: {self.fetched_at}")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata 必须是对象")

    def to_json(self) -> str:
        self.validate()
        return json.dumps(dataclasses.asdict(self), ensure_ascii=False, separators=(",", ":"))


@dataclass
class CrawlFailure:
    url: str
    stage: str
    reason: str
    detail: str | None = None


@dataclass
class CrawlReport:
    crawler_name: str
    crawler_version: str
    source_key: str
    list_url: str
    started_at: str
    finished_at: str | None = None
    pages_visited: list[str] = field(default_factory=list)
    jobs_emitted: int = 0
    jobs_skipped: int = 0
    extraction_failures: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    robots_checked: list[dict[str, Any]] = field(default_factory=list)
    max_jobs: int | None = None

    def add_failure(self, failure: CrawlFailure) -> None:
        self.extraction_failures.append(dataclasses.asdict(failure))

    def finish(self) -> None:
        self.finished_at = utc_now_iso()


@dataclass
class JobStub:
    detail_url: str
    title_hint: str | None = None
    location_hint: str | None = None
    employment_type_hint: str | None = None
    posted_at_hint: str | None = None
    external_job_id_hint: str | None = None
    department_hint: str | None = None
    team_hint: str | None = None
    raw_listing_payload: Any | None = None
    card_text: str | None = None


@dataclass(frozen=True)
class SourceConfig:
    key: str
    company_name: str
    company_slug: str
    list_url: str
    host: str
    detail_url_checker: Callable[[str], bool]
    canonicalize_detail_url: Callable[[str], str]
    build_stub_from_json_item: Callable[[Mapping[str, Any]], JobStub | None]
    parse_listing_card_hints: Callable[[str, str], dict[str, str | None]]
    detail_wait_keywords: tuple[str, ...]
    source_page_type: str = "career_site_job_detail"
    list_page_type: str = "career_site_job_list"
    title_regex: re.Pattern[str] | None = None
    req_id_regex: re.Pattern[str] | None = None
    location_label_patterns: tuple[re.Pattern[str], ...] = ()
    employment_label_patterns: tuple[re.Pattern[str], ...] = ()
    posted_at_patterns: tuple[re.Pattern[str], ...] = ()


class RobotsGuard:
    def __init__(self, user_agent: str = USER_AGENT) -> None:
        self.user_agent = user_agent
        self._cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    def can_fetch(self, url: str) -> tuple[bool, str]:
        parsed = urllib.parse.urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        parser = self._cache.get(robots_url)
        if parser is None:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(robots_url)
            try:
                parser.read()
            except Exception as exc:  # pragma: no cover - depends on runtime network
                raise RuntimeError(f"无法读取 robots.txt: {robots_url}: {exc}") from exc
            self._cache[robots_url] = parser
        return parser.can_fetch(self.user_agent, url), robots_url


class ResponseCollector:
    def __init__(self, page: Page, allowed_host: str):
        self.page = page
        self.allowed_host = allowed_host
        self.payloads: list[dict[str, Any]] = []
        self._listener = self._on_response
        self.page.on("response", self._listener)

    def close(self) -> None:
        try:
            self.page.remove_listener("response", self._listener)
        except Exception:
            pass

    def _on_response(self, response: Response) -> None:
        try:
            req = response.request
            resource_type = req.resource_type
            if resource_type not in {"xhr", "fetch"}:
                return
            parsed = urllib.parse.urlparse(response.url)
            if parsed.netloc != self.allowed_host:
                return
            headers = {k.lower(): v for k, v in response.headers.items()}
            content_type = headers.get("content-type", "")
            if "json" not in content_type.lower():
                return
            data = response.json()
            self.payloads.append({
                "url": response.url,
                "status": response.status,
                "data": data,
            })
        except Exception:
            return


def normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(key).strip().lower())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def looks_like_datetime(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def looks_like_date(value: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?", value.strip()))


def is_absolute_http_url(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def clean_whitespace(text: str | None) -> str | None:
    if text is None:
        return None
    text = text.replace("\xa0", " ").replace("\u200b", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    cleaned_lines: list[str] = []
    prev_blank = False
    for line in lines:
        if not line:
            if not prev_blank:
                cleaned_lines.append("")
            prev_blank = True
            continue
        cleaned_lines.append(line)
        prev_blank = False
    result = "\n".join(cleaned_lines).strip()
    return result or None


def html_to_text(html: str | None) -> str | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    return clean_whitespace(soup.get_text("\n"))


def sanitize_html(html: str | None) -> str | None:
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    content = str(soup)
    return content if content.strip() else None


def unique_preserve_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def first_non_empty(*values: Any) -> Any | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        return value
    return None


def deep_iter_dicts(obj: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(obj, Mapping):
        yield obj
        for value in obj.values():
            yield from deep_iter_dicts(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from deep_iter_dicts(item)


def deep_iter_lists(obj: Any) -> Iterator[list[Any]]:
    if isinstance(obj, list):
        yield obj
        for item in obj:
            yield from deep_iter_lists(item)
    elif isinstance(obj, Mapping):
        for value in obj.values():
            yield from deep_iter_lists(value)


def extract_value_from_mapping(mapping: Mapping[str, Any], keys: Sequence[str]) -> Any | None:
    normalized_lookup = {normalize_key(k): v for k, v in mapping.items()}
    for key in keys:
        value = normalized_lookup.get(normalize_key(key))
        if value not in (None, ""):
            return value
    return None


def extract_value_recursive(obj: Any, keys: Sequence[str]) -> Any | None:
    for mapping in deep_iter_dicts(obj):
        value = extract_value_from_mapping(mapping, keys)
        if value not in (None, ""):
            return value
    return None


def stringify_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return clean_whitespace(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = [stringify_value(item) for item in value]
        parts = [part for part in parts if part]
        return " / ".join(parts) if parts else None
    if isinstance(value, Mapping):
        parts = []
        for candidate_key in ("name", "title", "label", "value", "text", "city", "location"):
            part = extract_value_from_mapping(value, (candidate_key,))
            if part not in (None, ""):
                parts.append(str(part))
        if parts:
            return " / ".join(parts)
    return clean_whitespace(str(value))


def stringify_html_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, list):
        parts = [stringify_html_value(item) for item in value]
        parts = [part for part in parts if part]
        return "\n".join(parts) if parts else None
    return str(value)


def normalize_date_string(raw: str | None) -> str | None:
    raw = clean_whitespace(raw)
    if not raw:
        return None
    raw = raw.replace("/", "-").replace(".", "-")
    raw = raw.replace("年", "-").replace("月", "-").replace("日", "")
    raw = raw.replace("T", " ")
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ ](\d{1,2}:\d{2}(?::\d{2})?))?", raw)
    if not match:
        return None
    year, month, day, time_part = match.groups()
    date_part = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return f"{date_part} {time_part}" if time_part else date_part


def strip_tracking_params(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    query_items = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    kept = [
        (k, v)
        for k, v in query_items
        if normalize_key(k) not in {normalize_key(x) for x in TRACKING_QUERY_KEYS}
    ]
    query = urllib.parse.urlencode(kept, doseq=True)
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, ""))


def canonicalize_bytedance_detail_url(url: str) -> str:
    url = strip_tracking_params(url)
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    host = "jobs.bytedance.com"
    m = re.search(r"/campus/position/(\d+)/detail", path)
    if m:
        path = f"/campus/position/{m.group(1)}/detail"
    else:
        m = re.search(r"/campus/position/detail/(\d+)", path)
        if m:
            path = f"/campus/position/detail/{m.group(1)}"
    return urllib.parse.urlunparse((parsed.scheme or "https", host, path, "", parsed.query, ""))


def canonicalize_tencent_detail_url(url: str) -> str:
    url = strip_tracking_params(url)
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    host = "join.qq.com"
    path = "/post_detail.html"
    if "postid" in {k.lower() for k in query.keys()}:
        postid = None
        for key, value in query.items():
            if key.lower() == "postid" and value:
                postid = value[0]
                break
        new_query = urllib.parse.urlencode({"postid": postid}) if postid else ""
        return urllib.parse.urlunparse((parsed.scheme or "https", host, path, "", new_query, ""))
    kept: dict[str, str] = {}
    for key in ("id", "pid", "tid"):
        values = query.get(key)
        if values:
            kept[key] = values[0]
    new_query = urllib.parse.urlencode(kept)
    return urllib.parse.urlunparse((parsed.scheme or "https", host, path, "", new_query, ""))


def is_bytedance_detail_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc not in {"jobs.bytedance.com", "www.jobs.bytedance.com"}:
        return False
    return bool(
        re.search(r"/campus/position/(\d+)/detail", parsed.path)
        or re.search(r"/campus/position/detail/(\d+)", parsed.path)
    )


def is_tencent_detail_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc not in {"join.qq.com", "www.join.qq.com"}:
        return False
    if parsed.path not in {"/post_detail.html", "/m/post_detail.html"}:
        return False
    query = urllib.parse.parse_qs(parsed.query)
    return bool(query.get("id") or query.get("postid") or query.get("postId"))


def extract_url_job_id(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.endswith("bytedance.com"):
        match = re.search(r"/position/(\d+)/detail", parsed.path)
        if match:
            return match.group(1)
    if parsed.netloc.endswith("qq.com"):
        query = urllib.parse.parse_qs(parsed.query)
        for key in ("postid", "postId", "id"):
            values = query.get(key)
            if values:
                return values[0]
    return None


def probable_job_title(text: str | None) -> bool:
    text = clean_whitespace(text)
    if not text:
        return False
    if text in NAV_TEXT_BLACKLIST:
        return False
    if len(text) < 2 or len(text) > 120:
        return False
    if re.fullmatch(r"[\W_]+", text):
        return False
    if re.search(r"^(登录|注册|首页|招聘动态|相关职位|更多职位|校园招聘|求职攻略)$", text):
        return False
    return True


def parse_body_sections(body_text: str) -> dict[str, str]:
    body_text = clean_whitespace(body_text) or ""
    if not body_text:
        return {}
    heading_pattern = "|".join(map(re.escape, SECTION_HEADINGS + SECTION_END_MARKERS))
    pattern = re.compile(
        rf"(?P<heading>{heading_pattern})\s*[:：]?\s*(?P<body>.*?)(?=(?:{heading_pattern})\s*[:：]?|$)",
        re.S,
    )
    sections: dict[str, str] = {}
    for match in pattern.finditer(body_text):
        heading = match.group("heading")
        content = clean_whitespace(match.group("body"))
        if not content or heading in SECTION_END_MARKERS:
            continue
        sections[heading] = content
    return sections


def merge_description_sections(sections: dict[str, str], preferred: Sequence[str]) -> str | None:
    blocks: list[str] = []
    for key in preferred:
        value = sections.get(key)
        if value:
            blocks.append(f"{key}\n{value}")
    if not blocks:
        return None
    return "\n\n".join(blocks)


def select_best_dict_payload(payloads: Sequence[dict[str, Any]], url_job_id: str | None = None) -> dict[str, Any] | None:
    best_score = -1
    best: dict[str, Any] | None = None
    for payload in payloads:
        data = payload.get("data")
        for mapping in deep_iter_dicts(data):
            score = 0
            if extract_value_from_mapping(mapping, TITLE_KEYS):
                score += 3
            if extract_value_from_mapping(mapping, ID_KEYS):
                score += 2
            if extract_value_from_mapping(mapping, LOCATION_KEYS):
                score += 1
            if extract_value_from_mapping(mapping, DESCRIPTION_TEXT_KEYS) or extract_value_from_mapping(mapping, DESCRIPTION_HTML_KEYS):
                score += 3
            if url_job_id:
                candidate_id = stringify_value(extract_value_from_mapping(mapping, ID_KEYS))
                if candidate_id == url_job_id:
                    score += 3
            text_blob = " ".join(
                str(v)
                for v in mapping.values()
                if isinstance(v, (str, int, float))
            )
            if re.search(r"实习|校招|岗位|职位|intern|graduate|position|job", text_blob, re.I):
                score += 1
            if score > best_score:
                best_score = score
                best = dict(mapping)
    return best


def score_list_payload(items: list[Any]) -> int:
    if not items or not all(isinstance(item, Mapping) for item in items[: min(5, len(items))]):
        return -1
    score = 0
    merged_keys = {normalize_key(key) for item in items[: min(5, len(items))] for key in item.keys()}
    if merged_keys & {normalize_key(k) for k in TITLE_KEYS}:
        score += 3
    if merged_keys & {normalize_key(k) for k in ID_KEYS}:
        score += 3
    if merged_keys & {normalize_key(k) for k in URL_KEYS}:
        score += 1
    if merged_keys & {normalize_key(k) for k in LOCATION_KEYS}:
        score += 1
    sample_blob = " ".join(
        str(v)
        for item in items[: min(5, len(items))]
        for v in item.values()
        if isinstance(v, (str, int, float))
    )
    if re.search(r"实习|校招|岗位|职位|intern|graduate|position|job", sample_blob, re.I):
        score += 2
    return score


def select_best_list_payload(payloads: Sequence[dict[str, Any]]) -> list[Mapping[str, Any]] | None:
    best_score = -1
    best_items: list[Mapping[str, Any]] | None = None
    for payload in payloads:
        data = payload.get("data")
        for items in deep_iter_lists(data):
            score = score_list_payload(items)
            if score > best_score:
                best_score = score
                best_items = [item for item in items if isinstance(item, Mapping)]
    return best_items


def safe_wait_for_keywords(page: Page, keywords: Sequence[str], timeout_ms: int) -> None:
    end_time = time.time() + timeout_ms / 1000
    while time.time() < end_time:
        try:
            body_text = page.locator("body").inner_text(timeout=2_000)
        except Exception:
            page.wait_for_timeout(500)
            continue
        if any(keyword in body_text for keyword in keywords):
            return
        page.wait_for_timeout(500)


def detect_block_page(body_text: str) -> str | None:
    body_text = body_text.lower()
    suspicious = [
        "captcha",
        "人机验证",
        "验证",
        "访问频率",
        "forbidden",
        "access denied",
        "登录后查看",
        "sign in",
    ]
    for marker in suspicious:
        if marker in body_text:
            return marker
    return None


def page_snapshot(page: Page) -> dict[str, Any]:
    anchors = page.evaluate(
        """
        () => {
          const results = [];
          for (const a of document.querySelectorAll('a[href]')) {
            let cardText = (a.textContent || '').trim();
            let node = a;
            for (let i = 0; i < 4 && node; i += 1) {
              const candidate = ((node.innerText || node.textContent || '').trim()).replace(/\\s+/g, ' ').slice(0, 800);
              if (candidate.length > cardText.length) {
                cardText = candidate;
              }
              node = node.parentElement;
            }
            results.push({
              href: a.href,
              text: ((a.textContent || '').trim()).replace(/\\s+/g, ' '),
              cardText,
            });
          }
          return results;
        }
        """
    )
    body_text = page.locator("body").inner_text(timeout=5_000)
    page_html = page.content()
    return {
        "anchors": anchors,
        "body_text": body_text,
        "page_html": page_html,
    }


def build_bytedance_stub_from_json_item(item: Mapping[str, Any]) -> JobStub | None:
    detail_url = stringify_value(extract_value_from_mapping(item, URL_KEYS))
    job_id = stringify_value(extract_value_from_mapping(item, ID_KEYS))
    if not detail_url and job_id and re.fullmatch(r"\d{8,}", job_id):
        detail_url = f"https://jobs.bytedance.com/campus/position/{job_id}/detail"
    if not detail_url:
        return None
    detail_url = canonicalize_bytedance_detail_url(detail_url)
    title = stringify_value(extract_value_from_mapping(item, TITLE_KEYS))
    location = stringify_value(extract_value_from_mapping(item, LOCATION_KEYS))
    employment = stringify_value(extract_value_from_mapping(item, EMPLOYMENT_KEYS))
    posted_at = normalize_date_string(stringify_value(extract_value_from_mapping(item, POSTED_KEYS)))
    department = stringify_value(extract_value_from_mapping(item, DEPARTMENT_KEYS))
    team = stringify_value(extract_value_from_mapping(item, TEAM_KEYS))
    return JobStub(
        detail_url=detail_url,
        title_hint=title,
        location_hint=location,
        employment_type_hint=employment,
        posted_at_hint=posted_at,
        external_job_id_hint=job_id,
        department_hint=department,
        team_hint=team,
        raw_listing_payload=dict(item),
    )


def build_tencent_stub_from_json_item(item: Mapping[str, Any]) -> JobStub | None:
    detail_url = stringify_value(extract_value_from_mapping(item, URL_KEYS))
    job_id = stringify_value(extract_value_from_mapping(item, ("postid", "postId", "id", "jobId")))
    if not detail_url:
        postid = stringify_value(extract_value_from_mapping(item, ("postid", "postId")))
        if postid:
            detail_url = f"https://join.qq.com/post_detail.html?postid={postid}"
        else:
            id_value = stringify_value(extract_value_from_mapping(item, ("id", "jobId")))
            pid_value = stringify_value(extract_value_from_mapping(item, ("pid", "projectId")))
            tid_value = stringify_value(extract_value_from_mapping(item, ("tid", "typeId")))
            if id_value and pid_value and tid_value:
                detail_url = f"https://join.qq.com/post_detail.html?id={id_value}&pid={pid_value}&tid={tid_value}"
    if not detail_url:
        return None
    detail_url = canonicalize_tencent_detail_url(detail_url)
    title = stringify_value(extract_value_from_mapping(item, TITLE_KEYS))
    location = stringify_value(extract_value_from_mapping(item, LOCATION_KEYS))
    employment = stringify_value(extract_value_from_mapping(item, EMPLOYMENT_KEYS))
    posted_at = normalize_date_string(stringify_value(extract_value_from_mapping(item, POSTED_KEYS)))
    department = stringify_value(extract_value_from_mapping(item, DEPARTMENT_KEYS))
    team = stringify_value(extract_value_from_mapping(item, TEAM_KEYS))
    return JobStub(
        detail_url=detail_url,
        title_hint=title,
        location_hint=location,
        employment_type_hint=employment,
        posted_at_hint=posted_at,
        external_job_id_hint=job_id,
        department_hint=department,
        team_hint=team,
        raw_listing_payload=dict(item),
    )


def parse_bytedance_listing_card_hints(link_text: str, card_text: str) -> dict[str, str | None]:
    text = clean_whitespace(card_text) or ""
    text = text.replace(" · ", "\n")
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    title = link_text if probable_job_title(link_text) else None
    location = None
    employment = None
    department = None
    for line in lines:
        if not title and probable_job_title(line):
            title = line
        if not location and re.search(r"(北京|上海|深圳|广州|杭州|成都|远程|Remote|Singapore|San Jose|Seattle|London|Tokyo)", line, re.I):
            location = line
        if not employment and any(token.lower() == line.lower() for token in KNOWN_EMPLOYMENT_TOKENS):
            employment = line
        if not department and re.search(r"(研发|算法|后端|前端|运营|设计|产品|人力|技术|marketing|design|product|technology)", line, re.I):
            department = line
    return {
        "title": title,
        "location_text": location,
        "employment_type": employment,
        "department": department,
        "team": None,
    }


def parse_tencent_listing_card_hints(link_text: str, card_text: str) -> dict[str, str | None]:
    text = clean_whitespace(card_text) or ""
    text = text.replace(" · ", "\n")
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    title = link_text if probable_job_title(link_text) else None
    location = None
    employment = None
    department = None
    for line in lines:
        if not title and probable_job_title(line):
            title = line
        if not employment and re.search(r"(实习|校招|培训生|青云计划|Graduate|Intern)", line, re.I):
            employment = line
        if not location and re.search(r"(北京|上海|深圳|广州|成都|杭州|天津|武汉|西安|南京|远程|Remote)", line, re.I):
            location = line
        if not department and re.search(r"(CSIG|IEG|PCG|TEG|WXG|CDG|S[0-9]|事业群|部门)", line, re.I):
            department = line
    return {
        "title": title,
        "location_text": location,
        "employment_type": employment,
        "department": department,
        "team": None,
    }


BYTEDANCE_CONFIG = SourceConfig(
    key="bytedance_campus",
    company_name="字节跳动",
    company_slug="bytedance",
    list_url="https://jobs.bytedance.com/campus/position/list?keywords=",
    host="jobs.bytedance.com",
    detail_url_checker=is_bytedance_detail_url,
    canonicalize_detail_url=canonicalize_bytedance_detail_url,
    build_stub_from_json_item=build_bytedance_stub_from_json_item,
    parse_listing_card_hints=parse_bytedance_listing_card_hints,
    detail_wait_keywords=("职位描述", "职位要求", "职位ID", "团队介绍"),
    title_regex=re.compile(r"^(?P<title>.+?)\s*$"),
    req_id_regex=re.compile(r"职位ID\s*[:：]?\s*(?P<req>[A-Za-z0-9_-]+)"),
    location_label_patterns=(
        re.compile(r"工作地点\s*[:：]?\s*(?P<value>.+)"),
        re.compile(r"Location\s*[:：]?\s*(?P<value>.+)", re.I),
    ),
    employment_label_patterns=(
        re.compile(r"Employment Type\s*[:：]?\s*(?P<value>.+)", re.I),
        re.compile(r"招聘类型\s*[:：]?\s*(?P<value>.+)"),
    ),
    posted_at_patterns=(
        re.compile(r"发布时间\s*[:：]?\s*(?P<value>\d{4}[./-]\d{1,2}[./-]\d{1,2})"),
        re.compile(r"Posted\s*(?:on|at)?\s*[:：]?\s*(?P<value>\d{4}[./-]\d{1,2}[./-]\d{1,2})", re.I),
    ),
)

TENCENT_CONFIG = SourceConfig(
    key="tencent_campus",
    company_name="腾讯",
    company_slug="tencent",
    list_url="https://join.qq.com/post.html?query=p_2",
    host="join.qq.com",
    detail_url_checker=is_tencent_detail_url,
    canonicalize_detail_url=canonicalize_tencent_detail_url,
    build_stub_from_json_item=build_tencent_stub_from_json_item,
    parse_listing_card_hints=parse_tencent_listing_card_hints,
    detail_wait_keywords=("岗位描述", "岗位要求", "参加面试的城市", "招聘部门和工作地"),
    title_regex=re.compile(r"^(?P<title>.+?)\s*$"),
    req_id_regex=re.compile(r"(?:职位ID|岗位ID)\s*[:：]?\s*(?P<req>[A-Za-z0-9_-]+)"),
    location_label_patterns=(
        re.compile(r"招聘部门和工作地\s*[:：]?\s*(?P<value>.+)"),
        re.compile(r"参加面试的城市\s*[:：]?\s*(?P<value>.+)"),
    ),
    employment_label_patterns=(
        re.compile(r"^(?P<value>应届实习|日常实习|实习|校招|培训生)$", re.M),
    ),
    posted_at_patterns=(
        re.compile(r"发布时间\s*[:：]?\s*(?P<value>\d{4}[./-]\d{1,2}[./-]\d{1,2})"),
    ),
)

CONFIGS: dict[str, SourceConfig] = {
    BYTEDANCE_CONFIG.key: BYTEDANCE_CONFIG,
    TENCENT_CONFIG.key: TENCENT_CONFIG,
}


def choose_config(key: str, list_url: str | None = None) -> SourceConfig:
    config = CONFIGS[key]
    if not list_url:
        return config
    return dataclasses.replace(config, list_url=list_url)


def navigate_with_retry(page: Page, url: str, timeout_ms: int, retries: int = 3) -> None:
    delay = 1.0
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(800)
            return
        except Exception as exc:  # pragma: no cover - runtime dependent
            last_exc = exc
            if attempt == retries:
                break
            logger.warning("导航失败，准备重试: %s (attempt=%s/%s): %s", url, attempt, retries, exc)
            page.wait_for_timeout(int(delay * 1000))
            delay *= 2
    raise RuntimeError(f"页面打开失败: {url}: {last_exc}")


def click_more_if_present(page: Page) -> bool:
    candidates = ["加载更多", "查看更多", "更多", "下一页", "下页", "Next"]
    for text in candidates:
        try:
            locator = page.get_by_text(text, exact=False)
            if locator.count() == 0:
                continue
            target = locator.first
            if target.is_visible():
                target.scroll_into_view_if_needed(timeout=3_000)
                target.click(timeout=3_000)
                page.wait_for_timeout(1_000)
                return True
        except Exception:
            continue
    return False


def collect_listing_stubs(page: Page, config: SourceConfig, response_payloads: Sequence[dict[str, Any]]) -> list[JobStub]:
    snapshot = page_snapshot(page)
    anchors = snapshot["anchors"]
    stubs: list[JobStub] = []
    seen_urls: set[str] = set()
    for anchor in anchors:
        href = anchor.get("href")
        if not href or not isinstance(href, str):
            continue
        if not config.detail_url_checker(href):
            continue
        detail_url = config.canonicalize_detail_url(href)
        if detail_url in seen_urls:
            continue
        seen_urls.add(detail_url)
        link_text = clean_whitespace(anchor.get("text")) or ""
        card_text = clean_whitespace(anchor.get("cardText")) or link_text
        hints = config.parse_listing_card_hints(link_text, card_text)
        stubs.append(
            JobStub(
                detail_url=detail_url,
                title_hint=hints.get("title") or (link_text if probable_job_title(link_text) else None),
                location_hint=hints.get("location_text"),
                employment_type_hint=hints.get("employment_type"),
                department_hint=hints.get("department"),
                team_hint=hints.get("team"),
                external_job_id_hint=extract_url_job_id(detail_url),
                card_text=card_text,
            )
        )

    payload_items = select_best_list_payload(response_payloads) or []
    for item in payload_items:
        stub = config.build_stub_from_json_item(item)
        if not stub:
            continue
        if stub.detail_url in seen_urls:
            continue
        seen_urls.add(stub.detail_url)
        stubs.append(stub)

    return stubs


def expand_listing_page(page: Page, config: SourceConfig, timeout_ms: int, max_rounds: int = 25) -> list[dict[str, Any]]:
    collector = ResponseCollector(page, config.host)
    try:
        navigate_with_retry(page, config.list_url, timeout_ms=timeout_ms)
        safe_wait_for_keywords(page, config.detail_wait_keywords + ("职位", "岗位", "实习", "校招"), timeout_ms=min(timeout_ms, 12_000))
        previous_anchor_count = -1
        stale_rounds = 0
        for _ in range(max_rounds):
            try:
                current_count = page.locator("a[href]").count()
            except Exception:
                current_count = previous_anchor_count
            if current_count == previous_anchor_count:
                stale_rounds += 1
            else:
                stale_rounds = 0
                previous_anchor_count = current_count
            page.mouse.wheel(0, 5_000)
            page.wait_for_timeout(1_000)
            if stale_rounds >= 3 and not click_more_if_present(page):
                if stale_rounds >= 5:
                    break
        return list(collector.payloads)
    finally:
        collector.close()


def extract_text_with_patterns(text: str, patterns: Sequence[re.Pattern[str]]) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return clean_whitespace(match.group("value"))
    return None


def choose_title_from_page(body_text: str) -> str | None:
    lines = [line.strip() for line in (clean_whitespace(body_text) or "").split("\n") if line.strip()]
    for line in lines[:30]:
        if not probable_job_title(line):
            continue
        if re.search(r"(腾讯校园招聘|字节跳动|校园招聘|岗位详情|首页|求职攻略|招聘动态)", line):
            continue
        if len(line) <= 80:
            return line
    return None


def extract_detail_record(page: Page, config: SourceConfig, stub: JobStub, timeout_ms: int) -> RawJob:
    collector = ResponseCollector(page, config.host)
    try:
        navigate_with_retry(page, stub.detail_url, timeout_ms=timeout_ms)
        safe_wait_for_keywords(page, config.detail_wait_keywords, timeout_ms=min(timeout_ms, 10_000))
        snapshot = page_snapshot(page)
        body_text = clean_whitespace(snapshot["body_text"]) or ""
        page_html = sanitize_html(snapshot["page_html"])
        blocked_reason = detect_block_page(body_text)
        if blocked_reason:
            raise RuntimeError(f"页面疑似被风控或登录拦截: {blocked_reason}")

        url_job_id = extract_url_job_id(stub.detail_url)
        best_payload = select_best_dict_payload(collector.payloads, url_job_id=url_job_id)

        title = first_non_empty(
            stringify_value(extract_value_recursive(best_payload, TITLE_KEYS)) if best_payload else None,
            choose_title_from_page(body_text),
            stub.title_hint,
        )
        if not title:
            raise ValueError(f"无法从详情页提取标题: {stub.detail_url}")

        sections = parse_body_sections(body_text)
        description_text = first_non_empty(
            stringify_value(extract_value_recursive(best_payload, DESCRIPTION_TEXT_KEYS)) if best_payload else None,
            merge_description_sections(
                sections,
                (
                    "团队介绍",
                    "职位描述",
                    "岗位描述",
                    "职位要求",
                    "岗位要求",
                    "加分项或注意事项",
                    "加分项",
                ),
            ),
        )
        if description_text:
            description_text = clean_whitespace(description_text)
        description_html = first_non_empty(
            stringify_html_value(extract_value_recursive(best_payload, DESCRIPTION_HTML_KEYS)) if best_payload else None,
            page_html,
        )
        if description_html:
            description_html = sanitize_html(description_html)

        location_raw = first_non_empty(
            stringify_value(extract_value_recursive(best_payload, LOCATION_KEYS)) if best_payload else None,
            extract_text_with_patterns(body_text, config.location_label_patterns),
            stub.location_hint,
        )
        employment_raw = first_non_empty(
            stringify_value(extract_value_recursive(best_payload, EMPLOYMENT_KEYS)) if best_payload else None,
            extract_text_with_patterns(body_text, config.employment_label_patterns),
            stub.employment_type_hint,
        )
        posted_at_raw = first_non_empty(
            stringify_value(extract_value_recursive(best_payload, POSTED_KEYS)) if best_payload else None,
            extract_text_with_patterns(body_text, config.posted_at_patterns),
            stub.posted_at_hint,
        )
        posted_at = normalize_date_string(posted_at_raw)

        req_id_raw = None
        if config.req_id_regex:
            match = config.req_id_regex.search(body_text)
            if match:
                req_id_raw = clean_whitespace(match.group("req"))

        department_raw = first_non_empty(
            stringify_value(extract_value_recursive(best_payload, DEPARTMENT_KEYS)) if best_payload else None,
            stub.department_hint,
        )
        team_raw = first_non_empty(
            stringify_value(extract_value_recursive(best_payload, TEAM_KEYS)) if best_payload else None,
            stub.team_hint,
        )

        source_url = config.canonicalize_detail_url(stub.detail_url)
        external_job_id = first_non_empty(
            stringify_value(extract_value_recursive(best_payload, ID_KEYS)) if best_payload else None,
            stub.external_job_id_hint,
            extract_url_job_id(source_url),
        )

        metadata = {
            "company_slug": config.company_slug,
            "crawler_name": f"{config.company_slug}-company-site",
            "crawler_version": CRAWLER_VERSION,
            "list_url": config.list_url,
            "detail_url": source_url,
            "source_page_type": config.source_page_type,
            "location_raw": location_raw,
            "employment_type_raw": employment_raw,
            "posted_at_raw": posted_at_raw,
            "req_id_raw": req_id_raw,
            "department_raw": department_raw,
            "team_raw": team_raw,
            "scrape_notes": [
                "listing hints merged with detail extraction",
                "preferred first-party JSON/XHR payload when available",
                "fallback description_html may contain full page HTML",
            ],
        }

        if stub.card_text:
            metadata["listing_card_text"] = stub.card_text

        return RawJob(
            source_type="company_site",
            source_url=source_url,
            external_job_id=clean_whitespace(external_job_id),
            title=clean_whitespace(title) or title,
            company_name=config.company_name,
            location_text=clean_whitespace(location_raw),
            employment_type=clean_whitespace(employment_raw),
            posted_at=posted_at,
            description_text=description_text,
            description_html=description_html,
            json_payload=best_payload or stub.raw_listing_payload,
            metadata={k: v for k, v in metadata.items() if v not in (None, "", [], {})},
            fetched_at=utc_now_iso(),
        )
    finally:
        collector.close()


def make_browser_context(browser: Browser) -> BrowserContext:
    return browser.new_context(
        user_agent=USER_AGENT,
        locale="zh-CN",
        viewport={"width": 1440, "height": 2200},
        java_script_enabled=True,
    )


def crawl_source(
    config: SourceConfig,
    output_path: str,
    report_path: str | None,
    max_jobs: int | None,
    timeout_ms: int,
    delay_seconds: float,
    headful: bool,
) -> CrawlReport:
    report = CrawlReport(
        crawler_name=f"{config.company_slug}-company-site",
        crawler_version=CRAWLER_VERSION,
        source_key=config.key,
        list_url=config.list_url,
        started_at=utc_now_iso(),
        max_jobs=max_jobs,
    )

    robots = RobotsGuard()
    allow_list, robots_url = robots.can_fetch(config.list_url)
    report.robots_checked.append({"url": config.list_url, "robots_url": robots_url, "allowed": allow_list})
    if not allow_list:
        raise RuntimeError(f"robots.txt 不允许抓取列表页: {config.list_url}")

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    if report_path:
        os.makedirs(os.path.dirname(report_path) or ".", exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headful)
        context = make_browser_context(browser)
        page = context.new_page()
        try:
            listing_payloads = expand_listing_page(page, config, timeout_ms=timeout_ms)
            stubs = collect_listing_stubs(page, config, listing_payloads)
            report.pages_visited.append(config.list_url)
            if not stubs:
                report.warnings.append("列表页没有提取到任何岗位详情链接，可能是页面结构已变更或需要人工验证。")

            if max_jobs is not None:
                stubs = stubs[:max_jobs]

            detail_page = context.new_page()
            seen_source_urls: set[str] = set()
            emitted = 0
            with open(output_path, "w", encoding="utf-8") as out:
                for stub in stubs:
                    allow_detail, robots_detail_url = robots.can_fetch(stub.detail_url)
                    report.robots_checked.append({"url": stub.detail_url, "robots_url": robots_detail_url, "allowed": allow_detail})
                    if not allow_detail:
                        report.jobs_skipped += 1
                        report.add_failure(CrawlFailure(url=stub.detail_url, stage="robots", reason="robots_disallow"))
                        continue
                    try:
                        record = extract_detail_record(detail_page, config, stub, timeout_ms=timeout_ms)
                        if record.source_url in seen_source_urls:
                            report.jobs_skipped += 1
                            continue
                        record.validate()
                        out.write(record.to_json())
                        out.write("\n")
                        out.flush()
                        seen_source_urls.add(record.source_url)
                        emitted += 1
                        report.jobs_emitted = emitted
                        report.pages_visited.append(record.source_url)
                    except Exception as exc:  # pragma: no cover - depends on runtime site behavior
                        report.jobs_skipped += 1
                        report.add_failure(
                            CrawlFailure(
                                url=stub.detail_url,
                                stage="detail_extract",
                                reason=exc.__class__.__name__,
                                detail=str(exc),
                            )
                        )
                        logger.exception("详情页提取失败: %s", stub.detail_url)
                    finally:
                        time.sleep(delay_seconds)
        finally:
            context.close()
            browser.close()

    report.finish()
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(dataclasses.asdict(report), f, ensure_ascii=False, indent=2)
    return report


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="抓取公司官网岗位，并输出 RawJob JSONL。")
    parser.add_argument("--source", choices=sorted(CONFIGS), required=True, help="内置站点配置")
    parser.add_argument("--list-url", help="覆盖默认列表页 URL")
    parser.add_argument("--output", required=True, help="输出 JSONL 路径")
    parser.add_argument("--report", help="输出 crawl report JSON 路径")
    parser.add_argument("--max-jobs", type=int, default=None, help="最多抓取多少个岗位")
    parser.add_argument("--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS, help="单页超时毫秒数")
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS, help="详情页之间的等待秒数")
    parser.add_argument("--headful", action="store_true", help="使用有头浏览器，便于本地调试")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        config = choose_config(args.source, list_url=args.list_url)
        report = crawl_source(
            config=config,
            output_path=args.output,
            report_path=args.report,
            max_jobs=args.max_jobs,
            timeout_ms=args.timeout_ms,
            delay_seconds=args.delay_seconds,
            headful=args.headful,
        )
        logger.info(
            "完成: source=%s emitted=%s skipped=%s output=%s",
            report.source_key,
            report.jobs_emitted,
            report.jobs_skipped,
            args.output,
        )
        return 0
    except Exception as exc:
        logger.error("抓取失败: %s", exc)
        if logger.isEnabledFor(logging.DEBUG):
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
