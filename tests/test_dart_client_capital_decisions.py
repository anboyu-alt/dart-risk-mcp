import unittest
from unittest.mock import patch, MagicMock
from dart_risk_mcp.core.dart_client import (
    fetch_piic_decision,
    fetch_fric_decision,
    fetch_pifric_decision,
)


class TestFetchCapitalDecisions(unittest.TestCase):
    def _mock_response(self, payload):
        mock = MagicMock()
        mock.json.return_value = payload
        return mock

    def test_fetch_piic_decision_parses_investors(self):
        payload = {
            "status": "000",
            "list": [{
                "rcept_no": "20240201000001",
                "actsen": "제3자배정",
                "actnmn": "AA펀드",
                "fric_nstk_ostk": "1000000",
            }],
        }
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_piic_decision("20240201000001", "key")
        self.assertEqual(data["list"][0]["actnmn"], "AA펀드")

    def test_fetch_fric_decision_empty_on_no_data(self):
        payload = {"status": "013", "message": "조회된 데이타가 없습니다."}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_fric_decision("20240201000002", "key")
        self.assertEqual(data, {})

    def test_fetch_pifric_decision_parses(self):
        payload = {"status": "000", "list": [{"actnmn": "BB증권"}]}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_pifric_decision("20240201000003", "key")
        self.assertEqual(data["list"][0]["actnmn"], "BB증권")

    def test_fetch_piic_decision_empty_on_network_exception(self):
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            side_effect=Exception("connection refused"),
        ):
            data = fetch_piic_decision("20240201000001", "key")
        self.assertEqual(data, {})

    def test_fetch_piic_decision_empty_on_missing_api_key(self):
        data = fetch_piic_decision("20240201000001", "")
        self.assertEqual(data, {})


if __name__ == "__main__":
    unittest.main()
