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
             patch("dart_risk_mcp.server.fetch_executive_roster", return_value={}), \
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
             patch("dart_risk_mcp.server.fetch_executive_roster", return_value={}), \
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
             patch("dart_risk_mcp.server.fetch_executive_roster", return_value={}), \
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

    def test_director_overlap_detected_across_companies(self):
        # 두 회사에 같은 임원(겸직) — 공시(인수자)는 없고 임원만으로 공통 행위자 탐지
        from dart_risk_mcp.server import find_actor_overlap

        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        def _roster(corp_code, api_key, lookback_years):
            if corp_code == "a":
                return {"신승수": {"2023", "2024"}, "김갑": {"2024"}}
            if corp_code == "b":
                return {"신승수": {"2022"}, "이을": {"2022"}}
            return {}

        with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
             patch("dart_risk_mcp.server.fetch_company_disclosures", return_value=[]), \
             patch("dart_risk_mcp.server.fetch_executive_roster", side_effect=_roster), \
             patch.dict("os.environ", {"DART_API_KEY": "test_key"}):
            result = find_actor_overlap(["a", "b"], lookback_years=3)

        # 신승수는 2개사 공통 행위자로, [임원] 경로로 표기
        self.assertIn("신승수", result)
        self.assertIn("[임원]", result)
        self.assertIn("2개 회사에", result)
        # 단일 회사 임원은 공통 행위자가 아님
        self.assertNotIn("⚠️ **김갑**", result)

    def test_director_and_investor_same_person_merge(self):
        # A사 임원 = B사 인수자가 동일인이면 공통 행위자로 묶인다
        from dart_risk_mcp.server import find_actor_overlap

        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        def _disclosures(corp_code, api_key, lookback_days):
            if corp_code == "b":
                return [{"rcept_no": "B001", "report_nm": "전환사채권발행결정",
                         "rcept_dt": "20240401"}]
            return []

        def _match_signals(report_nm):
            if "전환사채" in report_nm:
                return [{"key": "CB_BW", "label": "CB/BW발행", "score": 3}]
            return []

        def _roster(corp_code, api_key, lookback_years):
            if corp_code == "a":
                return {"양민성": {"2024"}}
            return {}

        with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
             patch("dart_risk_mcp.server.fetch_company_disclosures", side_effect=_disclosures), \
             patch("dart_risk_mcp.server.match_signals", side_effect=_match_signals), \
             patch("dart_risk_mcp.server.fetch_executive_roster", side_effect=_roster), \
             patch("dart_risk_mcp.server.extract_cb_investors",
                   return_value=[{"name": "양민성", "type": "사모", "amount": "1"}]), \
             patch.dict("os.environ", {"DART_API_KEY": "test_key"}):
            result = find_actor_overlap(["a", "b"])

        self.assertIn("양민성", result)
        self.assertIn("2개 회사에", result)
        # 두 경로가 함께 표기됨
        self.assertIn("[CB · 임원]", result)

    def test_watchlist_loads_saved_companies(self):
        # watchlist 이름을 주면 저장된 회사군이 분석 대상이 된다
        import tempfile
        from pathlib import Path
        from dart_risk_mcp.server import find_actor_overlap
        from dart_risk_mcp.core.watchlist import add_person

        seen_corps = []

        def _resolve(query, api_key):
            seen_corps.append(query)
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {
                "DART_WATCHLIST_PATH": str(Path(tmp) / "wl.json"),
                "DART_API_KEY": "test_key",
            }):
                add_person("신승수", ["회사가", "회사나"])
                with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
                     patch("dart_risk_mcp.server.fetch_company_disclosures", return_value=[]), \
                     patch("dart_risk_mcp.server.fetch_executive_roster", return_value={}):
                    find_actor_overlap(watchlist="신승수")

        self.assertIn("회사가", seen_corps)
        self.assertIn("회사나", seen_corps)

    def test_watchlist_unknown_name_message(self):
        import tempfile
        from pathlib import Path
        from dart_risk_mcp.server import find_actor_overlap

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {
                "DART_WATCHLIST_PATH": str(Path(tmp) / "wl.json"),
                "DART_API_KEY": "test_key",
            }):
                result = find_actor_overlap(["회사가", "회사나"], watchlist="유령")

        # 미등록 워치리스트는 안내하되 company_names로 계속 진행
        self.assertIn("유령", result)

    def test_known_actor_cross_reference_appended(self):
        # 탐지된 임원이 공개기록 레지스트리에 있으면 참고 섹션이 붙는다
        import json, tempfile
        from pathlib import Path
        from dart_risk_mcp.server import find_actor_overlap

        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        def _roster(corp_code, api_key, lookback_years):
            if corp_code in ("a", "b"):
                return {"신승수": {"2024"}}
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            ka = Path(tmp) / "ka.json"
            ka.write_text(json.dumps({"version": 1, "actors": {
                "신승수": [{"source": "DART 임원현황", "evidence": "CG인바이츠 등기임원",
                           "url": "https://dart.fss.or.kr", "date": "2024"}]
            }}, ensure_ascii=False), encoding="utf-8")
            with patch.dict("os.environ", {
                "DART_KNOWN_ACTORS_PATH": str(ka), "DART_API_KEY": "test_key",
            }):
                with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
                     patch("dart_risk_mcp.server.fetch_company_disclosures", return_value=[]), \
                     patch("dart_risk_mcp.server.fetch_executive_roster", side_effect=_roster):
                    result = find_actor_overlap(["a", "b"])

        self.assertIn("공개기록 참고", result)
        self.assertIn("신승수", result)
        self.assertIn("동명이인", result)

    def test_no_known_actor_no_section(self):
        # 레지스트리에 없으면 참고 섹션이 붙지 않는다
        import tempfile
        from pathlib import Path
        from dart_risk_mcp.server import find_actor_overlap

        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        with tempfile.TemporaryDirectory() as tmp:
            ka = Path(tmp) / "ka.json"
            ka.write_text('{"version":1,"actors":{}}', encoding="utf-8")
            with patch.dict("os.environ", {
                "DART_KNOWN_ACTORS_PATH": str(ka), "DART_API_KEY": "test_key",
            }):
                with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
                     patch("dart_risk_mcp.server.fetch_company_disclosures", return_value=[]), \
                     patch("dart_risk_mcp.server.fetch_executive_roster", return_value={}):
                    result = find_actor_overlap(["a", "b"])

        self.assertNotIn("공개기록 참고", result)

    def test_single_company_no_overlap(self):
        from dart_risk_mcp.server import find_actor_overlap

        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
             patch("dart_risk_mcp.server.fetch_company_disclosures",
                   return_value=[]), \
             patch("dart_risk_mcp.server.fetch_executive_roster", return_value={}), \
             patch.dict("os.environ", {"DART_API_KEY": "test_key"}):
            result = find_actor_overlap(["a"])

        # 입력 검증: 최소 2개 기업 필요 (실제 메시지는 "2개 이상 5개 이하")
        self.assertIn("2개 이상 5개 이하", result)


if __name__ == "__main__":
    unittest.main()
