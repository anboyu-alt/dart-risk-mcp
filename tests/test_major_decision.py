"""fetch_major_decision·resolve_decision_type 검증."""
import unittest
from unittest.mock import patch, MagicMock

from dart_risk_mcp.core import dart_client
from dart_risk_mcp.core.dart_client import resolve_decision_type


def _mock_resp(status="000", lst=None):
    resp = MagicMock()
    resp.json.return_value = {
        "status": status,
        "message": "정상" if status == "000" else "",
        "list": lst or [],
    }
    return resp


class TestResolveDecisionType(unittest.TestCase):
    def test_stock_acquisition(self):
        self.assertEqual(
            resolve_decision_type("타법인 주식 및 출자증권 양수결정"),
            "stock_acq",
        )

    def test_merger(self):
        self.assertEqual(resolve_decision_type("회사합병결정"), "merger")

    def test_amendment_prefix_ignored(self):
        self.assertEqual(
            resolve_decision_type("[기재정정] 영업양수결정"),
            "business_acq",
        )

    def test_unknown_returns_empty(self):
        self.assertEqual(resolve_decision_type("분기보고서"), "")


class TestFetchMajorDecision(unittest.TestCase):
    def setUp(self):
        dart_client._major_decision_cache.clear()

    def test_invalid_rcept_no(self):
        result = dart_client.fetch_major_decision("123", "K", "merger")
        self.assertIn("error", result)

    def test_unknown_decision_type_returns_error(self):
        result = dart_client.fetch_major_decision(
            "20240101000001", "K", decision_type=""
        )
        self.assertIn("error", result)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_related_party_and_oversized_flags(self, mock_retry):
        mock_retry.return_value = _mock_resp(lst=[{
            "dlptn_cmpnm": "특수관계회사",
            "dlptn_rl_cmpn": "최대주주의 계열회사",
            "inh_pp": "50000000000",
            "inhdamount_totalast_rt": "35.5",
            "ftc_stt_atn": "예",
            "exevl_atn": "아니오",
            "bddd": "2024-05-10",
        }])
        result = dart_client.fetch_major_decision(
            "20240510000001", "K", decision_type="stock_acq"
        )
        self.assertNotIn("error", result)
        self.assertIn("DECISION_RELATED_PARTY", result["flags"])
        self.assertIn("DECISION_OVERSIZED", result["flags"])
        self.assertIn("DECISION_NO_EXTVAL", result["flags"])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_network_failure(self, mock_retry):
        mock_retry.side_effect = Exception("timeout")
        result = dart_client.fetch_major_decision(
            "20240510000002", "K", decision_type="merger"
        )
        self.assertIn("error", result)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_cache_hit(self, mock_retry):
        mock_retry.return_value = _mock_resp(lst=[{"bddd": "2024-01-01"}])
        dart_client.fetch_major_decision(
            "20240101000099", "K", decision_type="merger"
        )
        first = mock_retry.call_count
        dart_client.fetch_major_decision(
            "20240101000099", "K", decision_type="merger"
        )
        self.assertEqual(mock_retry.call_count, first)


if __name__ == "__main__":
    unittest.main()
