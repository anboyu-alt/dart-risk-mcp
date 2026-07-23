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


if __name__ == "__main__":
    unittest.main()
