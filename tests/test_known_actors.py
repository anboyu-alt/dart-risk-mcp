import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestKnownActors(unittest.TestCase):
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

    def test_lookup_returns_records(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {
            "신승수": [{"source": "DART 임원현황", "evidence": "CG인바이츠 등기임원",
                       "url": "https://dart.fss.or.kr", "date": "2024", "tags": ["겸직"]}]
        }})
        recs = lookup_actor("신승수")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["source"], "DART 임원현황")

    def test_lookup_unknown_returns_empty(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {}})
        self.assertEqual(lookup_actor("유령"), [])

    def test_lookup_strips_and_handles_blank(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {"신승수": [{"source": "X", "evidence": "y"}]}})
        self.assertEqual(len(lookup_actor("  신승수  ")), 1)
        self.assertEqual(lookup_actor(""), [])

    def test_load_missing_file_returns_empty(self):
        from dart_risk_mcp.core.known_actors import load_known_actors
        # 파일 미생성 상태
        self.assertEqual(load_known_actors(), {"version": 1, "actors": {}})

    def test_load_corrupt_returns_empty(self):
        from dart_risk_mcp.core.known_actors import load_known_actors
        Path(self._path).write_text("{ broken", encoding="utf-8")
        self.assertEqual(load_known_actors(), {"version": 1, "actors": {}})


if __name__ == "__main__":
    unittest.main()
