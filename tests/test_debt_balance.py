"""fetch_debt_balance / detect_debt_rollover 파싱·집계·판정 검증."""
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
            _resp(lst=[{"remndr_amount": "100000000", "remndr_within1y_amount": "50000000"}]),
            _resp(lst=[{"remndr_amount": "100000000", "remndr_within1y_amount": "0"}]),
            _resp(lst=[{"remndr_amount": "100000000", "remndr_within1y_amount": "0"}]),
            _resp(lst=[{"remndr_amount": "100000000", "remndr_within1y_amount": "0"}]),
            _resp(lst=[{"remndr_amount": "100000000", "remndr_within1y_amount": "0"}]),
        ]
        r = dart_client.fetch_debt_balance("00000001", "KEY", "2024")
        self.assertEqual(r["total"], 500_000_000)
        self.assertEqual(r["year"], 2024)
        self.assertEqual(len(r["by_kind"]), 5)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_maturity_1y_share_calculation(self, mock_retry):
        # 총 1,000,000,000 중 1년 이내 300,000,000 → 30%
        mock_retry.side_effect = [
            _resp(lst=[{"remndr_amount": "1000000000", "remndr_within1y_amount": "300000000"}]),
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
            _resp(lst=[{"remndr_amount": "100000000", "remndr_within1y_amount": "0"}]),
            _resp(status="013"),  # 실패
            _resp(lst=[{"remndr_amount": "200000000", "remndr_within1y_amount": "0"}]),
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
