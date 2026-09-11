# -*- coding: utf-8 -*-
"""정수 인자 — 느슨한 값에 도구가 통째로 죽지 않는다.

2026-08-30 라운드는 `lookback_years`만 봤다. 같은 부류를 전수로 두드리니
**여섯 자리가 더 죽었다**(2026-09-12 라이브):

    get_disclosure_document(rcept, "3000")   💥 TypeError: '<' not supported …
    get_disclosure_document(rcept, None)     💥 TypeError
    view_disclosure(rcept, "", "2", 2000)    💥 TypeError
    view_disclosure(rcept, "", 1, "2000")    💥 TypeError
    search_market_disclosures("cb_issue", "1")     💥 TypeError
    search_market_disclosures("cb_issue", 1, "5")  💥 TypeError

MCP 클라이언트가 느슨하면 숫자가 문자열로 온다. 프로젝트 규칙은 「예외를 도구
레벨로 전파하지 않는다」이고, 사용자에게는 도구가 통째로 사라진 것으로 보인다.

⚠ 클램프는 **기존 값을 그대로 지킨다** — 이 작업이 바꾸는 것은 「죽느냐 마느냐」
뿐이고 정상 입력의 동작은 건드리지 않는다.
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp import server as S


class TestHelper(unittest.TestCase):
    def test_문자열_숫자를_읽는다(self):
        self.assertEqual(S._coerce_int("3000", 8000, 1000, 20000), 3000)

    def test_숫자가_아니면_기본값이다(self):
        for v in (None, "", "abc", "2,000", "１２３", [], {}):
            self.assertEqual(S._coerce_int(v, 700, 1, 9999), 700, repr(v))

    def test_범위를_벗어나면_자른다(self):
        self.assertEqual(S._coerce_int(99999, 8000, 1000, 20000), 20000)
        self.assertEqual(S._coerce_int(0, 8000, 1000, 20000), 1000)

    def test_bool은_기본값이다(self):
        """`True`가 1로 통과하면 의미가 없다 — `_coerce_lookback`과 같은 판단."""
        self.assertEqual(S._coerce_int(True, 50, 1, 200), 50)
        self.assertEqual(S._coerce_int(False, 50, 1, 200), 50)

    def test_소수는_버림이_아니라_기본값이_아니다(self):
        """1.9는 숫자다 — 버려서 1로 읽는다(`_coerce_lookback`과 같은 태도)."""
        self.assertEqual(S._coerce_int(1.9, 50, 1, 200), 1)

    def test_기존_동작을_유지한다(self):
        self.assertEqual(S._coerce_int(4000, 4000, 1000, 8000), 4000)


class TestToolsSurvive(unittest.TestCase):
    """⚠ **키가 있어야 결함이 드러난다.**

    인자 클램프는 키 확인 **뒤**에 있어, `_api_key`를 빈 값으로 두면 도구가
    조기 반환해 이 결함을 못 잡는다(첫 판이 그렇게 짜여 6건이 전부 통과했다).
    키를 넣고 하부 fetch만 막아 **실행 경로**를 태운다.
    """

    RC = "20260324000035"

    def _ok(self, call):
        with patch.object(S, "_api_key", return_value="k"),              patch.object(S, "fetch_disclosure_full",
                          return_value={"files": ["f.xml"], "main_file": "f.xml",
                                        "text": "본문", "char_count": 2,
                                        "truncated": False}),              patch.object(S, "fetch_document_content",
                          return_value={"content": "본문", "page": 1,
                                        "total_pages": 1, "doc_title": "f.xml",
                                        "has_more": False, "section_title": "",
                                        "total_chars": 2}),              patch.object(S, "fetch_market_disclosures_with_status",
                          return_value=([], "FETCH_OK")),              patch.object(S, "resolve_disclosure_row_with_status",
                          return_value=({"report_nm": "사업보고서 (2025.12)",
                                         "corp_name": "갑"}, "ROW_FOUND")),              patch.object(S, "fetch_audit_report_text", return_value="본문"),              patch.object(S, "search_notes",
                          return_value={"notes": [], "scanned_notes": 0,
                                        "scope": "주석", "total_hits": 0}):
            out = call()
        self.assertIsInstance(out, str)
        self.assertTrue(out.strip())

    def test_원문_조회_max_chars(self):
        for v in ("3000", None, True, 1.9, -5, 10**9):
            self._ok(lambda v=v: S.get_disclosure_document(self.RC, v))

    def test_페이지_읽기_page(self):
        for v in ("2", None, True, 0, -1):
            self._ok(lambda v=v: S.view_disclosure(self.RC, "", v, 2000))

    def test_페이지_읽기_page_size(self):
        for v in ("2000", None, True, 10**9):
            self._ok(lambda v=v: S.view_disclosure(self.RC, "", 1, v))

    def test_시장_스캔_days(self):
        for v in ("1", None, True, 0, 10**6):
            self._ok(lambda v=v: S.search_market_disclosures("cb_issue", v))

    def test_시장_스캔_max_results(self):
        for v in ("5", None, True, 0, 10**6):
            self._ok(lambda v=v: S.search_market_disclosures("cb_issue", 1, v))

    def test_주석_검색_context_chars(self):
        for v in ("300", None, True, "abc"):
            self._ok(lambda v=v: S.search_notes_in_report(
                self.RC, ["계속기업"], "all", v))


if __name__ == "__main__":
    unittest.main()
