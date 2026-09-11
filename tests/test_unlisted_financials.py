# -*- coding: utf-8 -*-
"""get_unlisted_financials — 비상장 외부감사대상 법인의 재무·주석.

취재 대상이 비상장 계열사인 경우가 많은데 OpenDART 재무제표 API는 정기보고서
제출 법인 위주라 「조회된 데이타가 없습니다」를 돌려준다. 감사보고서 원문은
공시되므로 그쪽으로 우회한다.

## 왜 `fetch_disclosure_full`을 안 쓰나

그 함수는 `max_chars = min(max_chars, 20000)`으로 **하드 캡**이 걸려 있다
(화면 표시용이라 옳다). 하지만 구간을 자르려면 원문 전체가 있어야 한다 —
실측 올품 연결 2025는 마크다운 **103,968자**다. 20,000자만 받으면 주석이
통째로 밖에 있다. `fetch_audit_report_text`는 같은 내부(`_fetch_document_zip`
→ `_decode_zip_file` → `_html_to_structured_text`)를 쓰되 자르지 않는다.

## 동명 법인은 되묻는다

실측 '올품'은 corp_code가 둘이고 앞의 것(00442385)은 공시가 **0건**이다.
임의로 하나를 고르면 사용자가 빈손을 받고 이유를 모른다.
"""
import pathlib
import unittest
from unittest.mock import patch

from dart_risk_mcp import server
from dart_risk_mcp.core import dart_client as dc

_FX = pathlib.Path(__file__).resolve().parent / "fixtures" / "audit_reports"
_DOC = (_FX / "olpum_consolidated_2025.md").read_text(encoding="utf-8")

_AUDIT = [{
    "rcept_no": "20260407001504", "rcept_dt": "20260407",
    "report_nm": "연결감사보고서 (2025.12)", "flr_nm": "삼일회계법인",
    "corp_cls": "E", "fiscal_year": "2025",
}]
_ONE = [{"corp_code": "00455750", "stock_code": "", "modify_date": "20240110"}]
_TWO = _ONE + [{"corp_code": "00442385", "stock_code": "", "modify_date": "20170630"}]


def _run(section="fs", year="", scope="consolidated",
         candidates=None, audits=None, text=_DOC, name="올품"):
    with patch.object(server, "_api_key", return_value="k"), \
         patch.object(server, "find_corp_candidates",
                      return_value=list(_ONE if candidates is None else candidates)), \
         patch.object(server, "find_audit_reports",
                      return_value=list(_AUDIT if audits is None else audits)), \
         patch.object(server, "fetch_audit_report_text", return_value=text):
        return server.get_unlisted_financials(name, year, scope, section)


class TestFetchAuditReportTextIsUncapped(unittest.TestCase):
    def test_2만자_상한이_없다(self):
        """`fetch_disclosure_full`과 달리 자르지 않는다 — **동작으로** 잰다."""
        import io
        import zipfile

        body = ("<p>가나다라마바사</p>" * 6000)   # 변환 후 2만 자를 훌쩍 넘는다
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("doc.xml", body.encode("utf-8"))
        zf = zipfile.ZipFile(io.BytesIO(buf.getvalue()))

        with patch.object(dc, "_fetch_document_zip", return_value=zf):
            got = dc.fetch_audit_report_text("20260407001504", "k")
        self.assertGreater(len(got), 20000, "2만 자에서 잘렸다")

    def test_zip을_못_받으면_빈_문자열이다(self):
        with patch.object(dc, "_fetch_document_zip", return_value=None):
            self.assertEqual(dc.fetch_audit_report_text("2026", "k"), "")


