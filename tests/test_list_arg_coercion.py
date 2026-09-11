# -*- coding: utf-8 -*-
"""목록 인자에 문자열 하나가 오면 **글자 단위로 쪼개지던 것**.

파이썬에서 문자열은 순회 가능하다. `terms: list[str]`에 `"계속기업"`을 주면
`["계", "속", "기", "업"]`처럼 돌아간다 — 예외도 나지 않고 결과도 그럴듯해
보인다. 실측(2026-09-12, 라이브):

    search_notes_in_report("20260324000035", "계속기업")
      → 🔎 … 주석 검색 — `계` · `속` · `기` · `업` (모두 들어간 주석)
      → **16,808자** (mode="all"이라 네 글자가 다 든 주석이 거의 전부다)

화면이 제 데이터와 다른 것을 말하고, 사용자는 「계속기업」을 검색했다고 믿는다.
`compare_financials("삼성전자")`는 「찾을 수 없는 기업: 삼, 성, 전」으로 **드러나서
그나마 낫고**, `find_actor_overlap`·`find_risk_precedents`는 조용히 결과를 냈다.

MCP 클라이언트가 스키마를 지키면 리스트가 오지만, 느슨한 클라이언트·사람이 쓰는
호출에서는 문자열 하나가 흔하다. 「하나를 찾겠다」는 뜻이 분명하므로 감싼다.
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp import server as S


class TestHelper(unittest.TestCase):
    def test_문자열은_한_항목으로_감싼다(self):
        self.assertEqual(S._coerce_str_list("계속기업"), ["계속기업"])

    def test_리스트는_그대로_둔다(self):
        self.assertEqual(S._coerce_str_list(["가", "나"]), ["가", "나"])

    def test_빈_값은_빈_목록이다(self):
        for v in (None, "", "   ", [], ["", "  "]):
            self.assertEqual(S._coerce_str_list(v), [], repr(v))

    def test_앞뒤_공백을_접는다(self):
        self.assertEqual(S._coerce_str_list([" 가 ", "나\n"]), ["가", "나"])

    def test_문자열이_아닌_항목은_문자열로_만든다(self):
        self.assertEqual(S._coerce_str_list([1, "가"]), ["1", "가"])

    def test_튜플도_받는다(self):
        self.assertEqual(S._coerce_str_list(("가", "나")), ["가", "나"])

    def test_순서를_지킨다(self):
        self.assertEqual(S._coerce_str_list(["나", "가", "다"]), ["나", "가", "다"])


class TestToolsDoNotSplitStrings(unittest.TestCase):
    def test_주석_검색은_낱말_하나로_본다(self):
        """가장 위험한 자리 — 결과가 그럴듯해 사용자가 못 알아챈다."""
        with patch.object(S, "_api_key", return_value="k"), \
             patch.object(S, "search_notes",
                          return_value={"notes": [], "scanned_notes": 0,
                                        "scope": "주석", "total_hits": 0}), \
             patch.object(S, "fetch_audit_report_text", return_value="본문"), \
             patch.object(S, "resolve_disclosure_row_with_status",
                          return_value=({"report_nm": "사업보고서 (2025.12)",
                                         "corp_name": "갑"}, "ROW_FOUND")):
            out = S.search_notes_in_report("20260324000035", "계속기업")
        self.assertIn("계속기업", out)
        for ch in ("`계`", "`속`", "`기`", "`업`"):
            self.assertNotIn(ch, out, "글자 단위로 쪼개면 안 된다")

    def test_회사_비교는_이름_하나로_본다(self):
        """옛 동작은 「찾을 수 없는 기업: 삼, 성, 전」 — 세 회사를 찾은 척했다.

        지금은 「최소 2개 기업을 입력하세요」로 **입력이 하나라는 사실**을
        말한다(이 도구는 2개 이상을 요구한다).
        """
        with patch.object(S, "_api_key", return_value="k"), \
             patch.object(S, "resolve_corp", side_effect=Exception("no")):
            out = S.compare_financials("삼성전자", "2024")
        self.assertNotIn("삼, 성, 전", out)
        self.assertIn("2개", out)

    def test_겸직_비교는_이름_하나로_본다(self):
        with patch.object(S, "_api_key", return_value="k"), \
             patch.object(S, "resolve_corp", side_effect=Exception("no")):
            out = S.find_actor_overlap("삼성전자", 1)
        self.assertNotIn("'삼'", out)

    def test_신호_선례는_키_하나로_본다(self):
        """출력은 키가 아니라 라벨(「CB/BW발행」)이다 — 글자로 쪼개지면 그게 없다."""
        with patch.object(S, "_api_key", return_value="k"):
            out = S.find_risk_precedents("CB_BW", 90)
        self.assertIn("CB/BW발행", out)


class TestNormalCallsUnchanged(unittest.TestCase):
    def test_리스트로_부르면_그대로다(self):
        with patch.object(S, "_api_key", return_value="k"):
            out = S.find_risk_precedents(["CB_BW", "EB"], 90)
        self.assertIn("CB/BW발행", out)
        self.assertIn("교환사채(EB)발행", out)


if __name__ == "__main__":
    unittest.main()
