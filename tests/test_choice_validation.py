# -*- coding: utf-8 -*-
"""열거형 인자 — 모르는 값을 조용히 기본값으로 삼키지 않는다.

실측(2026-09-12, 키 있는 환경에서 실제로 두드림):

    get_audit_opinion_text("삼성전자", "2025", scope="엉뚱")
      → 🧾 **삼성전자** (005930) — 2025 사업연도 **연결감사보고서**

`scope="separate"`를 `seperate`로 오타 내면 별도가 아니라 **연결**을 받고,
화면은 그 사실을 말하지 않는다. 요청과 다른 것을 주면서 다르다고 말하지 않는
것이 이 부류의 결함이다(CLAUDE.md 「인자 검증」의 연도 사례와 같다).

    get_financial_statements_full("삼성전자", "2024", report_type="엉뚱")
      → 🔎 … 2024 엉뚱 전체 계정 재무제표를 **찾지 못했습니다**

「없다」가 아니라 **잘못 물은 것**이다. 같은 인자를 받는 `list_report_revisions`는
제대로 거절하고 있어 도구마다 답이 갈렸다.

    get_executive_compensation("삼성전자", "2024", report_type="엉뚱")
      → ━━━ [삼성전자] 임원 보수 현황 (2024년 **엉뚱**) ━━━

머리글이 「엉뚱」을 그대로 적고 결과를 낸다 — 무엇을 조회한 건지 알 수 없다.
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp import server as S


class TestHelper(unittest.TestCase):
    def test_허용값이면_통과한다(self):
        self.assertEqual(S._validate_choice("report_type", "annual",
                                            ("annual", "half")), "")

    def test_모르는_값은_거절한다(self):
        msg = S._validate_choice("report_type", "엉뚱", ("annual", "half"))
        self.assertTrue(msg.startswith("❌"))

    def test_받은_값과_허용값을_모두_알려준다(self):
        msg = S._validate_choice("scope", "seperate",
                                 ("consolidated", "separate"))
        self.assertIn("seperate", msg, "무엇을 받았는지 적는다")
        self.assertIn("consolidated", msg)
        self.assertIn("separate", msg)

    def test_빈_값은_기본값_경로라_통과시킨다(self):
        """빈 값은 「미지정」이고 도구가 제 기본값을 쓴다 — 오타와 다르다."""
        self.assertEqual(S._validate_choice("scope", "",
                                            ("consolidated", "separate")), "")


def _reject(call):
    with patch.object(S, "_api_key", return_value="k"):
        return call()


class TestToolsReject(unittest.TestCase):
    """네트워크를 타기 **전에** 거절해야 한다 — 그래서 API 키만 있으면 된다."""

    def test_감사의견_원문의_scope(self):
        out = _reject(lambda: S.get_audit_opinion_text("갑", "2025", "엉뚱"))
        self.assertTrue(out.startswith("❌"), out[:80])
        self.assertIn("consolidated", out)

    def test_비상장_재무의_scope(self):
        out = _reject(lambda: S.get_unlisted_financials("갑", "2025", "엉뚱", "fs"))
        self.assertTrue(out.startswith("❌"), out[:80])

    def test_전체_계정_재무제표의_report_type(self):
        out = _reject(lambda: S.get_financial_statements_full(
            "갑", "2024", "엉뚱", "CFS", ""))
        self.assertTrue(out.startswith("❌"), out[:80])
        self.assertIn("annual", out)

    def test_재무요약의_report_type(self):
        out = _reject(lambda: S.get_financial_summary("갑", "2024", "엉뚱"))
        self.assertTrue(out.startswith("❌"), out[:80])

    def test_임원보수의_report_type(self):
        out = _reject(lambda: S.get_executive_compensation("갑", "2024", "엉뚱"))
        self.assertTrue(out.startswith("❌"), out[:80])

    def test_재무이상_스캔의_report_type(self):
        out = _reject(lambda: S.scan_financial_anomaly("갑", "2024", "엉뚱"))
        self.assertTrue(out.startswith("❌"), out[:80])

    def test_다중_비교의_report_type(self):
        out = _reject(lambda: S.compare_financials(["갑", "을"], "2024",
                                                   report_type="엉뚱"))
        self.assertTrue(out.startswith("❌"), out[:80])


class TestValidValuesStillWork(unittest.TestCase):
    """거절이 정상 경로를 막으면 안 된다 — 빈 값·기본값은 그대로 흐른다."""

    def test_빈_scope는_거절되지_않는다(self):
        """⚠ 이 호출은 인자 검증을 **통과해** 네트워크로 간다.

        거절 테스트들은 검증 단계에서 멈추지만 이건 아니라, 하부를 막지 않으면
        가짜 키로 DART를 실제 호출한다 — 키 없는 CI에서 conftest 가드가 잡는다
        (제작자 PC는 env에 실제 키가 있어 그냥 통과했다).
        """
        with patch.object(S, "_api_key", return_value="k"), \
             patch.object(S, "find_audit_reports", return_value=[]), \
             patch.object(S, "fetch_company_disclosures", return_value=[]), \
             patch.object(S, "resolve_corp",
                          return_value=("갑", {"corp_code": "00000000",
                                               "stock_code": ""})):
            out = S.get_audit_opinion_text("갑", "2025", "")
        self.assertFalse(out.startswith("❌ scope"), out[:80])

    def test_기본_report_type은_거절되지_않는다(self):
        with patch.object(S, "_api_key", return_value=""):
            out = S.get_financial_statements_full("갑", "2024", "annual", "CFS", "")
        self.assertIn("DART_API_KEY", out, "인자가 아니라 키에서 걸려야 한다")


if __name__ == "__main__":
    unittest.main()
