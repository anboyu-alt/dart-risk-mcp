# -*- coding: utf-8 -*-
"""감사보고서를 **못 받은 것**과 **없는 것**을 가른다.

`find_audit_reports`는 `fetch_company_disclosures`(상태를 버리는 판)를 써서
조회가 실패해도 **빈 리스트**를 돌려준다. 그러면 그것을 쓰는 세 도구가
DART 한도 초과(status 020)·점검 때 「감사보고서를 찾지 못했습니다」라 말한다 —
회사에 대한 진술로 읽힌다.

CLAUDE.md 「오류 처리」가 못 박은 원칙이다:

    ⚠ 빈 값이 「없다」로 읽히면 안 된다 — DART는 오류를 HTTP 200 본문으로
    주는데, 구조화 fetcher들이 그걸 빈 리스트로 접어 여섯 도구가 「없음」을
    냈다. 전부 **회사에 대한 진술**로 읽힌다.

형제 함수 `fetch_company_disclosures_with_status`가 이미 있고, 다른 도구들은
그쪽을 쓴다(`track_capital_structure`·`analyze_company_risk` 등). 이 경로만
빠져 있었다.

⚠ **반환 타입은 바꾸지 않는다** — `FetchList`(list 상속 + `.fetch_failed`)를
쓰면 기존 호출부가 그대로 동작한다(이 저장소가 이미 쓰는 관례).
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp.core import dart_client as dc
from dart_risk_mcp import server as S

_ROWS = [{"rcept_no": "20260324000035", "rcept_dt": "20260324",
          "report_nm": "연결감사보고서 (2025.12)", "flr_nm": "삼일회계법인",
          "corp_cls": "E"}]


class TestFindAuditReports(unittest.TestCase):
    def test_정상이면_실패로_표시하지_않는다(self):
        with patch.object(dc, "fetch_company_disclosures_with_status",
                          return_value=(list(_ROWS), dc.FETCH_OK)):
            out = dc.find_audit_reports("00406037", "k", year="2025")
        self.assertEqual(len(out), 1)
        self.assertFalse(getattr(out, "fetch_failed", False))

    def test_조회_실패를_알린다(self):
        with patch.object(dc, "fetch_company_disclosures_with_status",
                          return_value=([], dc.FETCH_ERROR)):
            out = dc.find_audit_reports("00406037", "k", year="2025")
        self.assertEqual(list(out), [])
        self.assertTrue(getattr(out, "fetch_failed", False),
                        "조회 실패가 「없음」과 구분되지 않는다")

    def test_진짜_없음은_실패가_아니다(self):
        with patch.object(dc, "fetch_company_disclosures_with_status",
                          return_value=([], dc.FETCH_OK)):
            out = dc.find_audit_reports("00406037", "k", year="2025")
        self.assertEqual(list(out), [])
        self.assertFalse(getattr(out, "fetch_failed", False))

    def test_리스트처럼_그대로_쓸_수_있다(self):
        """반환 타입을 바꾸면 기존 호출부가 깨진다 — list 계약을 지킨다."""
        with patch.object(dc, "fetch_company_disclosures_with_status",
                          return_value=(list(_ROWS), dc.FETCH_OK)):
            out = dc.find_audit_reports("00406037", "k")
        self.assertIsInstance(out, list)
        self.assertEqual(out[0]["rcept_no"], "20260324000035")
        self.assertTrue(bool(out))


def _tool_out(fn, **kw):
    with patch.object(S, "_api_key", return_value="k"), \
         patch.object(S, "find_corp_candidates",
                      return_value=[{"corp_code": "00111111", "stock_code": "",
                                     "modify_date": ""}]), \
         patch.object(S, "resolve_corp",
                      return_value=("갑", {"corp_code": "00111111",
                                           "stock_code": "000000"})), \
         patch.object(S, "fetch_company_disclosures", return_value=[]), \
         patch.object(S, "find_audit_reports",
                      return_value=dc.FetchList(fetch_failed=True)):
        return fn(**kw)


class TestToolsSayItHonestly(unittest.TestCase):
    """조회에 실패했으면 「없다」가 아니라 「못 받았다」라고 말해야 한다."""

    def test_비상장_재무(self):
        out = _tool_out(S.get_unlisted_financials, company_name="갑",
                        year="2025", scope="consolidated", section="fs")
        self.assertIn("조회", out)
        self.assertNotIn("작성하지 않는 회사일 수 있습니다", out)

    def test_감사의견_원문(self):
        out = _tool_out(S.get_audit_opinion_text, company_name="갑",
                        year="2025", scope="consolidated")
        self.assertIn("조회", out)


if __name__ == "__main__":
    unittest.main()
