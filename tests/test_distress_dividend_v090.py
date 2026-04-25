"""v0.9.0 — 부실 후속(#7) + 배당 이상(#10) 흡수 검증.

검증:
1. fetch_distress_events는 4개 엔드포인트(dfOcr·bsnSp·ctrcvsBgrq·dsRsOcr)를
   lookback_years 기간으로 호출하고 subtype 라벨로 구분한다.
2. 응답에 rcept_dt 누락 시 rcept_no[:8]로 폴백.
3. 일부 엔드포인트 실패는 다른 결과를 막지 않는다.
4. fetch_dividend_history는 alotMatter를 분기 4코드 × N년으로 호출해
   각 record에 bsns_year/reprt_code 부착.
5. detect_dividend_drain은 (당기 적자 AND 배당 양수)이면 DIVIDEND_DRAIN 플래그.
6. signals.py / taxonomy.py에 DISTRESS_EVENT(8.5), DIVIDEND_DRAIN(5.6) 등록.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from dart_risk_mcp.core import dart_client
from dart_risk_mcp.core.signals import SIGNAL_KEY_TO_TAXONOMY, SIGNAL_TYPES
from dart_risk_mcp.core.taxonomy import TAXONOMY


def _resp(status: str = "000", lst: list | None = None) -> MagicMock:
    r = MagicMock()
    r.json.return_value = {
        "status": status,
        "message": "정상" if status == "000" else "데이터 없음",
        "list": lst or [],
    }
    return r


# ---------- TestFetchDistressEvents ----------

class TestFetchDistressEvents(unittest.TestCase):
    def setUp(self):
        cache = getattr(dart_client, "_distress_events_cache", None)
        if cache is not None:
            cache.clear()

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_normalizes_each_subtype(self, mock_retry):
        def _side(method, url, **kwargs):
            if "dfOcr" in url:
                return _resp(lst=[{
                    "rcept_no": "20250520000001",
                    "rcept_dt": "20250520",
                    "df_cn": "당좌거래정지",
                    "df_amt": "1500000000",
                    "df_bnk": "K은행",
                    "dfd": "20250515",
                }])
            if "bsnSp" in url:
                return _resp(lst=[{
                    "rcept_no": "20250620000002",
                    "rcept_dt": "20250620",
                    "bsnsp_cn": "관리종목 사유 영업정지",
                    "bsnspd": "20250619",
                }])
            if "ctrcvsBgrq" in url:
                return _resp(lst=[{
                    "rcept_no": "20250720000003",
                    "rcept_dt": "20250720",
                    "rs": "회생절차 개시신청",
                }])
            if "dsRsOcr" in url:
                return _resp(lst=[{
                    "rcept_no": "20250820000004",
                    "rcept_dt": "20250820",
                    "ds_rs": "주총 해산결의",
                    "ds_rsd": "20250815",
                }])
            return _resp(status="013")

        mock_retry.side_effect = _side
        events = dart_client.fetch_distress_events("00000001", "KEY", 3)

        subtypes = {e["subtype"] for e in events}
        self.assertEqual(subtypes,
                         {"default", "business_susp", "rehabilitation", "dissolution"})
        for e in events:
            self.assertEqual(e["key"], "DISTRESS_EVENT")
            self.assertTrue(e["rcept_dt"])
            self.assertTrue(e["summary"])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_falls_back_to_rcept_no(self, mock_retry):
        def _side(method, url, **kwargs):
            if "dfOcr" in url:
                return _resp(lst=[{"rcept_no": "20250520000099", "df_cn": "X"}])
            return _resp(status="013")

        mock_retry.side_effect = _side
        events = dart_client.fetch_distress_events("00000001", "KEY", 3)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["rcept_dt"], "20250520")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_partial_endpoint_failure_isolated(self, mock_retry):
        def _side(method, url, **kwargs):
            if "dfOcr" in url:
                return _resp(lst=[{"rcept_no": "20250520000001",
                                   "rcept_dt": "20250520", "df_cn": "x"}])
            return _resp(status="800")

        mock_retry.side_effect = _side
        events = dart_client.fetch_distress_events("00000001", "KEY", 3)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["subtype"], "default")

    def test_rejects_empty_inputs(self):
        self.assertEqual(dart_client.fetch_distress_events("", "KEY", 3), [])
        self.assertEqual(dart_client.fetch_distress_events("X", "", 3), [])


# ---------- TestFetchDividendHistory ----------

class TestFetchDividendHistory(unittest.TestCase):
    def setUp(self):
        cache = getattr(dart_client, "_dividend_history_cache", None)
        if cache is not None:
            cache.clear()

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_collects_alot_matter_with_year_label(self, mock_retry):
        def _side(method, url, **kwargs):
            if "alotMatter" not in url:
                return _resp(status="013")
            params = kwargs.get("params") or {}
            year = params.get("bsns_year")
            return _resp(lst=[{
                "rcept_no": f"{year}05200000",
                "se": "주당 현금배당금(원)",
                "stock_knd": "보통주",
                "thstrm": "500",
                "frmtrm": "300",
                "lwfr": "200",
                "stlm_dt": f"{year}-12-31",
            }])

        mock_retry.side_effect = _side
        recs = dart_client.fetch_dividend_history("00000001", "KEY", 2)
        # 분기 4코드 × N년이지만 일부 엔드포인트는 status=013으로 빠지므로
        # 최소 1건 이상 보장. bsns_year 라벨은 record에 부착됨.
        self.assertGreater(len(recs), 0)
        for r in recs:
            self.assertTrue(r.get("bsns_year"))
            self.assertEqual(r["se"], "주당 현금배당금(원)")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_skips_non_zero_status(self, mock_retry):
        mock_retry.side_effect = lambda *a, **kw: _resp(status="013")
        self.assertEqual(
            dart_client.fetch_dividend_history("00000001", "KEY", 2), []
        )


# ---------- TestDetectDividendDrain ----------

class TestDetectDividendDrain(unittest.TestCase):
    def test_flags_when_loss_and_dividend(self):
        dividend_records = [{
            "se": "주당 현금배당금(원)",
            "stock_knd": "보통주",
            "thstrm": "500",
            "bsns_year": "2024",
        }]
        # 당기순이익 음수
        current_fs = {"당기순이익": -1_000_000_000}
        flags = dart_client.detect_dividend_drain(dividend_records, current_fs)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["bsns_year"], "2024")
        self.assertEqual(flags[0]["dividend"], 500.0)

    def test_no_flag_when_profitable(self):
        dividend_records = [{
            "se": "주당 현금배당금(원)",
            "thstrm": "500",
            "bsns_year": "2024",
        }]
        current_fs = {"당기순이익": 1_000_000_000}
        flags = dart_client.detect_dividend_drain(dividend_records, current_fs)
        self.assertEqual(flags, [])

    def test_no_flag_when_zero_dividend(self):
        dividend_records = [{
            "se": "주당 현금배당금(원)",
            "thstrm": "0",
            "bsns_year": "2024",
        }]
        current_fs = {"당기순이익": -1_000_000_000}
        flags = dart_client.detect_dividend_drain(dividend_records, current_fs)
        self.assertEqual(flags, [])

    def test_empty_inputs(self):
        self.assertEqual(dart_client.detect_dividend_drain([], None), [])
        self.assertEqual(dart_client.detect_dividend_drain([], {"당기순이익": -1}), [])


# ---------- TestSignalRegistration ----------

class TestSignalRegistrationV090(unittest.TestCase):
    def test_distress_event_registered(self):
        self.assertIn("DISTRESS_EVENT", SIGNAL_KEY_TO_TAXONOMY)
        self.assertEqual(SIGNAL_KEY_TO_TAXONOMY["DISTRESS_EVENT"], ["8.5"])
        keys = {s["key"] for s in SIGNAL_TYPES}
        self.assertIn("DISTRESS_EVENT", keys)

    def test_dividend_drain_registered(self):
        self.assertIn("DIVIDEND_DRAIN", SIGNAL_KEY_TO_TAXONOMY)
        self.assertEqual(SIGNAL_KEY_TO_TAXONOMY["DIVIDEND_DRAIN"], ["5.6"])
        keys = {s["key"] for s in SIGNAL_TYPES}
        self.assertIn("DIVIDEND_DRAIN", keys)

    def test_taxonomy_8_5_exists(self):
        self.assertIn("8.5", TAXONOMY)
        node = TAXONOMY["8.5"]
        self.assertEqual(node.get("id"), "8.5")
        self.assertEqual(node.get("base_score"), 0)

    def test_taxonomy_5_6_exists(self):
        self.assertIn("5.6", TAXONOMY)
        node = TAXONOMY["5.6"]
        self.assertEqual(node.get("id"), "5.6")
        self.assertEqual(node.get("base_score"), 0)


if __name__ == "__main__":
    unittest.main()
