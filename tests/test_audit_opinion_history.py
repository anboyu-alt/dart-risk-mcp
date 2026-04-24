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


def _make_side_effect(opinion=None, audit=None, non_audit=None,
                      target_year: str = "2025", status: str = "000"):
    """지정 연도 호출에만 데이터 반환. 다른 해에는 빈 리스트.

    연도 × 엔드포인트 루프가 있어도 items 자체의 bsns_year로 처리되므로
    한 연도 호출만 데이터를 반환해도 테스트 의도가 보존된다.
    """
    opinion = opinion or []
    audit = audit or []
    non_audit = non_audit or []

    def _side(method, url, **kwargs):
        if status != "000":
            return _resp(status=status)
        if kwargs.get("params", {}).get("bsns_year") != target_year:
            return _resp(lst=[])
        if "accnutAdtorNmNdAdtOpinion" in url:
            return _resp(lst=opinion)
        if "adtServcCnclsSttus" in url:
            return _resp(lst=audit)
        if "accnutAdtorNonAdtServcCnclsSttus" in url:
            return _resp(lst=non_audit)
        return _resp(lst=[])
    return _side


class TestFetchAuditOpinionHistory(unittest.TestCase):
    def setUp(self):
        dart_client._audit_history_cache.clear()

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_parses_opinion_auditor_year(self, mock_retry):
        mock_retry.side_effect = _make_side_effect(
            opinion=[
                {"bsns_year": "2025", "adtor": "삼일회계법인", "adt_opinion": "적정"},
                {"bsns_year": "2024", "adtor": "삼일회계법인", "adt_opinion": "적정"},
                {"bsns_year": "2023", "adtor": "한영회계법인", "adt_opinion": "적정"},
            ],
            audit=[{"bsns_year": "2025", "mendng": "820000000", "tot_reqre_time": "3000"}],
            non_audit=[{"bsns_year": "2025", "cntrct_cncls_de": "2025-03-10",
                        "servc_cn": "세무자문", "mendng": "110000000"}],
        )
        result = dart_client.fetch_audit_opinion_history("00000001", "KEY", 5)
        self.assertEqual(len(result["opinions"]), 3)
        self.assertEqual(result["opinions"][0]["year"], 2025)
        self.assertEqual(result["opinions"][0]["opinion"], "적정")
        self.assertEqual(result["opinions"][0]["auditor"], "삼일회계법인")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_detects_auditor_change(self, mock_retry):
        mock_retry.side_effect = _make_side_effect(
            opinion=[
                {"bsns_year": "2025", "adtor": "삼일", "adt_opinion": "적정"},
                {"bsns_year": "2024", "adtor": "한영", "adt_opinion": "적정"},
            ],
        )
        r = dart_client.fetch_audit_opinion_history("00000001", "KEY", 5)
        self.assertEqual(len(r["auditor_changes"]), 1)
        self.assertEqual(r["auditor_changes"][0]["from"], "한영")
        self.assertEqual(r["auditor_changes"][0]["to"], "삼일")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_no_change_when_same_auditor(self, mock_retry):
        mock_retry.side_effect = _make_side_effect(
            opinion=[
                {"bsns_year": "2025", "adtor": "삼일", "adt_opinion": "적정"},
                {"bsns_year": "2024", "adtor": "삼일", "adt_opinion": "적정"},
            ],
        )
        r = dart_client.fetch_audit_opinion_history("00000001", "KEY", 5)
        self.assertEqual(r["auditor_changes"], [])
        self.assertEqual(r["opinions"][0]["tenure_years"], 2)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_non_audit_warning_at_30_percent(self, mock_retry):
        mock_retry.side_effect = _make_side_effect(
            opinion=[{"bsns_year": "2025", "adtor": "삼일", "adt_opinion": "적정"}],
            audit=[{"bsns_year": "2025", "mendng": "700000000"}],
            non_audit=[{"bsns_year": "2025", "cntrct_cncls_de": "2025-03-10",
                        "servc_cn": "세무", "mendng": "300000000"}],
        )
        r = dart_client.fetch_audit_opinion_history("00000001", "KEY", 5)
        self.assertTrue(any("30%" in w for w in r["independence_warnings"]))

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_non_audit_no_warning_below_30_percent(self, mock_retry):
        mock_retry.side_effect = _make_side_effect(
            opinion=[{"bsns_year": "2025", "adtor": "삼일", "adt_opinion": "적정"}],
            audit=[{"bsns_year": "2025", "mendng": "900000000"}],
            non_audit=[{"bsns_year": "2025", "cntrct_cncls_de": "2025-03-10",
                        "servc_cn": "세무", "mendng": "100000000"}],
        )
        r = dart_client.fetch_audit_opinion_history("00000001", "KEY", 5)
        self.assertEqual(r["independence_warnings"], [])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_partial_failure_one_endpoint(self, mock_retry):
        def _side(method, url, **kwargs):
            if kwargs.get("params", {}).get("bsns_year") != "2025":
                return _resp(lst=[])
            if "accnutAdtorNmNdAdtOpinion" in url:
                return _resp(lst=[{"bsns_year": "2025", "adtor": "삼일", "adt_opinion": "적정"}])
            return _resp(status="013")  # adt fee & non-audit 실패
        mock_retry.side_effect = _side
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
        mock_retry.side_effect = _make_side_effect(
            opinion=[{"bsns_year": "2025", "adtor": "삼일", "adt_opinion": "적정"}],
        )
        dart_client.fetch_audit_opinion_history("00000099", "KEY", 5)
        calls_first = mock_retry.call_count
        dart_client.fetch_audit_opinion_history("00000099", "KEY", 5)
        # 2번째 호출은 캐시 히트이므로 추가 _retry 호출 없음
        self.assertEqual(mock_retry.call_count, calls_first)


