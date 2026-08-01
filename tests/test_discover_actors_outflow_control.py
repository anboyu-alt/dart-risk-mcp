"""자금유출 상대방·신규 최대주주 수집원(v1.8.0) 단위 테스트.

합성 이름만 사용한다 — 실명 fixture는 금지(노출 경계 정책). 실제 사례
(아틀라스링크→로아앤코홀딩스·미래산업)는 보고서 텍스트에서만 언급하고
테스트 데이터로는 쓰지 않는다.
"""
import unittest
from contextlib import ExitStack
from unittest.mock import patch


class TestClassifyTrackedEntity(unittest.TestCase):
    def test_person_fund_corp_pass(self):
        import scripts.discover_actors as da
        self.assertEqual(da.classify_tracked_entity("홍길동"), "person")
        self.assertEqual(da.classify_tracked_entity("가나1호투자조합"), "fund")
        self.assertEqual(da.classify_tracked_entity("(주)가나홀딩스"), "corp")

    def test_institution_excluded(self):
        import scripts.discover_actors as da
        self.assertIsNone(da.classify_tracked_entity("가나은행"))
        self.assertIsNone(da.classify_tracked_entity("가나증권"))
        self.assertIsNone(da.classify_tracked_entity("가나캐피탈"))
        self.assertIsNone(da.classify_tracked_entity("가나저축은행"))
        self.assertIsNone(da.classify_tracked_entity("가나자산운용"))

    def test_trust_extension_excluded(self):
        # '신탁'은 classify_actor의 institution 패턴에 없어 별도 확장 필요
        # ('투자신탁'만 institution, 단독 '신탁'은 corp로 분류됨을 확인 후 추가).
        import scripts.discover_actors as da
        from dart_risk_mcp.core.known_actors import classify_actor
        self.assertEqual(classify_actor("가나부동산신탁"), "corp")
        self.assertIsNone(da.classify_tracked_entity("가나부동산신탁"))

    def test_noise_and_empty_excluded(self):
        import scripts.discover_actors as da
        self.assertIsNone(da.classify_tracked_entity(""))
        self.assertIsNone(da.classify_tracked_entity("합계"))


