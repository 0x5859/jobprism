from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.pipeline import db, enrich, normalize
from apps.pipeline.build_graph import build_public_graph
from apps.pipeline.cli import _pipeline_stage_plan, _run_pipeline_command


REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RAW_INPUT_DIR = REPO_ROOT / "sample-data/input"
COMPANY_ALIASES = REPO_ROOT / "config/company_aliases.json"
SKILL_TAXONOMY = REPO_ROOT / "config/skill_taxonomy.json"
LEVER_FIXTURE = REPO_ROOT / "sample-data/lever_sample_payload.json"


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class RunPipelineTests(unittest.TestCase):
    def test_pipeline_stage_plan_respects_from_to_and_skip_flags(self) -> None:
        args = argparse.Namespace(
            from_stage="enrich",
            to_stage="build_graph",
            skip_fetch=True,
            skip_build_site=False,
            config=None,
        )

        plan = _pipeline_stage_plan(args)

        self.assertEqual(plan["fetch_sources"], {"run": False, "reason": "skip_fetch"})
        self.assertEqual(plan["import_raw"]["run"], False)
        self.assertTrue(str(plan["import_raw"]["reason"]).startswith("before_from_stage"))
        self.assertEqual(plan["normalize"]["run"], False)
        self.assertEqual(plan["enrich"]["run"], True)
        self.assertEqual(plan["build_graph"]["run"], True)
        self.assertEqual(plan["build_site"]["run"], False)
        self.assertTrue(str(plan["build_site"]["reason"]).startswith("after_to_stage"))

    def test_run_pipeline_from_stage_build_site_skips_prior_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "recruit_graph.sqlite3"
            public_dir = root / "public"
            site_out = root / "dist"
            reports_dir = root / "reports"
            logs_dir = root / "logs"
            db.init_db(db_path)

            normalize.import_raw_inputs(db_path, SAMPLE_RAW_INPUT_DIR)
            normalize.normalize_all(db_path, COMPANY_ALIASES)
            enrich.enrich_jobs(db_path, SKILL_TAXONOMY)
            build_public_graph(db_path, public_dir)

            args = argparse.Namespace(
                config=None,
                raw_dir=str(root / "raw"),
                import_input=[],
                db=str(db_path),
                company_aliases=str(COMPANY_ALIASES),
                skill_taxonomy=str(SKILL_TAXONOMY),
                public_dir=str(public_dir),
                site_out=str(site_out),
                site_dir=None,
                continue_on_error=False,
                provider=None,
                provider_config_file=None,
                provider_config_json=None,
                provider_model=None,
                provider_base_url=None,
                provider_endpoint=None,
                provider_api_key=None,
                cache_path=None,
                no_cache=False,
                from_stage="build_site",
                to_stage=None,
                resume_run_id="previous-run-id",
                run_id="resumetest",
                reports_dir=str(reports_dir),
                logs_dir=str(logs_dir),
                skip_fetch=False,
                skip_build_site=False,
            )

            _run_pipeline_command(args)

            report = json.loads((reports_dir / "resumetest-run.json").read_text(encoding="utf-8"))
            stage_status = {stage["name"]: stage["status"] for stage in report["stages"]}

            self.assertEqual(report["details"]["resume_run_id"], "previous-run-id")
            self.assertEqual(report["details"]["from_stage"], "build_site")
            self.assertEqual(report["details"]["to_stage"], "build_site")
            self.assertEqual(report["details"]["requested_stages"], ["build_site"])
            self.assertEqual(
                report["details"]["skipped_stages"],
                ["fetch_sources", "import_raw", "normalize", "enrich", "build_graph"],
            )
            self.assertEqual(report["details"]["effective_stage_plan"]["build_site"]["run"], True)
            self.assertEqual(report["details"]["effective_stage_plan"]["build_graph"]["run"], False)
            self.assertEqual(stage_status["fetch_sources"], "skipped")
            self.assertEqual(stage_status["import_raw"], "skipped")
            self.assertEqual(stage_status["normalize"], "skipped")
            self.assertEqual(stage_status["enrich"], "skipped")
            self.assertEqual(stage_status["build_graph"], "skipped")
            self.assertEqual(stage_status["build_site"], "ok")
            self.assertTrue((site_out / "index.html").exists())

    def test_run_pipeline_records_lever_source_in_top_level_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "recruit_graph.sqlite3"
            raw_dir = root / "raw"
            public_dir = root / "public"
            site_out = root / "dist"
            reports_dir = root / "reports"
            logs_dir = root / "logs"
            config_path = root / "source-config.json"
            payload = LEVER_FIXTURE.read_text(encoding="utf-8").encode("utf-8")
            db.init_db(db_path)

            config_path.write_text(
                json.dumps(
                    {
                        "sources": [
                            {
                                "name": "acme-lever",
                                "type": "lever",
                                "enabled": True,
                                "config": {"account": "acme"},
                            }
                        ]
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            args = argparse.Namespace(
                config=str(config_path),
                raw_dir=str(raw_dir),
                import_input=[],
                db=str(db_path),
                company_aliases=str(COMPANY_ALIASES),
                skill_taxonomy=str(SKILL_TAXONOMY),
                public_dir=str(public_dir),
                site_out=str(site_out),
                site_dir=None,
                continue_on_error=False,
                provider=None,
                provider_config_file=None,
                provider_config_json=None,
                provider_model=None,
                provider_base_url=None,
                provider_endpoint=None,
                provider_api_key=None,
                cache_path=None,
                no_cache=False,
                from_stage=None,
                to_stage=None,
                resume_run_id=None,
                run_id="leverrun",
                reports_dir=str(reports_dir),
                logs_dir=str(logs_dir),
                skip_fetch=False,
                skip_build_site=False,
            )

            with patch(
                "apps.pipeline.adapters.lever.urllib.request.urlopen",
                return_value=FakeResponse(payload),
            ):
                _run_pipeline_command(args)

            report = json.loads((reports_dir / "leverrun-run.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "ok")
            self.assertEqual(len(report["sources"]), 1)
            source = report["sources"][0]
            self.assertEqual(source["name"], "acme-lever")
            self.assertEqual(source["status"], "ok")
            self.assertEqual(source["details"]["type"], "lever")
            self.assertEqual(source["details"]["seen"], 2)
            self.assertEqual(source["details"]["succeeded"], 2)
            self.assertEqual(
                source["details"]["output_files"],
                [str(raw_dir / "acme-lever.jsonl")],
            )


if __name__ == "__main__":
    unittest.main()
