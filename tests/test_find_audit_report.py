# -*- coding: utf-8 -*-
"""감사보고서 공시 찾기 — 비상장 재무 조회의 진입점.

실측(올품 00455750, 2026-09-11): 한 회사가 같은 날 **연결/별도 두 건**을 낸다.

    20260407 | E | 삼일회계법인 | 연결감사보고서 (2025.12)   rcept 20260407001504
    20260407 | E | 삼일회계법인 | 감사보고서 (2025.12)       rcept 20260407001502
    20250408 | E | 삼일회계법인 | 연결감사보고서 (2024.12)   rcept 20250408000408

⚠ 「감사보고서」는 「연결감사보고서」의 **부분 문자열**이다. 별도를 찾을 때
낱말 포함으로 고르면 연결이 먼저 잡힌다.

사업연도는 공시 제목의 괄호(`(2025.12)`)에 있다 — 접수일(2026년)과 다르다.
접수일로 고르면 한 해가 밀린다.

제출인(`flr_nm`)은 **회계법인**이라 회사가 낸 공시와 구분된다.
법인구분(`corp_cls`)은 비상장이면 `E`다.
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp.core import dart_client as dc

ROWS = [
    {"rcept_no": "20260828000001", "rcept_dt": "20260828", "corp_cls": "E",
     "flr_nm": "올품", "report_nm": "대규모기업집단현황공시[분기별공시(개별회사용)]"},
    {"rcept_no": "20260407001504", "rcept_dt": "20260407", "corp_cls": "E",
     "flr_nm": "삼일회계법인", "report_nm": "연결감사보고서 (2025.12)"},
    {"rcept_no": "20260407001502", "rcept_dt": "20260407", "corp_cls": "E",
     "flr_nm": "삼일회계법인", "report_nm": "감사보고서 (2025.12)"},
    {"rcept_no": "20250408000408", "rcept_dt": "20250408", "corp_cls": "E",
     "flr_nm": "삼일회계법인", "report_nm": "연결감사보고서 (2024.12)"},
    {"rcept_no": "20250408000405", "rcept_dt": "20250408", "corp_cls": "E",
     "flr_nm": "삼일회계법인", "report_nm": "감사보고서 (2024.12)"},
]


def _find(**kw):
    # 2026-09-12: `find_audit_reports`가 상태를 보는 판으로 바뀌었다 —
    # 조회 실패와 「감사보고서 없음」을 가르기 위해서다.
    with patch.object(dc, "fetch_company_disclosures_with_status",
                      return_value=(list(ROWS), dc.FETCH_OK)):
        return dc.find_audit_reports("00455750", "k", **kw)


class TestFindAuditReports(unittest.TestCase):
    def test_연결을_고른다(self):
        got = _find(scope="consolidated")
        self.assertEqual(got[0]["rcept_no"], "20260407001504")

    def test_별도는_연결을_집지_않는다(self):
        """「감사보고서」가 「연결감사보고서」의 부분 문자열이라는 함정."""
        got = _find(scope="separate")
        self.assertEqual(got[0]["rcept_no"], "20260407001502")
        for r in got:
            self.assertNotIn("연결감사보고서", r["report_nm"])

    def test_사업연도로_고른다(self):
        """제목 괄호의 연도다 — 접수일(2026)이 아니다."""
        got = _find(scope="consolidated", year="2024")
        self.assertEqual(got[0]["rcept_no"], "20250408000408")

    def test_최신이_앞에_온다(self):
        got = _find(scope="consolidated")
        self.assertEqual([r["rcept_no"] for r in got],
                         ["20260407001504", "20250408000408"])

    def test_감사보고서가_아닌_공시는_빠진다(self):
        for r in _find(scope="separate"):
            self.assertIn("감사보고서", r["report_nm"])

    def test_없는_연도는_빈_목록이다(self):
        self.assertEqual(_find(scope="consolidated", year="2019"), [])

    def test_제출인과_법인구분을_보존한다(self):
        """회계법인이 냈다는 사실·비상장(E)이라는 사실을 화면이 쓴다."""
        r = _find(scope="consolidated")[0]
        self.assertEqual(r["flr_nm"], "삼일회계법인")
        self.assertEqual(r["corp_cls"], "E")

    def test_사업연도를_해석해_싣는다(self):
        r = _find(scope="consolidated")[0]
        self.assertEqual(r["fiscal_year"], "2025")

    def test_알_수_없는_scope는_연결로_본다(self):
        self.assertEqual(_find(scope="이상한값")[0]["rcept_no"], "20260407001504")

    def test_자료가_없으면_빈_목록이다(self):
        """⚠ 이 테스트는 2026-09-12까지 「조회 실패는 빈 목록이다」라는 **이름**을
        달고 있었지만 실제로 먹인 것은 **빈 응답**이었다 — 이름이 결함을
        정당화하고 있었다. 둘은 다른 사실이고 아래 테스트가 그 차이를 잡는다.
        """
        with patch.object(dc, "fetch_company_disclosures_with_status",
                          return_value=([], dc.FETCH_OK)):
            got = dc.find_audit_reports("00455750", "k")
        self.assertEqual(list(got), [])
        self.assertFalse(getattr(got, "fetch_failed", False))

    def test_조회_실패는_빈_목록과_구분된다(self):
        with patch.object(dc, "fetch_company_disclosures_with_status",
                          return_value=([], dc.FETCH_ERROR)):
            got = dc.find_audit_reports("00455750", "k")
        self.assertEqual(list(got), [])
        self.assertTrue(getattr(got, "fetch_failed", False))


if __name__ == "__main__":
    unittest.main()
