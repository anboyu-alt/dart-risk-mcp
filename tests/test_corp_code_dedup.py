# -*- coding: utf-8 -*-
"""동명 법인 충돌 정책 — _merge_corp_entry / _load_corp_codes 캐시 버전 관리.

실측 사례(2026-08): "앤로보틱스"라는 이름으로 corpCode.xml에 법인이 2개
존재한다 — 상장(00808068, 종목 138360, modify_date 20260303, 구 협진)과
비상장(01358296, 종목 없음, modify_date 20251202, 구 나이콤). 옛
`_load_corp_codes`는 이름을 키로 쓰는 dict를 XML 등장 순서대로 마지막
항목이 덮어쓰는 구조라 어느 쪽이 남을지가 우연에 맡겨졌고, 실측으로는
상장 쪽이 소실되어 resolve_corp·뷰어 양쪽에서 검색 불가 상태였다.
"""
import io
import json
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from dart_risk_mcp.core import dart_client as dc


def _make_corp_zip(entries: list[tuple[str, str, str, str]]) -> bytes:
    """entries: [(corp_name, corp_code, stock_code, modify_date), ...] → corpCode.xml ZIP bytes."""
    items = "".join(
        f"<list><corp_code>{code}</corp_code><corp_name>{name}</corp_name>"
        f"<corp_eng_name></corp_eng_name><stock_code>{stock}</stock_code>"
        f"<modify_date>{mdate}</modify_date></list>"
        for name, code, stock, mdate in entries
    )
    xml = f"<result>{items}</result>".encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", xml)
    return buf.getvalue()


class TestMergeCorpEntry(unittest.TestCase):
    """순수 함수 단위 테스트 — 이름 충돌 정책."""

    def test_listed_wins_over_unlisted_regardless_of_order_first(self):
        cache, mdates = {}, {}
        dc._merge_corp_entry(cache, mdates, "앤로보틱스", "00808068", "138360", "20260303")
        dc._merge_corp_entry(cache, mdates, "앤로보틱스", "01358296", "", "20251202")
        self.assertEqual(cache["앤로보틱스"], {"corp_code": "00808068", "stock_code": "138360"})

    def test_listed_wins_over_unlisted_regardless_of_order_second(self):
        # 비상장이 먼저 등장하고(더 최신 modify_date라도) 상장이 나중에 나와도 상장이 이긴다.
        cache, mdates = {}, {}
        dc._merge_corp_entry(cache, mdates, "앤로보틱스", "01358296", "", "20260101")
        dc._merge_corp_entry(cache, mdates, "앤로보틱스", "00808068", "138360", "20251202")
        self.assertEqual(cache["앤로보틱스"], {"corp_code": "00808068", "stock_code": "138360"})

    def test_both_listed_newer_modify_date_wins(self):
        cache, mdates = {}, {}
        dc._merge_corp_entry(cache, mdates, "회사", "c1", "111111", "20250101")
        dc._merge_corp_entry(cache, mdates, "회사", "c2", "222222", "20260101")
        self.assertEqual(cache["회사"], {"corp_code": "c2", "stock_code": "222222"})

    def test_both_unlisted_newer_modify_date_wins(self):
        cache, mdates = {}, {}
        dc._merge_corp_entry(cache, mdates, "회사", "c1", "", "20260101")
        dc._merge_corp_entry(cache, mdates, "회사", "c2", "", "20250101")
        self.assertEqual(cache["회사"], {"corp_code": "c1", "stock_code": ""})

    def test_no_collision_single_entry_kept(self):
        cache, mdates = {}, {}
        dc._merge_corp_entry(cache, mdates, "단독회사", "c1", "999999", "20250101")
        self.assertEqual(cache["단독회사"], {"corp_code": "c1", "stock_code": "999999"})


class TestLoadCorpCodesCollision(unittest.TestCase):
    """_load_corp_codes 종단 테스트 — 앤로보틱스 실측 픽스처(상장+비상장)."""

    def setUp(self):
        self._orig_cache = dict(dc._corp_cache)
        dc._corp_cache.clear()
        self._tmp_patch = patch.object(dc, "_CACHE_DIR", Path(self._make_tmp_dir()))
        self._tmp_patch.start()

    def tearDown(self):
        self._tmp_patch.stop()
        dc._corp_cache.clear()
        dc._corp_cache.update(self._orig_cache)

    @staticmethod
    def _make_tmp_dir():
        import tempfile
        d = tempfile.mkdtemp()
        return d

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_anrobotics_listed_survives(self, mock_retry):
        raw = _make_corp_zip([
            ("앤로보틱스", "00808068", "138360", "20260303"),
            ("앤로보틱스", "01358296", "", "20251202"),
        ])
        resp = MagicMock()
        resp.status_code = 200
        resp.content = raw
        mock_retry.return_value = resp

        dc._load_corp_codes("dummy-key")

        self.assertEqual(dc._corp_cache.get("앤로보틱스"),
                          {"corp_code": "00808068", "stock_code": "138360"})

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_cache_file_written_with_version(self, mock_retry):
        raw = _make_corp_zip([("삼성전자", "00126380", "005930", "20250101")])
        resp = MagicMock()
        resp.status_code = 200
        resp.content = raw
        mock_retry.return_value = resp

        dc._load_corp_codes("dummy-key")

        cache_file = dc._CACHE_DIR / "corp_codes.json"
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
        self.assertEqual(payload["_v"], dc._CORP_CACHE_VERSION)
        self.assertEqual(payload["data"]["삼성전자"],
                          {"corp_code": "00126380", "stock_code": "005930"})

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_legacy_cache_format_triggers_redownload(self, mock_retry):
        """구버전 캐시(포맷 버전 필드 없는 평범한 dict)는 24h TTL 내여도 무시하고 재다운로드한다."""
        dc._CACHE_DIR.mkdir(parents=True, exist_ok=True)
        legacy_file = dc._CACHE_DIR / "corp_codes.json"
        legacy_file.write_text(
            json.dumps({"오염된회사": {"corp_code": "bad", "stock_code": ""}}, ensure_ascii=False),
            encoding="utf-8")

        raw = _make_corp_zip([("새회사", "c9", "999999", "20260101")])
        resp = MagicMock()
        resp.status_code = 200
        resp.content = raw
        mock_retry.return_value = resp

        dc._load_corp_codes("dummy-key")

        mock_retry.assert_called_once()
        self.assertNotIn("오염된회사", dc._corp_cache)
        self.assertEqual(dc._corp_cache.get("새회사"), {"corp_code": "c9", "stock_code": "999999"})

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_current_version_cache_within_ttl_skips_network(self, mock_retry):
        dc._CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = dc._CACHE_DIR / "corp_codes.json"
        cache_file.write_text(json.dumps({
            "_v": dc._CORP_CACHE_VERSION,
            "data": {"기존회사": {"corp_code": "c1", "stock_code": "111111"}},
        }, ensure_ascii=False), encoding="utf-8")

        dc._load_corp_codes("dummy-key")

        mock_retry.assert_not_called()
        self.assertEqual(dc._corp_cache.get("기존회사"), {"corp_code": "c1", "stock_code": "111111"})


if __name__ == "__main__":
    unittest.main()
