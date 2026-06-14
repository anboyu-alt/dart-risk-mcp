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
