import unittest
from unittest.mock import patch, MagicMock
from dart_risk_mcp.core.cb_extractor import extract_cb_investors


class TestCBExtractorStructuredFirst(unittest.TestCase):
    def test_uses_structured_endpoint_when_available(self):
        cb_payload = {
            "status": "000",
            "list": [{"actsen": "사모", "actnmn": "OO투자조합", "bd_fta": "30000000000"}],
        }
        with patch(
            "dart_risk_mcp.core.cb_extractor.fetch_cb_issue_decision",
            return_value=cb_payload,
        ), patch(
            "dart_risk_mcp.core.cb_extractor._legacy_html_extract"
        ) as mock_html:
            investors = extract_cb_investors("20240101000001", "key")
        self.assertEqual(investors[0]["name"], "OO투자조합")
        mock_html.assert_not_called()

    def test_tries_bw_when_cb_empty(self):
        bw_payload = {
            "status": "000",
            "list": [{"actsen": "사모", "actnmn": "XX파트너스", "bd_fta": "10000000000"}],
        }
        with patch(
            "dart_risk_mcp.core.cb_extractor.fetch_cb_issue_decision",
            return_value={},
        ), patch(
            "dart_risk_mcp.core.cb_extractor.fetch_bw_issue_decision",
            return_value=bw_payload,
        ), patch(
            "dart_risk_mcp.core.cb_extractor._legacy_html_extract"
        ) as mock_html:
            investors = extract_cb_investors("20240101000002", "key")
        self.assertEqual(investors[0]["name"], "XX파트너스")
        mock_html.assert_not_called()

    def test_tries_eb_when_cb_and_bw_empty(self):
        eb_payload = {
            "status": "000",
            "list": [{"actsen": "사모", "actnmn": "YY캐피탈", "bd_fta": "5000000000"}],
        }
        with patch(
            "dart_risk_mcp.core.cb_extractor.fetch_cb_issue_decision",
            return_value={},
        ), patch(
            "dart_risk_mcp.core.cb_extractor.fetch_bw_issue_decision",
            return_value={},
        ), patch(
            "dart_risk_mcp.core.cb_extractor.fetch_eb_issue_decision",
            return_value=eb_payload,
        ), patch(
            "dart_risk_mcp.core.cb_extractor._legacy_html_extract"
        ) as mock_html:
            investors = extract_cb_investors("20240101000003", "key")
        self.assertEqual(investors[0]["name"], "YY캐피탈")
        mock_html.assert_not_called()

    def test_falls_back_to_html_when_all_structured_empty(self):
        html_result = [{"name": "ZZ자산운용", "type": "사모", "amount": "2000000000"}]
        with patch(
            "dart_risk_mcp.core.cb_extractor.fetch_cb_issue_decision",
            return_value={},
        ), patch(
            "dart_risk_mcp.core.cb_extractor.fetch_bw_issue_decision",
            return_value={},
        ), patch(
            "dart_risk_mcp.core.cb_extractor.fetch_eb_issue_decision",
            return_value={},
        ), patch(
            "dart_risk_mcp.core.cb_extractor._legacy_html_extract",
            return_value=html_result,
        ):
            investors = extract_cb_investors("20240101000004", "key")
        self.assertEqual(investors[0]["name"], "ZZ자산운용")

    def test_falls_back_to_html_when_structured_raises(self):
        html_result = [{"name": "WW캐피탈", "type": "사모", "amount": "100"}]
        with patch(
            "dart_risk_mcp.core.cb_extractor.fetch_cb_issue_decision",
            side_effect=Exception("boom"),
        ), patch(
            "dart_risk_mcp.core.cb_extractor.fetch_bw_issue_decision",
            side_effect=Exception("boom"),
        ), patch(
            "dart_risk_mcp.core.cb_extractor.fetch_eb_issue_decision",
            side_effect=Exception("boom"),
        ), patch(
            "dart_risk_mcp.core.cb_extractor._legacy_html_extract",
            return_value=html_result,
        ):
            investors = extract_cb_investors("20240101000005", "key")
        self.assertEqual(investors[0]["name"], "WW캐피탈")


if __name__ == "__main__":
    unittest.main()
