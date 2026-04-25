"""v0.8.7 — fetch_treasury_decisions 통합 + TREASURY_TRUST(2.8) 등록 검증.

검증:
1. fetch_treasury_decisions는 4개 결정 엔드포인트(tsstkAqDecsn·tsstkDpDecsn·
   tsstkAqTrctrCnsDecsn·tsstkAqTrctrCcDecsn)를 lookback_years 기간으로 호출하고
   직접 취득/처분은 key="TREASURY", 신탁 체결/해지는 key="TREASURY_TRUST"로
   정규화한다.
2. 응답에 rcept_dt가 없으면 rcept_no[:8]으로 폴백.
3. 일부 엔드포인트 실패는 다른 결과를 막지 않는다.
4. signals.py / taxonomy.py에 TREASURY_TRUST(2.8) 등록.
5. NON_DILUTIVE_CAPITAL_EVENTS에 TREASURY_TRUST 포함.
6. detect_capital_churn이 결정 공시 입력으로도 12개월 카운팅을 정상 수행한다.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from dart_risk_mcp.core import dart_client
from dart_risk_mcp.core.signals import (
    CAPITAL_EVENT_KEYS,
    NON_DILUTIVE_CAPITAL_EVENTS,
    SIGNAL_KEY_TO_TAXONOMY,
    SIGNAL_TYPES,
)
from dart_risk_mcp.core.taxonomy import TAXONOMY


def _resp(status: str = "000", lst: list | None = None) -> MagicMock:
    r = MagicMock()
    r.json.return_value = {
        "status": status,
        "message": "정상" if status == "000" else "데이터 없음",
        "list": lst or [],
    }
    return r


def _make_side(
    aq_lst: list | None = None,
    dp_lst: list | None = None,
    trust_cons_lst: list | None = None,
    trust_canc_lst: list | None = None,
):
    aq_lst = aq_lst or []
    dp_lst = dp_lst or []
    trust_cons_lst = trust_cons_lst or []
    trust_canc_lst = trust_canc_lst or []

    def _side(method, url, **kwargs):
        if "tsstkAqDecsn" in url and "Trctr" not in url:
            return _resp(lst=aq_lst)
        if "tsstkDpDecsn" in url:
            return _resp(lst=dp_lst)
        if "tsstkAqTrctrCnsDecsn" in url:
            return _resp(lst=trust_cons_lst)
        if "tsstkAqTrctrCcDecsn" in url:
            return _resp(lst=trust_canc_lst)
        return _resp(status="013")

    return _side


class TestFetchTreasuryDecisions(unittest.TestCase):
    def setUp(self):
        # 캐시가 있다면 클리어 (있으면)
        cache = getattr(dart_client, "_treasury_decisions_cache", None)
        if cache is not None:
            cache.clear()

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_normalizes_acq_to_treasury(self, mock_retry):
        mock_retry.side_effect = _make_side(
            aq_lst=[{
                "rcept_no": "20240520000123",
                "rcept_dt": "20240520",
                "corp_code": "00413046",
                "corp_name": "셀트리온",
                "aqpln_stk_ostk": "1000000",
            }],
        )
        events = dart_client.fetch_treasury_decisions("00413046", "KEY", 1)
        treasury = [e for e in events if e["key"] == "TREASURY"]
        self.assertGreaterEqual(len(treasury), 1)
        self.assertEqual(treasury[0]["decision_type"], "acq")
        self.assertEqual(treasury[0]["rcept_dt"], "20240520")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_normalizes_disp_to_treasury(self, mock_retry):
        mock_retry.side_effect = _make_side(
            dp_lst=[{
                "rcept_no": "20240601000456",
                "rcept_dt": "20240601",
                "corp_code": "00413046",
                "aq_wtn_div_ostk": "500000",
            }],
        )
        events = dart_client.fetch_treasury_decisions("00413046", "KEY", 1)
        disp = [e for e in events if e.get("decision_type") == "disp"]
        self.assertEqual(len(disp), 1)
        self.assertEqual(disp[0]["key"], "TREASURY")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_normalizes_trust_to_treasury_trust(self, mock_retry):
        mock_retry.side_effect = _make_side(
            trust_cons_lst=[{
                "rcept_no": "20240701000789",
                "rcept_dt": "20240701",
                "corp_code": "00413046",
                "ctr_prd_bgd": "20240701",
                "ctr_prd_edd": "20250630",
            }],
            trust_canc_lst=[{
                "rcept_no": "20240901000111",
                "rcept_dt": "20240901",
                "corp_code": "00413046",
            }],
        )
        events = dart_client.fetch_treasury_decisions("00413046", "KEY", 1)
        trust = [e for e in events if e["key"] == "TREASURY_TRUST"]
        types = {e["decision_type"] for e in trust}
        self.assertEqual(types, {"trust_cons", "trust_canc"})

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_falls_back_to_rcept_no_when_no_rcept_dt(self, mock_retry):
        mock_retry.side_effect = _make_side(
            aq_lst=[{
                "rcept_no": "20240715000999",
                # rcept_dt 누락
                "corp_code": "00413046",
                "aqpln_stk_ostk": "100",
            }],
        )
        events = dart_client.fetch_treasury_decisions("00413046", "KEY", 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["rcept_dt"], "20240715")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_partial_endpoint_failure_isolated(self, mock_retry):
        def _side(method, url, **kwargs):
            if "tsstkAqDecsn" in url and "Trctr" not in url:
                return _resp(lst=[{"rcept_no": "20240520000001", "rcept_dt": "20240520",
                                   "corp_code": "X", "aqpln_stk_ostk": "1"}])
            return _resp(status="800")  # 나머지 모두 실패

        mock_retry.side_effect = _side
        events = dart_client.fetch_treasury_decisions("00413046", "KEY", 1)
        # acq 이벤트 1건만 살아남음
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["decision_type"], "acq")

    def test_rejects_empty_corp_code(self):
        self.assertEqual(dart_client.fetch_treasury_decisions("", "KEY", 1), [])

    def test_rejects_empty_api_key(self):
        self.assertEqual(dart_client.fetch_treasury_decisions("00413046", "", 1), [])


class TestTreasuryTrustRegistration(unittest.TestCase):
    def test_signal_key_in_taxonomy_map(self):
        self.assertIn("TREASURY_TRUST", SIGNAL_KEY_TO_TAXONOMY)
        self.assertEqual(SIGNAL_KEY_TO_TAXONOMY["TREASURY_TRUST"], ["2.8"])

    def test_signal_type_registered(self):
        keys = {s["key"] for s in SIGNAL_TYPES}
        self.assertIn("TREASURY_TRUST", keys)

    def test_taxonomy_2_8_exists(self):
        self.assertIn("2.8", TAXONOMY)
        node = TAXONOMY["2.8"]
        self.assertEqual(node.get("id"), "2.8")
        self.assertEqual(node.get("base_score"), 0)
        self.assertTrue(node.get("category"), "category 라벨 누락")

    def test_treasury_trust_in_non_dilutive_set(self):
        self.assertIn("TREASURY_TRUST", NON_DILUTIVE_CAPITAL_EVENTS)
        self.assertIn("TREASURY_TRUST", CAPITAL_EVENT_KEYS)


class TestDetectCapitalChurnWithDecisions(unittest.TestCase):
    """결정 공시 입력으로 detect_capital_churn 12개월 카운팅 정상 동작 확인."""

    def test_treasury_decisions_counted_in_window(self):
        # TREASURY 4건 + TREASURY_TRUST 2건 (모두 비희석)이 12개월 안에 분포
        events = [
            {"key": "TREASURY", "rcept_dt": "20240301"},
            {"key": "TREASURY", "rcept_dt": "20240601"},
            {"key": "TREASURY", "rcept_dt": "20240901"},
            {"key": "TREASURY_TRUST", "rcept_dt": "20241101"},
            {"key": "TREASURY_TRUST", "rcept_dt": "20250101"},
            {"key": "TREASURY", "rcept_dt": "20250201"},
        ]
        result = dart_client.detect_capital_churn(events, lookback_years=2)
        # 비희석 이벤트만 있으므로 dilutive=0, non_dilutive 최대 카운트 ≥ 5
        self.assertEqual(result["max_dilutive_12m"], 0)
        self.assertGreaterEqual(result["max_non_dilutive_12m"], 5)


if __name__ == "__main__":
    unittest.main()
