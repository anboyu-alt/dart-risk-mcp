"""주석 카테고리 분류 (core/notes.py, PR-4) 테스트."""
import unittest
from unittest.mock import patch

from dart_risk_mcp.core.notes import (
    NOTE_CATEGORIES,
    classify_note_title,
    summarize_note_sections,
    build_note_summary,
)
from dart_risk_mcp import server


class TestClassifyNoteTitle(unittest.TestCase):
    def test_going_concern(self):
        self.assertEqual(classify_note_title("계속기업 관련 중요한 불확실성"), ["going_concern"])
        self.assertIn("going_concern", classify_note_title("자본잠식 해소 계획"))

    def test_related_parties(self):
        self.assertEqual(classify_note_title("34. 특수관계자 거래"), ["related_parties"])

    def test_contingencies(self):
        self.assertIn("commitments_contingencies", classify_note_title("우발부채 및 약정사항"))

    def test_subsidiaries(self):
        self.assertEqual(classify_note_title("연결대상 종속기업의 현황"), ["subsidiaries_associates"])

    def test_multiple_categories_capped_at_two(self):
        # 계속기업 + 특수관계자 + 우발부채가 한 제목에 있어도 우선순위순 2개까지만
        hits = classify_note_title("계속기업 불확실성, 특수관계자 거래 및 우발부채")
        self.assertEqual(hits, ["going_concern", "related_parties"])

    def test_priority_order(self):
        # 낮은 우선순위(금융상품)와 높은 우선순위(계속기업) 동시 매칭 시 계속기업 먼저
        hits = classify_note_title("계속기업 및 금융상품 위험관리")
        self.assertEqual(hits[0], "going_concern")

    def test_generic_words_not_matched(self):
        # kreports 원본의 범용 키워드("수익"/"매출"/"유동성" 단독)는 제목 태깅에서 제외 — 오탐 방지
        self.assertEqual(classify_note_title("매출액 및 수익 구조"), [])
        self.assertEqual(classify_note_title("II. 사업의 내용"), [])
        self.assertEqual(classify_note_title("유동성 개선 방안"), [])

    def test_english_case_insensitive(self):
        # 키워드 비교는 소문자 정규화 경유 — 한글은 영향 없음
        self.assertEqual(classify_note_title(""), [])
        self.assertEqual(classify_note_title(None), [])

    def test_long_pseudo_title_rejected(self):
        # 라이브 발견 사례: 본문 덩어리(80자 초과)가 헤딩으로 잡히면 태깅 제외
        long_body = "당사의 부외거래는 재무에 관한 사항의 연결재무제표 주석 및 재무제표 주석의 우발부채와 약정사항을 참고하시기 바랍니다 " * 2
        self.assertGreater(len(long_body), 80)
        self.assertEqual(classify_note_title(long_body), [])


class TestSummarizeNoteSections(unittest.TestCase):
    FILES = [
        {"file_index": 0, "doc_title": "감사보고서", "filename": "a.xml", "char_length": 100,
         "sections": [
             {"id": "f0s0", "title": "독립된 감사인의 감사보고서"},
             {"id": "f0s1", "title": "계속기업 관련 중요한 불확실성"},
             {"id": "f0s2", "title": "34. 특수관계자 거래"},
             {"id": "f0s3", "title": "35. 우발부채와 약정사항"},
         ]},
        {"file_index": 1, "doc_title": "재무제표", "filename": "b.xml", "char_length": 100,
         "sections": [
             {"id": "f1s0", "title": "특수관계자"},
         ]},
    ]

    def test_summary_groups_and_order(self):
        summary = summarize_note_sections(self.FILES)
        labels = [s[0] for s in summary]
        # 우선순위: 계속기업 → 특수관계자 → 우발부채·약정
        self.assertEqual(labels, ["계속기업", "특수관계자", "우발부채·약정"])
        # 특수관계자는 두 파일에서 수집
        d = dict(summary)
        self.assertEqual(d["특수관계자"], ["f0s2", "f1s0"])

    def test_empty_input(self):
        self.assertEqual(summarize_note_sections([]), [])
        self.assertEqual(summarize_note_sections(None), [])


