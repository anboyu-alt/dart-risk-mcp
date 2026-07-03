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

    def test_lookup_matches_case_variant(self):
        # 레지스트리 키 'LIU HUAN'(자동 발굴 정규화 표기)을 'Liu Huan'으로 조회해도 매칭
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {
            "LIU HUAN": [{"source": "자동 발굴", "evidence": "e"}]}})
        self.assertEqual(len(lookup_actor("Liu Huan")), 1)
        self.assertEqual(len(lookup_actor("liu  huan")), 1)

    def test_normalize_name(self):
        from dart_risk_mcp.core.known_actors import normalize_name
        self.assertEqual(normalize_name("  Liu   Huan "), "LIU HUAN")
        self.assertEqual(normalize_name("홍길동"), "홍길동")
        self.assertEqual(normalize_name(""), "")

    def test_load_missing_file_returns_empty(self):
        from dart_risk_mcp.core.known_actors import load_known_actors
        # 파일 미생성 상태
        self.assertEqual(load_known_actors(), {"version": 1, "actors": {}})

    def test_load_corrupt_returns_empty(self):
        from dart_risk_mcp.core.known_actors import load_known_actors
        Path(self._path).write_text("{ broken", encoding="utf-8")
        self.assertEqual(load_known_actors(), {"version": 1, "actors": {}})

    def test_override_skips_notion(self):
        # DART_KNOWN_ACTORS_PATH 지정 시 Notion 조회를 호출하지 않는다
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        self._write({"version": 1, "actors": {"X": [{"source": "s", "evidence": "e"}]}})
        with _p("dart_risk_mcp.core.known_actors.requests.post") as post:
            data = ka.load_known_actors()
        post.assert_not_called()
        self.assertIn("X", data["actors"])

    def _notion_page(self, name, source="자동 발굴", status="auto_matched", rcept=""):
        props = {
            "인물명": {"title": [{"plain_text": name}]},
            "source": {"rich_text": [{"plain_text": source}]},
            "status": {"select": {"name": status}},
            "evidence": {"rich_text": [{"plain_text": "e"}]},
            "url": {"url": "https://dart.fss.or.kr"},
            "date": {"rich_text": [{"plain_text": "2026-07"}]},
            "tags": {"multi_select": [{"name": "자동 발굴"}]},
            "rcept_no": {"rich_text": [{"plain_text": rcept}] if rcept else []},
        }
        return {"properties": props}

    def test_notion_fetch_when_env_set(self):
        # env 설정 + Notion 성공 → 파싱된 레지스트리 반환 + 캐시 저장
        import os
        import tempfile
        from unittest.mock import patch as _p, MagicMock
        from pathlib import Path
        from dart_risk_mcp.core import known_actors as ka
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp) / "notion.json"
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {
                    "results": [self._notion_page("LIU HUAN", rcept="R1"),
                                self._notion_page("LIU HUAN", rcept="R2"),
                                self._notion_page("신승수", source="DART 임원현황",
                                                  status="verified")],
                    "has_more": False,
                }
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache), \
                     _p("dart_risk_mcp.core.known_actors.requests.post",
                        return_value=resp) as post, \
                     _p.dict("os.environ", {"NOTION_TOKEN": "t",
                                            "DB_KNOWN_ACTORS": "db"}):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    data = ka.load_known_actors()
                post.assert_called_once()
                self.assertEqual(len(data["actors"]["LIU HUAN"]), 2)
                self.assertEqual(data["actors"]["LIU HUAN"][0]["rcept_no"], "R1")
                self.assertEqual(data["actors"]["신승수"][0]["status"], "verified")
                self.assertTrue(cache.exists())
        finally:
            self._env.start()

    def test_notion_failure_falls_back_to_bundled(self):
        # Notion 실패 → 동봉 데이터 fallback (예외 없음)
        import os
        import tempfile
        from unittest.mock import patch as _p
        from pathlib import Path
        from dart_risk_mcp.core import known_actors as ka
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp) / "notion.json"
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache), \
                     _p("dart_risk_mcp.core.known_actors.requests.post",
                        side_effect=Exception("net")), \
                     _p.dict("os.environ", {"NOTION_TOKEN": "t",
                                            "DB_KNOWN_ACTORS": "db"}):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    data = ka.load_known_actors()
                self.assertIsInstance(data.get("actors"), dict)
        finally:
            self._env.start()

    def test_no_notion_env_uses_bundled_without_network(self):
        # opt-in — env 미설정 시 네트워크 시도 없이 동봉 데이터 사용
        import os
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        self._env.stop()
        try:
            with _p("dart_risk_mcp.core.known_actors.requests.post") as post:
                for k in ("NOTION_TOKEN", "DB_KNOWN_ACTORS", "DART_KNOWN_ACTORS_PATH"):
                    os.environ.pop(k, None)
                data = ka.load_known_actors()
            post.assert_not_called()
            self.assertIsInstance(data.get("actors"), dict)
        finally:
            self._env.start()

    def test_add_registry_record_skips_without_env(self):
        import os
        from unittest.mock import patch as _p
        from dart_risk_mcp.core.known_actors import add_registry_record
        with _p("dart_risk_mcp.core.known_actors.requests.post") as post:
            for k in ("NOTION_TOKEN", "DB_KNOWN_ACTORS"):
                os.environ.pop(k, None)
            ok = add_registry_record("홍길동", {"source": "자동 발굴", "evidence": "e"})
        self.assertFalse(ok)
        post.assert_not_called()

    def test_add_registry_record_writes_with_env(self):
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core.known_actors import add_registry_record
        resp = MagicMock()
        resp.status_code = 200
        with _p("dart_risk_mcp.core.known_actors.requests.post",
                return_value=resp) as post:
            ok = add_registry_record(
                "홍길동",
                {"source": "자동 발굴", "status": "auto_matched", "evidence": "e",
                 "url": "https://dart.fss.or.kr", "date": "2026-07",
                 "tags": ["자동 발굴"], "rcept_no": "R1"},
                token="t", db_id="db")
        self.assertTrue(ok)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["parent"]["database_id"], "db")
        self.assertEqual(
            payload["properties"]["인물명"]["title"][0]["text"]["content"], "홍길동")
        self.assertEqual(
            payload["properties"]["rcept_no"]["rich_text"][0]["text"]["content"], "R1")

    def test_add_registry_record_tags_companies(self):
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core.known_actors import add_registry_record
        resp = MagicMock()
        resp.status_code = 200
        with _p("dart_risk_mcp.core.known_actors.requests.post",
                return_value=resp) as post:
            ok = add_registry_record(
                "홍길동",
                {"source": "자동 발굴", "evidence": "e",
                 "companies": ["A전자", "B바이오"]},
                token="t", db_id="db")
        self.assertTrue(ok)
        payload = post.call_args.kwargs["json"]
        names = {o["name"] for o in payload["properties"]["관련기업"]["multi_select"]}
        self.assertEqual(names, {"A전자", "B바이오"})

    def test_add_registry_record_omits_company_prop_when_empty(self):
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core.known_actors import add_registry_record
        resp = MagicMock()
        resp.status_code = 200
        with _p("dart_risk_mcp.core.known_actors.requests.post",
                return_value=resp) as post:
            add_registry_record("홍길동", {"source": "s", "evidence": "e"},
                                token="t", db_id="db")
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("관련기업", payload["properties"])

    def test_page_to_record_roundtrips_companies(self):
        from dart_risk_mcp.core.known_actors import _page_to_record
        page = {"properties": {
            "인물명": {"title": [{"plain_text": "홍길동"}]},
            "source": {"rich_text": [{"plain_text": "s"}]},
            "status": {"select": {"name": "auto_matched"}},
            "evidence": {"rich_text": [{"plain_text": "e"}]},
            "url": {"url": ""},
            "date": {"rich_text": []},
            "tags": {"multi_select": []},
            "관련기업": {"multi_select": [{"name": "A전자"}, {"name": "B바이오"}]},
        }}
        name, rec = _page_to_record(page)
        self.assertEqual(name, "홍길동")
        self.assertEqual(set(rec["companies"]), {"A전자", "B바이오"})

    def test_ensure_company_property_skips_without_env(self):
        import os
        from unittest.mock import patch as _p
        from dart_risk_mcp.core.known_actors import ensure_company_property
        with _p("dart_risk_mcp.core.known_actors.requests.patch") as patch_call:
            for k in ("NOTION_TOKEN", "DB_KNOWN_ACTORS"):
                os.environ.pop(k, None)
            ok = ensure_company_property()
        self.assertFalse(ok)
        patch_call.assert_not_called()

    def test_ensure_company_property_patches_with_env(self):
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core.known_actors import ensure_company_property
        resp = MagicMock()
        resp.status_code = 200
        with _p("dart_risk_mcp.core.known_actors.requests.patch",
                return_value=resp) as patch_call:
            ok = ensure_company_property(token="t", db_id="db")
        self.assertTrue(ok)
        payload = patch_call.call_args.kwargs["json"]
        self.assertIn("관련기업", payload["properties"])


if __name__ == "__main__":
    unittest.main()
