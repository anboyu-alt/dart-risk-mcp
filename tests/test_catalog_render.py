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
        # 2026-08-25: 「탐지 키워드」는 `match_signals`가 **쓰지 않는** 목록이라
        # 제목이 거짓이었다(1년 실측: taxonomy 키워드 217개 중 166개가 신호
        # 제목에 0건). 실제로 켜는 신호를 위에 두고, 개념어는 그렇게 이름 붙였다.
        for section in ("### 정의", "### 이 유형을 켜는 신호",
                        "### 개념어 (참고 — 도구가 검색하는 말이 아닙니다)",
                        "### 위험 신호",
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


class TestAggregateLaws(unittest.TestCase):
    def test_counts_and_sorts_desc(self):
        cases = [{"laws": ["자본시장법", "금융감독규정"]}, {"laws": ["자본시장법"]}]
        self.assertEqual(render.aggregate_laws(cases), [("자본시장법", 2), ("금융감독규정", 1)])

    def test_respects_top_n(self):
        cases = [{"laws": [f"L{i}" for i in range(20)]}]
        self.assertEqual(len(render.aggregate_laws(cases, top_n=5)), 5)


class TestFixRound1Sections(unittest.TestCase):
    """fix round 1: 실제 카탈로그 MD에 있던 '인용 법조'·'기존 현장 기사 인용' 섹션 보존."""

    def _render(self, labels=None, cases_by_tid=None):
        labels = labels if labels is not None else {
            "1.1": {"title": "전환가액 하향조정(리픽싱)",
                    "definition": "DART 공시 없이 전환가액을 조정하는 행위입니다.",
                    "red_flags": ["한 번에 10% 이상의 큰 폭 하향 조정"],
                    "field_articles": ["위메이드 800억원 CB조기상환", "리픽싱모니터"]}
        }
        cases_by_tid = cases_by_tid if cases_by_tid is not None else {"1.1": [_CASE]}
        return render.render_category(
            "Convertible Bond & Debt Manipulation", ["1.1"], cases_by_tid,
            labels, TAXONOMY, "2026-08-16",
        )

    def test_section_order(self):
        md = self._render()
        order = ["### 정의", "### 이 유형을 켜는 신호",
                 "### 개념어 (참고 — 도구가 검색하는 말이 아닙니다)", "### 위험 신호",
                  "### 금감원·금융위 적발 사례", "### 적발 기법 종합",
                  "### 인용 법조", "### 기존 현장 기사 인용"]
        positions = [md.index(sec) for sec in order]
        self.assertEqual(positions, sorted(positions))

    def test_laws_aggregated_with_counts(self):
        md = self._render()
        self.assertIn("### 인용 법조\n\n- 자본시장법 (1건)", md)

    def test_field_articles_rendered_as_bullets(self):
        md = self._render()
        self.assertIn("### 기존 현장 기사 인용\n\n- 위메이드 800억원 CB조기상환\n- 리픽싱모니터", md)

    def test_field_articles_empty_renders_em_dash(self):
        labels = {"1.1": {"title": "전환가액 하향조정(리픽싱)", "definition": "정의", "red_flags": ["신호"]}}
        md = self._render(labels=labels)
        self.assertIn("### 기존 현장 기사 인용\n\n—", md)

    def test_laws_empty_renders_em_dash(self):
        labels = {"1.1": {"title": "전환가액 하향조정(리픽싱)", "definition": "정의", "red_flags": ["신호"]}}
        md = self._render(labels=labels, cases_by_tid={})
        self.assertIn("### 인용 법조\n\n—", md)


class TestBuildMdEndToEnd(unittest.TestCase):
    """생성된 MD로 load_catalog_excerpt가 실제 발췌를 내는지 종단 검증.

    catalog.py docstring이 경고하는 '죽은 배선'(조용히 빈 문자열) 회귀 방지.
    """

    def test_writes_eight_files_and_excerpt_is_non_empty(self):
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock

        from scripts.catalog import build_md

        fixture = Path(__file__).parent / "fixtures" / "catalog" / "classified_sample.jsonl"
        records = [json.loads(line) for line in fixture.read_text(encoding="utf-8").splitlines() if line.strip()]

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            written = build_md.write_catalog(records, out, "2026-08-16")
            self.assertEqual(len(written), 8)
            names = sorted(p.name for p in written)
            self.assertEqual(names, sorted(render.CATEGORY_FILES.values()))

            # 생성된 MD를 카탈로그 디렉터리로 바꿔치기해 발췌가 비지 않는지 확인
            from dart_risk_mcp.core import catalog as core_catalog

            with mock.patch.object(core_catalog, "_CATALOG_DIR", out):
                excerpt = core_catalog.load_catalog_excerpt(["1.1", "8.1"])
            self.assertTrue(excerpt.strip(), "발췌가 비어있음 — 죽은 배선 회귀")
            self.assertIn("카탈로그 선례", excerpt)
            self.assertNotIn("**Severity**", excerpt)  # 런타임 제거 확인

    def test_unmapped_records_excluded_from_catalog(self):
        from scripts.catalog import build_md
        from dart_risk_mcp.core.taxonomy import TAXONOMY

        records = [{"taxonomy_ids": [], "title": "미매핑", "techniques": []}]
        grouped = build_md.group_cases(records, TAXONOMY)
        self.assertEqual(sum(len(v) for v in grouped.values()), 0)


class TestWriteReadmeDataSource(unittest.TestCase):
    """README의 데이터 소스 문구가 실제 수집 방식과 일치해야 한다.

    설계가 게시판 웹 파싱 + FSS 단일 소스로 바뀌었는데도(오픈API는 일일 30회
    한도로 폐기, 정책브리핑은 범위 밖) README 생성 코드가 옛 문구를 그대로
    박고 있었다(Finding 3, 2026-08-17 전체 브랜치 리뷰).
    """

    def test_readme_states_actual_collection_method(self):
        import tempfile
        from pathlib import Path

        from scripts.catalog import build_md

        with tempfile.TemporaryDirectory() as tmp:
            path = build_md.write_readme([], Path(tmp), "2026-08-16")
            text = path.read_text(encoding="utf-8")

        self.assertIn("게시판", text)
        self.assertNotIn("오픈API", text)
        self.assertNotIn("정책브리핑", text)


class TestClassifyAgencyField(unittest.TestCase):
    """classify.py의 agency 분기가 죽은 코드가 아닌지 확인(Finding 4).

    collect.py는 항상 source="fss"만 내므로 "금융위원회" 분기는 도달 불가능한
    죽은 코드였다. 실제로 도달 가능한 값 하나로 정리했는지, README의 데이터
    소스 정정과 일관되게 "금융감독원" 단일 값을 쓰는지 확인한다.
    """

    def test_classify_source_reads_agency_field_literally(self):
        import inspect

        from scripts.catalog import classify

        src = inspect.getsource(classify.main)
        self.assertIn('"agency": "금융감독원"', src)
        self.assertNotIn("금융위원회", src)


class TestWriteReadmeScreenedOutSeparation(unittest.TestCase):
    """README 통계에서 1차 스크리닝 탈락분이 '미매핑'에 섞이면 안 된다.

    회귀 배경(2026-08-17 재리뷰): Finding 2를 고치며 classify.py가 탈락 레코드도
    catalog_classified.jsonl에 쓰게 됐다(screened_out=True, taxonomy_ids 없음).
    gaps.py/group_cases는 이를 올바르게 걸러냈지만 write_readme만 놓쳐서,
    탈락분이 전부 "미매핑(신규 유형 후보)"으로 집계돼 실제로는 정밀 분류조차
    안 거친 건이 신종 수법인 것처럼 부풀려 보였다.
    """

    _RECORDS = [
        {"date": "2026-01-01", "taxonomy_ids": ["1.1"], "body_source": "pdf"},
        {"date": "2026-02-01", "taxonomy_ids": [], "body_source": "page"},
        {"date": "2026-03-01", "screened_out": True, "title": "탈락1"},
        {"date": "2026-04-01", "screened_out": True, "title": "탈락2"},
        {"date": "2026-05-01", "screened_out": True, "title": "탈락3"},
    ]

    def _write(self):
        import tempfile
        from pathlib import Path

        from scripts.catalog import build_md

        with tempfile.TemporaryDirectory() as tmp:
            path = build_md.write_readme(self._RECORDS, Path(tmp), "2026-08-17")
            return path.read_text(encoding="utf-8")

    def test_unmapped_count_excludes_screened_out(self):
        text = self._write()
        # 1건(매핑) + 1건(진짜 미매핑) + 3건(스크리닝 탈락) = 5건 총계지만,
        # "미매핑"은 스크리닝 탈락 3건을 포함하지 않고 정확히 1건이어야 한다.
        self.assertIn("미매핑(신규 유형 후보) 1건", text)

    def test_three_categories_reported_with_exact_counts(self):
        text = self._write()
        self.assertIn("총 레코드**: 5건", text)
        self.assertIn("1차 스크리닝 제외: 3건", text)
        self.assertIn("정밀 분류 대상: 2건", text)
        self.assertIn("유형 매핑 1건", text)

    def test_body_source_excludes_screened_out_records(self):
        # 탈락 레코드는 body_source가 아예 없다(상세 페이지를 열지 않음).
        # 정밀 분류 대상(2건: pdf 1 + page 1)만 집계해야 한다 — 탈락분의
        # "unknown"이 섞여 분포가 왜곡되면 안 된다.
        text = self._write()
        self.assertIn("본문 확보 경로**(정밀 분류 대상 2건 기준): page 1건, pdf 1건", text)
        self.assertNotIn("unknown", text)

    def test_all_screened_out_yields_zero_unmapped_not_all(self):
        # 전부 탈락인 극단 케이스에서 "미매핑"이 5건으로 부풀지 않고 0건이어야 한다.
        import tempfile
        from pathlib import Path

        from scripts.catalog import build_md

        records = [{"date": "2026-01-01", "screened_out": True, "title": f"탈락{i}"} for i in range(5)]
        with tempfile.TemporaryDirectory() as tmp:
            path = build_md.write_readme(records, Path(tmp), "2026-08-17")
            text = path.read_text(encoding="utf-8")
        self.assertIn("미매핑(신규 유형 후보) 0건", text)
        self.assertIn("1차 스크리닝 제외: 5건", text)


if __name__ == "__main__":
    unittest.main()
