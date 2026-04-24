"""analyze_company_risk v0.6.0 통합 검증.

v0.7.1에서 렌더러가 내부 flag 코드('AR_SURGE', 'CAPITAL_CHURN')를 사용자 출력
경계 밖으로 내보내지 않도록 재작성되면서, 이 파일의 assert 대상도 한글 prose
제목(`FLAG_PROSE[...]["title"]`)로 갱신했다. 내부 코드가 다시 노출되면
tests/test_golden_output_hygiene.py가 대신 회귀를 잡는다.
"""
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
        # 12개월 내 희석성 자본 이벤트 3건 → CAPITAL_CHURN 발화 기대 (v0.6.1 이원화 규칙)
        return [
            {"rcept_no": "20250101000001", "rcept_dt": "20250101",
             "report_nm": "유상증자결정(제3자배정)", "corp_code": "00000001"},
            {"rcept_no": "20250501000001", "rcept_dt": "20250501",
             "report_nm": "전환사채권발행결정", "corp_code": "00000001"},
            {"rcept_no": "20251001000001", "rcept_dt": "20251001",
             "report_nm": "교환사채권발행결정", "corp_code": "00000001"},
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
    @patch("dart_risk_mcp.server.fetch_financial_statements_all")
    @patch("dart_risk_mcp.server.fetch_company_disclosures")
    @patch("dart_risk_mcp.server.resolve_corp")
    def test_includes_capital_churn_flag(self, m_resolve, m_disc, m_fs, m_fund):
        m_resolve.return_value = ("테스트기업", {"corp_code": "00000001", "stock_code": "000001"})
        m_disc.return_value = self._mock_disclosures()
        m_fs.return_value = []  # 재무 조회 실패/없음
        m_fund.return_value = []
        from dart_risk_mcp.server import analyze_company_risk
        out = analyze_company_risk("테스트기업", 365)
        # v0.7.1+: 내부 코드 'CAPITAL_CHURN' 대신 한글 라벨('자본 이벤트 과다 반복')이
        # signal_event 스트림에 삽입된 뒤 '가장 무게 있는 신호' 헤드라인으로 노출된다.
        self.assertIn("자본 이벤트 과다 반복", out)
        self.assertNotIn("CAPITAL_CHURN", out)

    @patch("dart_risk_mcp.server.fetch_fund_usage")
    @patch("dart_risk_mcp.server.fetch_financial_statements_all")
    @patch("dart_risk_mcp.server.fetch_company_disclosures")
    @patch("dart_risk_mcp.server.resolve_corp")
    def test_includes_financial_anomaly_flag(self, m_resolve, m_disc, m_fs, m_fund):
        m_resolve.return_value = ("테스트기업", {"corp_code": "00000001", "stock_code": "000001"})
        m_disc.return_value = []
        m_fs.return_value = self._mock_fs()
        m_fund.return_value = []
        from dart_risk_mcp.server import analyze_company_risk
        out = analyze_company_risk("테스트기업", 365)
        # v0.7.1+: 내부 코드 'AR_SURGE' 대신 FLAG_PROSE 한글 제목이 노출된다.
        self.assertIn("매출채권이 매출보다 훨씬 빠르게 늘고 있습니다", out)
        self.assertNotIn("AR_SURGE", out)

    @patch("dart_risk_mcp.server.fetch_fund_usage")
    @patch("dart_risk_mcp.server.fetch_financial_statements_all")
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
