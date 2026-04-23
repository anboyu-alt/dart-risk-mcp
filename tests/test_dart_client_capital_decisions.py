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
        # corp_code + bgn_de/end_de 방식으로 조회 후 rcept_no 필터
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
            data = fetch_piic_decision("20240201000001", "key", "testcc")
        self.assertEqual(data["list"][0]["actnmn"], "AA펀드")

    def test_fetch_fric_decision_empty_on_no_data(self):
        payload = {"status": "013", "message": "조회된 데이타가 없습니다."}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_fric_decision("20240201000002", "key", "testcc")
        self.assertEqual(data, {})

    def test_fetch_pifric_decision_parses(self):
        # rcept_no가 list의 rcept_no와 일치해야 필터 통과
        payload = {"status": "000", "list": [{"rcept_no": "20240201000003", "actnmn": "BB증권"}]}
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            return_value=self._mock_response(payload),
        ):
            data = fetch_pifric_decision("20240201000003", "key", "testcc")
        self.assertEqual(data["list"][0]["actnmn"], "BB증권")

    def test_fetch_piic_decision_empty_on_network_exception(self):
        with patch(
            "dart_risk_mcp.core.dart_client._retry",
            side_effect=Exception("connection refused"),
        ):
            data = fetch_piic_decision("20240201000001", "key", "testcc")
        self.assertEqual(data, {})

    def test_fetch_piic_decision_empty_on_missing_api_key(self):
        data = fetch_piic_decision("20240201000001", "", "testcc")
        self.assertEqual(data, {})

    def test_fetch_piic_decision_empty_on_missing_corp_code(self):
        # corp_code 없으면 즉시 빈 dict 반환 (HTML 폴백 유도)
        data = fetch_piic_decision("20240201000001", "key")
        self.assertEqual(data, {})


if __name__ == "__main__":
    unittest.main()