class TestAmbiguousCorpAsksBack(unittest.TestCase):
    def test_후보가_둘이면_조회하지_않고_되묻는다(self):
        out = _run(candidates=_TWO)
        self.assertIn("00455750", out)
        self.assertIn("00442385", out)
        self.assertIn("20240110", out, "어느 쪽이 최신인지 알 수 있어야 한다")

    def test_되물을_때_원문을_열지_않는다(self):
        with patch.object(server, "_api_key", return_value="k"), \
             patch.object(server, "find_corp_candidates", return_value=list(_TWO)), \
             patch.object(server, "find_audit_reports") as fa, \
             patch.object(server, "fetch_audit_report_text") as ft:
            server.get_unlisted_financials("올품")
        fa.assert_not_called()
        ft.assert_not_called()

    def test_못_찾으면_그렇게_말한다(self):
        out = _run(candidates=[])
        self.assertIn("찾", out)


class TestListedGoesElsewhere(unittest.TestCase):
    def test_상장사면_기존_도구로_보낸다(self):
        listed = [{"corp_code": "00126380", "stock_code": "005930", "modify_date": ""}]
        out = _run(candidates=listed)
        self.assertIn("get_financial_summary", out)

    def test_원문_계정명이_필요한_사람에게_갈_곳을_알려준다(self):
        """상장사를 되돌려 보내는 이유는 「구조화 값이 있어서」인데, 그 값의
        **계정명은 XBRL 표준 태그**라 회사가 쓴 표기와 다를 수 있다(실측 8개사
        2,144행 중 15.7%). 원문 표기를 찾아 이 도구에 온 사람을 아무 말 없이
        되돌려 보내면 그 사람의 용건은 해결되지 않는다.
        """
        listed = [{"corp_code": "00126380", "stock_code": "005930", "modify_date": ""}]
        out = _run(candidates=listed)
        self.assertIn("get_financial_statements_full", out)


class TestSections(unittest.TestCase):
    def test_fs는_재무제표_숫자를_낸다(self):
        out = _run(section="fs")
        self.assertIn("534,796,185,759", out)
        self.assertIn("1,384,173,296,748", out)

    def test_fs는_주석_참조열을_보존한다(self):
        """숫자에서 주석으로 건너뛰는 통로다."""
        self.assertIn("| 매출액 | 28 | 534,796,185,759", _run(section="fs"))

    def test_notes는_목차를_먼저_낸다(self):
        out = _run(section="notes")
        self.assertIn("39", out, "주석 개수")
        self.assertIn("일반사항", out)
        self.assertIn("영업부문", out)

    def test_notes_목차에_카테고리를_태깅한다(self):
        """core/notes.py를 재사용한다 — 같은 일을 새로 만들지 않는다."""
        out = _run(section="notes")
        self.assertIn("특수관계자", out)

    def test_all은_둘_다_낸다(self):
        out = _run(section="all")
        self.assertIn("534,796,185,759", out)
        self.assertIn("일반사항", out)

    def test_모르는_section은_안내한다(self):
        out = _run(section="엉뚱")
        self.assertIn("fs", out)


class TestTruncationIsHonest(unittest.TestCase):
    def test_잘리면_어디서_잘렸는지_적는다(self):
        out = _run(section="all")
        if "…" in out or "잘렸" in out or "생략" in out:
            self.assertRegex(out, r"\d[\d,]*자")

    def test_이어받는_법을_적는다(self):
        out = _run(section="all")
        self.assertIn("20260407001504", out)
        self.assertTrue("view_disclosure" in out or "search_notes_in_report" in out)


class TestFactsAreKept(unittest.TestCase):
    def test_제출인과_법인구분을_적는다(self):
        out = _run()
        self.assertIn("삼일회계법인", out)
        self.assertIn("비상장", out)

    def test_감사보고서가_없으면_그렇게_말한다(self):
        out = _run(audits=[])
        self.assertIn("감사보고서", out)
        self.assertNotIn("534,796,185,759", out)

    def test_점수나_등급을_붙이지_않는다(self):
        out = _run(section="all")
        for banned in ("매우위험", "고위험", "위험도", "점수", "등급"):
            self.assertNotIn(banned, out)


if __name__ == "__main__":
    unittest.main()
