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

    def test_company_signal_keys_collects(self):
        import scripts.discover_actors as da
        discs = [{"report_nm": "전환사채권발행결정"},
                 {"report_nm": "최대주주변경"},
                 {"report_nm": "[기재정정]조회공시요구"}]  # 정정은 제외

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
    def _patches(self, da, discs, signal_map, company_keys, cb_invs, rights_invs):
        return [
            patch.object(da, "fetch_market_disclosures", return_value=discs),
            patch.object(da, "match_signals", side_effect=lambda n: signal_map.get(n, [])),
            patch.object(da, "is_amendment_disclosure", return_value=False),
            patch.object(da, "company_signal_keys", side_effect=lambda cc, k, **kw: company_keys.get(cc, set())),
            patch.object(da, "extract_cb_investors", return_value=cb_invs),
            patch.object(da, "extract_rights_offering_investors", return_value=rights_invs),
        ]

    def test_collects_only_problem_company_persons(self):
        import scripts.discover_actors as da
        from contextlib import ExitStack
        discs = [{"rcept_no": "R1", "report_nm": "전환사채권발행결정",
                  "corp_name": "문제전자", "corp_code": "c1", "rcept_dt": "20260612"},
                 {"rcept_no": "R2", "report_nm": "전환사채권발행결정",
                  "corp_name": "정상전자", "corp_code": "c2", "rcept_dt": "20260612"}]
        signal_map = {"전환사채권발행결정": [{"key": "CB_BW"}]}
        company_keys = {"c1": {"CB_BW", "SHAREHOLDER"},   # 문제 회사
                        "c2": {"CB_BW"}}                   # 정상(불안정 없음)
        with ExitStack() as st:
            for p in self._patches(da, discs, signal_map, company_keys,
                                   [{"name": "홍길동"}, {"name": "아레스1호투자조합"}], []):
                st.enter_context(p)
            sightings = da.collect_problem_sightings("key")
        names = [s["name"] for s in sightings]
        self.assertIn("홍길동", names)              # 문제회사 개인
        self.assertNotIn("아레스1호투자조합", names)  # 조합 제외
        self.assertTrue(all(s["corp_code"] == "c1" for s in sightings))  # 정상회사 c2 제외
        self.assertEqual(sightings[0]["rcept_no"], "R1")


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


if __name__ == "__main__":
    unittest.main()
