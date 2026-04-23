import unittest
from unittest.mock import patch, MagicMock
from dart_risk_mcp.core.dart_client import (
    fetch_cb_issue_decision,
    fetch_bw_issue_decision,
    fetch_eb_issue_decision,
)


class TestFetchIssueDecisions(unittest.TestCase):
    def _mock_response(self, payload):
        mock = MagicMock()
        mock.json.return_value = payload
        return mock

    def test_fetch_cb_issue_decision_parses_actnmn(self):
        payload = {
            "status": "000",
            "list": [{
                "rcept_no": "20240101000001",
                "actsen": "제3자배정",
                "actnmn": "OO투자조합",
                "bd_fta": "30000000000",
            }],
        }
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_cb_issue_decision("20240101000001", "key")
        self.assertEqual(data["status"], "000")
        self.assertEqual(data["list"][0]["actnmn"], "OO투자조합")

    def test_fetch_cb_issue_decision_empty_on_error_status(self):
        payload = {"status": "013", "message": "조회된 데이타가 없습니다."}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_cb_issue_decision("20240101000001", "key")
        self.assertEqual(data, {})

    def test_fetch_bw_issue_decision_parses(self):
        payload = {"status": "000", "list": [{"actnmn": "XX파트너스"}]}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_bw_issue_decision("20240101000002", "key")
        self.assertEqual(data["list"][0]["actnmn"], "XX파트너스")

    def test_fetch_eb_issue_decision_parses(self):
        payload = {"status": "000", "list": [{"actnmn": "YY캐피탈"}]}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_eb_issue_decision("20240101000003", "key")
        self.assertEqual(data["list"][0]["actnmn"], "YY캐피탈")

    def test_fetch_cb_issue_decision_empty_on_network_exception(self):
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            side_effect=Exception("connection refused"),
        ):
            data = fetch_cb_issue_decision("20240101000001", "key")
        self.assertEqual(data, {})

    def test_fetch_bw_issue_decision_empty_on_error_status(self):
        payload = {"status": "013", "message": "조회된 데이타가 없습니다."}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_bw_issue_decision("20240101000002", "key")
        self.assertEqual(data, {})

    def test_fetch_bw_issue_decision_empty_on_network_exception(self):
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            side_effect=Exception("connection refused"),
        ):
            data = fetch_bw_issue_decision("20240101000002", "key")
        self.assertEqual(data, {})

    def test_fetch_eb_issue_decision_empty_on_error_status(self):
        payload = {"status": "013", "message": "조회된 데이타가 없습니다."}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_eb_issue_decision("20240101000003", "key")
        self.assertEqual(data, {})

    def test_fetch_eb_issue_decision_empty_on_network_exception(self):
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            side_effect=Exception("connection refused"),
        ):
            data = fetch_eb_issue_decision("20240101000003", "key")
        self.assertEqual(data, {})


if __name__ == "__main__":
    unittest.main()
