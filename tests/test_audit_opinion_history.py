"""fetch_audit_opinion_history 파싱·경고·부분실패·캐시 검증."""
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


class TestFetchAuditOpinionHistory(unittest.TestCase):
    def setUp(self):
        dart_client._audit_history_cache.clear()

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_parses_opinion_auditor_year(self, mock_retry):
        mock_retry.side_effect = [
            _resp(lst=[
                {"bsns_year": "2025", "adtor": "삼일회계법인", "adt_opinion": "적정"},
                {"bsns_year": "2024", "adtor": "삼일회계법인", "adt_opinion": "적정"},
                {"bsns_year": "2023", "adtor": "한영회계법인", "adt_opinion": "적정"},
            ]),
            _resp(lst=[
                {"bsns_year": "2025", "mendng": "820000000", "tot_reqre_time": "3000"},
            ]),
            _resp(lst=[
                {"bsns_year": "2025", "cntrct_cncls_de": "2025-03-10",
                 "servc_cn": "세무자문", "mendng": "110000000"},
            ]),
        ]
        result = dart_client.fetch_audit_opinion_history("00000001", "KEY", 5)
        self.assertEqual(len(result["opinions"]), 3)
        self.assertEqual(result["opinions"][0]["year"], 2025)
        self.assertEqual(result["opinions"][0]["opinion"], "적정")
        self.assertEqual(result["opinions"][0]["auditor"], "삼일회계법인")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_detects_auditor_change(self, mock_retry):
        mock_retry.side_effect = [
            _resp(lst=[
                {"bsns_year": "2025", "adtor": "삼일", "adt_opinion": "적정"},
                {"bsns_year": "2024", "adtor": "한영", "adt_opinion": "적정"},
            ]),
            _resp(lst=[]),
            _resp(lst=[]),
        ]
        r = dart_client.fetch_audit_opinion_history("00000001", "KEY", 5)
        self.assertEqual(len(r["auditor_changes"]), 1)
        self.assertEqual(r["auditor_changes"][0]["from"], "한영")
        self.assertEqual(r["auditor_changes"][0]["to"], "삼일")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_no_change_when_same_auditor(self, mock_retry):
        mock_retry.side_effect = [
            _resp(lst=[
                {"bsns_year": "2025", "adtor": "삼일", "adt_opinion": "적정"},
                {"bsns_year": "2024", "adtor": "삼일", "adt_opinion": "적정"},
            ]),
            _resp(lst=[]),
            _resp(lst=[]),
        ]
        r = dart_client.fetch_audit_opinion_history("00000001", "KEY", 5)
        self.assertEqual(r["auditor_changes"], [])
        self.assertEqual(r["opinions"][0]["tenure_years"], 2)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_non_audit_warning_at_30_percent(self, mock_retry):
        mock_retry.side_effect = [
            _resp(lst=[{"bsns_year": "2025", "adtor": "삼일", "adt_opinion": "적정"}]),
            _resp(lst=[{"bsns_year": "2025", "mendng": "700000000"}]),
            _resp(lst=[{"bsns_year": "2025", "cntrct_cncls_de": "2025-03-10",
                        "servc_cn": "세무", "mendng": "300000000"}]),
        ]
        r = dart_client.fetch_audit_opinion_history("00000001", "KEY", 5)
        self.assertTrue(any("30%" in w for w in r["independence_warnings"]))

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_non_audit_no_warning_below_30_percent(self, mock_retry):
        mock_retry.side_effect = [
            _resp(lst=[{"bsns_year": "2025", "adtor": "삼일", "adt_opinion": "적정"}]),
            _resp(lst=[{"bsns_year": "2025", "mendng": "900000000"}]),
            _resp(lst=[{"bsns_year": "2025", "cntrct_cncls_de": "2025-03-10",
                        "servc_cn": "세무", "mendng": "100000000"}]),
        ]
        r = dart_client.fetch_audit_opinion_history("00000001", "KEY", 5)
        self.assertEqual(r["independence_warnings"], [])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_partial_failure_one_endpoint(self, mock_retry):
        mock_retry.side_effect = [
            _resp(lst=[{"bsns_year": "2025", "adtor": "삼일", "adt_opinion": "적정"}]),
            _resp(status="013"),
            _resp(status="013"),
        ]
        r = dart_client.fetch_audit_opinion_history("00000001", "KEY", 5)
        self.assertEqual(len(r["opinions"]), 1)
        self.assertEqual(r["opinions"][0]["audit_fee_okwon"], 0)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_all_endpoints_fail_returns_empty(self, mock_retry):
        mock_retry.side_effect = Exception("network error")
        r = dart_client.fetch_audit_opinion_history("00000001", "KEY", 5)
        self.assertEqual(r["opinions"], [])
        self.assertEqual(r["auditor_changes"], [])
        self.assertEqual(r["independence_warnings"], [])

    def test_rejects_empty_corp_code(self):
        r = dart_client.fetch_audit_opinion_history("", "KEY", 5)
        self.assertEqual(r, {"opinions": [], "auditor_changes": [], "independence_warnings": []})

    def test_rejects_empty_api_key(self):
        r = dart_client.fetch_audit_opinion_history("00000001", "", 5)
        self.assertEqual(r["opinions"], [])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_cache_hit_skips_network(self, mock_retry):
        mock_retry.side_effect = [
            _resp(lst=[{"bsns_year": "2025", "adtor": "삼일", "adt_opinion": "적정"}]),
            _resp(lst=[]),
            _resp(lst=[]),
        ]
        dart_client.fetch_audit_opinion_history("00000099", "KEY", 5)
        dart_client.fetch_audit_opinion_history("00000099", "KEY", 5)
        self.assertEqual(mock_retry.call_count, 3)


if __name__ == "__main__":
    unittest.main()
