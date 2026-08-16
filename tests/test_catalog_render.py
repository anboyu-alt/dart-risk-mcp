"""카탈로그 MD 렌더러 회귀 테스트.

핵심 계약 2가지:
1. 파일명 매핑이 core/catalog.py의 _CATEGORY_TO_FILE과 정확히 일치해야 한다.
   불일치하면 load_catalog_excerpt가 예외 없이 빈 문자열을 반환한다(죽은 배선).
2. Severity/Base Score/Crisis Timeline 3줄의 표기가 정확해야 한다.
   core/catalog.py의 _TAXONOMY_META_LINE 정규식이 이 형식에 의존한다.
"""
import re
import unittest

from dart_risk_mcp.core.catalog import _CATEGORY_TO_FILE, _TAXONOMY_META_LINE
from dart_risk_mcp.core.taxonomy import TAXONOMY
from scripts.catalog import render

_CASE = {
    "date": "2024-01-23",
    "agency": "금융감독원",
    "title": "「전환사채 시장 건전성 제고 간담회」 개최",
    "url": "https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId=133310&menuNo=200218",
    "techniques": ["전환가액 조정 기준 명확화 부재", "콜옵션 행사자 지정 공시 의무화"],
    "sanctions": [],
    "laws": ["자본시장법"],
    "summary": "제도 개선안을 발표했습니다.",
    "taxonomy_ids": ["1.1"],
    "confidence": "high",
    "body_source": "pdf",
}


class TestCategoryMapping(unittest.TestCase):
    def test_file_mapping_matches_core_catalog(self):
        self.assertEqual(render.CATEGORY_FILES, _CATEGORY_TO_FILE)

    def test_every_taxonomy_category_has_korean_title(self):
        cats = {v["category"] for v in TAXONOMY.values()}
        missing = [c for c in cats if c not in render.CATEGORY_KO]
        self.assertEqual(missing, [])


class TestRenderCategory(unittest.TestCase):
    def _render(self):
        labels = {"1.1": {"title": "전환가액 하향조정(리픽싱)",
                          "definition": "DART 공시 없이 전환가액을 조정하는 행위입니다.",
                          "red_flags": ["한 번에 10% 이상의 큰 폭 하향 조정"]}}
        return render.render_category(
            "Convertible Bond & Debt Manipulation", ["1.1"], {"1.1": [_CASE]},
            labels, TAXONOMY, "2026-08-16",
        )

    def test_uses_korean_title_not_taxonomy_name(self):
        md = self._render()
        self.assertIn("## 1.1: 전환가액 하향조정(리픽싱)", md)
        self.assertNotIn("Refixing (리픽싱)", md)

    def test_metadata_lines_match_strip_regex(self):
        # core/catalog.py가 이 3줄을 제거할 수 있어야 한다.
        md = self._render()
        self.assertIn("- **Severity**: HIGH", md)
        self.assertIn("- **Base Score**: 3", md)
        self.assertIn("- **Crisis Timeline**: 12개월", md)
        stripped = _TAXONOMY_META_LINE.sub("", md)
        self.assertNotIn("**Severity**", stripped)
        self.assertNotIn("**Base Score**", stripped)
        self.assertNotIn("**Crisis Timeline**", stripped)

    def test_header_and_sections_present(self):
        md = self._render()
        self.assertTrue(md.startswith("# 전환사채·부채 조작"))
        self.assertIn("> 카테고리: Convertible Bond & Debt Manipulation", md)
        self.assertIn("> 생성일: 2026-08-16", md)
        self.assertIn("> 포함 유형: 1.1", md)
        for section in ("### 정의", "### 탐지 키워드", "### 위험 신호",
                        "### 금감원·금융위 적발 사례", "### 적발 기법 종합"):
            self.assertIn(section, md)

    def test_case_rendered_with_link_and_fields(self):
        md = self._render()
        self.assertIn("[「전환사채 시장 건전성 제고 간담회」 개최](https://www.fss.or.kr", md)
        self.assertIn("적발 기법: 전환가액 조정 기준 명확화 부재", md)
        self.assertIn("제재: —", md)  # 빈 리스트는 em dash
        self.assertIn("인용 법조: 자본시장법", md)

    def test_type_without_cases_omits_case_section_body(self):
        labels = {"1.2": {"title": "콜옵션 남용", "definition": "정의", "red_flags": ["신호"]}}
        md = render.render_category(
            "Convertible Bond & Debt Manipulation", ["1.2"], {}, labels, TAXONOMY, "2026-08-16")
        self.assertIn("## 1.2: 콜옵션 남용", md)
        self.assertIn("적발 사례 없음", md)


class TestRenderCase(unittest.TestCase):
    def test_pipe_and_newline_sanitized(self):
        case = dict(_CASE, title="제목|파이프\n줄바꿈")
        out = render.render_case(case)
        self.assertNotIn("\n줄바꿈", out.split("\n")[0])
        self.assertNotIn("|파이프", out)


class TestAggregate(unittest.TestCase):
    def test_counts_and_sorts_desc(self):
        cases = [{"techniques": ["A", "B"]}, {"techniques": ["A"]}]
        self.assertEqual(render.aggregate_techniques(cases), [("A", 2), ("B", 1)])

    def test_respects_top_n(self):
        cases = [{"techniques": [f"T{i}" for i in range(20)]}]
        self.assertEqual(len(render.aggregate_techniques(cases, top_n=5)), 5)


if __name__ == "__main__":
    unittest.main()
