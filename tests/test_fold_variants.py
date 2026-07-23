# -*- coding: utf-8 -*-
"""표기 변형 폴딩 보강 검증 — 실데이터(sightings) 감사에서 확인된 병합 누락 사례.

2026-07 감사에서 fold_name이 놓친 실사례:
- 쉼표 변형: 'LIM CHARLES CHANGWAN' vs 'LIM, CHARLES CHANGWAN'
- 영문 법인 접사: 'CBI USA, INC.' vs 'CBI USA'
- 한글(로마자) 병기: '정소영(DING SHAO YING)' vs 'DING SHAO YING'
- 구명칭 병기: '팩토링플러스투자조합(구. 센시오2호투자조합)' vs '센시오2호투자조합'
"""
import unittest

from dart_risk_mcp.core.known_actors import fold_name, fold_variants


class TestFoldNameCommaAndEnSuffix(unittest.TestCase):
    """쉼표·영문 법인 접사(CO/LTD/INC/CORP/LLC 등) 폴딩."""

    def test_trailing_comma(self):
        self.assertEqual(fold_name("NEW ARK INVESTMENT CO., LTD."),
                         fold_name("NEW ARK INVESTMENT CO., LTD.,"))

    def test_en_legal_suffix(self):
        self.assertEqual(fold_name("CBI USA, INC."), fold_name("CBI USA"))

    def test_person_name_comma(self):
        self.assertEqual(fold_name("LIM CHARLES CHANGWAN"),
                         fold_name("LIM, CHARLES CHANGWAN"))
        self.assertEqual(fold_name("LIM ALEXANDRA"), fold_name("LIM, ALEXANDRA"))

    def test_corp_suffix_order_variants(self):
        self.assertEqual(fold_name("CHOISANGHO, CORP"), fold_name("CHOISANGHO CORP."))

    def test_llc_punct_variants(self):
        self.assertEqual(fold_name("FYSIKUS.LLC"), fold_name("FYSIKUS,LLC"))

    def test_no_overmerge_korean_company_word(self):
        # '컴퍼니케이파트너스'는 실존 VC(Company K Partners) — '케이파트너스'와 별개 실체.
        # 한글 '컴퍼니'는 접사로 취급하지 않는다.
        self.assertNotEqual(fold_name("컴퍼니케이파트너스주식회사"),
                            fold_name("케이파트너스(주)"))
        self.assertNotEqual(fold_name("주식회사 서영컴퍼니"), fold_name("주식회사 서영"))

    def test_en_suffix_only_at_tail(self):
        # 'CO'가 이름 중간에 있으면 제거하지 않는다.
        self.assertNotEqual(fold_name("CO SMITH FUND"), fold_name("SMITH FUND"))


class TestFoldVariants(unittest.TestCase):
    """한글(로마자) 병기·구명칭 병기 → 대체 폴드 산출."""

    def test_bilingual_paren(self):
        v = fold_variants("정소영(DING SHAO YING)")
        self.assertIn(fold_name("DING SHAO YING"), v)
        self.assertIn(fold_name("정소영"), v)

    def test_former_name_paren(self):
        v = fold_variants("팩토링플러스투자조합(구. 센시오2호투자조합)")
        self.assertIn(fold_name("센시오2호투자조합"), v)
        self.assertIn(fold_name("팩토링플러스투자조합"), v)

    def test_former_name_bracket(self):
        v = fold_variants("(주)폴라리스에이아이[舊 (주)리노스]")
        self.assertIn(fold_name("(주)리노스"), v)
        self.assertIn(fold_name("(주)폴라리스에이아이"), v)

    def test_plain_name_single_variant(self):
        self.assertEqual(fold_variants("홍길동"), [fold_name("홍길동")])

    def test_short_component_excluded(self):
        # 1글자 폴드는 오병합 위험 → 변형에서 제외
        v = fold_variants("김(K)")
        self.assertEqual(v, [fold_name("김(K)")])


class TestDiscoverMergeBilingual(unittest.TestCase):
    """merge_sightings가 병기 표기를 실제 병합하는지 통합 검증."""

    @staticmethod
    def _rec(cc, corp):
        return {"corp_code": cc, "corp": corp, "rcept_no": "r" + cc,
                "date": "2099-01", "event": "in"}

    def test_bilingual_keys_merged(self):
        import scripts.discover_actors as da
        data = {"sightings": {
            "정소영(DING SHAO YING)": [self._rec("c1", "회사1"), self._rec("c2", "회사2")],
            "DING SHAO YING": [self._rec("c3", "회사3")],
        }, "aliases": {}}
        da.merge_sightings(data, [], window_months=12000)
        keys = set(data["sightings"].keys())
        self.assertEqual(len(keys), 1)
        canon = next(iter(keys))
        self.assertEqual(len(data["sightings"][canon]), 3)
        self.assertEqual(set(data["aliases"].values()), {canon})


