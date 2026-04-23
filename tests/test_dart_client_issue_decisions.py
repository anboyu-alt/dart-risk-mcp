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
        # corp_code + bgn_de/end_de 방식으로 조회, rcept_no 필터 통과
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
            data = fetch_cb_issue_decision("20240101000001", "key", "testcc")
        self.assertEqual(data["status"], "000")
        self.assertEqual(data["list"][0]["actnmn"], "OO투자조합")

    def test_fetch_cb_issue_decision_empty_on_error_status(self):
        payload = {"status": "013", "message": "조회된 데이타가 없습니다."}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_cb_issue_decision("20240101000001", "key", "testcc")
        self.assertEqual(data, {})

    def test_fetch_cb_issue_decision_empty_on_missing_corp_code(self):
        # corp_code 없으면 _retry 호출 없이 즉시 빈 dict (HTML 폴백 유도)
        data = fetch_cb_issue_decision("20240101000001", "key")
        self.assertEqual(data, {})

    def test_fetch_bw_issue_decision_parses(self):
        # rcept_no가 list의 rcept_no와 일치해야 필터 통과
        payload = {"status": "000", "list": [{"rcept_no": "20240101000002", "actnmn": "XX파트너스"}]}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_bw_issue_decision("20240101000002", "key", "testcc")
        self.assertEqual(data["list"][0]["actnmn"], "XX파트너스")

    def test_fetch_eb_issue_decision_parses(self):
        payload = {"status": "000", "list": [{"rcept_no": "20240101000003", "actnmn": "YY캐피탈"}]}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_eb_issue_decision("20240101000003", "key", "testcc")
        self.assertEqual(data["list"][0]["actnmn"], "YY캐피탈")

    def test_fetch_cb_issue_decision_empty_on_network_exception(self):
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            side_effect=Exception("connection refused"),
        ):
            data = fetch_cb_issue_decision("20240101000001", "key", "testcc")
        self.assertEqual(data, {})

    def test_fetch_bw_issue_decision_empty_on_error_status(self):
        payload = {"status": "013", "message": "조회된 데이타가 없습니다."}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_bw_issue_decision("20240101000002", "key", "testcc")
        self.assertEqual(data, {})

    def test_fetch_bw_issue_decision_empty_on_network_exception(self):
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            side_effect=Exception("connection refused"),
        ):
            data = fetch_bw_issue_decision("20240101000002", "key", "testcc")
        self.assertEqual(data, {})

    def test_fetch_eb_issue_decision_empty_on_error_status(self):
        payload = {"status": "013", "message": "조회된 데이타가 없습니다."}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_eb_issue_decision("20240101000003", "key", "testcc")
        self.assertEqual(data, {})

    def test_fetch_eb_issue_decision_empty_on_network_exception(self):
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            side_effect=Exception("connection refused"),
        ):
            data = fetch_eb_issue_decision("20240101000003", "key", "testcc")
        self.assertEqual(data, {})


if __name__ == "__main__":
    unittest.main()
