"""load_catalog_excerpt 섹션 순서 결정성 회귀 테스트.

버그: 호출부(server.py의 analyze_company_risk 등)가 taxonomy ID 목록을
`list({...})` set 순회로 만들어 넘기기 때문에, 카탈로그 발췌 섹션 순서가
PYTHONHASHSEED에 따라 실행마다 달라졌다 (2026-08-03 PR #146 골드 재생성 중 실측
— PYTHONHASHSEED=0 고정으로 우회했던 것을 근본 수정). load_catalog_excerpt가
입력 순서와 무관하게 taxonomy ID 숫자 순으로 정렬해 어떤 해시 시드에서든
동일한 출력을 내는지 검증한다.
"""
import re
import unittest

from dart_risk_mcp.core.catalog import load_catalog_excerpt
from dart_risk_mcp.core.taxonomy import TAXONOMY

_HEADER_RE = re.compile(r"━━ 카탈로그 선례: (.+?) ━━")

# 8개 카테고리 전부를 걸치는 taxonomy ID 표본 (repro: server.py:844 구성 방식)
_SAMPLE_IDS = ["3.1", "1.1", "3.2", "1.6", "4.4", "7.1", "5.7", "1.5", "4.3", "2.1", "8.4"]


class TestCatalogExcerptOrder(unittest.TestCase):
    def test_output_independent_of_input_order(self):
        # set 순회 순서가 어떻게 나오든(= 입력 순서가 무엇이든) 출력은 동일해야 한다.
        baseline = load_catalog_excerpt(_SAMPLE_IDS)
        self.assertTrue(baseline, "테스트 전제 깨짐: 발췌가 비어있음")
        self.assertEqual(load_catalog_excerpt(list(reversed(_SAMPLE_IDS))), baseline)
        # 다른 섞임도 하나 더 — 해시 시드 1에서 실측된 순서
        shuffled = ["3.1", "7.1", "1.6", "8.4", "4.3", "1.1", "1.5", "5.7", "2.1", "4.4", "3.2"]
        self.assertEqual(load_catalog_excerpt(shuffled), baseline)

    def test_sections_in_ascending_category_order(self):
        # 정렬 기준이 명시적인지 확인: taxonomy ID 숫자 오름차순 → 카테고리 1~8 순.
        excerpt = load_catalog_excerpt(["7.1", "1.1", "3.1"])
        headers = _HEADER_RE.findall(excerpt)
        self.assertEqual(
            headers,
            [
                "Convertible Bond & Debt Manipulation",
                "Ownership & Control",
                "Market Manipulation & Trading",
            ],
        )

    def test_unknown_keys_still_silently_skipped(self):
        # 기존 계약 유지: 패턴 키 등 알 수 없는 키는 정렬 단계에서도 죽지 않고 스킵.
        self.assertEqual(load_catalog_excerpt(["zombie_ma", "fake_new_biz"]), "")
        with_junk = load_catalog_excerpt(["zombie_ma", "7.1", "1.1"])
        self.assertEqual(with_junk, load_catalog_excerpt(["1.1", "7.1"]))


class TestCatalogExcerptBlockIsolation(unittest.TestCase):
    """load_catalog_excerpt가 카테고리 파일 전체를 앞에서부터 자르는 게 아니라,
    요청받은 taxonomy id의 블록만 뽑는지 검증한다.

    회귀 배경: 예전 구현은 카테고리 MD 파일 전체를 읽어 `content[:max_chars]`로
    잘랐다 — 카테고리 파일 앞쪽 유형만 우연히 발췌에 들어가고 뒤쪽 유형은
    자기 내용이 한 글자도 안 나왔다(45종 중 21종 영향, 2026-08-16 실측).
    """

    def test_every_taxonomy_id_sees_its_own_block(self):
        # 핵심 회귀 가드: TAXONOMY 45종 전부가 자기 헤더를 자기 발췌에서 봐야 한다.
        missing = [
            tid for tid in TAXONOMY
            if f"## {tid}:" not in load_catalog_excerpt([tid])
        ]
        self.assertEqual(missing, [], f"자기 블록을 못 보는 taxonomy id: {missing}")

    def test_same_category_two_ids_both_included_in_order(self):
        # 3.1, 3.6은 같은 카테고리(Ownership & Control) — 섹션은 1개이되
        # 두 블록 모두 포함되고 3.1이 3.6보다 먼저 나와야 한다.
        excerpt = load_catalog_excerpt(["3.1", "3.6"])
        headers = _HEADER_RE.findall(excerpt)
        self.assertEqual(headers, ["Ownership & Control"])
        self.assertIn("## 3.1:", excerpt)
        self.assertIn("## 3.6:", excerpt)
        self.assertLess(excerpt.index("## 3.1:"), excerpt.index("## 3.6:"))

    def test_different_categories_two_sections_ascending(self):
        # 7.2(Market Manipulation)와 1.1(CB & Debt)을 섞어 넘겨도 섹션은 2개이고
        # 1.x 섹션이 입력 순서와 무관하게 먼저 온다.
        excerpt = load_catalog_excerpt(["7.2", "1.1"])
        headers = _HEADER_RE.findall(excerpt)
        self.assertEqual(
            headers,
            ["Convertible Bond & Debt Manipulation", "Market Manipulation & Trading"],
        )
        self.assertLess(excerpt.index("## 1.1:"), excerpt.index("## 7.2:"))

    def test_no_internal_score_metadata_leaks(self):
        excerpt = load_catalog_excerpt(["3.1", "3.6", "7.2", "1.1"])
        self.assertNotIn("Severity", excerpt)
        self.assertNotIn("Base Score", excerpt)
        self.assertNotIn("Crisis Timeline", excerpt)

    def test_pattern_key_yields_empty_string(self):
        self.assertEqual(load_catalog_excerpt(["zombie_ma"]), "")


if __name__ == "__main__":
    unittest.main()
