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
        # v0.7.x 포맷: 공통 행위자 라인은 "2개 회사에 [CB · 유상증자] 경로로 등장" 형태.
        # "N개 회사" 집계 문구(separator=" · ")와 기업별 명단의 [CB]/[유상증자]
        # 소스 태그로 머지 결과를 검증한다.
        self.assertIn("2개 회사에", result)
        self.assertIn("[CB · 유상증자]", result)
        # 기업별 인수자 요약: 각 인수자 앞에 "[CB]" 또는 "[유상증자]" 소스 태그가 붙음.
        self.assertIn("[CB]", result)
        self.assertIn("[유상증자]", result)

    def _capture_lookback(self, *call_args, **call_kwargs):
        """find_actor_overlap 호출 시 fetch_company_disclosures에 전달된
        lookback_days 값을 캡처해 반환한다."""
        from dart_risk_mcp.server import find_actor_overlap

        captured = {}

        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        def _disclosures(corp_code, api_key, lookback_days):
            captured["lookback_days"] = lookback_days
            return []

        with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
             patch("dart_risk_mcp.server.fetch_company_disclosures",
                   side_effect=_disclosures), \
             patch.dict("os.environ", {"DART_API_KEY": "test_key"}):
            find_actor_overlap(*call_args, **call_kwargs)

        return captured["lookback_days"]

    def test_default_lookback_is_one_year(self):
        # lookback_years 미지정 시 기존 동작(365일)을 유지해야 한다 (하위호환).
        self.assertEqual(self._capture_lookback(["a", "b"]), 365)

    def test_lookback_years_widens_disclosure_window(self):
        # lookback_years=3 지정 시 조회 윈도우가 3*365일로 확장된다.
        self.assertEqual(self._capture_lookback(["a", "b"], lookback_years=3), 3 * 365)

    def test_lookback_years_clamped_to_five(self):
        # 무자본 M&A 다년 추적이라도 상한은 5년으로 제한된다.
        self.assertEqual(self._capture_lookback(["a", "b"], lookback_years=99), 5 * 365)

    def _run_empty(self, *call_args, **call_kwargs):
        """공시 0건 시나리오로 find_actor_overlap을 실행해 출력 문자열을 반환한다."""
        from dart_risk_mcp.server import find_actor_overlap

        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
             patch("dart_risk_mcp.server.fetch_company_disclosures", return_value=[]), \
             patch.dict("os.environ", {"DART_API_KEY": "test_key"}):
            return find_actor_overlap(*call_args, **call_kwargs)

    def test_default_window_label_unchanged(self):
        # 기본 1년: 기존 '최근 365일' 문구를 유지해 골드와 호환된다.
        self.assertIn("최근 365일", self._run_empty(["a", "b"]))

    def test_multi_year_window_label_is_honest(self):
        # 3년 조회 시 출력 안내가 '최근 3년'을 반영하고, 거짓인 '최근 365일'은 쓰지 않는다.
        result = self._run_empty(["a", "b"], lookback_years=3)
        self.assertIn("최근 3년", result)
        self.assertNotIn("최근 365일", result)

    def test_single_company_no_overlap(self):
        from dart_risk_mcp.server import find_actor_overlap

        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
             patch("dart_risk_mcp.server.fetch_company_disclosures",
                   return_value=[]), \
             patch.dict("os.environ", {"DART_API_KEY": "test_key"}):
            result = find_actor_overlap(["a"])

        # 입력 검증: 최소 2개 기업 필요 (실제 메시지는 "2개 이상 5개 이하")
        self.assertIn("2개 이상 5개 이하", result)


if __name__ == "__main__":
    unittest.main()
