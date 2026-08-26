"""fetch_debt_balance / detect_debt_rollover 파싱·집계·판정 검증.
⚠ 2026-08-25 — 이 파일의 가짜 응답은 오래 `remndr_amount`·
`remndr_within1y_amount`를 썼다. **DART에는 그런 필드가 없다.** 테스트는
통과했지만 실제로는 `fetch_debt_balance`가 **모든 회사에서 늘 빈 결과**였고,
그 위에 선 `track_debt_balance`·「채무증권 잔액 추이」·`CB_ROLLOVER`가 통째로
죽어 있었다(8개사 스윕에서 세 블록 전부 0/8).

**존재하지 않는 계약을 검증하는 테스트는 통과할수록 위험하다** — 이 세션의
「테스트 픽스처는 원문 그대로」 교훈과 같은 종류다. 이제 실제 응답 모양
(공모·사모·**합계** 3행 · 금액 `sm` · 만기 `yy1_below`)을 쓴다.
"""
import unittest
from unittest.mock import patch, MagicMock

from dart_risk_mcp.core import dart_client


def _resp(status="000", lst=None):
    r = MagicMock()
    r.json.return_value = {
        "status": status,
        "message": "정상" if status == "000" else "데이터 없음",
        "list": lst or [],
    }
    return r


class TestFetchDebtBalance(unittest.TestCase):
    def setUp(self):
        dart_client._debt_balance_cache.clear()

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_aggregates_five_endpoints_total(self, mock_retry):
        # 5개 엔드포인트 각 1억씩 → 총 5억
        mock_retry.side_effect = [
            _resp(lst=[{"remndr_exprtn2": "공모", "sm": "100000000", "yy1_below": "50000000"}, {"remndr_exprtn2": "사모", "sm": "-", "yy1_below": "-"}, {"remndr_exprtn2": "합계", "sm": "100000000", "yy1_below": "50000000"}]),
            _resp(lst=[{"remndr_exprtn2": "공모", "sm": "100000000", "yy1_below": "0"}, {"remndr_exprtn2": "사모", "sm": "-", "yy1_below": "-"}, {"remndr_exprtn2": "합계", "sm": "100000000", "yy1_below": "0"}]),
            _resp(lst=[{"remndr_exprtn2": "공모", "sm": "100000000", "yy1_below": "0"}, {"remndr_exprtn2": "사모", "sm": "-", "yy1_below": "-"}, {"remndr_exprtn2": "합계", "sm": "100000000", "yy1_below": "0"}]),
            _resp(lst=[{"remndr_exprtn2": "공모", "sm": "100000000", "yy1_below": "0"}, {"remndr_exprtn2": "사모", "sm": "-", "yy1_below": "-"}, {"remndr_exprtn2": "합계", "sm": "100000000", "yy1_below": "0"}]),
            _resp(lst=[{"remndr_exprtn2": "공모", "sm": "100000000", "yy1_below": "0"}, {"remndr_exprtn2": "사모", "sm": "-", "yy1_below": "-"}, {"remndr_exprtn2": "합계", "sm": "100000000", "yy1_below": "0"}]),
        ]
        r = dart_client.fetch_debt_balance("00000001", "KEY", "2024")
        self.assertEqual(r["total"], 500_000_000)
        self.assertEqual(r["year"], 2024)
        self.assertEqual(len(r["by_kind"]), 5)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_maturity_1y_share_calculation(self, mock_retry):
        # 총 1,000,000,000 중 1년 이내 300,000,000 → 30%
        mock_retry.side_effect = [
            _resp(lst=[{"remndr_exprtn2": "공모", "sm": "1000000000", "yy1_below": "300000000"}, {"remndr_exprtn2": "사모", "sm": "-", "yy1_below": "-"}, {"remndr_exprtn2": "합계", "sm": "1000000000", "yy1_below": "300000000"}]),
            _resp(lst=[]),
            _resp(lst=[]),
            _resp(lst=[]),
            _resp(lst=[]),
        ]
        r = dart_client.fetch_debt_balance("00000001", "KEY", "2024")
        self.assertAlmostEqual(r["maturity_1y_share"], 0.30, places=4)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_empty_when_zero_balance(self, mock_retry):
        mock_retry.side_effect = [_resp(lst=[]) for _ in range(5)]
        r = dart_client.fetch_debt_balance("00000001", "KEY", "2024")
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["by_kind"], {})
        self.assertEqual(r["maturity_1y_share"], 0.0)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_partial_failure_one_endpoint(self, mock_retry):
        mock_retry.side_effect = [
            _resp(lst=[{"remndr_exprtn2": "공모", "sm": "100000000", "yy1_below": "0"}, {"remndr_exprtn2": "사모", "sm": "-", "yy1_below": "-"}, {"remndr_exprtn2": "합계", "sm": "100000000", "yy1_below": "0"}]),
            _resp(status="013"),  # 실패
            _resp(lst=[{"remndr_exprtn2": "공모", "sm": "200000000", "yy1_below": "0"}, {"remndr_exprtn2": "사모", "sm": "-", "yy1_below": "-"}, {"remndr_exprtn2": "합계", "sm": "200000000", "yy1_below": "0"}]),
            _resp(lst=[]),
            _resp(lst=[]),
        ]
        r = dart_client.fetch_debt_balance("00000001", "KEY", "2024")
        self.assertEqual(r["total"], 300_000_000)
        self.assertEqual(len(r["by_kind"]), 2)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_all_endpoints_fail_returns_empty(self, mock_retry):
        mock_retry.side_effect = Exception("network")
        r = dart_client.fetch_debt_balance("00000001", "KEY", "2024")
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["by_kind"], {})

    def test_rejects_empty_corp_code(self):
        r = dart_client.fetch_debt_balance("", "KEY", "2024")
        self.assertEqual(r["total"], 0)
        self.assertIsNone(r["year"])

    def test_rejects_empty_api_key(self):
        r = dart_client.fetch_debt_balance("00000001", "", "2024")
        self.assertEqual(r["total"], 0)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_cache_hit_skips_network(self, mock_retry):
        mock_retry.side_effect = [_resp(lst=[]) for _ in range(5)]
        dart_client.fetch_debt_balance("00000099", "KEY", "2024")
        dart_client.fetch_debt_balance("00000099", "KEY", "2024")
        self.assertEqual(mock_retry.call_count, 5)  # 2번째 호출은 캐시


