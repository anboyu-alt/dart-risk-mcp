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

    def test_override_skips_remote(self):
        # DART_KNOWN_ACTORS_PATH 지정 시 원격 fetch를 호출하지 않는다
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        self._write({"version": 1, "actors": {"X": [{"source": "s", "evidence": "e"}]}})
        with _p("dart_risk_mcp.core.known_actors.requests.get") as get:
            data = ka.load_known_actors()
        get.assert_not_called()
        self.assertIn("X", data["actors"])

    def test_remote_fetch_when_no_cache(self):
        # 캐시 없음 + 원격 성공 → 원격 데이터 반환 + 캐시 저장
        import os
        import tempfile
        from unittest.mock import patch as _p, MagicMock
        from pathlib import Path
        from dart_risk_mcp.core import known_actors as ka
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp) / "remote.json"
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {"version": 1, "actors": {
                    "원격인물": [{"source": "DART", "evidence": "e"}]}}
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache), \
                     _p("dart_risk_mcp.core.known_actors.requests.get", return_value=resp) as get:
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    data = ka.load_known_actors()
                get.assert_called_once()
                self.assertIn("원격인물", data["actors"])
                self.assertTrue(cache.exists())
        finally:
            self._env.start()

    def test_remote_failure_falls_back_to_bundled(self):
        # 원격 실패 → 동봉 데이터 fallback (예외 없음)
        import os
        import tempfile
        from unittest.mock import patch as _p
        from pathlib import Path
        from dart_risk_mcp.core import known_actors as ka
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp) / "remote.json"
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache), \
                     _p("dart_risk_mcp.core.known_actors.requests.get", side_effect=Exception("net")):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    data = ka.load_known_actors()
                self.assertIsInstance(data.get("actors"), dict)
        finally:
            self._env.start()


if __name__ == "__main__":
    unittest.main()