class TestCollectOutflowSightings(unittest.TestCase):
    def _disc(self, rn, nm, corp, cc, dt="20260710", corp_cls="K"):
        return {"rcept_no": rn, "report_nm": nm, "corp_name": corp,
                "corp_code": cc, "rcept_dt": dt, "corp_cls": corp_cls}

    def test_excludes_subsidiary_keeps_affiliated_and_external(self):
        import scripts.discover_actors as da
        discs_i = [
            self._disc("R1", "타인에대한채무보증결정", "가나전자", "c1"),
            self._disc("R2", "타인에대한담보제공결정", "가나전자", "c2"),
            self._disc("R3", "금전대여결정", "가나전자", "c3"),
        ]
        details = {
            "R1": {"counterparty": "가나홀딩스", "relation": "종속회사", "kind": "guarantee"},
            "R2": {"counterparty": "가나파트너스", "relation": "계열회사", "kind": "collateral"},
            "R3": {"counterparty": "다나인베스트", "relation": "타인", "kind": "loan"},
        }
        with ExitStack() as st:
            st.enter_context(patch.object(
                da, "fetch_market_disclosures",
                side_effect=lambda k, b, e, pblntf_ty="", max_pages=10:
                    discs_i if pblntf_ty == "I" else []))
            st.enter_context(patch.object(
                da, "fetch_outflow_detail",
                side_effect=lambda rn, key: details.get(rn, {})))
            sightings, stats = da.collect_outflow_sightings_range("key", "20260701", "20260731")
        names = {s["name"] for s in sightings}
        self.assertNotIn("가나홀딩스", names)   # 종속회사 — 제외
        self.assertIn("가나파트너스", names)     # 계열회사(affiliated) — 포함
        self.assertIn("다나인베스트", names)     # 타인(external) — 포함
        self.assertEqual(stats["outflow"], 3)
        self.assertEqual(stats["extracted"], 2)

    def test_excludes_institution_and_self_name_counterparty(self):
        import scripts.discover_actors as da
        discs_i = [
            self._disc("R1", "금전대여결정", "가나전자", "c1"),
            self._disc("R2", "금전대여결정", "가나전자", "c2"),
        ]
        details = {
            "R1": {"counterparty": "가나은행", "relation": "타인", "kind": "loan"},
            "R2": {"counterparty": "가나전자", "relation": "타인", "kind": "loan"},  # 자기 자신
        }
        with ExitStack() as st:
            st.enter_context(patch.object(
                da, "fetch_market_disclosures",
                side_effect=lambda k, b, e, pblntf_ty="", max_pages=10:
                    discs_i if pblntf_ty == "I" else []))
            st.enter_context(patch.object(
                da, "fetch_outflow_detail",
                side_effect=lambda rn, key: details.get(rn, {})))
            sightings, _ = da.collect_outflow_sightings_range("key", "20260701", "20260731")
        self.assertEqual(sightings, [])

    def test_tangible_acq_uses_major_decision_endpoint(self):
        # 유형자산양수결정은 pblntf_ty='B'에서만 확인됐다 — DS005 경로로 조회.
        import scripts.discover_actors as da
        discs_b = [self._disc("R9", "주요사항보고서(유형자산양수결정)", "가나전자", "c9")]
        with ExitStack() as st:
            st.enter_context(patch.object(
                da, "fetch_market_disclosures",
                side_effect=lambda k, b, e, pblntf_ty="", max_pages=10:
                    discs_b if pblntf_ty == "B" else []))
            st.enter_context(patch.object(da, "resolve_decision_type", return_value="tangible_acq"))
            fmd = st.enter_context(patch.object(
                da, "fetch_major_decision",
                return_value={"counterparty": "다나에셋", "relation_text": "특수관계인",
                             "related_party": True}))
            sightings, stats = da.collect_outflow_sightings_range("key", "20260701", "20260731")
        fmd.assert_called_once_with("R9", "key", "tangible_acq", "c9")
        self.assertEqual([s["name"] for s in sightings], ["다나에셋"])
        self.assertEqual(stats["outflow"], 1)

    def test_deduplicates_when_disclosure_appears_in_both_types(self):
        # 채무보증·담보제공은 I·B 양쪽에 병행 공시되는 사례가 있어 rcept_no로 dedup.
        import scripts.discover_actors as da
        disc = self._disc("R1", "타인에대한채무보증결정", "가나전자", "c1")
        with ExitStack() as st:
            st.enter_context(patch.object(
                da, "fetch_market_disclosures", return_value=[disc]))
            st.enter_context(patch.object(
                da, "fetch_outflow_detail",
                return_value={"counterparty": "다나인베스트", "relation": "타인", "kind": "guarantee"}))
            sightings, stats = da.collect_outflow_sightings_range("key", "20260701", "20260731")
        self.assertEqual(stats["outflow"], 1)   # I·B 둘 다 R1을 반환해도 1건만 카운트
        self.assertEqual(len(sightings), 1)

    def test_sighting_records_have_outflow_src_and_kind(self):
        import scripts.discover_actors as da
        discs_i = [self._disc("R1", "금전대여결정", "가나전자", "c1")]
        with ExitStack() as st:
            st.enter_context(patch.object(
                da, "fetch_market_disclosures",
                side_effect=lambda k, b, e, pblntf_ty="", max_pages=10:
                    discs_i if pblntf_ty == "I" else []))
            st.enter_context(patch.object(
                da, "fetch_outflow_detail",
                return_value={"counterparty": "다나홀딩스", "relation": "타인", "kind": "loan"}))
            sightings, _ = da.collect_outflow_sightings_range("key", "20260701", "20260731")
        self.assertEqual(len(sightings), 1)
        rec = sightings[0]
        self.assertEqual(rec["src"], "outflow")
        self.assertEqual(rec["kind"], "corp")   # '다나홀딩스' — 법인성 접미어(홀딩스)로 corp 분류
        self.assertEqual(rec["corp_code"], "c1")
        self.assertEqual(rec["signals"], ["FUND_OUTFLOW"])


class TestCollectControlChangeSightings(unittest.TestCase):
    def _disc(self, rn, nm, corp, cc, dt="20260710", corp_cls="K"):
        return {"rcept_no": rn, "report_nm": nm, "corp_name": corp,
                "corp_code": cc, "rcept_dt": dt, "corp_cls": corp_cls}

    def test_strips_holder_suffix_and_collects_new_holder(self):
        import scripts.discover_actors as da
        discs = [self._disc("R1", "최대주주변경", "가나전자", "c1")]
        with ExitStack() as st:
            st.enter_context(patch.object(da, "fetch_market_disclosures", return_value=discs))
            st.enter_context(patch.object(
                da, "fetch_control_change_detail",
                return_value={"new_holder": "홍길동 외 3인", "new_ratio": 12.3}))
            sightings, stats = da.collect_control_change_sightings_range(
                "key", "20260701", "20260731")
        self.assertEqual([s["name"] for s in sightings], ["홍길동"])
        self.assertEqual(sightings[0]["src"], "control")
        self.assertEqual(sightings[0]["signals"], ["SHAREHOLDER"])
        self.assertEqual(stats["control"], 1)

    def test_excludes_amendment_and_precursor_contract_titles(self):
        import scripts.discover_actors as da
        discs = [
            self._disc("R1", "[기재정정]최대주주변경", "가나전자", "c1"),
            self._disc("R2", "최대주주 변경을 수반하는 주식양수도계약체결", "가나전자", "c2"),
        ]
        with ExitStack() as st:
            st.enter_context(patch.object(da, "fetch_market_disclosures", return_value=discs))
            fcd = st.enter_context(patch.object(da, "fetch_control_change_detail"))
            sightings, stats = da.collect_control_change_sightings_range(
                "key", "20260701", "20260731")
        fcd.assert_not_called()   # 제목 단계에서 이미 걸러져 원문 조회 자체가 없어야 함
        self.assertEqual(sightings, [])
        self.assertEqual(stats["control"], 0)

    def test_excludes_undisclosed_and_institutional_new_holder(self):
        import scripts.discover_actors as da
        discs = [
            self._disc("R1", "최대주주변경", "가나전자", "c1"),
            self._disc("R2", "최대주주변경", "가나전자", "c2"),
        ]
        details = {
            "R1": {"new_holder": "-"},
            "R2": {"new_holder": "가나자산운용"},
        }
        with ExitStack() as st:
            st.enter_context(patch.object(da, "fetch_market_disclosures", return_value=discs))
            st.enter_context(patch.object(
                da, "fetch_control_change_detail",
                side_effect=lambda rn, key: details.get(rn, {})))
            sightings, _ = da.collect_control_change_sightings_range(
                "key", "20260701", "20260731")
        self.assertEqual(sightings, [])

    def test_excludes_self_name_new_holder(self):
        import scripts.discover_actors as da
        discs = [self._disc("R1", "최대주주변경", "가나전자", "c1")]
        with ExitStack() as st:
            st.enter_context(patch.object(da, "fetch_market_disclosures", return_value=discs))
            st.enter_context(patch.object(
                da, "fetch_control_change_detail", return_value={"new_holder": "가나전자"}))
            sightings, _ = da.collect_control_change_sightings_range(
                "key", "20260701", "20260731")
        self.assertEqual(sightings, [])


