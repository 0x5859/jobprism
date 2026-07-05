from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from apps.pipeline.adapters.company_site import crawl_company_site_source


class CompanySiteSourceTests(unittest.TestCase):
    def test_wrapper_runs_and_loads_raw_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            script_path = tmp_path / "company_site_crawler.py"
            python_path = tmp_path / ".venv" / "bin" / "python"
            output_path = tmp_path / "out.jsonl"
            report_path = tmp_path / "out.report.json"

            script_path.write_text("# stub", encoding="utf-8")
            python_path.parent.mkdir(parents=True, exist_ok=True)
            python_path.write_text("", encoding="utf-8")

            payload = {
                "source_type": "company_site",
                "source_url": "https://example.com/jobs/123",
                "title": "Crawler Test",
                "company_name": "Example Co",
                "fetched_at": "2026-04-06T00:00:00+00:00",
                "external_job_id": "123",
                "description_text": "desc",
                "metadata": {"company_slug": "example-co"},
            }

            def fake_run(cmd, capture_output, text):  # type: ignore[no-untyped-def]
                output_path.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
                report_path.write_text('{"jobs_emitted":1}', encoding="utf-8")

                class Result:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                return Result()

            with patch("apps.pipeline.adapters.company_site.subprocess.run", side_effect=fake_run) as mocked:
                records, generated_report = crawl_company_site_source(
                    source="tencent_campus",
                    output_path=output_path,
                    report_path=report_path,
                    script_path=script_path,
                    python_bin=python_path,
                )

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].external_job_id, "123")
            self.assertEqual(generated_report, str(report_path))
            command = mocked.call_args.args[0]
            self.assertIn("--source", command)
            self.assertIn("tencent_campus", command)
            self.assertIn(str(output_path), command)


if __name__ == "__main__":
    unittest.main()
