# Company Website Crawler Spec

## Purpose

This document defines the mandatory contract for adding new company-website crawling sources into this repository.

It is written for a stronger external AI or engineer who will implement the crawler.

The crawler may be implemented outside this repo, but its output must fit this repo's ingestion model.

## Recommended Integration Modes

There are two supported integration modes.

### Mode A: External crawler artifact mode

Use this when the crawler needs browser automation, anti-fragile DOM handling, or non-stdlib dependencies.

Required behavior:

- The crawler runs outside the core pipeline.
- It outputs UTF-8 `JSONL` records that conform to the `RawJob` contract.
- The output is imported through:

```bash
python -m apps.pipeline.cli run-pipeline \
  --import-input path/to/crawler-output.jsonl \
  --db data/recruit_graph.sqlite3
```

or:

```bash
python -m apps.pipeline.cli import-raw --input path/to/crawler-output.jsonl --db data/recruit_graph.sqlite3
```

This is the preferred mode if the crawler needs Playwright, Selenium, Scrapy, browser stealth, or similar tooling.

### Repo bundle default

If this repo uses the bundled crawler under `includes/company_site_crawler_bundle/`, prefer the repo defaults instead of hardcoding paths in config.

For the built-in `company_site` source wrapper:

- omit `script_path` unless you are overriding the bundled script
- omit `python_bin` unless you are overriding the bundled virtualenv/interpreter

The wrapper already defaults to:

- `includes/company_site_crawler_bundle/company_site_crawler.py`
- `includes/company_site_crawler_bundle/.venv/bin/python` when that venv exists

This makes the config more portable when the config file is moved outside the repo root.

### Mode B: In-repo source type mode

Use this only when the crawler can stay aligned with the repo constraints and be maintained as a first-class source.

Required behavior:

- Implement a new adapter under `apps/pipeline/adapters/`.
- Return `list[RawJob]`.
- Wire the new source type into `apps/pipeline/source_registry.py`.
- Make it runnable via `fetch-sources` / `run-pipeline`.

This repo currently favors a simple core with minimal runtime assumptions. Do not add heavy crawler stacks into the main pipeline without explicit approval.

## Hard Requirements

### Scope

- Only collect job posting data from public company-owned career pages or clearly company-controlled hiring pages.
- Prefer company website sources over third-party mirrors when both exist.
- Prefer structured data extraction over brittle DOM scraping when available.

### Extraction priority

Use this order of preference:

1. Embedded `JobPosting` JSON-LD
2. Structured ATS JSON embedded on the company page
3. First-party JSON/XHR endpoints used by the site
4. Stable semantic HTML extraction
5. Last-resort heuristic DOM scraping

Do not start with screenshot/OCR-style extraction.

### Compliance and safety

- Respect `robots.txt` unless the user explicitly instructs otherwise.
- Respect site terms and basic crawl politeness.
- Do not bypass login, paywalls, CAPTCHAs, rate limits, or anti-bot controls.
- Do not scrape private candidate portals or application submission flows.
- Do not submit forms or mutate remote state.

### Performance and crawl behavior

- Default to low concurrency per host.
- Default to a conservative request rate for company websites.
- Use bounded retries with backoff.
- Time out cleanly.
- Emit partial results when possible rather than failing silently.

### Pipeline boundary

The crawler must remain a raw acquisition step.

The crawler must not:

- write directly to SQLite
- write directly to `data/public`
- normalize company names
- normalize job titles
- deduplicate jobs
- infer skills
- infer seniority
- infer remote mode beyond preserving source wording

All normalization belongs to the existing pipeline stages.

## RawJob Contract

The output must conform to [raw-job.schema.json](/Volumes/meowhub/agents/jobvisualizer/packages/schema/raw-job.schema.json) and the `RawJob` dataclass in [base.py](/Volumes/meowhub/agents/jobvisualizer/apps/pipeline/adapters/base.py).

Required top-level fields:

- `source_type`
- `source_url`
- `title`
- `company_name`
- `fetched_at`

Preferred fields:

- `external_job_id`
- `location_text`
- `employment_type`
- `posted_at`
- `description_text`
- `description_html`
- `json_payload`
- `metadata`

### Field rules

#### `source_type`

- Use one stable source family name.
- Recommended value for company website crawlers: `company_site`
- Do not vary this per run.
- Put company-specific detail in `metadata`, not in `source_type`.

#### `source_url`

- Must be the canonical job detail page URL when available.
- Must not be the listings page unless the source truly exposes no detail pages.
- Must be stable enough to help trace provenance.

#### `external_job_id`

- Strongly preferred.
- Extract the native job ID from the site, embedded JSON, API payload, or URL slug if the site uses a stable identifier.
- This is the best dedupe anchor in the current pipeline.
- If no stable ID exists, leave it `null`.

#### `title`

- Preserve the raw job title from the source.
- Do not title-case, translate, or normalize it.

#### `company_name`

- Preserve the company name as it appears on the source.
- Do not map aliases in the crawler.

#### `location_text`

- Preserve source wording if possible.
- If multiple locations exist, join them in a readable way.
- If unknown, use `null`.

#### `employment_type`

- Preserve explicit source value if available.
- Do not infer from title alone.

#### `posted_at`

- Use the source-provided posting date if available.
- Prefer ISO-like source values.
- If uncertain, use `null`.
- Do not fabricate crawl date as posting date.

#### `description_text`

- Strongly preferred.
- Must be clean readable text with tags removed.
- Preserve meaning and paragraph order as much as possible.
- Do not summarize.