class TestSrcFieldBackwardCompatibility(unittest.TestCase):
    def test_merge_accepts_records_without_src_field(self):
        # 기존 funding 레코드에는 "src" 필드가 없다 — merge_sightings가
        # 이를 깨지 않고 그대로 병합해야 한다(하위 호환).
        import scripts.discover_actors as da
        data = {"sightings": {}}
        new = [{"name": "홍길동", "corp_code": "c1", "rcept_no": "R1", "date": "2026-06",
               "kind": "person"}]   # src 없음 — 기존 funding 레코드 형태
        changed = da.merge_sightings(data, new, window_months=12)
        self.assertTrue(changed)
        self.assertNotIn("src", data["sightings"]["홍길동"][0])

    def test_merge_preserves_src_field_across_sources(self):
        import scripts.discover_actors as da
        data = {"sightings": {"홍길동": [
            {"corp_code": "c1", "rcept_no": "R1", "date": "2026-06", "kind": "person"}]}}
        new = [{"name": "홍길동", "corp_code": "c2", "rcept_no": "R2", "date": "2026-06",
               "kind": "person", "src": "outflow"},
               {"name": "홍길동", "corp_code": "c3", "rcept_no": "R3", "date": "2026-06",
               "kind": "person", "src": "control"}]
        da.merge_sightings(data, new, window_months=12)
        srcs = {e.get("rcept_no"): e.get("src") for e in data["sightings"]["홍길동"]}
        self.assertEqual(srcs, {"R1": None, "R2": "outflow", "R3": "control"})


class TestPromoteMixedSourceEvidence(unittest.TestCase):
    def test_evidence_labels_default_funding_when_no_src(self):
        import scripts.discover_actors as da
        sd = {"sightings": {"홍길동": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06"}]}}
        kd = {"actors": {}}
        da.promote_repeat_actors(sd, kd, n=2)
        ev = kd["actors"]["홍길동"][0]["evidence"]
        self.assertIn("인수자", ev)

    def test_evidence_labels_mixed_outflow_and_control(self):
        import scripts.discover_actors as da
        sd = {"sightings": {"홍길동": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06",
             "src": "outflow"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06",
             "src": "control"}]}}
        kd = {"actors": {}}
        da.promote_repeat_actors(sd, kd, n=2)
        ev = kd["actors"]["홍길동"][0]["evidence"]
        self.assertIn("유출 상대방", ev)
        self.assertIn("신규 최대주주", ev)
        # 순서 고정 확인 — 유출 상대방이 신규 최대주주보다 먼저
        self.assertLess(ev.index("유출 상대방"), ev.index("신규 최대주주"))
        self.assertIn("2곳", ev)
        self.assertIn("A", ev)
        self.assertIn("B", ev)

    def test_evidence_labels_all_three_sources_in_fixed_order(self):
        import scripts.discover_actors as da
        sd = {"sightings": {"홍길동": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06",
             "src": "outflow"},
            {"corp_code": "c3", "corp": "C", "rcept_no": "R3", "date": "2026-06",
             "src": "control"}]}}
        kd = {"actors": {}}
        da.promote_repeat_actors(sd, kd, n=3)
        ev = kd["actors"]["홍길동"][0]["evidence"]
        self.assertLess(ev.index("인수자"), ev.index("유출 상대방"))
        self.assertLess(ev.index("유출 상대방"), ev.index("신규 최대주주"))


if __name__ == "__main__":
    unittest.main()
