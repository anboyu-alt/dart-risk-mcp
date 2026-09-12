# -*- coding: utf-8 -*-
"""주석 검색의 띄어쓰기 무시 (2026-09-13).

배경: `search_notes`는 `body.find(v)` 단순 부분 문자열이라 사용자가
`"영업권손상차손|영업권 손상차손"`처럼 표기 변형을 손수 나열해야 했다.
15개사 사업보고서 원문 7,641,985자 실측에서 절반 가까이 놓치고 있었다:

    '매입채무및기타채무'  정확 8곳 → 공백 무시 15곳
    '매출채권및기타채권'  정확 8곳 → 공백 무시 13곳
    '판매비와 관리비'     정확 10곳 → 공백 무시 15곳

오탐 위험도 따로 쟀다 — 위험 검색어 27개 × 15문서에서 **공백을 건너뛰어야만
걸리는 사례 0건**. 아래 `TestNoNewFalseMatch`가 그 경계를 고정한다.
"""
import unittest

from dart_risk_mcp.core.audit_report import search_notes, _fold_spaces


def _doc(body: str) -> str:
    return "주석 1. 시험용\n" + body + "\n주석 2. 끝\n마무리 문장.\n"


class TestFoldSpaces(unittest.TestCase):
    def test_역매핑이_원문_좌표를_가리킨다(self):
        folded, idx = _fold_spaces("가 나  다")
        self.assertEqual(folded, "가나다")
        self.assertEqual(idx, [0, 2, 5])
        for i, ch in enumerate(folded):
            self.assertEqual("가 나  다"[idx[i]], ch)

    def test_공백이_없으면_그대로(self):
        folded, idx = _fold_spaces("가나다")
        self.assertEqual(folded, "가나다")
        self.assertEqual(idx, [0, 1, 2])


class TestSpacingInsensitive(unittest.TestCase):
    """실측에서 나온 세 쌍 — 양방향 모두 걸려야 한다."""

    PAIRS = [
        ("매출채권및기타채권", "매출채권 및 기타채권"),
        ("매입채무및기타채무", "매입채무 및 기타채무"),
        ("판매비와관리비", "판매비와 관리비"),
        # ⚠ 이마트 실측 — 띄어쓰기가 **두 군데** 다르다. `|`로 손수 나열하기 어렵다.
        ("매입채무및기타채무", "매입채무 및 기타 채무"),
        ("영업권손상차손", "영업권 손상차손"),
    ]

    def test_붙여_찾으면_띄어_쓴_원문이_걸린다(self):
        for needle, written in self.PAIRS:
            with self.subTest(needle=needle):
                r = search_notes(_doc(f"당기 {written}의 내용은 다음과 같습니다."),
                                 [needle])
                self.assertTrue(r["notes"], f"{needle!r}로 {written!r}를 못 찾았다")

    def test_띄어_찾으면_붙여_쓴_원문이_걸린다(self):
        for needle, written in self.PAIRS:
            with self.subTest(needle=written):
                r = search_notes(_doc(f"당기 {needle}의 내용은 다음과 같습니다."),
                                 [written])
                self.assertTrue(r["notes"], f"{written!r}로 {needle!r}를 못 찾았다")

    def test_원문_표기를_함께_돌려준다(self):
        # 사용자가 「매출채권및기타채권」으로 찾았는데 원문이 띄어 쓰였으면
        # 그 사실이 보여야 한다 — 원문에서 그 줄을 찾아야 하기 때문이다.
        r = search_notes(_doc("당기 매출채권 및 기타채권의 내용"),
                         ["매출채권및기타채권"])
        hit = r["notes"][0]["hits"][0]
        self.assertEqual(hit["term"], "매출채권및기타채권")
        self.assertEqual(hit["matched"], "매출채권 및 기타채권")

    def test_발췌와_오프셋이_원문_좌표다(self):
        body = "앞말 " + "매출채권 및 기타채권" + " 뒷말"
        text = _doc(body)
        r = search_notes(text, ["매출채권및기타채권"], context_chars=20)
        hit = r["notes"][0]["hits"][0]
        self.assertEqual(text[hit["offset"]:hit["offset"] + len(hit["matched"])],
                         "매출채권 및 기타채권")
        self.assertIn("앞말", hit["excerpt"])
        self.assertIn("뒷말", hit["excerpt"])

    def test_한_자리를_변형끼리_중복_보고하지_않는다(self):
        # `|`로 두 표기를 함께 넣어도 같은 자리는 한 번만 센다.
        r = search_notes(_doc("당기 매출채권 및 기타채권의 내용"),
                         ["매출채권및기타채권|매출채권 및 기타채권"])
        self.assertEqual(r["total_hits"], 1)


class TestNoNewFalseMatch(unittest.TestCase):
    """⚠ 내가 가정했던 오탐 — 실측 코퍼스에는 0건이었지만 경계는 고정한다."""

    def test_경계를_넘어_붙는_것은_원래_설계다(self):
        # 「대여금」으로 찾을 때 원문 "대여 금액"이 걸린다. 실측 코퍼스
        # 7,641,985자에서 이런 자리는 3곳뿐이고 **그 문서에는 「대여금」이
        # 이미 정확히 있어** 새 주석을 만들지 않았다. 동작을 사실대로 고정한다.
        r = search_notes(_doc("특수관계자에 대한 대여 금액은 다음과 같습니다."),
                         ["대여금"])
        self.assertTrue(r["notes"])
        self.assertEqual(r["notes"][0]["hits"][0]["matched"], "대여 금")

    def test_없는_낱말은_여전히_못_찾는다(self):
        r = search_notes(_doc("당기 매출채권의 내용"), ["영업권손상차손"])
        self.assertEqual(r["notes"], [])

    def test_공백만으로는_아무것도_안_걸린다(self):
        r = search_notes(_doc("당기 매출채권의 내용"), ["   "])
        self.assertEqual(r["notes"], [])


class TestModeStillWorks(unittest.TestCase):
    def test_all은_모든_원소를_요구한다(self):
        text = _doc("당기 매출채권 및 기타채권과 판매비와 관리비.")
        both = search_notes(text, ["매출채권및기타채권", "판매비와관리비"], mode="all")
        self.assertTrue(both["notes"])
        missing = search_notes(text, ["매출채권및기타채권", "없는낱말자리표"],
                               mode="all")
        self.assertEqual(missing["notes"], [])

    def test_any는_하나만_있어도_된다(self):
        text = _doc("당기 매출채권 및 기타채권.")
        r = search_notes(text, ["매출채권및기타채권", "없는낱말자리표"], mode="any")
        self.assertTrue(r["notes"])


if __name__ == "__main__":
    unittest.main()
