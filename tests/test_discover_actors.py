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

    def test_collects_persons_funds_corps_but_not_institutions(self):
        # 문제 회사 필터는 수집 시점에 적용하지 않는다 — 아직 깨끗한 회사의
        # 인수자도 기록해야 이후 회사가 무너질 때 추적 가능(등재 시점 재평가).
        # 개인·조합·법인은 수집하고, 제도권 기관(반복 등장이 정상)만 제외한다.
        import scripts.discover_actors as da
        from contextlib import ExitStack
        discs = [{"rcept_no": "R1", "report_nm": "전환사채권발행결정",
                  "corp_name": "문제전자", "corp_code": "c1", "rcept_dt": "20260612"},
                 {"rcept_no": "R2", "report_nm": "전환사채권발행결정",
                  "corp_name": "아직깨끗전자", "corp_code": "c2", "rcept_dt": "20260612"}]
        signal_map = {"전환사채권발행결정": [{"key": "CB_BW"}]}
        invs = [{"name": "홍길동"}, {"name": "아레스1호투자조합"},
                {"name": "(주)스마트에쿼티파트너스"}, {"name": "한국투자증권"}]
        with ExitStack() as st:
            for p in self._patches(da, discs, signal_map, invs, []):
                st.enter_context(p)
            sightings, stats = da.collect_funding_sightings("key")
        by_name = {s["name"]: s["kind"] for s in sightings}
        self.assertEqual(by_name.get("홍길동"), "person")
        self.assertEqual(by_name.get("아레스1호투자조합"), "fund")
        self.assertEqual(by_name.get("(주)스마트에쿼티파트너스"), "corp")
        self.assertNotIn("한국투자증권", by_name)   # 제도권 기관 제외
        corp_codes = {s["corp_code"] for s in sightings}
        self.assertEqual(corp_codes, {"c1", "c2"})  # 두 회사 모두 수집
        self.assertEqual(stats["scanned"], 2)
        self.assertEqual(stats["funding"], 2)
        self.assertEqual(stats["extracted"], 6)     # (개인+조합+법인) × 공시 2건
        self.assertEqual(stats["extracted_persons"], 2)
        self.assertEqual(stats["extracted_entities"], 4)
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


