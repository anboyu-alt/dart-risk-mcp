# -*- coding: utf-8 -*-
"""search_notes_in_report — 한 보고서 안의 주석 본문 검색 도구.

⚠ 이 도구의 가장 큰 오해 위험은 **범위**다. 사용자가 「전 상장사에서 이런
주석을 찾아줘」로 읽으면 안 된다 — 사전 색인 DB가 없으므로 불가능하다.
독스트링과 출력 모두에 한 줄로 적는다.
"""
import pathlib
import unittest
from unittest.mock import patch

from dart_risk_mcp import server

_FX = pathlib.Path(__file__).resolve().parent / "fixtures" / "audit_reports"
_DOC = (_FX / "olpum_consolidated_2025.md").read_text(encoding="utf-8")


def _run(terms, mode="all", context_chars=600, text=_DOC, rcept="20260407001504"):
    with patch.object(server, "_api_key", return_value="k"), \
         patch.object(server, "fetch_audit_report_text", return_value=text):
        return server.search_notes_in_report(rcept, terms, mode, context_chars)


class TestScopeIsOneReport(unittest.TestCase):
    def test_독스트링이_한_건_검색임을_밝힌다(self):
        doc = server.search_notes_in_report.__doc__ or ""
        self.assertIn("한 건", doc)

    def test_출력이_한_건_검색임을_밝힌다(self):
        out = _run(["김준영"])
        self.assertTrue("한 건" in out or "이 보고서" in out)


class TestFindsAndLocates(unittest.TestCase):
    def test_주석_번호와_제목을_함께_낸다(self):
        out = _run(["김준영"])
        self.assertIn("37", out)
        self.assertIn("특수관계자", out)

    def test_문맥을_낸다(self):
        self.assertIn("김준영", _run(["김준영"], context_chars=200))

    def test_모든_낱말_모드(self):
        out = _run(["김준영", "종속기업"], mode="all")
        self.assertIn("모두", out)

    def test_하나라도_모드(self):
        out = _run(["김준영", "종속기업"], mode="any")
        self.assertIn("하나라도", out)

    def test_세로줄_OR을_안내한다(self):
        out = _run(["관계기업투자|관계기업 투자"])
        self.assertIn("관계기업", out)

    def test_못_찾으면_찾지_못했다고_한다(self):
        out = _run(["없는낱말자리표"])
        self.assertIn("찾지 못", out)
        self.assertIn("39", out, "몇 개 주석을 훑었는지 말해야 한다")


class TestInputGuards(unittest.TestCase):
    def test_접수번호가_없으면_안내한다(self):
        out = _run(["가"], rcept="")
        self.assertIn("접수번호", out)

    def test_terms가_비면_안내한다(self):
        out = _run([])
        self.assertIn("낱말", out)

    def test_원문을_못_받으면_실패라고_말한다(self):
        out = _run(["가"], text="")
        self.assertIn("조회", out)
        self.assertNotIn("찾지 못했습니다", out.split("\n")[0])


class TestOutputIsBounded(unittest.TestCase):
    def test_적중이_많아도_상한을_밝힌다(self):
        out = _run(["연결회사"], mode="any")
        if "생략" in out:
            self.assertRegex(out, r"\d+건")

    def test_점수나_등급을_붙이지_않는다(self):
        out = _run(["김준영"])
        for banned in ("매우위험", "고위험", "위험도", "점수", "등급"):
            self.assertNotIn(banned, out)


if __name__ == "__main__":
    unittest.main()