class TestBuildNoteSummary(unittest.TestCase):
    def test_merges_sections_and_title_hits(self):
        title_hits = [
            {"file_index": 2, "title": "32.우발부채와 약정사항",
             "categories": ["commitments_contingencies"], "position_pct": 62},
            {"file_index": 2, "title": "34. 특수관계자",
             "categories": ["related_parties"], "position_pct": 70},
        ]
        summary = build_note_summary(TestSummarizeNoteSections.FILES, title_hits)
        d = dict(summary)
        # 섹션 근거 먼저, TITLE 스캔 근거 뒤에
        self.assertEqual(d["특수관계자"][0], "f0s2")
        self.assertIn("파일2 '34. 특수관계자' (약 70% 지점)", d["특수관계자"])
        self.assertIn("파일2 '32.우발부채와 약정사항' (약 62% 지점)", d["우발부채·약정"])

    def test_title_hits_only(self):
        title_hits = [
            {"file_index": 1, "title": "계속기업 관련 중요한 불확실성",
             "categories": ["going_concern"], "position_pct": 5},
        ]
        summary = build_note_summary([], title_hits)
        self.assertEqual(summary[0][0], "계속기업")

    def test_cap_per_category(self):
        hits = [
            {"file_index": i, "title": f"특수관계자 거래 {i}",
             "categories": ["related_parties"], "position_pct": i}
            for i in range(10)
        ]
        summary = build_note_summary([], hits, max_per_category=4)
        self.assertEqual(len(dict(summary)["특수관계자"]), 4)


@patch("dart_risk_mcp.server._DART_API_KEY", "KEY")
@patch("dart_risk_mcp.server.scan_note_titles")
@patch("dart_risk_mcp.server.list_document_sections")
class TestListDisclosureSectionsTool(unittest.TestCase):
    def test_tags_and_summary_rendered(self, mock_sections, mock_scan):
        mock_sections.return_value = TestSummarizeNoteSections.FILES
        mock_scan.return_value = [
            {"file_index": 1, "title": "32.우발부채와 약정사항",
             "categories": ["commitments_contingencies"], "position_pct": 62},
        ]
        out = server.list_disclosure_sections("20240101000001")
        self.assertIn("⟨주석: 계속기업⟩", out)
        self.assertIn("⟨주석: 특수관계자⟩", out)
        self.assertIn("주석 카테고리 감지", out)
        self.assertIn("계속기업: f0s1", out)
        self.assertIn("파일1 '32.우발부채와 약정사항' (약 62% 지점)", out)

    def test_no_tags_no_summary_block(self, mock_sections, mock_scan):
        mock_sections.return_value = [
            {"file_index": 0, "doc_title": "표지", "filename": "c.xml", "char_length": 10,
             "sections": [{"id": "f0s0", "title": "대표이사의 확인"}]},
        ]
        mock_scan.return_value = []
        out = server.list_disclosure_sections("20240101000001")
        self.assertNotIn("주석 카테고리 감지", out)
        self.assertNotIn("⟨주석:", out)
        # 기존 출력 형식 유지 (회귀 확인)
        self.assertIn("[f0s0] 대표이사의 확인", out)
        self.assertIn("view_disclosure", out)

    def test_scan_failure_degrades_gracefully(self, mock_sections, mock_scan):
        mock_sections.return_value = TestSummarizeNoteSections.FILES
        mock_scan.side_effect = RuntimeError("network down")
        out = server.list_disclosure_sections("20240101000001")
        # 스캔 실패해도 섹션 기반 요약은 계속 동작
        self.assertIn("계속기업: f0s1", out)


if __name__ == "__main__":
    unittest.main()
