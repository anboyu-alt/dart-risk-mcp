# -*- coding: utf-8 -*-
"""주석 본문 검색 — 제목만 보던 것에서 본문까지.

`scan_note_titles`는 제목만 스캔한다. 본문을 꺼내오는 경로가 없었다.
`get_unlisted_financials`가 원문을 받아 오게 되면서, 그 원문 안에서 낱말로
주석을 찾는 것이 가능해졌다.

⚠ **한 건의 보고서 안에서만 도는 검색이다.** 전 상장사 주석을 가로질러 찾으려면
사전 색인 DB가 있어야 한다 — 이 도구로는 안 된다.

## 붙여 쓰기와 띄어 쓰기

한국 공시는 같은 말을 붙여도 쓰고 띄어도 쓴다(「영업권손상차손」 ↔
「영업권 손상차손」). `terms` 원소 안의 세로줄(`|`)이 OR이라
`["영업권손상차손|영업권 손상차손"]` 한 항목으로 두 표기를 함께 잡는다.

⚠ 세로줄은 **정규식이 아니라 낱말 구분자**다 — 사용자가 넣은 문자열을 그대로
찾는다. 정규식으로 해석하면 괄호·별표가 든 회계 용어에서 터진다.
"""
import pathlib
import unittest

from dart_risk_mcp.core.audit_report import search_notes

_FX = pathlib.Path(__file__).resolve().parent / "fixtures" / "audit_reports"
_DOC = (_FX / "olpum_consolidated_2025.md").read_text(encoding="utf-8")


class TestSearchScope(unittest.TestCase):
    def test_주석_구간만_훑는다(self):
        r = search_notes(_DOC, ["매출액"])
        self.assertEqual(r["scope"], "주석")
        self.assertEqual(r["scanned_notes"], 39)

    def test_주석이_없으면_문서_전체를_훑고_그렇게_말한다(self):
        txt = "| 과 목 | 금액 |\n|---|---|\n| 매출 | 10 |\n"
        r = search_notes(txt, ["매출"])
        self.assertEqual(r["scope"], "문서 전체")
        self.assertEqual(r["scanned_notes"], 0)
        self.assertTrue(r["notes"])


class TestModes(unittest.TestCase):
    def test_all은_모든_낱말이_함께_있는_주석만(self):
        r = search_notes(_DOC, ["김준영", "종속기업"], mode="all")
        for n in r["notes"]:
            span = _DOC[n["offset"]:n["end"]]
            self.assertIn("김준영", span)
            self.assertIn("종속기업", span)

    def test_any는_하나라도_있으면(self):
        a = search_notes(_DOC, ["김준영", "종속기업"], mode="all")
        o = search_notes(_DOC, ["김준영", "종속기업"], mode="any")
        self.assertGreater(len(o["notes"]), len(a["notes"]))

    def test_없는_낱말은_빈_결과다(self):
        r = search_notes(_DOC, ["없는낱말자리표"])
        self.assertEqual(r["notes"], [])

    def test_모르는_mode는_all로_본다(self):
        a = search_notes(_DOC, ["김준영", "종속기업"], mode="all")
        x = search_notes(_DOC, ["김준영", "종속기업"], mode="엉뚱")
        self.assertEqual(len(x["notes"]), len(a["notes"]))


class TestOrSyntax(unittest.TestCase):
    def test_세로줄이_OR이다(self):
        """붙여 쓴 표기와 띄어 쓴 표기를 한 항목으로 묶는다."""
        one = search_notes(_DOC, ["관계기업투자"])
        both = search_notes(_DOC, ["관계기업투자|관계기업 투자"])
        self.assertGreaterEqual(len(both["notes"]), len(one["notes"]))

    def test_어느_표기가_걸렸는지_밝힌다(self):
        r = search_notes(_DOC, ["관계기업투자|없는표기"])
        hit = r["notes"][0]["hits"][0]
        self.assertEqual(hit["term"], "관계기업투자")

    def test_세로줄을_정규식으로_해석하지_않는다(self):
        """괄호·별표가 든 회계 용어가 터지면 안 된다."""
        txt = "1. 가\n내용 (주1) 손상(*)\n2. 나\n다른 내용\n"
        r = search_notes(txt, ["(주1)", "손상(*)"], mode="all")
        self.assertEqual(len(r["notes"]), 1)
        self.assertEqual(r["notes"][0]["no"], 1)

    def test_빈_조각은_무시한다(self):
        r = search_notes(_DOC, ["관계기업투자||"])
        self.assertTrue(r["notes"])

    def test_빈_terms는_빈_결과다(self):
        self.assertEqual(search_notes(_DOC, [])["notes"], [])
        self.assertEqual(search_notes(_DOC, ["", "  "])["notes"], [])


class TestContext(unittest.TestCase):
    def test_앞뒤_문맥을_함께_낸다(self):
        r = search_notes(_DOC, ["김준영"], context_chars=200)
        ex = r["notes"][0]["hits"][0]["excerpt"]
        self.assertIn("김준영", ex)
        self.assertGreater(len(ex), 100)

    def test_문맥_길이를_지킨다(self):
        r = search_notes(_DOC, ["김준영"], context_chars=100)
        ex = r["notes"][0]["hits"][0]["excerpt"]
        self.assertLessEqual(len(ex), 100 * 2 + 40)

    def test_어느_주석_아래인지_함께_준다(self):
        r = search_notes(_DOC, ["김준영"])
        n = r["notes"][0]
        self.assertIn("no", n)
        self.assertIn("title", n)
        self.assertIsInstance(n["no"], int)

    def test_한_주석의_여러_번_등장을_모은다(self):
        r = search_notes(_DOC, ["연결회사"], mode="any")
        self.assertTrue(any(len(n["hits"]) > 1 for n in r["notes"]))

    def test_총_적중_수를_센다(self):
        r = search_notes(_DOC, ["연결회사"], mode="any")
        self.assertEqual(r["total_hits"], sum(len(n["hits"]) for n in r["notes"]))


if __name__ == "__main__":
    unittest.main()
