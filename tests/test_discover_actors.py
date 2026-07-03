import unittest
from unittest.mock import patch


class TestDiscoverPredicates(unittest.TestCase):
    def test_is_problem_company_requires_both(self):
        import scripts.discover_actors as da
        self.assertTrue(da.is_problem_company({"CB_BW", "SHAREHOLDER"}))
        self.assertTrue(da.is_problem_company({"3PCA", "AUDIT", "MGMT"}))
        self.assertFalse(da.is_problem_company({"CB_BW", "MGMT"}))       # 불안정 없음
        self.assertFalse(da.is_problem_company({"SHAREHOLDER", "AUDIT"})) # 자금조달 없음
        self.assertFalse(da.is_problem_company(set()))

    def test_is_person_filters_orgs(self):
        import scripts.discover_actors as da
        self.assertTrue(da._is_person("홍길동"))
        self.assertTrue(da._is_person("신승수"))
        self.assertFalse(da._is_person("르퓨쳐 코스닥벤처 일반사모투자신탁"))
        self.assertFalse(da._is_person("(주)스마트에쿼티파트너스"))
        self.assertFalse(da._is_person("아레스1호투자조합"))
        self.assertFalse(da._is_person(""))

    def test_is_person_filters_institutions_and_foreign_orgs(self):
        import scripts.discover_actors as da
        self.assertFalse(da._is_person("Citibank, N.A."))
        self.assertFalse(da._is_person("AMPLE OCEAN LIMITED"))
        self.assertFalse(da._is_person("PAN ORION Corp. Limited"))
        self.assertFalse(da._is_person("RUI XING INTERNATIONALHOLDINGS LIMITED"))
        self.assertFalse(da._is_person("ZHUOHUA INVESTMENT HOLDINGS PTE. LTD"))
        self.assertFalse(da._is_person("한국산업은행(첨단전략산업기금의 관리,운용기관)"))
        self.assertFalse(da._is_person("한국토지주택공사 부산울산지역본부"))
        self.assertFalse(da._is_person("아주기술시스템"))
        self.assertFalse(da._is_person("BOLD (Business Opportunities for L'Oreal Development)"))
        # 정상 개인명(로마자 3단어 이하)은 여전히 통과
        self.assertTrue(da._is_person("DING SHAO BIN"))
        self.assertTrue(da._is_person("GAN XIAOCHUN"))

    def test_is_person_filters_names_with_digits(self):
        # '베이스100' 같은 숫자 섞인 법인명은 개인이 아님
        import scripts.discover_actors as da
        self.assertFalse(da._is_person("베이스100"))
        self.assertFalse(da._is_person("에이치1"))

    def test_company_signal_keys_collects(self):
        import scripts.discover_actors as da
        discs = [{"report_nm": "전환사채권발행결정"},
                 {"report_nm": "최대주주변경"},
                 {"report_nm": "[기재정정]조회공시요구"}]  # 신호 집계에서 정정은 제외

        def _match(nm):
            if "전환사채" in nm:
                return [{"key": "CB_BW"}]
            if "최대주주변경" in nm:
                return [{"key": "SHAREHOLDER"}]
            if "조회공시" in nm:
                return [{"key": "INQUIRY"}]
            return []

        with patch.object(da, "fetch_company_disclosures", return_value=discs), \
             patch.object(da, "match_signals", side_effect=_match), \
             patch.object(da, "is_amendment_disclosure", side_effect=lambda n: n.startswith("[기재정정]")):
            keys = da.company_signal_keys("cc", "key")
        self.assertEqual(keys, {"CB_BW", "SHAREHOLDER"})  # 정정 조회공시 제외


