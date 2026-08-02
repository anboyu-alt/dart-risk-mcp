"""resolve_corp의 옛 상호(상호변경) 별칭 해석 — 단위 테스트.

배경: DART corpCode.xml은 상호변경 시 옛 이름을 지운다(예: 297570
알로이스→아틀라스링크). 뷰어(docs/tool/corp-aliases.json)는 이미 이
별칭 맵으로 옛 상호 검색을 해석해 왔고, core도 `load_corp_aliases`로
동일 데이터를 재사용해 resolve_corp에서 해석한다.

우선순위: env DART_CORP_ALIASES_PATH > 레포 상대 docs/tool/corp-aliases.json
(개발 체크아웃) > 원격(24h 파일 캐시) > {}.
"""

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import dart_risk_mcp.core.dart_client as dc


class TestResolveCorpAliases(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = str(Path(self._tmp.name) / "aliases.json")
        self._env = patch.dict("os.environ", {"DART_CORP_ALIASES_PATH": self._path})
        self._env.start()

        # resolve_corp가 _load_corp_codes를 다시 타지 않도록 _corp_cache를
        # 직접 주입한다(기존 dart_client 테스트들의 전역 주입 관행과 동일).
        self._orig_corp_cache = dict(dc._corp_cache)
        dc._corp_cache.clear()
        dc._corp_cache.update({
            "아틀라스링크": {"corp_code": "01309795", "stock_code": "297570"},
            "삼성전자": {"corp_code": "00126380", "stock_code": "005930"},
            # 알로이스형 동명 충돌: 별개의 죽은 법인이 같은 이름으로 존재
            "알로이스": {"corp_code": "01194892", "stock_code": ""},
        })

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()
        dc._corp_cache.clear()
        dc._corp_cache.update(self._orig_corp_cache)

    def _write(self, data):
        Path(self._path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # (a) 옛 상호 정확 입력(현재명에 없음) → current로 해석 + alias_note
    def test_old_name_resolves_to_current_with_note(self):
        self._write({"알로이스구버전": {
            "corp_code": "01309795", "stock_code": "297570", "current": "아틀라스링크",
        }})
        name, info = dc.resolve_corp("알로이스구버전", "dummy-key")
        self.assertEqual(name, "아틀라스링크")
        self.assertEqual(info["corp_code"], "01309795")
        self.assertIn("alias_note", info)
        self.assertIn("아틀라스링크", info["alias_note"])
        self.assertIn("알로이스구버전", info["alias_note"])

    # (b) 알로이스형 동명 충돌 → 기존 정확 매칭 유지 + 병기 note (자동 전환 없음)
    def test_name_collision_keeps_exact_match_with_conflict_note(self):
        self._write({"알로이스": {
            "corp_code": "01309795", "stock_code": "297570", "current": "아틀라스링크",
        }})
        name, info = dc.resolve_corp("알로이스", "dummy-key")
        # 기존 정확 일치(동명의 죽은 법인)가 그대로 반환된다 — 자동 전환 안 함
        self.assertEqual(name, "알로이스")
        self.assertEqual(info["corp_code"], "01194892")
        self.assertIn("alias_note", info)
        self.assertIn("아틀라스링크", info["alias_note"])
        self.assertIn("참고", info["alias_note"])

    # (c) 별칭 파일 없음/빈 파일/깨진 JSON → 기존 동작 그대로(예외 없음)
    def test_missing_alias_file_no_crash(self):
        # self._path를 가리키지만 파일 자체를 만들지 않음
        name, info = dc.resolve_corp("삼성전자", "dummy-key")
        self.assertEqual(name, "삼성전자")
        self.assertNotIn("alias_note", info)

    def test_empty_alias_file_no_crash(self):
        self._write({})
        name, info = dc.resolve_corp("삼성전자", "dummy-key")
        self.assertEqual(name, "삼성전자")
        self.assertNotIn("alias_note", info)

    def test_broken_json_alias_file_no_crash(self):
        Path(self._path).write_text("{not valid json", encoding="utf-8")
        name, info = dc.resolve_corp("삼성전자", "dummy-key")
        self.assertEqual(name, "삼성전자")
        self.assertNotIn("alias_note", info)
        # load_corp_aliases 자체도 예외 없이 {}를 반환해야 한다
        self.assertEqual(dc.load_corp_aliases(), {})

    # (d) 부분 일치보다 별칭 정확 일치가 우선하는 순서
    def test_alias_exact_match_wins_over_partial_match(self):
        self._write({"삼성전": {
            "corp_code": "99999999", "stock_code": "999999", "current": "삼성전자",
        }})
        # "삼성전"은 _corp_cache 부분 일치로도 "삼성전자"를 찾을 수 있지만,
        # 별칭 정확 일치가 먼저 걸려 그 경로(alias_note 有)로 해석돼야 한다.
        name, info = dc.resolve_corp("삼성전", "dummy-key")
        self.assertEqual(name, "삼성전자")
        self.assertIn("alias_note", info)

    def test_partial_match_still_works_without_alias_hit(self):
        name, info = dc.resolve_corp("아틀라스", "dummy-key")
        self.assertEqual(name, "아틀라스링크")
        self.assertNotIn("alias_note", info)

    def test_alias_current_not_in_corp_cache_falls_back_to_code_lookup(self):
        # current 이름 자체가 _corp_cache에 없어도(예: 정식명 표기 차이),
        # corp_code로 역조회해 실제 캐시 엔트리를 찾아 반환한다.
        self._write({"옛이름": {
            "corp_code": "01309795", "stock_code": "297570", "current": "표기다른이름",
        }})
        name, info = dc.resolve_corp("옛이름", "dummy-key")
        self.assertEqual(name, "아틀라스링크")  # corp_code 역조회 결과
        self.assertEqual(info["corp_code"], "01309795")
        self.assertIn("alias_note", info)


class TestLoadCorpAliasesRemoteFallback(unittest.TestCase):
    """env·레포 상대 파일이 모두 없을 때의 원격 24h 캐시 경로."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._cache_dir = Path(self._tmp.name) / "cache"
        self._repo_path_patch = patch.object(
            dc, "_repo_relative_aliases_path",
            return_value=Path(self._tmp.name) / "does-not-exist" / "corp-aliases.json",
        )
        self._cache_dir_patch = patch.object(dc, "_CACHE_DIR", self._cache_dir)
        self._env_patch = patch.dict("os.environ", {}, clear=False)
        for p in (self._repo_path_patch, self._cache_dir_patch, self._env_patch):
            p.start()
        import os
        os.environ.pop("DART_CORP_ALIASES_PATH", None)

    def tearDown(self):
        for p in (self._repo_path_patch, self._cache_dir_patch, self._env_patch):
            p.stop()
        self._tmp.cleanup()

    def _fake_response(self, payload):
        class _Resp:
            status_code = 200
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return _Resp()

    def test_remote_fetch_caches_and_reuses_within_24h(self):
        payload = {"옛이름": {"corp_code": "c1", "stock_code": "111111", "current": "새이름"}}
        with patch.object(dc, "_retry", return_value=self._fake_response(payload)) as mock_retry:
            data1 = dc.load_corp_aliases()
            self.assertEqual(data1, payload)
            self.assertEqual(mock_retry.call_count, 1)

            cache_file = self._cache_dir / "corp_aliases.json"
            self.assertTrue(cache_file.exists())

            # 두 번째 호출은 24h 이내 파일 캐시를 써서 네트워크를 다시 타지 않는다
            data2 = dc.load_corp_aliases()
            self.assertEqual(data2, payload)
            self.assertEqual(mock_retry.call_count, 1)

    def test_stale_cache_refetches(self):
        payload = {"옛이름": {"corp_code": "c1", "stock_code": "111111", "current": "새이름"}}
        with patch.object(dc, "_retry", return_value=self._fake_response(payload)) as mock_retry:
            dc.load_corp_aliases()
            self.assertEqual(mock_retry.call_count, 1)

            cache_file = self._cache_dir / "corp_aliases.json"
            # 캐시 파일을 24시간보다 오래된 것처럼 만든다
            old_time = time.time() - 90000
            import os
            os.utime(cache_file, (old_time, old_time))

            dc.load_corp_aliases()
            self.assertEqual(mock_retry.call_count, 2)

    def test_remote_failure_returns_empty_dict(self):
        with patch.object(dc, "_retry", side_effect=Exception("network down")):
            self.assertEqual(dc.load_corp_aliases(), {})

    def test_remote_non_200_returns_empty_dict(self):
        class _Resp:
            status_code = 500
            content = b""
        with patch.object(dc, "_retry", return_value=_Resp()):
            self.assertEqual(dc.load_corp_aliases(), {})


if __name__ == "__main__":
    unittest.main()
