"""fetch_fund_usage 정규화·이상 플래그·캐시·부분실패 검증."""
import unittest
from unittest.mock import patch, MagicMock

from dart_risk_mcp.core import dart_client


def _mock_resp(status="000", lst=None):
    resp = MagicMock()
    resp.json.return_value = {
        "status": status,
        "message": "정상" if status == "000" else "데이터 없음",
        "list": lst or [],
    }
    return resp


class TestFetchFundUsage(unittest.TestCase):
    def setUp(self):
        dart_client._fund_usage_cache.clear()

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_normal_response_no_anomaly(self, mock_retry):
        mock_retry.return_value = _mock_resp(
            lst=[{
                "se_nm": "일반공모",
                "tm": "1",
                "pay_de": "2024-03-10",
                "pay_amount": "10000000000",
                "rs_cptal_use_plan_useprps": "운영자금",
                "rs_cptal_use_plan_prcure_amount": "10000000000",
                "real_cptal_use_dtls_cn": "운영자금 집행",
                "real_cptal_use_dtls_amount": "10000000000",
                "dffrnc_occrrnc_resn": "",
            }],
        )
        result = dart_client.fetch_fund_usage("00000001", "K", 1)
        self.assertTrue(result)
        self.assertEqual(result[0]["plan_amount"], 10_000_000_000)
        self.assertEqual(result[0]["real_dtls_amount"], 10_000_000_000)
        self.assertEqual(result[0]["flags"], [])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_fund_unreported_flag(self, mock_retry):
        mock_retry.return_value = _mock_resp(
            lst=[{
                "tm": "2",
                "pay_amount": "5000000000",
                "mtrpt_cptal_use_plan_useprps": "시설투자",
                "mtrpt_cptal_use_plan_prcure_amount": "5000000000",
                "real_cptal_use_dtls_cn": "",
                "real_cptal_use_dtls_amount": "0",
                "dffrnc_occrrnc_resn": "",
            }],
        )
        result = dart_client.fetch_fund_usage("00000002", "K", 1)
        self.assertTrue(any("FUND_UNREPORTED" in r["flags"] for r in result))

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_fund_diversion_flag(self, mock_retry):
        mock_retry.return_value = _mock_resp(
            lst=[{
                "tm": "1",
                "pay_amount": "3000000000",
                "mtrpt_cptal_use_plan_useprps": "신사업투자",
                "mtrpt_cptal_use_plan_prcure_amount": "3000000000",
                "real_cptal_use_dtls_cn": "운영자금",
                "real_cptal_use_dtls_amount": "3000000000",
                "dffrnc_occrrnc_resn": "사업 취소로 일반 운영자금으로 변경 사용",
            }],
        )
        result = dart_client.fetch_fund_usage("00000003", "K", 1)
        self.assertTrue(any("FUND_DIVERSION" in r["flags"] for r in result))

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_status_013_returns_empty(self, mock_retry):
        mock_retry.return_value = _mock_resp(status="013", lst=[])
        result = dart_client.fetch_fund_usage("00000004", "K", 1)
        self.assertEqual(result, [])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_network_failure_silent(self, mock_retry):
        mock_retry.side_effect = Exception("network down")
        result = dart_client.fetch_fund_usage("00000005", "K", 1)
        self.assertEqual(result, [])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_cache_hit_skips_second_call(self, mock_retry):
        mock_retry.return_value = _mock_resp(lst=[])
        dart_client.fetch_fund_usage("00000006", "K", 2)
        first_count = mock_retry.call_count
        dart_client.fetch_fund_usage("00000006", "K", 2)
        self.assertEqual(mock_retry.call_count, first_count)


if __name__ == "__main__":
    unittest.main()