class TestCollectSightings(unittest.TestCase):
    def _patches(self, da, discs, signal_map, cb_invs, rights_invs):
        return [
            patch.object(da, "fetch_market_disclosures", return_value=discs),
            patch.object(da, "match_signals", side_effect=lambda n: signal_map.get(n, [])),
            patch.object(da, "extract_cb_investors", return_value=cb_invs),
            patch.object(da, "extract_rights_offering_investors", return_value=rights_invs),
        ]

    def test_collects_persons_from_all_funding_filings(self):
        # 문제 회사 필터는 수집 시점에 적용하지 않는다 — 아직 깨끗한 회사의
        # 인수자도 기록해야 이후 회사가 무너질 때 추적 가능(등재 시점 재평가).
        import scripts.discover_actors as da
        from contextlib import ExitStack
        discs = [{"rcept_no": "R1", "report_nm": "전환사채권발행결정",
                  "corp_name": "문제전자", "corp_code": "c1", "rcept_dt": "20260612"},
                 {"rcept_no": "R2", "report_nm": "전환사채권발행결정",
                  "corp_name": "아직깨끗전자", "corp_code": "c2", "rcept_dt": "20260612"}]
        signal_map = {"전환사채권발행결정": [{"key": "CB_BW"}]}
        with ExitStack() as st:
            for p in self._patches(da, discs, signal_map,
                                   [{"name": "홍길동"}, {"name": "아레스1호투자조합"}], []):
                st.enter_context(p)
            sightings, stats = da.collect_funding_sightings("key")
        names = [s["name"] for s in sightings]
        self.assertIn("홍길동", names)              # 개인 수집
        self.assertNotIn("아레스1호투자조합", names)  # 조합 제외
        corp_codes = {s["corp_code"] for s in sightings}
        self.assertEqual(corp_codes, {"c1", "c2"})  # 두 회사 모두 수집
        self.assertEqual(stats["scanned"], 2)
        self.assertEqual(stats["funding"], 2)
        self.assertEqual(stats["extracted"], 2)
        self.assertFalse(stats["truncated"])

    def test_collects_from_amendment_filings(self):
        # 정정공시([기재정정])도 접두사를 벗겨 자금조달 유형으로 판별하고 추출한다.
        # 실전에서 인수자 확정 명단은 정정본에 실리는 경우가 많다.
        import scripts.discover_actors as da
        from contextlib import ExitStack
        discs = [{"rcept_no": "R9", "report_nm": "[기재정정]전환사채권발행결정",
                  "corp_name": "정정전자", "corp_code": "c9", "rcept_dt": "20260612"}]
        signal_map = {"전환사채권발행결정": [{"key": "CB_BW"}]}  # 접두사 제거 후 매칭
        with ExitStack() as st:
            for p in self._patches(da, discs, signal_map, [{"name": "김확정"}], []):
                st.enter_context(p)
            sightings, stats = da.collect_funding_sightings("key")
        self.assertEqual([s["name"] for s in sightings], ["김확정"])
        self.assertEqual(sightings[0]["rcept_no"], "R9")
        self.assertEqual(stats["funding"], 1)

    def test_truncation_flag_when_page_cap_reached(self):
        import scripts.discover_actors as da
        from contextlib import ExitStack
        discs = [{"rcept_no": f"R{i}", "report_nm": "임원변동",
                  "corp_name": "X", "corp_code": "c", "rcept_dt": "20260612"}
                 for i in range(100)]
        with ExitStack() as st:
            for p in self._patches(da, discs, {}, [], []):
                st.enter_context(p)
            _, stats = da.collect_funding_sightings("key", max_pages=1)
        self.assertTrue(stats["truncated"])


