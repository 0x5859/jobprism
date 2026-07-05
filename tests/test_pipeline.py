from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.pipeline import db, enrich, normalize
from apps.pipeline import source_registry
from apps.pipeline.adapters.base import RawJob
from apps.pipeline.adapters import greenhouse, html_fallback, jsonld
from apps.pipeline.build_graph import build_public_graph
from apps.pipeline.io_utils import iter_input_paths


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_JOBPOSTING_HTML = REPO_ROOT / "sample-data/raw_html/sample_job_posting.html"
SAMPLE_HTML_FALLBACK = REPO_ROOT / "sample-data/raw_html/sample_html_fallback.html"
SAMPLE_RAW_INPUT_DIR = REPO_ROOT / "sample-data/input"
COMPANY_ALIASES = REPO_ROOT / "config/company_aliases.json"
SKILL_TAXONOMY = REPO_ROOT / "config/skill_taxonomy.json"


ALIAS_RAW_JOB = {
    "source_type": "greenhouse",
    "source_url": "https://boards.greenhouse.io/openai/jobs/alias-001",
    "external_job_id": "alias-001",
    "title": "Platform Engineer",
    "company_name": "Open AI",
    "location_text": "San Francisco, CA",
    "employment_type": "full-time",
    "posted_at": "2026-03-25",
    "description_text": "Build Python and SQL services for internal data workflows.",
    "description_html": "<p>Build Python and SQL services for internal data workflows.</p>",
    "json_payload": {"id": 99999, "board_token": "openai"},
    "fetched_at": "2026-03-25T00:20:00+00:00",
    "metadata": {"departments": [{"name": "Platform"}]},
}


class PipelineFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.db_path = self.root / "recruit_graph.sqlite3"
        db.init_db(self.db_path)

    def _seed_sample_db(self) -> None:
        normalize.import_raw_inputs(self.db_path, SAMPLE_RAW_INPUT_DIR)
        with db.connect(self.db_path) as conn:
            db.insert_raw_jobs(conn, [ALIAS_RAW_JOB])
            conn.commit()
        normalize.normalize_all(self.db_path, COMPANY_ALIASES)

    def test_jsonld_parser_uses_sample_fixture(self) -> None:
        records = jsonld.parse_jobposting_from_file(SAMPLE_JOBPOSTING_HTML)

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.source_type, "jsonld")
        self.assertEqual(record.company_name, "Example Labs")
        self.assertEqual(record.title, "Research Engineer")
        self.assertEqual(record.external_job_id, "example-research-001")
        self.assertEqual(record.location_text, "San Francisco, CA, US")
        self.assertEqual(record.employment_type, "FULL_TIME")
        self.assertEqual(record.source_url, "https://example.com/jobs/research-engineer")
        self.assertIn("large language models", record.description_text.lower())

    def test_html_fallback_parser_uses_sample_fixture(self) -> None:
        records = html_fallback.parse_generic_html_file(SAMPLE_HTML_FALLBACK, company_name="Fallback Labs")

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.source_type, "html")
        self.assertEqual(record.company_name, "Fallback Labs")
        self.assertEqual(record.title, "Data Platform Engineer")
        self.assertIn("Taipei, Taiwan", record.location_text or "")
        self.assertIn("Remote option available", record.description_text)

    def test_greenhouse_adapter_parses_api_payload(self) -> None:
        payload = {
            "jobs": [
                {
                    "id": 12345,
                    "title": "Firmware Engineer",
                    "absolute_url": "https://boards.greenhouse.io/example/jobs/12345",
                    "content": "<p>Build hardware control software.</p>",
                    "internal_job_id": 777,
                    "updated_at": "2026-03-25",
                    "departments": [{"name": "Hardware Engineering"}],
                    "offices": [{"name": "Taipei"}],
                }
            ]
        }

        class FakeResponse:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:
                return False

        with patch("apps.pipeline.adapters.greenhouse.urllib.request.urlopen", return_value=FakeResponse(json.dumps(payload).encode("utf-8"))):
            records = greenhouse.fetch_greenhouse_board("example")

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.source_type, "greenhouse")
        self.assertEqual(record.external_job_id, "12345")
        self.assertEqual(record.title, "Firmware Engineer")
        self.assertEqual(record.company_name, "example")
        self.assertEqual(record.location_text, "Taipei")
        self.assertIn("hardware control software", record.description_text.lower())

    def test_import_and_normalize_resolve_aliases(self) -> None:
        imported = normalize.import_raw_inputs(self.db_path, SAMPLE_RAW_INPUT_DIR)
        self.assertEqual(imported, 2)

        with db.connect(self.db_path) as conn:
            db.insert_raw_jobs(conn, [ALIAS_RAW_JOB])
            conn.commit()

        summary = normalize.normalize_all(self.db_path, COMPANY_ALIASES)
        self.assertEqual(summary["raw_rows"], 3)
        self.assertEqual(summary["companies_upserted"], 3)
        self.assertEqual(summary["jobs_upserted"], 3)

        with db.connect(self.db_path) as conn:
            companies = [dict(row) for row in db.fetch_all(conn, "SELECT * FROM companies ORDER BY id ASC")]
            jobs = [dict(row) for row in db.fetch_all(conn, "SELECT * FROM jobs ORDER BY id ASC")]

        self.assertEqual({company["id"] for company in companies}, {"company:nvidia", "company:openai"})
        self.assertEqual({company["name"] for company in companies}, {"NVIDIA", "OpenAI"})

        job_map = {job["external_id"]: job for job in jobs}
        self.assertEqual(job_map["12345"]["company_id"], "company:nvidia")
        self.assertEqual(job_map["12345"]["remote_mode"], "hybrid")
        self.assertEqual(job_map["98765"]["remote_mode"], "remote")
        self.assertEqual(job_map["alias-001"]["company_id"], "company:openai")
        self.assertEqual(job_map["alias-001"]["title_normalized"], "platform engineer")

    def test_enrich_populates_structured_shape(self) -> None:
        self._seed_sample_db()
        result = enrich.enrich_jobs(self.db_path, SKILL_TAXONOMY)

        self.assertEqual(result["jobs_processed"], 3)
        self.assertGreater(result["skills_upserted"], 0)
        self.assertGreater(result["edges_upserted"], 0)

        with db.connect(self.db_path) as conn:
            enrichments = [dict(row) for row in db.fetch_all(conn, "SELECT * FROM job_enrichment ORDER BY job_id ASC")]
            edges = [dict(row) for row in db.fetch_all(conn, "SELECT * FROM job_skill_edges ORDER BY job_id ASC, skill_id ASC")]
            skills = [dict(row) for row in db.fetch_all(conn, "SELECT * FROM skills ORDER BY id ASC")]

        self.assertEqual(len(enrichments), 3)
        self.assertGreaterEqual(len(skills), 6)
        self.assertGreaterEqual(len(edges), 6)

        nvidia = next(row for row in enrichments if row["job_id"] == "job:nvidia:12345")
        self.assertEqual(nvidia["model_name"], "heuristic")
        self.assertEqual(nvidia["prompt_version"], "n/a")
        self.assertIsInstance(json.loads(nvidia["responsibilities_json"]), list)
        self.assertIsInstance(json.loads(nvidia["qualifications_json"]), list)
        self.assertIsInstance(json.loads(nvidia["evidence_json"]), list)
        self.assertIsNotNone(nvidia["summary"])
        self.assertIn(nvidia["role_family"], {"hardware", "photonics", "machine-learning", "data", "software", None})

    def test_build_graph_exports_read_models(self) -> None:
        self._seed_sample_db()
        enrich.enrich_jobs(self.db_path, SKILL_TAXONOMY)

        out_dir = self.root / "public"
        counts = build_public_graph(self.db_path, out_dir)

        for filename in [
            "jobs.json",
            "companies.json",
            "skills.json",
            "graph.full.json",
            "company_jobs.json",
            "skill_jobs.json",
            "job_skills.json",
            "company_skill_stats.json",
            "job_neighbors.json",
            "search-index.json",
            "summary.json",
        ]:
            self.assertTrue((out_dir / filename).exists(), filename)

        summary = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        jobs = json.loads((out_dir / "jobs.json").read_text(encoding="utf-8"))
        companies = json.loads((out_dir / "companies.json").read_text(encoding="utf-8"))
        skills = json.loads((out_dir / "skills.json").read_text(encoding="utf-8"))
        graph = json.loads((out_dir / "graph.full.json").read_text(encoding="utf-8"))
        company_jobs = json.loads((out_dir / "company_jobs.json").read_text(encoding="utf-8"))
        job_neighbors = json.loads((out_dir / "job_neighbors.json").read_text(encoding="utf-8"))
        search_index = json.loads((out_dir / "search-index.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["counts"]["companies"], len(companies))
        self.assertEqual(summary["counts"]["jobs"], len(jobs))
        self.assertEqual(summary["counts"]["skills"], len(skills))
        self.assertEqual(counts["companies"], len(companies))
        self.assertEqual(counts["jobs"], len(jobs))
        self.assertEqual(counts["skills"], len(skills))
        self.assertEqual(set(company_jobs), {company["id"] for company in companies})
        self.assertEqual(set(job_neighbors), {job["id"] for job in jobs})
        self.assertEqual(len(search_index), len(jobs) + len(companies) + len(skills))
        self.assertIn("company", {node["type"] for node in graph["nodes"]})
        self.assertIn("job", {node["type"] for node in graph["nodes"]})
        self.assertIn("skill", {node["type"] for node in graph["nodes"]})
        self.assertTrue({"POSTS", "REQUIRES", "PREFERS"}.issubset({edge["type"] for edge in graph["edges"]}))

    def test_source_registry_supports_typed_and_legacy_sources(self) -> None:
        config_dir = self.root / "configs"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_path = config_dir / "source-config.json"

        payload = {
            "sources": [
                {
                    "name": "typed-greenhouse",
                    "type": "greenhouse",
                    "enabled": True,
                    "config": {"board": "demo-board"},
                },
                {
                    "name": "typed-jsonld",
                    "type": "jsonld",
                    "enabled": True,
                    "config": {"html_file": str(SAMPLE_JOBPOSTING_HTML)},
                },
                {
                    "name": "legacy-html",
                    "kind": "html",
                    "enabled": True,
                    "html_file": str(SAMPLE_HTML_FALLBACK),
                    "company_name": "Fallback Labs",
                },
                {
                    "name": "disabled-lever",
                    "type": "lever",
                    "enabled": False,
                    "config": {"account": "openai"},
                },
                {
                    "name": "bad-ashby",
                    "type": "ashby",
                    "enabled": True,
                    "config": {},
                },
            ]
        }
        config_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        typed_greenhouse = RawJob(
            source_type="greenhouse",
            source_url="https://boards.greenhouse.io/demo/jobs/1",
            title="Platform Engineer",
            company_name="Demo Co",
            fetched_at="2026-03-25T00:00:00+00:00",
            external_job_id="1",
            description_text="Build Python services.",
            description_html="<p>Build Python services.</p>",
            metadata={},
        )

        with patch(
            "apps.pipeline.source_registry.fetch_greenhouse_board",
            return_value=[typed_greenhouse],
        ) as greenhouse_fetch:
            summary = source_registry.run_source_registry(config_path, self.root / "source-out", continue_on_error=True)

        self.assertEqual(greenhouse_fetch.call_count, 1)
        self.assertEqual(summary["sources_total"], 5)
        self.assertEqual(summary["sources_seen"], 5)
        self.assertEqual(summary["sources_processed"], 3)
        self.assertEqual(summary["sources_succeeded"], 3)
        self.assertEqual(summary["sources_failed"], 1)
        self.assertEqual(summary["sources_skipped"], 1)
        self.assertEqual(summary["records_seen"], 3)
        self.assertEqual(summary["records_written"], 3)
        self.assertEqual(summary["status"], "error")
        self.assertEqual(len(summary["output_files"]), 3)

        results = {item["name"]: item for item in summary["results"]}
        self.assertEqual(results["typed-greenhouse"]["type"], "greenhouse")
        self.assertEqual(results["typed-greenhouse"]["seen"], 1)
        self.assertEqual(results["typed-greenhouse"]["succeeded"], 1)
        self.assertEqual(results["typed-greenhouse"]["output_files"], [results["typed-greenhouse"]["out_path"]])
        self.assertEqual(results["typed-jsonld"]["type"], "jsonld")
        self.assertEqual(results["legacy-html"]["type"], "html")
        self.assertEqual(results["disabled-lever"]["status"], "skipped")
        self.assertEqual(results["disabled-lever"]["skipped"], 1)
        self.assertEqual(results["bad-ashby"]["status"], "error")
        self.assertEqual(results["bad-ashby"]["failed"], 1)

        report_path = self.root / "source-out" / "source-registry-report.json"
        self.assertTrue(report_path.exists())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["sources_failed"], 1)
        self.assertEqual(report["sources_skipped"], 1)
        self.assertEqual(report["results"][0]["config"]["board"], "demo-board")
        self.assertEqual(report["results"][1]["config"]["html_file"], str(SAMPLE_JOBPOSTING_HTML))

    def test_iter_input_paths_ignores_report_sidecars(self) -> None:
        raw_dir = self.root / "raw-inputs"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "jobs.jsonl").write_text('{"source_type":"x"}\n', encoding="utf-8")
        (raw_dir / "crawler.report.json").write_text('{"jobs_emitted":1}', encoding="utf-8")
        (raw_dir / "source-registry-report.json").write_text('{"status":"ok"}', encoding="utf-8")

        paths = iter_input_paths(raw_dir)

        self.assertEqual(paths, [raw_dir / "jobs.jsonl"])


