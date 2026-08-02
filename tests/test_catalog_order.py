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


if __name__ == "__main__":
    unittest.main()