class TestMergeAndPromote(unittest.TestCase):
    def test_merge_dedup_and_window(self):
        import scripts.discover_actors as da
        data = {"sightings": {"홍길동": [
            {"corp_code": "c1", "rcept_no": "R1", "date": "2026-06"}]}}
        new = [{"name": "홍길동", "corp_code": "c1", "rcept_no": "R1", "date": "2026-06"},  # 중복
               {"name": "홍길동", "corp_code": "c2", "rcept_no": "R2", "date": "2026-06"}]  # 신규
        changed = da.merge_sightings(data, new, window_months=12)
        self.assertTrue(changed)
        rcepts = {e["rcept_no"] for e in data["sightings"]["홍길동"]}
        self.assertEqual(rcepts, {"R1", "R2"})

    def test_merge_normalizes_case_and_whitespace_variants(self):
        # 'Liu Huan'과 'LIU HUAN'처럼 표기만 다른 동일 인물이 분리 집계되던 버그 회귀 테스트
        import scripts.discover_actors as da
        data = {"sightings": {}}
        new = [{"name": "Liu Huan", "corp_code": "c1", "rcept_no": "R1", "date": "2026-06"},
               {"name": "LIU  HUAN", "corp_code": "c2", "rcept_no": "R2", "date": "2026-06"}]
        changed = da.merge_sightings(data, new, window_months=12)
        self.assertTrue(changed)
        self.assertEqual(set(data["sightings"].keys()), {"LIU HUAN"})
        rcepts = {e["rcept_no"] for e in data["sightings"]["LIU HUAN"]}
        self.assertEqual(rcepts, {"R1", "R2"})

    def test_merge_drops_old_outside_window(self):
        import scripts.discover_actors as da
        data = {"sightings": {"김갑": [
            {"corp_code": "c1", "rcept_no": "OLD", "date": "2000-01"}]}}
        changed = da.merge_sightings(data, [], window_months=12)
        self.assertTrue(changed)
        self.assertNotIn("김갑", data["sightings"])  # 전부 윈도우 밖 → 제거

    def test_promote_two_distinct_companies(self):
        import scripts.discover_actors as da
        sd = {"sightings": {"홍길동": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06"}]}}
        kd = {"actors": {}}
        promoted = da.promote_repeat_actors(sd, kd, n=2)
        self.assertEqual(promoted, ["홍길동"])
        self.assertIn("홍길동", kd["actors"])
        self.assertEqual(kd["actors"]["홍길동"][0]["status"], "auto_matched")

    def test_promote_applies_problem_gate_at_promotion_time(self):
        # 회사 상태 판정은 등재 시점에 수행 — 문제 회사 2곳 미만이면 등재 안 함
        import scripts.discover_actors as da
        sd = {"sightings": {"홍길동": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06"}]}}
        kd = {"actors": {}}
        # c1만 문제 회사 → 임계치(2) 미달 → 등재 안 함
        promoted = da.promote_repeat_actors(sd, kd, n=2,
                                            is_problem_fn=lambda cc: cc == "c1")
        self.assertEqual(promoted, [])
        self.assertEqual(kd["actors"], {})
        # 둘 다 문제 회사 → 등재
        promoted = da.promote_repeat_actors(sd, kd, n=2, is_problem_fn=lambda cc: True)
        self.assertEqual(promoted, ["홍길동"])
        self.assertIn("A", kd["actors"]["홍길동"][0]["evidence"])
        self.assertIn("B", kd["actors"]["홍길동"][0]["evidence"])

    def test_promote_evidence_lists_problem_companies_only(self):
        # 3곳 중 2곳만 문제로 판정되면 evidence에 그 2곳만 표기
        import scripts.discover_actors as da
        sd = {"sightings": {"홍길동": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06"},
            {"corp_code": "c3", "corp": "C", "rcept_no": "R3", "date": "2026-06"}]}}
        kd = {"actors": {}}
        promoted = da.promote_repeat_actors(sd, kd, n=2,
                                            is_problem_fn=lambda cc: cc in ("c1", "c3"))
        self.assertEqual(promoted, ["홍길동"])
        ev = kd["actors"]["홍길동"][0]["evidence"]
        self.assertIn("2곳", ev)
        self.assertIn("A", ev)
        self.assertIn("C", ev)
        self.assertNotIn("B", ev)

    def test_promote_skips_non_person_legacy_keys(self):
        # 과거 수집분에 남은 법인·기관 키는 등재하지 않는다
        import scripts.discover_actors as da
        sd = {"sightings": {"베이스100": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06"}]}}
        kd = {"actors": {}}
        self.assertEqual(da.promote_repeat_actors(sd, kd, n=2), [])
        self.assertEqual(kd["actors"], {})

    def test_promote_skips_single_company(self):
        import scripts.discover_actors as da
        sd = {"sightings": {"외톨이": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"}]}}
        kd = {"actors": {}}
        self.assertEqual(da.promote_repeat_actors(sd, kd, n=2), [])
        self.assertEqual(kd["actors"], {})

    def test_promote_skips_already_discovered(self):
        import scripts.discover_actors as da
        sd = {"sightings": {"홍길동": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06"}]}}
        kd = {"actors": {"홍길동": [{"source": "자동 발굴", "status": "auto_matched"}]}}
        self.assertEqual(da.promote_repeat_actors(sd, kd, n=2), [])  # 이미 발굴 등재


class TestDailyReport(unittest.TestCase):
    def test_build_daily_report_always_summarizes(self):
        import scripts.discover_actors as da
        kd = {"actors": {"A": [{"status": "verified"}],
                         "B": [{"status": "auto_matched"}],
                         "C": [{"status": "maintainer_seed"}]}}
        r = da.build_daily_report({"sightings": {}}, kd, True, ["B"])
        self.assertIn("오늘 실행: 정상", r)
        self.assertIn("sightings: 갱신", r)
        self.assertIn("신규 등재: 1명", r)
        self.assertIn("verified 1", r)
        self.assertIn("auto_matched 1", r)
        self.assertIn("maintainer_seed 1", r)

    def test_build_daily_report_no_change_still_reports(self):
        import scripts.discover_actors as da
        r = da.build_daily_report({"sightings": {}}, {"actors": {}}, False, [])
        self.assertIn("오늘 실행: 정상", r)   # 변경 없어도 heartbeat
        self.assertIn("sightings: 무변경", r)
        self.assertIn("신규 등재: 0명", r)

    def test_build_daily_report_includes_collection_stats(self):
        # 수집 통계가 리포트에 실려야 '0명'이 정상인지 수집 고장인지 판별 가능
        import scripts.discover_actors as da
        stats = {"scanned": 312, "funding": 41, "extracted": 7, "truncated": False}
        r = da.build_daily_report({"sightings": {"X": []}}, {"actors": {}}, True, [],
                                  stats=stats)
        self.assertIn("공시 312건 스캔", r)
        self.assertIn("자금조달 41건", r)
        self.assertIn("개인 인수자 7명 추출", r)
        self.assertIn("추적 인물 1명", r)
        self.assertNotIn("페이지 상한", r)

    def test_build_daily_report_warns_on_truncation(self):
        import scripts.discover_actors as da
        stats = {"scanned": 1000, "funding": 90, "extracted": 3, "truncated": True}
        r = da.build_daily_report({"sightings": {}}, {"actors": {}}, True, [], stats=stats)
        self.assertIn("페이지 상한 도달", r)


if __name__ == "__main__":
    unittest.main()
