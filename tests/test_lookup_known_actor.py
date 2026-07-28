import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestLookupKnownActor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = str(Path(self._tmp.name) / "ka.json")
        Path(self._path).write_text(json.dumps({"version": 1, "actors": {
            "신승수": [{"source": "DART 임원현황", "evidence": "CG인바이츠 등기임원",
                       "url": "https://dart.fss.or.kr", "date": "2024", "tags": ["겸직"]}]
        }}, ensure_ascii=False), encoding="utf-8")
        self._env = patch.dict("os.environ", {"DART_KNOWN_ACTORS_PATH": self._path})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_known_person_renders_evidence_and_disclaimer(self):
        from dart_risk_mcp.server import lookup_known_actor
        out = lookup_known_actor("신승수")
        self.assertIn("CG인바이츠", out)
        self.assertIn("DART 임원현황", out)
        self.assertIn("판정", out)          # 면책 문구
        self.assertIn("동명이인", out)

    def test_unknown_person(self):
        from dart_risk_mcp.server import lookup_known_actor
        self.assertIn("없습니다", lookup_known_actor("유령"))

    def test_auto_matched_marked_with_strong_warning(self):
        import json
        from pathlib import Path
        from dart_risk_mcp.server import lookup_known_actor
        Path(self._path).write_text(json.dumps({"version": 1, "actors": {
            "이준민": [{"source": "DART CB인수(자동매칭)", "status": "auto_matched",
                       "evidence": "△△전자 CB 인수자로 등장", "url": "https://dart.fss.or.kr",
                       "date": "2026-06", "rcept_no": "20260612000123",
                       "tags": ["자동 매칭", "동명이인 미확인"]}]
        }}, ensure_ascii=False), encoding="utf-8")
        out = lookup_known_actor("이준민")
        self.assertIn("자동 매칭", out)
        self.assertIn("동명이인", out)
        self.assertIn("동일인 여부", out)   # 강한 경고 문구

    def test_blank_status_treated_as_unverified(self):
        # 최종 리뷰 Finding 1: Notion 파서가 status select 비어있는 행을
        # 내보내면 키는 있고 값이 ""인 레코드가 된다. `== "auto_matched"`
        # 동등비교였다면 이 경우 아무 경고도 안 붙어 미검증 실명이 검증된
        # 것처럼 보였다 — actor_status 화이트리스트로 강등돼야 한다.
        import json
        from pathlib import Path
        from dart_risk_mcp.server import lookup_known_actor
        Path(self._path).write_text(json.dumps({"version": 1, "actors": {
            "이준민": [{"source": "자동 발굴", "status": "",
                       "evidence": "△△전자 CB 인수자로 등장"}]
        }}, ensure_ascii=False), encoding="utf-8")
        out = lookup_known_actor("이준민")
        self.assertIn("자동 매칭", out)
        self.assertIn("동일인 여부", out)   # 강한 경고 문구

    def test_none_status_treated_as_unverified(self):
        import json
        from pathlib import Path
        from dart_risk_mcp.server import lookup_known_actor
        Path(self._path).write_text(json.dumps({"version": 1, "actors": {
            "이준민": [{"source": "자동 발굴", "status": None,
                       "evidence": "△△전자 CB 인수자로 등장"}]
        }}, ensure_ascii=False), encoding="utf-8")
        out = lookup_known_actor("이준민")
        self.assertIn("자동 매칭", out)
        self.assertIn("동일인 여부", out)

    def test_unknown_status_treated_as_unverified(self):
        import json
        from pathlib import Path
        from dart_risk_mcp.server import lookup_known_actor
        Path(self._path).write_text(json.dumps({"version": 1, "actors": {
            "이준민": [{"source": "자동 발굴", "status": "오타",
                       "evidence": "△△전자 CB 인수자로 등장"}]
        }}, ensure_ascii=False), encoding="utf-8")
        out = lookup_known_actor("이준민")
        self.assertIn("자동 매칭", out)
        self.assertIn("동일인 여부", out)

    def test_maintainer_seed_marked_distinctly(self):
        # 제작자 등록(근거 사후 확보) 인물은 verified와 구분 표기 + 강한 면책
        import json
        from pathlib import Path
        from dart_risk_mcp.server import lookup_known_actor
        Path(self._path).write_text(json.dumps({"version": 1, "actors": {
            "이준민": [{"source": "제작자 모니터링 등록", "status": "maintainer_seed",
                       "evidence": "제작자가 모니터링 대상으로 등록", "url": "", "date": "",
                       "tags": ["제작자 시드"]}]
        }}, ensure_ascii=False), encoding="utf-8")
        out = lookup_known_actor("이준민")
        self.assertIn("제작자 모니터링 등록", out)
        self.assertIn("공시 자동매칭이 아닌", out)   # 제작자 판단 면책
        self.assertIn("동명이인", out)


if __name__ == "__main__":
    unittest.main()
