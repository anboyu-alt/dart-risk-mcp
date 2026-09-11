# -*- coding: utf-8 -*-
"""주석 표 뼈대 — 어느 주석을 열지 고르는 데만 쓴다.

`get_unlisted_financials(section="notes")`는 주석 목차를 내는데, 제목만으로는
어느 주석에 무엇이 들었는지 알 수 없어 본문을 여러 번 왕복하게 된다. 올품
연결감사보고서는 주석이 10~99페이지, 마크다운 103,968자다.

목차 각 항목에 **표 제목·열 이름·행 수·단위 표기**를 덧붙인다. **금액은 넣지
않는다** — 이미 받아 둔 원문을 다시 파싱하는 순수 함수라 추가 API 호출 0.

## ⚠ 2열 블록은 표가 아니다

실측(올품 주석 1·13·19)에서 마크다운 표로 잡히는 것 중 상당수가 데이터 표가
아니다.

    | | (단위: 천원) |            ← 단위 표기 줄
    | - 당기 | (단위: 천원) |      ← 소제목 + 단위
    | (*1) | 공동무한책임사원으로 … |  ← 각주

데이터 표는 **열 3개 이상**이다. 주석 19는 「표」가 14개 잡히지만 실제 데이터
표는 6개뿐이다.

## 단위는 바로 앞 2열 블록에 있다

`(단위: 천원)`이 표 위 별도 블록으로 온다. 주석마다 단위가 달라서 이것만으로도
오독을 막는다 — 그래서 **딸려 보낸다**.
"""
import pathlib
import unittest

from dart_risk_mcp.core.notes import outline_note_tables

_FX = pathlib.Path(__file__).resolve().parent / "fixtures" / "audit_reports"
_OLPUM = (_FX / "olpum_consolidated_2025.md").read_text(encoding="utf-8")


def _by_no(outline, no):
    return next((o for o in outline if o["note_no"] == no), None)


class TestVerificationCase(unittest.TestCase):
    def test_종속기업_현황_표가_열_이름과_함께_잡힌다(self):
        n1 = _by_no(outline_note_tables(_OLPUM), 1)
        self.assertIsNotNone(n1)
        cols = [c for t in n1["tables"] for c in t["columns"]]
        for want in ("종속기업명", "업종", "자본", "투자주식수",
                     "지분율", "소재지", "결산월"):
            self.assertIn(want, cols, f"열 {want}이 없다")

    def test_특수관계자_거래_주석의_표도_잡힌다(self):
        n37 = _by_no(outline_note_tables(_OLPUM), 37)
        self.assertIsNotNone(n37)
        self.assertIn("특수관계자", n37["title"])
        self.assertTrue(n37["tables"], "표가 하나도 안 잡혔다")


class TestTwoColumnBlocksAreNotTables(unittest.TestCase):
    def test_단위_표기_줄을_표로_세지_않는다(self):
        n13 = _by_no(outline_note_tables(_OLPUM), 13)
        for t in n13["tables"]:
            self.assertNotIn("(단위: 천원)", t["columns"])

    def test_각주_줄을_표로_세지_않는다(self):
        n19 = _by_no(outline_note_tables(_OLPUM), 19)
        for t in n19["tables"]:
            self.assertFalse(any(c.startswith("(*") for c in t["columns"]),
                             f"각주가 표로 잡혔다: {t['columns']}")

    def test_열이_셋_이상인_것만_남는다(self):
        for o in outline_note_tables(_OLPUM):
            for t in o["tables"]:
                self.assertGreaterEqual(len(t["columns"]), 3)


class TestUnitTravelsWithTable(unittest.TestCase):
    def test_단위_표기를_딸려_보낸다(self):
        n13 = _by_no(outline_note_tables(_OLPUM), 13)
        self.assertTrue(any("천원" in (t["unit_as_reported"] or "")
                            for t in n13["tables"]))

    def test_단위가_없으면_빈_값이다(self):
        txt = "1. 가\n| 구분 | 당기 | 전기 |\n|---|---|---|\n| 매출 | 1 | 2 |\n2. 나\n내용\n"
        o = outline_note_tables(txt)
        self.assertEqual(o[0]["tables"][0]["unit_as_reported"], "")


class TestShapeAndLimits(unittest.TestCase):
    def test_행_수를_센다(self):
        n13 = _by_no(outline_note_tables(_OLPUM), 13)
        self.assertTrue(any(t["rows_n"] > 0 for t in n13["tables"]))

    def test_행_이름은_넣지_않는다(self):
        """목차가 길어지면 목차의 의미가 없다."""
        for o in outline_note_tables(_OLPUM):
            for t in o["tables"]:
                self.assertNotIn("rows", t)
                self.assertNotIn("row_labels", t)

    def test_금액을_넣지_않는다(self):
        n1 = _by_no(outline_note_tables(_OLPUM), 1)
        blob = repr(n1)
        self.assertNotIn("906,876,415", blob)
        self.assertNotIn("540,331,606", blob)

    def test_표_수_상한을_지키고_몇_개를_뺐는지_적는다(self):
        o = outline_note_tables(_OLPUM, max_tables=2)
        n19 = _by_no(o, 19)
        self.assertLessEqual(len(n19["tables"]), 2)
        self.assertGreater(n19["tables_omitted"], 0)
        self.assertGreater(n19["tables_total"], 2)

    def test_열_상한을_지키고_밝힌다(self):
        o = outline_note_tables(_OLPUM, max_columns=3)
        wide = [t for x in o for t in x["tables"] if t["columns_total"] > 3]
        self.assertTrue(wide)
        for t in wide:
            self.assertEqual(len(t["columns"]), 3)


class TestUnstructured(unittest.TestCase):
    def test_구조화_못_하면_이유를_담고_추측하지_않는다(self):
        txt = ("1. 가\n| 구분 | 당기 |\n|---|---|\n| 매출 | 1 |\n"
               "2. 나\n표가 없습니다.\n")
        o = outline_note_tables(txt)
        n1 = _by_no(o, 1)
        self.assertFalse(n1["structured"])
        self.assertTrue(n1["reason"])
        self.assertEqual(n1["tables"], [])

    def test_표가_아예_없는_주석은_표_0개다(self):
        txt = "1. 가\n내용만 있습니다.\n2. 나\n여기도 내용뿐.\n"
        o = outline_note_tables(txt)
        self.assertEqual(o[0]["tables"], [])
        self.assertEqual(o[0]["tables_total"], 0)

    def test_빈_문서는_빈_목록이다(self):
        self.assertEqual(outline_note_tables(""), [])


if __name__ == "__main__":
    unittest.main()
