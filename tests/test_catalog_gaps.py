"""Phase E 갭 리포트 회귀 테스트.

목적: taxonomy 45개에 매핑되지 않은 수법을 신규 신호 후보로 표면화한다.
자동으로 taxonomy.py를 고치지 않는다 — 사람 검토용 리포트까지가 범위다.
"""
import unittest

from scripts.catalog import gaps

_RECORDS = [
    {"id": "1", "date": "2026-01-05", "title": "신종 수법 A 적발", "url": "https://x.invalid/1",
     "taxonomy_ids": [], "summary": "토큰증권 발행을 가장한 자금모집", "techniques": ["가장 발행"],
     "confidence": "high", "body_source": "pdf"},
    {"id": "2", "date": "2026-02-05", "title": "신종 수법 B", "url": "https://x.invalid/2",
     "taxonomy_ids": [], "summary": "해외법인 통한 우회 지분취득", "techniques": ["우회 취득"],
     "confidence": "low", "body_source": "page"},
    {"id": "3", "date": "2026-03-05", "title": "기존 유형", "url": "https://x.invalid/3",
     "taxonomy_ids": ["1.1"], "summary": "리픽싱", "techniques": [], "confidence": "high",
     "body_source": "pdf"},
]


class TestGapReport(unittest.TestCase):
    def test_includes_only_unmapped(self):
        md = gaps.build_gap_report(_RECORDS, "2026-08-16")
        self.assertIn("신종 수법 A", md)
        self.assertIn("신종 수법 B", md)
        self.assertNotIn("기존 유형", md)

    def test_reports_counts(self):
        md = gaps.build_gap_report(_RECORDS, "2026-08-16")
        self.assertIn("전체 3건", md)
        self.assertIn("미매핑 2건", md)

    def test_marks_low_confidence_and_body_source(self):
        md = gaps.build_gap_report(_RECORDS, "2026-08-16")
        self.assertIn("confidence: low", md)
        self.assertIn("page", md)

    def test_links_source_url(self):
        md = gaps.build_gap_report(_RECORDS, "2026-08-16")
        self.assertIn("(https://x.invalid/1)", md)

    def test_states_no_auto_taxonomy_edit(self):
        md = gaps.build_gap_report(_RECORDS, "2026-08-16")
        self.assertIn("자동으로 반영하지 않습니다", md)

    def test_empty_when_all_mapped(self):
        md = gaps.build_gap_report([_RECORDS[2]], "2026-08-16")
        self.assertIn("미매핑 0건", md)
        self.assertIn("후보 없음", md)


# Fix round 1: 제목·요약·기법에 개행·파이프·대괄호가 섞여도 마크다운 구조가
# 깨지지 않아야 한다. 금감원 제목의 "[보도자료]" 접두가 실측 사례.
_EDGE_RECORDS = [
    {"id": "4", "date": "2026-04-05", "title": "[보도자료] 신종 수법 C", "url": "https://x.invalid/4",
     "taxonomy_ids": [], "summary": "다단계 자금모집", "techniques": [],
     "confidence": "high", "body_source": "pdf"},
    {"id": "5", "date": "2026-05-05", "title": "신종 수법 D\n두번째 줄", "url": "https://x.invalid/5",
     "taxonomy_ids": [], "summary": "요약 줄1\n요약 줄2", "techniques": ["기법1\n개행", "기법2|파이프"],
     "confidence": "high", "body_source": "pdf"},
    {"id": "6", "date": "2026-06-05", "title": "제목|파이프", "url": "https://x.invalid/6",
     "taxonomy_ids": [], "summary": "요약", "techniques": [], "confidence": "high", "body_source": "pdf"},
]


class TestGapReportSanitization(unittest.TestCase):
    def test_bracket_title_does_not_break_link(self):
        md = gaps.build_gap_report([_EDGE_RECORDS[0]], "2026-08-16")
        self.assertNotIn("[보도자료]", md)
        self.assertIn("[(보도자료) 신종 수법 C](https://x.invalid/4)", md)

    def test_title_newline_folds_heading_to_one_line(self):
        md = gaps.build_gap_report([_EDGE_RECORDS[1]], "2026-08-16")
        heading_lines = [l for l in md.splitlines() if l.startswith("## 2026-05-05")]
        self.assertEqual(len(heading_lines), 1)
        self.assertIn("신종 수법 D 두번째 줄", heading_lines[0])

    def test_title_pipe_handled(self):
        md = gaps.build_gap_report([_EDGE_RECORDS[2]], "2026-08-16")
        self.assertIn("제목/파이프", md)
        self.assertNotIn("제목|파이프", md)

    def test_summary_newline_folds_to_one_line(self):
        md = gaps.build_gap_report([_EDGE_RECORDS[1]], "2026-08-16")
        summary_lines = [l for l in md.splitlines() if l.startswith("- 요약:")]
        self.assertEqual(len(summary_lines), 1)
        self.assertIn("요약 줄1 요약 줄2", summary_lines[0])

    def test_techniques_newline_and_pipe_handled(self):
        md = gaps.build_gap_report([_EDGE_RECORDS[1]], "2026-08-16")
        tech_lines = [l for l in md.splitlines() if l.startswith("- 적발 기법:")]
        self.assertEqual(len(tech_lines), 1)
        self.assertIn("기법1 개행", tech_lines[0])
        self.assertIn("기법2/파이프", tech_lines[0])


if __name__ == "__main__":
    unittest.main()
