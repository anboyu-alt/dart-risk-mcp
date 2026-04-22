"""analyze_company_risk v0.6.0 통합 검증."""
import os
import unittest
from unittest.mock import patch


class TestAnalyzeV6Integration(unittest.TestCase):
    def setUp(self):
        os.environ["DART_API_KEY"] = "TESTKEY"
        # Re-read module-level _DART_API_KEY
        import dart_risk_mcp.server as _srv
        _srv._DART_API_KEY = "TESTKEY"

    def _mock_disclosures(self):
        # 12개월 내 자본 이벤트 3건 → CAPITAL_CHURN 발화 기대
        return [
            {"rcept_no": "20250101000001", "rcept_dt": "20250101",
             "report_nm": "유상증자결정(제3자배정)", "corp_code": "00000001"},
            {"rcept_no": "20250501000001", "rcept_dt": "20250501",
             "report_nm": "전환사채권발행결정", "corp_code": "00000001"},
            {"rcept_no": "20251001000001", "rcept_dt": "20251001",
             "report_nm": "자기주식취득결정", "corp_code": "00000001"},
        ]

    def _mock_fs(self):
        # AR_SURGE 발화: 매출채권/매출 전기 20% → 당기 71%
        return [
            {"account_nm": "매출액", "thstrm_amount": "1,000", "frmtrm_amount": "1,000"},
            {"account_nm": "매출채권", "thstrm_amount": "710", "frmtrm_amount": "200"},
            {"account_nm": "재고자산", "thstrm_amount": "100", "frmtrm_amount": "100"},
            {"account_nm": "당기순이익", "thstrm_amount": "50", "frmtrm_amount": "50"},
            {"account_nm": "영업활동현금흐름", "thstrm_amount": "50", "frmtrm_amount": "50"},
            {"account_nm": "자본총계", "thstrm_amount": "500", "frmtrm_amount": "500"},
            {"account_nm": "자본금", "thstrm_amount": "100", "frmtrm_amount": "100"},
        ]

    @patch("dart_risk_mcp.server.fetch_fund_usage")
    @patch("dart_risk_mcp.server.fetch_financial_statements")
    @patch("dart_risk_mcp.server.fetch_company_disclosures")
    @patch("dart_risk_mcp.server.resolve_corp")
    def test_includes_capital_churn_flag(self, m_resolve, m_disc, m_fs, m_fund):
        m_resolve.return_value = ("테스트기업", {"corp_code": "00000001", "stock_code": "000001"})
        m_disc.return_value = self._mock_disclosures()
        m_fs.return_value = []  # 재무 조회 실패/없음
        m_fund.return_value = []
        from dart_risk_mcp.server import analyze_company_risk
        out = analyze_company_risk("테스트기업", 365)
        self.assertIn("CAPITAL_CHURN", out)

    @patch("dart_risk_mcp.server.fetch_fund_usage")
    @patch("dart_risk_mcp.server.fetch_financial_statements")
    @patch("dart_risk_mcp.server.fetch_company_disclosures")
    @patch("dart_risk_mcp.server.resolve_corp")
    def test_includes_financial_anomaly_flag(self, m_resolve, m_disc, m_fs, m_fund):
        m_resolve.return_value = ("테스트기업", {"corp_code": "00000001", "stock_code": "000001"})
        m_disc.return_value = []
        m_fs.return_value = self._mock_fs()
        m_fund.return_value = []
        from dart_risk_mcp.server import analyze_company_risk
        out = analyze_company_risk("테스트기업", 365)
        self.assertIn("AR_SURGE", out)

    @patch("dart_risk_mcp.server.fetch_fund_usage")
    @patch("dart_risk_mcp.server.fetch_financial_statements")
    @patch("dart_risk_mcp.server.fetch_company_disclosures")
    @patch("dart_risk_mcp.server.resolve_corp")
    def test_financial_fetch_failure_isolated(self, m_resolve, m_disc, m_fs, m_fund):
        m_resolve.return_value = ("테스트기업", {"corp_code": "00000001", "stock_code": "000001"})
        m_disc.return_value = []
        m_fs.side_effect = Exception("network error")
        m_fund.return_value = []
        from dart_risk_mcp.server import analyze_company_risk
        out = analyze_company_risk("테스트기업", 365)
        self.assertIsInstance(out, str)
        self.assertIn("테스트기업", out)


if __name__ == "__main__":
    unittest.main()