class HeuristicChineseTests(unittest.TestCase):
    """I-4 smoke tests: heuristic provider must extract skills from Chinese postings."""

    @classmethod
    def setUpClass(cls) -> None:
        from apps.pipeline.providers.heuristic import HeuristicEnrichmentProvider, load_taxonomy

        cls.provider = HeuristicEnrichmentProvider(taxonomy=load_taxonomy(SKILL_TAXONOMY))

    def test_chinese_tencent_backend_posting_hits_skills(self) -> None:
        job = {
            "id": "job:tencent:demo-1",
            "title": "高级后端开发工程师 - 推荐算法方向",
            "description_text": (
                "岗位职责：负责腾讯视频推荐系统的后端服务开发，使用 Java 和 Go 构建高并发微服务。"
                "结合机器学习与深度学习优化推荐效果。\n"
                "任职要求：3年以上后端开发经验，精通 Java 或 Go，熟悉分布式系统。熟悉 SQL 数据库。\n"
                "加分项：有大模型 LLM 落地经验，熟悉 Kubernetes 和 Docker。"
            ),
        }
        result = self.provider.enrich(job)
        labels = {s.label for s in result.skills}
        # At least 2 skills from a Chinese posting (acceptance criteria for I-4)
        self.assertGreaterEqual(len(result.skills), 2, f"expected ≥2 skills, got {labels}")
        # Spot-check Chinese-only matches (no English equivalents in description)
        self.assertIn("Backend", labels)
        self.assertIn("Recommendation Systems", labels)
        self.assertEqual(result.role_family, "machine-learning")
        self.assertEqual(result.seniority, "senior")

    def test_chinese_bytedance_campus_posting_hits_skills(self) -> None:
        job = {
            "id": "job:bytedance:campus-1",
            "title": "2026校招 - 算法工程师（多模态方向）",
            "description_text": (
                "工作职责：负责字节跳动短视频的多模态算法研究与落地，包括 NLP、CV 与大模型的融合。\n"
                "岗位要求：本科及以上学历，应届毕业生。熟悉 Python，了解 PyTorch。熟练使用 SQL。\n"
                "优先考虑：有 LLM 大模型相关项目经验。"
            ),
        }
        result = self.provider.enrich(job)
        labels = {s.label for s in result.skills}
        self.assertGreaterEqual(len(result.skills), 2, f"expected ≥2 skills, got {labels}")
        self.assertIn("Multimodal", labels)
        self.assertIn("Python", labels)
        self.assertEqual(result.seniority, "entry")  # 应届/校招

    def test_section_pattern_distinguishes_required_vs_preferred_chinese(self) -> None:
        from apps.pipeline.providers.heuristic import SECTION_PATTERNS

        self.assertIsNotNone(SECTION_PATTERNS["required"].search("任职要求："))
        self.assertIsNotNone(SECTION_PATTERNS["responsibilities"].search("岗位职责："))
        self.assertIsNotNone(SECTION_PATTERNS["preferred"].search("加分项："))
        self.assertIsNotNone(SECTION_PATTERNS["preferred"].search("优先考虑："))

    def test_english_patterns_still_work(self) -> None:
        """Regression: do not break the existing English heuristic."""
        job = {
            "id": "job:openai:legacy",
            "title": "Senior Machine Learning Engineer",
            "description_text": (
                "Responsibilities: Build ML pipelines. "
                "Required: Python, SQL, machine learning. "
                "Nice to have: LLM experience."
            ),
        }
        result = self.provider.enrich(job)
        labels = {s.label for s in result.skills}
        self.assertIn("Python", labels)
        self.assertIn("SQL", labels)
        self.assertIn("Machine Learning", labels)
        self.assertEqual(result.seniority, "senior")


if __name__ == "__main__":
    unittest.main()
