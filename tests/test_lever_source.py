from __future__ import annotations

import json
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from apps.pipeline import source_registry
from apps.pipeline.adapters import lever


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


class LeverSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)

    def test_adapter_parses_fixture_payload(self) -> None:
        payload = LEVER_FIXTURE.read_text(encoding="utf-8").encode("utf-8")

        with patch(
            "apps.pipeline.adapters.lever.urllib.request.urlopen",
            return_value=FakeResponse(payload),
        ):
            records = lever.fetch_lever_postings("acme")

        self.assertEqual(len(records), 2)
        first, second = records
        self.assertEqual(first.source_type, "lever")
        self.assertEqual(first.external_job_id, "lever-001")
        self.assertEqual(first.company_name, "acme")
        self.assertEqual(first.title, "Platform Engineer")
        self.assertEqual(first.location_text, "Taipei, Taiwan")
        self.assertEqual(first.employment_type, "full-time")
        self.assertIn("Python services", first.description_text)

        self.assertEqual(second.external_job_id, "lever-002")
        self.assertEqual(second.location_text, "Remote")
        self.assertEqual(second.employment_type, "contract")
        self.assertIn("internal APIs", second.description_text)

    def test_registry_emits_lever_source_report(self) -> None:
        config_path = self.root / "source-config.json"
        out_dir = self.root / "out"
        payload = LEVER_FIXTURE.read_text(encoding="utf-8").encode("utf-8")
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

        with patch(
            "apps.pipeline.adapters.lever.urllib.request.urlopen",
            return_value=FakeResponse(payload),
        ):
            summary = source_registry.run_source_registry(config_path, out_dir)

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["sources_total"], 1)
        self.assertEqual(summary["sources_seen"], 1)
        self.assertEqual(summary["sources_succeeded"], 1)
        self.assertEqual(summary["sources_failed"], 0)
        self.assertEqual(summary["sources_skipped"], 0)
        self.assertEqual(summary["records_seen"], 2)
        self.assertEqual(summary["records_written"], 2)
        self.assertEqual(summary["output_files"], [str(out_dir / "acme-lever.jsonl")])

        result = summary["results"][0]
        self.assertEqual(result["type"], "lever")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["seen"], 2)
        self.assertEqual(result["succeeded"], 2)
        self.assertEqual(result["output_files"], [str(out_dir / "acme-lever.jsonl")])

        report_path = out_dir / "source-registry-report.json"
        self.assertTrue(report_path.exists())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["sources_total"], 1)
        self.assertEqual(report["results"][0]["type"], "lever")


if __name__ == "__main__":
    unittest.main()