class TestRegistryFoldLookup(unittest.TestCase):
    """레지스트리 조회 경로의 표기 변형 폴백 — 노션 등재 표기와 조회 표기가 달라도 매칭."""

    _REGISTRY = {"actors": {
        "주식회사 액션": [{"status": "verified", "source": "DART",
                          "companies": ["(주)베이트리"]}],
        "정소영(DING SHAO YING)": [{"status": "auto_matched", "source": "DART",
                                    "companies": []}],
    }}

    def _patched(self):
        from unittest.mock import patch
        return patch("dart_risk_mcp.core.known_actors.load_known_actors",
                     return_value=self._REGISTRY)

    def test_lookup_actor_corp_suffix_variant(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        with self._patched():
            self.assertTrue(lookup_actor("(주)액션"))
            self.assertTrue(lookup_actor("액션 주식회사"))
            self.assertFalse(lookup_actor("(주)액션홀딩스"))   # 다른 실체는 미스

    def test_lookup_actor_bilingual_variant(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        with self._patched():
            self.assertTrue(lookup_actor("DING SHAO YING"))
            self.assertTrue(lookup_actor("정소영"))

    def test_lookup_by_company_suffix_variant(self):
        from dart_risk_mcp.core.known_actors import lookup_actors_by_company
        with self._patched():
            hits = lookup_actors_by_company("주식회사 베이트리")
            self.assertEqual([h[0] for h in hits], ["주식회사 액션"])
            self.assertFalse(lookup_actors_by_company("주식회사 베이"))


class TestRenameSelfHeal(unittest.TestCase):
    """법인명 변경(같은 corp_code, 다른 사명) 자기치유 — 행위자·회사 병합."""

    @staticmethod
    def _rec(cc, corp, rc="r1", date="2099-01"):
        return {"corp_code": cc, "corp": corp, "rcept_no": rc,
                "date": date, "event": "in"}

    def test_merge_sightings_rename_aliases_actor_keys(self):
        """corp_code c5가 '(주)암니스'→'(주)폴루스바이오팜'으로 개명 관측되고,
        두 사명이 각각 행위자 키로도 존재하면 한 키로 병합된다."""
        import scripts.discover_actors as da
        data = {"sightings": {
            # 행위자 두 표기 — 개명 전/후 사명으로 각각 타사에 투자
            "(주)암니스": [self._rec("c1", "회사1", "a1")],
            "(주)폴루스바이오팜": [self._rec("c2", "회사2", "a2"),
                                   self._rec("c3", "회사3", "a3")],
            # 제3의 행위자 기록에서 c5의 개명 이력(옛/새 사명)이 관측됨
            "홍길동": [self._rec("c5", "(주)암니스", "b1", "2098-01"),
                       self._rec("c5", "(주)폴루스바이오팜", "b2", "2099-01")],
        }, "aliases": {}}
        da.merge_sightings(data, [], window_months=12000)
        keys = set(data["sightings"].keys())
        self.assertIn("홍길동", keys)
        merged = keys - {"홍길동"}
        self.assertEqual(merged, {"(주)폴루스바이오팜"})   # 레코드 최다 표기가 정본
        self.assertEqual(len(data["sightings"]["(주)폴루스바이오팜"]), 3)
        self.assertEqual(data["aliases"].get("(주)암니스"), "(주)폴루스바이오팜")

    def test_build_graph_rename_folds_actor_into_company(self):
        """회사 cc=100의 과거 사명으로 활동한 행위자가 c:100 노드로 접힌다."""
        from scripts.build_network_html import build_graph
        sightings = {"sightings": {
            # cc=100은 회사로서 옛/새 사명 모두 관측됨 (개명 이력)
            "투자자甲": [self._rec("100", "암니스", "x1", "2098-01"),
                         self._rec("100", "폴루스바이오팜", "x2", "2099-01"),
                         self._rec("200", "다른회사", "x3")],
            # 옛 사명 '주식회사 암니스' 명의로 2개사에 투자한 행위자
            "주식회사 암니스": [self._rec("300", "회사3", "y1"),
                               self._rec("400", "회사4", "y2")],
        }}
        g = build_graph(sightings, min_companies=2)
        ids = {n["id"] for n in g["nodes"]}
        self.assertNotIn("a:주식회사 암니스", ids)   # 별도 행위자 노드 아님
        self.assertIn("c:100", ids)                  # 회사 노드로 병합


class TestReconcileCorpRenames(unittest.TestCase):
    """corpCode 명부 기반 행위자 개명 추적 — 같은 corp_code가 다른 키로
    재해석되면(=사명 변경) 같은 실체로 병합."""

    @staticmethod
    def _rec(cc, corp, rc):
        return {"corp_code": cc, "corp": corp, "rcept_no": rc,
                "date": "2099-01", "event": "in"}

    def test_rename_detected_via_corp_id(self):
        import scripts.discover_actors as da
        from dart_risk_mcp.core.known_actors import fold_name
        data = {"sightings": {
            "(주)암니스": [self._rec("c1", "회사1", "a1"),
                           self._rec("c2", "회사2", "a2")],
            "(주)폴루스바이오팜": [self._rec("c3", "회사3", "a3")],
        }, "aliases": {},
            # 이전 실행에서 '(주)암니스'가 corp_code cc9로 해석돼 있었음
            "actor_corp_ids": {"cc9": "(주)암니스"}}
        # 현재 corpCode 명부: cc9의 현재 사명은 폴루스바이오팜 (개명 완료)
        corp_index = {fold_name("(주)폴루스바이오팜"): {"cc9"}}
        self.assertTrue(da.reconcile_corp_renames(data, corp_index))
        s = data["sightings"]
        self.assertNotIn("(주)암니스", s)                       # 옛 키 병합됨
        self.assertEqual(len(s["(주)폴루스바이오팜"]), 3)       # 새 사명이 정본
        self.assertEqual(data["aliases"].get("(주)암니스"), "(주)폴루스바이오팜")
        self.assertEqual(data["actor_corp_ids"]["cc9"], "(주)폴루스바이오팜")

    def test_ambiguous_fold_skipped(self):
        import scripts.discover_actors as da
        from dart_risk_mcp.core.known_actors import fold_name
        data = {"sightings": {"(주)액션": [self._rec("c1", "회사1", "a1")]},
                "aliases": {}, "actor_corp_ids": {}}
        # 동명 회사 2곳 → 모호 → 매핑·병합 없음
        corp_index = {fold_name("(주)액션"): {"cc1", "cc2"}}
        da.reconcile_corp_renames(data, corp_index)
        self.assertEqual(data["actor_corp_ids"], {})

    def test_person_key_not_resolved(self):
        import scripts.discover_actors as da
        from dart_risk_mcp.core.known_actors import fold_name
        data = {"sightings": {"홍길동": [self._rec("c1", "회사1", "a1")]},
                "aliases": {}, "actor_corp_ids": {}}
        corp_index = {fold_name("홍길동"): {"cc1"}}   # 우연히 동명 회사 존재해도
        da.reconcile_corp_renames(data, corp_index)
        self.assertEqual(data["actor_corp_ids"], {})   # 개인 키는 해석 안 함


class TestBackfillRenames(unittest.TestCase):
    """상호변경안내 원문 추출 + legacy_index 소급 병합."""

    # 엑스큐어(20260722900410) 라이브 원문 구조 기반
    _SAMPLE = ("상호변경안내 1. 변경내용 가. 변경전 국문 엑스큐어 주식회사 "
               "영문 Xcure Corp. 나. 변경후 국문 주식회사 퀀텀레일 영문 "
               "QuantumRail Inc. 2. 변경사유 기업 성장 전략 강화 "
               "4. 과거 상호변경 내역 2020.03.03 상호변경공시(변경전: "
               "한솔시큐어 주식회사 → 변경후: 엑스큐어 주식회사")

    def test_extract_before_after_and_history(self):
        from scripts.backfill_renames import extract_renames_from_text
        olds, after = extract_renames_from_text(self._SAMPLE)
        self.assertEqual(after, "주식회사 퀀텀레일")
        self.assertIn("엑스큐어 주식회사", olds)
        self.assertIn("한솔시큐어 주식회사", olds)   # 과거 내역까지 소급
        self.assertNotIn("주식회사 퀀텀레일", olds)  # 새 사명은 제외

    def test_reconcile_legacy_merges_old_name_key(self):
        import scripts.discover_actors as da
        from dart_risk_mcp.core.known_actors import fold_name
        rec = TestReconcileCorpRenames._rec
        data = {"sightings": {
            # 옛 사명 키가 레코드 최다여도 정본은 현재 명부 쪽
            "엑스큐어 주식회사": [rec("c1", "회사1", "a1"),
                                  rec("c2", "회사2", "a2")],
            "주식회사 퀀텀레일": [rec("c3", "회사3", "a3")],
        }, "aliases": {}, "actor_corp_ids": {},
            "corp_renames": {"cc7": {"names": ["엑스큐어 주식회사",
                                               "한솔시큐어 주식회사"],
                                     "events": []}}}
        corp_index = {fold_name("주식회사 퀀텀레일"): {"cc7"}}   # 현재 명부
        legacy = da._legacy_name_index(data)
        self.assertTrue(da.reconcile_corp_renames(data, corp_index, legacy))
        s = data["sightings"]
        self.assertEqual(set(s.keys()), {"주식회사 퀀텀레일"})
        self.assertEqual(len(s["주식회사 퀀텀레일"]), 3)
        self.assertEqual(data["aliases"].get("엑스큐어 주식회사"),
                         "주식회사 퀀텀레일")
        self.assertEqual(data["actor_corp_ids"]["cc7"], "주식회사 퀀텀레일")


if __name__ == "__main__":
    unittest.main()