#### `description_html`

- Strongly preferred whenever the source has detail-page HTML.
- Preserve the raw job description HTML block if possible.
- If only full-page HTML is available, that is acceptable as a fallback.

#### `json_payload`

- Use this to preserve the original structured payload when available.
- Good examples:
  - embedded JSON-LD object
  - first-party API response fragment
  - extracted structured object before flattening
- If unavailable, `null` is acceptable.

#### `metadata`

This is where crawler-specific provenance goes.

Required recommended keys:

- `company_slug`
- `crawler_name`
- `crawler_version`
- `list_url`
- `detail_url`
- `source_page_type`

Strongly recommended keys when available:

- `location_raw`
- `employment_type_raw`
- `posted_at_raw`
- `req_id_raw`
- `department_raw`
- `team_raw`
- `scrape_notes`

Do not hide important primary fields inside `metadata` if a first-class `RawJob` field already exists.

## Output File Rules

### Format

- Output must be UTF-8 `JSONL`.
- One line per job.
- One record represents one job posting.
- No wrapper object.
- No comments.

### Path conventions

Recommended artifact locations:

- `data/raw/company-sites/<source-name>.jsonl`
- `data/raw/external/<source-name>.jsonl`

If the crawler runs outside the repo, the final handoff must still produce a `.jsonl` file that can be copied into or referenced from this workspace.

### Stability

- Re-running the crawler on unchanged source pages should produce semantically stable records.
- Field names must not drift across runs.
- `metadata` keys must remain stable once adopted.

## Required Deliverables From The Crawler Author

The stronger AI or engineer must provide all of the following.

### 1. Runnable crawler

- A documented entrypoint command
- Clear dependency list
- Clear input parameters
- Clear output path behavior

### 2. Field mapping note

For each company site, document:

- where `external_job_id` comes from
- where `posted_at` comes from
- where `location_text` comes from
- where `description_text` / `description_html` come from
- which fields are direct vs inferred

### 3. Sample output

- At least one sample `.jsonl` artifact
- At least one example record with every available field populated

### 4. Crawl report

A machine-readable or human-readable report that includes:

- pages visited
- jobs emitted
- jobs skipped
- extraction failures
- rate-limit or timeout failures

### 5. Failure policy

Document what happens when:

- the listings page loads but detail pages fail
- embedded data disappears
- fields are partially missing
- the site changes layout

## Acceptance Checklist

The crawler is acceptable only if all items below are true.

- Output is valid `JSONL`
- Each line parses as JSON
- Records conform to `RawJob` expectations
- `source_url` points to the actual detail page when one exists
- `external_job_id` is populated whenever a stable native ID exists
- `description_text` is present for the majority of records
- `description_html` is preserved when available
- `json_payload` preserves structured source data when available
- The crawler does not normalize, dedupe, or enrich
- The crawler can be run repeatedly without changing field semantics
- The crawler does not require manual browsing to extract every job
- The crawler respects public-site boundaries and crawl politeness

## Example Record

```json
{
  "source_type": "company_site",
  "source_url": "https://company.example/careers/jobs/12345",
  "external_job_id": "12345",
  "title": "Senior Data Engineer",
  "company_name": "Example Corp",
  "location_text": "San Francisco, CA, US",
  "employment_type": "FULL_TIME",
  "posted_at": "2026-04-01",
  "description_text": "Build data pipelines, operate analytics systems, and partner with product teams.",
  "description_html": "<div><p>Build data pipelines...</p></div>",
  "json_payload": {
    "id": "12345",
    "department": "Data",
    "locations": ["San Francisco, CA, US"]
  },
  "metadata": {
    "company_slug": "example-corp",
    "crawler_name": "example-corp-careers",
    "crawler_version": "1.0.0",
    "list_url": "https://company.example/careers",
    "detail_url": "https://company.example/careers/jobs/12345",
    "source_page_type": "career_site_job_detail",
    "location_raw": "San Francisco, CA, US",
    "employment_type_raw": "Full time"
  },
  "fetched_at": "2026-04-06T00:00:00+00:00"
}
```

## In-Repo Adapter Rules

If the crawler is promoted into this repo as a first-class source:

- Add a dedicated adapter module under `apps/pipeline/adapters/`
- Reuse the `RawJob` dataclass from [base.py](/Volumes/meowhub/agents/jobvisualizer/apps/pipeline/adapters/base.py)
- Validate before writing JSONL
- Wire the source type into [source_registry.py](/Volumes/meowhub/agents/jobvisualizer/apps/pipeline/source_registry.py)
- Keep the adapter focused on fetch + extraction only
- Add a fixture under `sample-data/` when practical
- Add at least one test covering parse success and a missing-field path

Do not silently change the meaning of existing source types like `html` or `jsonld`.

## Config Path Semantics

If `script_path`, `python_bin`, or `report_path` are explicitly provided in source config, they are resolved relative to the config file location.

Because of that:

- do not set these fields in normal repo-local examples unless override behavior is required
- prefer leaving them unset when you want the bundled crawler defaults
- if you must set them in a non-repo-local config, prefer absolute paths

## Preferred Default For This Repo

For company-website crawling, the default recommendation is:

1. Let the stronger AI build the crawler outside the core repo
2. Make it emit `RawJob` JSONL
3. Import that artifact through `--import-input`
4. Only promote it into `source_registry` after the output contract is stable

This keeps the pipeline boundary clean and avoids forcing heavy crawler dependencies into the core acquisition path too early.
