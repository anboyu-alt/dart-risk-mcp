import unittest
from unittest.mock import patch, MagicMock


def _resp(payload):
    m = MagicMock()
    m.json.return_value = payload
    return m


class TestFetchExecutiveRoster(unittest.TestCase):
    def test_collects_names_across_years_as_union(self):
        from dart_risk_mcp.core.dart_client import fetch_executive_roster

        # 연도별로 다른 임원 명단 — _retry는 (method, url, params=...) 로 호출됨
        def _fake_retry(method, url, params=None, timeout=None):
            year = params["bsns_year"]
            if year == "2023":
                return _resp({"status": "000", "list": [
                    {"nm": "신승수", "ofcps": "사내이사", "rgist_exctv_at": "사내이사"},
                    {"nm": "조중명", "ofcps": "대표이사", "rgist_exctv_at": "사내이사"},
                ]})
            if year == "2024":
                return _resp({"status": "000", "list": [
                    {"nm": "신승수", "ofcps": "사내이사", "rgist_exctv_at": "사내이사"},
                ]})
            return _resp({"status": "013", "list": []})  # 그 외 연도: 데이터 없음

        with patch("dart_risk_mcp.core.dart_client._retry", side_effect=_fake_retry):
            roster = fetch_executive_roster("00407814", "key", lookback_years=3)

        # 합집합: 신승수는 2023·2024 모두, 조중명은 2023만
        self.assertIn("신승수", roster)
        self.assertEqual(roster["신승수"], {"2023", "2024"})
        self.assertEqual(roster["조중명"], {"2023"})

    def test_empty_inputs_return_empty(self):
        from dart_risk_mcp.core.dart_client import fetch_executive_roster
        self.assertEqual(fetch_executive_roster("", "key"), {})
        self.assertEqual(fetch_executive_roster("c", ""), {})

    def test_skips_blank_and_total_rows(self):
        from dart_risk_mcp.core.dart_client import fetch_executive_roster

        def _fake_retry(method, url, params=None, timeout=None):
            return _resp({"status": "000", "list": [
                {"nm": " "}, {"nm": "계"}, {"nm": "합계"}, {"nm": "양민성"},
            ]})

        with patch("dart_risk_mcp.core.dart_client._retry", side_effect=_fake_retry):
            roster = fetch_executive_roster("c", "key", lookback_years=1)

        self.assertEqual(list(roster.keys()), ["양민성"])


if __name__ == "__main__":
    unittest.main()