class TestFundBackers(unittest.TestCase):
    def test_extract_fund_backers_from_document(self):
        from unittest.mock import patch
        from dart_risk_mcp.core import cb_extractor as ce
        doc = ("<TABLE>발행 대상자: 아레스1호투자조합 (조합 기본정보) "
               "업무집행조합원: 김지피 최대출자자: 박엘피 지분율 45%</TABLE>")
        with patch.object(ce, "_fetch_text", return_value=doc):
            out = ce.extract_fund_backers("R1", "key", ["아레스1호투자조합"])
        got = {(b["role"], b["name"]) for b in out}
        self.assertIn(("대표조합원", "김지피"), got)
        self.assertIn(("최대출자자", "박엘피"), got)
        self.assertTrue(all(b["fund"] == "아레스1호투자조합" for b in out))

    def test_extract_fund_backers_empty_when_absent(self):
        # 서식 개정 전 공시 등 기재 없음 → 빈 결과 (graceful)
        from unittest.mock import patch
        from dart_risk_mcp.core import cb_extractor as ce
        with patch.object(ce, "_fetch_text", return_value="조합 언급만 아레스1호투자조합"):
            self.assertEqual(ce.extract_fund_backers("R1", "key", ["아레스1호투자조합"]), [])

    def test_collect_adds_backer_sightings_with_via(self):
        import scripts.discover_actors as da
        from contextlib import ExitStack
        from unittest.mock import patch
        discs = [{"rcept_no": "R1", "report_nm": "전환사채권발행결정",
                  "corp_name": "문제전자", "corp_code": "c1", "rcept_dt": "20260612"}]
        signal_map = {"전환사채권발행결정": [{"key": "CB_BW"}]}
        backers = [{"fund": "아레스1호투자조합", "role": "대표조합원", "name": "김지피"}]
        with ExitStack() as st:
            for p in self._patches if False else []:
                pass
            with patch.object(da, "fetch_market_disclosures", return_value=discs), \
                 patch.object(da, "match_signals",
                              side_effect=lambda n: signal_map.get(n, [])), \
                 patch.object(da, "extract_cb_investors",
                              return_value=[{"name": "아레스1호투자조합"}]), \
                 patch.object(da, "extract_rights_offering_investors", return_value=[]), \
                 patch.object(da, "extract_fund_backers", return_value=backers) as bc:
                sightings, stats = da.collect_funding_sightings("key")
        bc.assert_called_once_with("R1", "key", ["아레스1호투자조합"])
        by_name = {s["name"]: s for s in sightings}
        self.assertIn("김지피", by_name)
        self.assertEqual(by_name["김지피"]["via"], "아레스1호투자조합 대표조합원")
        self.assertEqual(by_name["김지피"]["kind"], "person")
        self.assertEqual(stats["extracted_backers"], 1)

    def test_promote_tags_fund_backer(self):
        import scripts.discover_actors as da
        sd = {"sightings": {"김지피": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06",
             "via": "아레스1호투자조합 대표조합원"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06",
             "via": "제네시스2호조합 대표조합원"}]}}
        kd = {"actors": {}}
        self.assertEqual(da.promote_repeat_actors(sd, kd, n=2), ["김지피"])
        self.assertIn("조합 배후 인물", kd["actors"]["김지피"][0]["tags"])

    def test_report_shows_watch_candidates(self):
        import scripts.discover_actors as da
        r = da.build_daily_report({"sightings": {}}, {"actors": {}}, True, [],
                                  watch=[("홍길동", 3, 1)])
        self.assertIn("등재 임박 후보", r)
        self.assertIn("홍길동(3개사, 문제 1곳)", r)


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

    def test_merge_prunes_fragment_keys(self):
        # 추출 조각 키는 병합 시 제거 (오염 데이터 자기정화)
        import scripts.discover_actors as da
        data = {"sightings": {
            "으로서 결성 및": [{"corp_code": "c1", "rcept_no": "R1", "date": "2026-06"}],
            "홍길동": [{"corp_code": "c2", "rcept_no": "R2", "date": "2026-06"}],
        }}
        changed = da.merge_sightings(data, [], window_months=12)
        self.assertTrue(changed)
        self.assertNotIn("으로서 결성 및", data["sightings"])
        self.assertIn("홍길동", data["sightings"])

    def test_merge_keeps_other_institutions_prunes_securities_banks(self):
        # 증권·은행은 프루닝하되, 자산운용 등 기타 제도권 기관은 보존한다.
        import scripts.discover_actors as da
        data = {"sightings": {
            "가나자산운용": [{"corp_code": "c1", "rcept_no": "R1", "date": "2026-06"}],
            "가나증권": [{"corp_code": "c2", "rcept_no": "R2", "date": "2026-06"}],
            "가나은행": [{"corp_code": "c3", "rcept_no": "R3", "date": "2026-06"}],
            "홍길동": [{"corp_code": "c4", "rcept_no": "R4", "date": "2026-06"}],
        }}
        changed = da.merge_sightings(data, [], window_months=12)
        self.assertTrue(changed)
        # 기타 기관(자산운용)과 개인은 보존, 증권·은행은 제거
        self.assertIn("가나자산운용", data["sightings"])
        self.assertIn("홍길동", data["sightings"])
        self.assertNotIn("가나증권", data["sightings"])
        self.assertNotIn("가나은행", data["sightings"])

    def test_merge_canonicalizes_new_alias_records(self):
        # 신규 레코드가 별칭이면 정본 키로 합류 (같은 인물 = 여러 이름)
        import scripts.discover_actors as da
        from dart_risk_mcp.core.known_actors import normalize_name
        # 가공의 예시 — 실제 별칭은 비공개 sightings 저장소에만 둔다
        canon = normalize_name("KIM CHULSOO")
        data = {"sightings": {}, "aliases": {
            normalize_name("김철수"): canon, normalize_name("철수"): canon}}
        new = [{"name": "김철수", "corp_code": "c1", "rcept_no": "R1", "date": "2026-06"},
               {"name": "철수", "corp_code": "c2", "rcept_no": "R2", "date": "2026-06"},
               {"name": "KIM CHULSOO", "corp_code": "c3", "rcept_no": "R3", "date": "2026-06"}]
        changed = da.merge_sightings(data, new, window_months=12)
        self.assertTrue(changed)
        self.assertEqual(set(data["sightings"].keys()), {canon})
        rcepts = {e["rcept_no"] for e in data["sightings"][canon]}
        self.assertEqual(rcepts, {"R1", "R2", "R3"})

    def test_merge_rekeys_existing_alias_keys(self):
        # 별칭 맵 갱신 후 과거에 별칭 키로 쌓인 데이터를 정본으로 self-heal
        import scripts.discover_actors as da
        from dart_risk_mcp.core.known_actors import normalize_name
        canon = normalize_name("KIM CHULSOO")
        data = {"sightings": {
            normalize_name("김철수"): [
                {"corp_code": "c1", "rcept_no": "R1", "date": "2026-06"}],
            canon: [{"corp_code": "c2", "rcept_no": "R2", "date": "2026-06"}],
        }, "aliases": {normalize_name("김철수"): canon}}
        changed = da.merge_sightings(data, [], window_months=12)
        self.assertTrue(changed)
        self.assertEqual(set(data["sightings"].keys()), {canon})
        rcepts = {e["rcept_no"] for e in data["sightings"][canon]}
        self.assertEqual(rcepts, {"R1", "R2"})

    def test_merge_prunes_noise_table_artifact_keys(self):
        # 표 헤더·합계행이 이름으로 잘못 들어온 키는 병합 시 제거
        import scripts.discover_actors as da
        data = {"sightings": {
            "합계": [{"corp_code": "c1", "rcept_no": "R1", "date": "2026-06"}],
            "으로": [{"corp_code": "c2", "rcept_no": "R2", "date": "2026-06"}],
            "기타": [{"corp_code": "c3", "rcept_no": "R3", "date": "2026-06"}],
            "홍길동": [{"corp_code": "c4", "rcept_no": "R4", "date": "2026-06"}],
        }}
        changed = da.merge_sightings(data, [], window_months=12)
        self.assertTrue(changed)
        self.assertEqual(set(data["sightings"].keys()), {"홍길동"})

    def test_merge_self_heals_role_qualifier_keys(self):
        # 역할 괄호가 붙은 기존 키가 기저 실체 키로 self-heal.
        # 법인 기저(가나파트너스)는 후행·선행 괄호 변형이 한 키로 합쳐지고,
        # 증권사 기저(가나증권)는 기관으로 프루닝된다. 모두 가공 이름.
        import scripts.discover_actors as da
        data = {"sightings": {
            "가나파트너스 (본건 펀드1의 신탁업자 지위에서)": [
                {"corp_code": "c1", "rcept_no": "R1", "date": "2026-06"}],
            "(본건 펀드2의 신탁업자 지위에서) 가나파트너스": [
                {"corp_code": "c2", "rcept_no": "R2", "date": "2026-06"}],
            "가나증권 주식회사 (밸류 사모투자신탁의 신탁업자 지위에서)": [
                {"corp_code": "c3", "rcept_no": "R3", "date": "2026-06"}],
            "홍길동": [{"corp_code": "c4", "rcept_no": "R4", "date": "2026-06"}],
        }}
        changed = da.merge_sightings(data, [], window_months=12)
        self.assertTrue(changed)
        keys = set(data["sightings"].keys())
        # 증권사 기저 키는 기관으로 프루닝 (역할 괄호 안 사모투자신탁에도 불구)
        self.assertNotIn("가나증권 주식회사 (밸류 사모투자신탁의 신탁업자 지위에서)", keys)
        self.assertNotIn("가나증권 주식회사", keys)
        # 법인 기저는 두 괄호 변형이 한 키로 수렴
        self.assertIn("가나파트너스", keys)
        self.assertIn("홍길동", keys)
        rcepts = {e["rcept_no"] for e in data["sightings"]["가나파트너스"]}
        self.assertEqual(rcepts, {"R1", "R2"})

    def test_merge_self_heals_entity_and_bracket_keys(self):
        # HTML 엔티티('&CR;')·대괄호 역할 수식이 붙은 기존 키가 기저 실체 키로
        # self-heal. 'X&CR;'와 'X'가 한 키로 수렴하고, 미래에셋대우류 기저는
        # 기관으로 프루닝된다. 모두 가공 이름.
        import scripts.discover_actors as da
        data = {"sightings": {
            "가나파트너스&CR;": [
                {"corp_code": "c1", "rcept_no": "R1", "date": "2026-06"}],
            "가나파트너스": [
                {"corp_code": "c2", "rcept_no": "R2", "date": "2026-06"}],
            "가나펀드&CR;[업무집행조합원: 나다인베스트먼트 주식회사]": [
                {"corp_code": "c3", "rcept_no": "R3", "date": "2026-06"}],
            "미래에셋대우 주식회사&CR;": [
                {"corp_code": "c4", "rcept_no": "R4", "date": "2026-06"}],
            "홍길동": [{"corp_code": "c5", "rcept_no": "R5", "date": "2026-06"}],
        }}
        changed = da.merge_sightings(data, [], window_months=12)
        self.assertTrue(changed)
        keys = set(data["sightings"].keys())
        # 'X&CR;'와 'X'가 한 키로 수렴 (엔티티 제거 후 정규화)
        self.assertIn("가나파트너스", keys)
        self.assertNotIn("가나파트너스&CR;", keys)
        rcepts = {e["rcept_no"] for e in data["sightings"]["가나파트너스"]}
        self.assertEqual(rcepts, {"R1", "R2"})
        # 엔티티 + 대괄호 역할 수식 키는 기저 '가나펀드'로 self-heal
        self.assertIn("가나펀드", keys)
        self.assertNotIn(
            "가나펀드&CR;[업무집행조합원: 나다인베스트먼트 주식회사]", keys)
        # 미래에셋대우 기저 키는 기관으로 프루닝(엔티티 붙어도)
        self.assertNotIn("미래에셋대우 주식회사&CR;", keys)
        self.assertNotIn("미래에셋대우 주식회사", keys)
        self.assertIn("홍길동", keys)

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
        self.assertEqual(kd["actors"]["홍길동"][0]["companies"], ["A", "B"])

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
        # companies 태그도 문제 회사만 포함 (B 제외)
        self.assertEqual(kd["actors"]["홍길동"][0]["companies"], ["A", "C"])

    def test_promote_skips_institution_keys(self):
        # 제도권 기관은 반복 등장이 정상 — 등재하지 않는다
        import scripts.discover_actors as da
        sd = {"sightings": {"한국투자증권": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06"}]}}
        kd = {"actors": {}}
        self.assertEqual(da.promote_repeat_actors(sd, kd, n=2), [])
        self.assertEqual(kd["actors"], {})

    def test_promote_registers_fund_with_kind_and_tag(self):
        # 조합도 문제 회사 2곳+ 반복이면 등재 — 구분·태그가 법인용으로 표기
        import scripts.discover_actors as da
        sd = {"sightings": {"아레스1호투자조합": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06"}]}}
        kd = {"actors": {}}
        promoted = da.promote_repeat_actors(sd, kd, n=2)
        self.assertEqual(promoted, ["아레스1호투자조합"])
        rec = kd["actors"]["아레스1호투자조합"][0]
        self.assertEqual(rec["kind"], "조합")
        self.assertIn("동명 법인·조합 미확인", rec["tags"])
        self.assertNotIn("동명이인 미확인", rec["tags"])

    def test_promote_registers_person_with_kind(self):
        import scripts.discover_actors as da
        sd = {"sightings": {"홍길동": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06"}]}}
        kd = {"actors": {}}
        da.promote_repeat_actors(sd, kd, n=2)
        rec = kd["actors"]["홍길동"][0]
        self.assertEqual(rec["kind"], "개인")
        self.assertIn("동명이인 미확인", rec["tags"])

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
        stats = {"scanned": 312, "funding": 41, "extracted": 7,
                 "extracted_persons": 5, "extracted_entities": 2, "truncated": False}
        r = da.build_daily_report({"sightings": {"X": []}}, {"actors": {}}, True, [],
                                  stats=stats)
        self.assertIn("공시 312건 스캔", r)
        self.assertIn("자금조달 41건", r)
        self.assertIn("인수자 7건 추출", r)
        self.assertIn("개인 5 · 조합/법인 2", r)
        self.assertIn("추적 인물 1명", r)
        self.assertNotIn("페이지 상한", r)

    def test_build_daily_report_warns_on_truncation(self):
        import scripts.discover_actors as da
        stats = {"scanned": 1000, "funding": 90, "extracted": 3, "truncated": True}
        r = da.build_daily_report({"sightings": {}}, {"actors": {}}, True, [], stats=stats)
        self.assertIn("페이지 상한 도달", r)


if __name__ == "__main__":
    unittest.main()


class TestFoldDedupe(unittest.TestCase):
    def _rec(self, cc, rn):
        return {"corp_code": cc, "rcept_no": rn, "date": "2026-06"}

    def test_merge_folds_corp_suffix_variants(self):
        # (주)·㈜·주식회사 접사 변형이 최다 레코드 표기로 자동 병합
        import scripts.discover_actors as da
        data = {"sightings": {
            "(주)베이트리": [self._rec("c1", "R1"), self._rec("c2", "R2")],
            "주식회사 베이트리": [self._rec("c3", "R3")],
            "베이트리": [self._rec("c4", "R4")],
        }}
        changed = da.merge_sightings(data, [], window_months=12)
        self.assertTrue(changed)
        self.assertEqual(set(data["sightings"].keys()), {"(주)베이트리"})
        self.assertEqual(len(data["sightings"]["(주)베이트리"]), 4)
        self.assertEqual(data["aliases"]["베이트리"], "(주)베이트리")

    def test_merge_folds_latin_phonetic(self):
        # ABC바이오 ↔ 에이비씨바이오 (라틴↔한글 음차). 가공 법인명 —
        # '금융투자'는 이제 제도권 기관으로 분류·제외되므로 폴딩 예시로 부적합.
        import scripts.discover_actors as da
        data = {"sightings": {
            "ABC바이오 주식회사": [self._rec("c1", "R1"), self._rec("c2", "R2")],
            "에이비씨바이오 주식회사": [self._rec("c3", "R3")],
        }}
        da.merge_sightings(data, [], window_months=12)
        self.assertEqual(set(data["sightings"].keys()), {"ABC바이오 주식회사"})

    def test_merge_folds_spaced_person(self):
        # '정 상 용' ↔ '정상용' (개인명 공백 변형)
        import scripts.discover_actors as da
        data = {"sightings": {
            "정상용": [self._rec("c1", "R1"), self._rec("c2", "R2")],
            "정 상 용": [self._rec("c3", "R3")],
        }}
        da.merge_sightings(data, [], window_months=12)
        self.assertEqual(set(data["sightings"].keys()), {"정상용"})

    def test_merge_does_not_fold_distinct_names(self):
        import scripts.discover_actors as da
        data = {"sightings": {
            "베이트리": [self._rec("c1", "R1")],
            "베이스트리": [self._rec("c2", "R2")],
        }}
        da.merge_sightings(data, [], window_months=12)
        self.assertEqual(set(data["sightings"].keys()), {"베이트리", "베이스트리"})

    def test_fold_canon_prefers_non_alias_key(self):
        # 수동 별칭의 정본이 이미 있으면 폴딩 정본 선정에서 별칭 키를 피함(체인 방지)
        import scripts.discover_actors as da
        data = {"sightings": {
            "(주)씨알엠": [self._rec("c1", "R1")],
            "씨알엠": [self._rec("c2", "R2"), self._rec("c3", "R3")],
        }, "aliases": {"씨알엠": "CRM홀딩스"}}   # 씨알엠은 이미 다른 정본의 별칭
        da.merge_sightings(data, [], window_months=12)
        # 별칭이 아닌 '(주)씨알엠'이 정본 — 체인 없이 병합
        self.assertIn("(주)씨알엠", data["aliases"].values())
