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


class TestFetchExecutiveRosterDetail(unittest.TestCase):
    """SE-6 Task 2b: fetch_executive_roster가 버리는 exctvSttus 원본 필드
    (birth_ym·ofcps·rgist_exctv_at·corp_name)를 보존하는 옆 함수.

    동명이인을 자동으로 가리지 않고 이용자가 직접 확인하게 하는 SE-6
    설계에서, 확인할 재료(생년월·직위·등기 여부)가 화면까지 가려면 이
    함수가 필요하다 — 기존 fetch_executive_roster는 {임원명: {연도}}만
    돌려주고 나머지를 버린다.
    """

    def _fake_retry_two_years(self, method, url, params=None, timeout=None):
        year = params["bsns_year"]
        if year == "2023":
            return _resp({"status": "000", "list": [
                {"nm": "신승수", "corp_name": "이엠앤아이", "birth_ym": "196503",
                 "ofcps": "사내이사", "rgist_exctv_at": "등기"},
                {"nm": "조중명", "corp_name": "이엠앤아이", "birth_ym": "195001",
                 "ofcps": "대표이사", "rgist_exctv_at": "등기"},
            ]})
        if year == "2024":
            return _resp({"status": "000", "list": [
                # 신승수는 2024년에 직위가 바뀌었다 — 최신 값이 남아야 한다.
                {"nm": "신승수", "corp_name": "이엠앤아이", "birth_ym": "196503",
                 "ofcps": "대표이사", "rgist_exctv_at": "등기"},
            ]})
        return _resp({"status": "013", "list": []})

    def test_preserves_birth_ym_ofcps_rgist_exctv_at(self):
        from dart_risk_mcp.core.dart_client import fetch_executive_roster_detail

        with patch("dart_risk_mcp.core.dart_client._retry",
                    side_effect=self._fake_retry_two_years):
            rows = fetch_executive_roster_detail("00407814", "key", lookback_years=3)

        by_name = {r["nm"]: r for r in rows}
        self.assertIn("신승수", by_name)
        self.assertEqual(by_name["신승수"]["birth_ym"], "196503")
        self.assertEqual(by_name["신승수"]["corp_name"], "이엠앤아이")
        self.assertEqual(by_name["신승수"]["rgist_exctv_at"], "등기")

    def test_same_person_across_years_merges_into_one_row(self):
        from dart_risk_mcp.core.dart_client import fetch_executive_roster_detail

        with patch("dart_risk_mcp.core.dart_client._retry",
                    side_effect=self._fake_retry_two_years):
            rows = fetch_executive_roster_detail("00407814", "key", lookback_years=3)

        by_name = {r["nm"]: r for r in rows}
        # 한 행으로 합쳐지고, 두 해가 모두 남는다.
        self.assertEqual(len(rows), 2)
        self.assertEqual(by_name["신승수"]["years"], ["2023", "2024"])
        self.assertEqual(by_name["조중명"]["years"], ["2023"])
        # 직위는 최신(2024) 값으로 덮인다 — 화면은 "지금" 기준을 보여줘야 한다.
        self.assertEqual(by_name["신승수"]["ofcps"], "대표이사")

    def test_fetch_executive_roster_unaffected(self):
        """같은 입력을 기존 fetch_executive_roster에 줘도 반환형·값이
        그대로다 — server.py의 find_actor_overlap과 runner.py의 겸직
        판정이 dict[str, set[str]]에 묶여 있으므로 MCP 도구 26개가
        무영향임을 증명한다."""
        from dart_risk_mcp.core.dart_client import fetch_executive_roster

        with patch("dart_risk_mcp.core.dart_client._retry",
                    side_effect=self._fake_retry_two_years):
            roster = fetch_executive_roster("00407814", "key", lookback_years=3)

        self.assertEqual(roster, {
            "신승수": {"2023", "2024"},
            "조중명": {"2023"},
        })

    def test_dart_no_data_status_returns_empty_list(self):
        """DART가 013(자료 없음)을 주면 빈 목록이고 예외가 없다 (셀트리온 실측)."""
        from dart_risk_mcp.core.dart_client import fetch_executive_roster_detail

        def _fake_retry(method, url, params=None, timeout=None):
            return _resp({"status": "013", "list": []})

        with patch("dart_risk_mcp.core.dart_client._retry", side_effect=_fake_retry):
            rows = fetch_executive_roster_detail("00126380", "key", lookback_years=1)

        self.assertEqual(rows, [])

    def test_empty_inputs_return_empty_list(self):
        from dart_risk_mcp.core.dart_client import fetch_executive_roster_detail
        self.assertEqual(fetch_executive_roster_detail("", "key"), [])
        self.assertEqual(fetch_executive_roster_detail("c", ""), [])

    def test_skips_blank_and_total_rows(self):
        from dart_risk_mcp.core.dart_client import fetch_executive_roster_detail

        def _fake_retry(method, url, params=None, timeout=None):
            return _resp({"status": "000", "list": [
                {"nm": " "}, {"nm": "계"}, {"nm": "합계"}, {"nm": "양민성"},
            ]})

        with patch("dart_risk_mcp.core.dart_client._retry", side_effect=_fake_retry):
            rows = fetch_executive_roster_detail("c", "key", lookback_years=1)

        self.assertEqual([r["nm"] for r in rows], ["양민성"])


if __name__ == "__main__":
    unittest.main()
