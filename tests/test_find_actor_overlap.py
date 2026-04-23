import unittest
from unittest.mock import patch


class TestFindActorOverlapMerging(unittest.TestCase):
    def test_merges_cb_and_rights_investors_with_source_tags(self):
        # 2개 기업이 동일 인수인을 CB(A기업) + 유상증자(B기업)에서 공유하는 시나리오
        from dart_risk_mcp.server import find_actor_overlap

        # Mock corp resolution
        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        def _disclosures(corp_code, api_key, lookback_days):
            # A기업: CB 공시 1건, B기업: 유상증자 공시 1건
            if corp_code == "a":
                return [{"rcept_no": "A001", "report_nm": "전환사채권발행결정",
                         "rcept_dt": "20240301"}]
            if corp_code == "b":
                return [{"rcept_no": "B001", "report_nm": "주요사항보고서(유상증자결정)",
                         "rcept_dt": "20240401"}]
            return []

        def _match_signals(report_nm):
            if "전환사채" in report_nm:
                return [{"key": "CB_BW", "label": "CB/BW발행", "score": 3}]
            if "유상증자" in report_nm:
                return [{"key": "3PCA", "label": "제3자배정", "score": 4}]
            return []

        with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
             patch("dart_risk_mcp.server.fetch_company_disclosures",
                   side_effect=_disclosures), \
             patch("dart_risk_mcp.server.match_signals", side_effect=_match_signals), \
             patch("dart_risk_mcp.server.extract_cb_investors",
                   return_value=[{"name": "공통펀드", "type": "사모", "amount": "1"}]), \
             patch("dart_risk_mcp.server.extract_rights_offering_investors",
                   return_value=[{"name": "공통펀드", "type": "제3자배정",
                                  "amount": "2", "source": "rights_offering"}]), \
             patch.dict("os.environ", {"DART_API_KEY": "test_key"}):
            result = find_actor_overlap(["a", "b"])

        self.assertIn("공통펀드", result)
        # source 태그 확인 — CB와 rights_offering 모두 표시
        self.assertIn("CB", result)
        self.assertIn("유상증자", result)

    def test_single_company_no_overlap(self):
        from dart_risk_mcp.server import find_actor_overlap

        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
             patch("dart_risk_mcp.server.fetch_company_disclosures",
                   return_value=[]), \
             patch.dict("os.environ", {"DART_API_KEY": "test_key"}):
            result = find_actor_overlap(["a"])

        # 입력 검증: 최소 2개 기업 필요
        self.assertIn("2개 이상", result)


if __name__ == "__main__":
    unittest.main()
