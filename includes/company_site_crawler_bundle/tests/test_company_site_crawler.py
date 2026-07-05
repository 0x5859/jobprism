import json
import unittest

from company_site_crawler import (
    RawJob,
    build_bytedance_stub_from_json_item,
    build_tencent_stub_from_json_item,
    canonicalize_bytedance_detail_url,
    canonicalize_tencent_detail_url,
    extract_url_job_id,
    merge_description_sections,
    normalize_date_string,
    parse_body_sections,
    utc_now_iso,
)


class CanonicalizationTests(unittest.TestCase):
    def test_bytedance_canonicalization_strips_tracking(self):
        url = (
            "https://jobs.bytedance.com/campus/position/7210243621324671288/detail"
            "?external_referral_code=2JV7GXE&recomId=abc&sourceJobId=123"
        )
        self.assertEqual(
            canonicalize_bytedance_detail_url(url),
            "https://jobs.bytedance.com/campus/position/7210243621324671288/detail",
        )

    def test_tencent_canonicalization_prefers_postid(self):
        url = (
            "https://join.qq.com/post_detail.html?postId=1150926126932393984"
            "&activity=123&from=foo"
        )
        self.assertEqual(
            canonicalize_tencent_detail_url(url),
            "https://join.qq.com/post_detail.html?postid=1150926126932393984",
        )

    def test_extract_url_job_id(self):
        self.assertEqual(
            extract_url_job_id("https://jobs.bytedance.com/campus/position/7210243621324671288/detail"),
            "7210243621324671288",
        )
        self.assertEqual(
            extract_url_job_id("https://join.qq.com/post_detail.html?id=114&pid=2&tid=2"),
            "114",
        )


class ParsingTests(unittest.TestCase):
    def test_parse_body_sections(self):
        text = """
        职位描述
        负责模型训练与优化。
        职位要求
        2026届硕士或博士。
        相关职位
        其他岗位
        """
        sections = parse_body_sections(text)
        self.assertEqual(sections["职位描述"], "负责模型训练与优化。")
        self.assertEqual(sections["职位要求"], "2026届硕士或博士。")
        merged = merge_description_sections(sections, ("职位描述", "职位要求"))
        self.assertIn("职位描述", merged)
        self.assertIn("职位要求", merged)

    def test_normalize_date_string(self):
        self.assertEqual(normalize_date_string("2026年4月6日"), "2026-04-06")
        self.assertEqual(normalize_date_string("2026/4/6 12:30"), "2026-04-06 12:30")


class StubBuilderTests(unittest.TestCase):
    def test_build_bytedance_stub(self):
        item = {
            "id": "7210243621324671288",
            "title": "机器人算法研究实习生-Seed",
            "city": "北京",
            "recruitType": "日常实习",
        }
        stub = build_bytedance_stub_from_json_item(item)
        self.assertIsNotNone(stub)
        assert stub is not None
        self.assertEqual(stub.external_job_id_hint, "7210243621324671288")
        self.assertEqual(stub.detail_url, "https://jobs.bytedance.com/campus/position/7210243621324671288/detail")

    def test_build_tencent_stub(self):
        item = {
            "id": "114",
            "pid": "2",
            "tid": "2",
            "title": "测试开发",
            "location": ["深圳", "北京"],
            "employmentType": "应届实习",
        }
        stub = build_tencent_stub_from_json_item(item)
        self.assertIsNotNone(stub)
        assert stub is not None
        self.assertEqual(stub.detail_url, "https://join.qq.com/post_detail.html?id=114&pid=2&tid=2")
        self.assertEqual(stub.location_hint, "深圳 / 北京")


class RawJobTests(unittest.TestCase):
    def test_raw_job_validation(self):
        record = RawJob(
            source_type="company_site",
            source_url="https://join.qq.com/post_detail.html?id=114&pid=2&tid=2",
            title="测试开发",
            company_name="腾讯",
            fetched_at=utc_now_iso(),
            external_job_id="114",
            description_text="岗位描述",
            metadata={"company_slug": "tencent"},
        )
        line = record.to_json()
        parsed = json.loads(line)
        self.assertEqual(parsed["external_job_id"], "114")


if __name__ == "__main__":
    unittest.main()