class TestDetectDebtRollover(unittest.TestCase):
    def test_flags_when_flat_3y_with_2_cb(self):
        balances = [(2022, 1_000_000_000), (2023, 1_020_000_000), (2024, 1_050_000_000)]
        events = [
            {"key": "CB_BW", "rcept_dt": "20230515"},
            {"key": "CB_BW", "rcept_dt": "20240310"},
        ]
        self.assertEqual(dart_client.detect_debt_rollover(balances, events), "CB_ROLLOVER")

    def test_no_flag_when_yoy_exceeds_10pct(self):
        # 2022→2023 +20% → 평탄 조건 미충족
        balances = [(2022, 1_000_000_000), (2023, 1_200_000_000), (2024, 1_250_000_000)]
        events = [
            {"key": "CB_BW", "rcept_dt": "20230515"},
            {"key": "CB_BW", "rcept_dt": "20240310"},
        ]
        self.assertIsNone(dart_client.detect_debt_rollover(balances, events))

    def test_no_flag_when_years_not_consecutive(self):
        # 결측 연도로 비연속(2020→2023→2024)이면 "3년 연속" 판정을 하지
        # 않는다 — 몇 년 건너뛴 간격에 YoY 평탄 판정이 적용되던 문제(E-6)
        balances = [(2020, 1_000_000_000), (2023, 1_020_000_000), (2024, 1_050_000_000)]
        events = [
            {"key": "CB_BW", "rcept_dt": "20230515"},
            {"key": "CB_BW", "rcept_dt": "20240310"},
        ]
        self.assertIsNone(dart_client.detect_debt_rollover(balances, events))

    def test_no_flag_when_cb_events_below_2(self):
        balances = [(2022, 1_000_000_000), (2023, 1_020_000_000), (2024, 1_050_000_000)]
        events = [{"key": "CB_BW", "rcept_dt": "20230515"}]
        self.assertIsNone(dart_client.detect_debt_rollover(balances, events))

    def test_no_flag_when_balances_below_3_years(self):
        balances = [(2023, 1_000_000_000), (2024, 1_020_000_000)]
        events = [
            {"key": "CB_BW", "rcept_dt": "20230515"},
            {"key": "CB_BW", "rcept_dt": "20240310"},
        ]
        self.assertIsNone(dart_client.detect_debt_rollover(balances, events))


if __name__ == "__main__":
    unittest.main()
