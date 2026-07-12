import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestRegistryCompanySection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = str(Path(self._tmp.name) / "ka.json")
        self._env = patch.dict("os.environ", {"DART_KNOWN_ACTORS_PATH": self._path})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _write(self, data):
        Path(self._path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_empty_when_no_match(self):
        from dart_risk_mcp.server import _registry_company_section
        self._write({"version": 1, "actors": {}})
        self.assertEqual(_registry_company_section("티쓰리"), [])

    def test_renders_matched_records_only(self):
        from dart_risk_mcp.server import _registry_company_section
        self._write({"version": 1, "actors": {
            "신승수": [
                {"source": "DART 임원현황", "evidence": "CG인바이츠 등기임원",
                 "date": "2024", "status": "verified",
                 "companies": ["CG인바이츠", "이엠앤아이"]},
                {"source": "CB 인수", "evidence": "티쓰리 CB",
                 "date": "2023", "status": "verified", "companies": ["티쓰리"]},
            ],
        }})
        lines = _registry_company_section("이엠앤아이")
        text = "\n".join(lines)
        self.assertIn("공개기록 참고", text)
        self.assertIn("사실 표기 — 판정 아님", text)
        self.assertIn("신승수 — DART 임원현황(2024)", text)
        self.assertNotIn("티쓰리 CB", text)  # 다른 회사 기록은 미표시
        # 전체 기록 수(2) > 표시(1) → 드릴다운 안내
        self.assertIn('lookup_known_actor("신승수")', text)
        self.assertIn("전체 기록 2건", text)
        # 공통 면책
        self.assertIn("동명이인 가능성", text)

    def test_status_warnings(self):
        from dart_risk_mcp.server import _registry_company_section
        self._write({"version": 1, "actors": {
            "이호영": [{"source": "자동 발굴", "evidence": "e", "date": "2025",
                       "status": "auto_matched", "companies": ["티쓰리"]}],
            "김모니": [{"source": "제작자 등록", "evidence": "e2", "date": "2025",
                       "status": "maintainer_seed", "companies": ["티쓰리"]}],
        }})
        text = "\n".join(_registry_company_section("티쓰리"))
        self.assertIn("[자동 매칭 · 동명이인 미확인] 이호영", text)
        self.assertIn("동일인 여부 미확인", text)
        self.assertIn("제작자 모니터링 등록", text)

    def test_no_drilldown_hint_when_all_shown(self):
        from dart_risk_mcp.server import _registry_company_section
        self._write({"version": 1, "actors": {
            "신승수": [{"source": "X", "evidence": "y", "status": "verified",
                       "companies": ["티쓰리"]}],
        }})
        text = "\n".join(_registry_company_section("티쓰리"))
        self.assertNotIn("lookup_known_actor", text)


if __name__ == "__main__":
    unittest.main()