class TestCheckDisclosureAnomalyAuditBonus(unittest.TestCase):
    """check_disclosure_anomaly — 감사의견 구조화 보강(+5점/+3점) 검증."""

    def setUp(self):
        dart_client._audit_history_cache.clear()

    @patch("dart_risk_mcp.server.fetch_audit_opinion_history")
    @patch("dart_risk_mcp.server.match_signals")
    @patch("dart_risk_mcp.server.fetch_company_disclosures")
    @patch("dart_risk_mcp.server.resolve_corp")
    def test_audit_bonus_from_auditor_change(
        self, mock_resolve, mock_fetch, mock_match, mock_audit_hist
    ):
        from dart_risk_mcp import server

        mock_resolve.return_value = ("테스트", {"corp_code": "00000001", "stock_code": "000000"})
        mock_fetch.return_value = [
            {"rcept_no": "1", "rcept_dt": "20260101", "report_nm": "사업보고서"},
        ]
        mock_match.return_value = []  # 키워드 매칭은 0건
        mock_audit_hist.return_value = {
            "opinions": [],
            "auditor_changes": [
                {"from_year": 2023, "to_year": 2024, "from": "A", "to": "B"},
                {"from_year": 2024, "to_year": 2025, "from": "B", "to": "C"},
            ],
            "independence_warnings": [],
        }
        result = server.check_disclosure_anomaly("테스트", 365)
        self.assertIn("감사인 교체 2회", result)
        self.assertIn("+5점", result)

    @patch("dart_risk_mcp.server.fetch_audit_opinion_history")
    @patch("dart_risk_mcp.server.match_signals")
    @patch("dart_risk_mcp.server.fetch_company_disclosures")
    @patch("dart_risk_mcp.server.resolve_corp")
    def test_audit_bonus_from_non_audit_warning(
        self, mock_resolve, mock_fetch, mock_match, mock_audit_hist
    ):
        from dart_risk_mcp import server

        mock_resolve.return_value = ("테스트", {"corp_code": "00000001", "stock_code": "000000"})
        mock_fetch.return_value = [
            {"rcept_no": "1", "rcept_dt": "20260101", "report_nm": "사업보고서"},
        ]
        mock_match.return_value = []
        mock_audit_hist.return_value = {
            "opinions": [],
            "auditor_changes": [],
            "independence_warnings": ["2025", "2024"],
        }
        result = server.check_disclosure_anomaly("테스트", 365)
        self.assertIn("비감사용역 비중 초과", result)
        self.assertIn("2025", result)
        self.assertIn("+3점", result)


if __name__ == "__main__":
    unittest.main()
