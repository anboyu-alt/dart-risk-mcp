# -*- coding: utf-8 -*-
"""감사의견 도구 — 일반화 점검에서 나온 결함 3건 (2026-09-11).

만들 때 쓴 3곳(CSA 코스믹·올품·제이스코홀딩스)에서는 통과했는데, 만들 때 안 쓴
8곳으로 넓히니 **4곳이 깨졌다**. 원인이 셋이다.

## ① 정정본 ZIP에는 감사보고서 첨부가 없다 — 가장 심각

    카카오 20250318001297 사업보고서        → ['사업보고서','감사보고서','연결감사보고서']
    카카오 20250324000901 [기재정정]사업보고서 → ['사업보고서']   ← 첨부 없음

공시목록 최신순의 **첫 번째**를 골라 정정본을 읽었고, 감사보고서를 못 찾자
`fetch_audit_report_text`의 폴백이 **사업보고서 본문 895,967자**를 돌려줬다.
그 본문에는 감사의견 요약 표(「| 계속기업 관련중요한 불확실성 |」)가 있어서
**카카오에 「계속기업 관련 있음」**이 찍혔다 — 기사에 옮기면 사고다.

## ② 절 제목이 본문과 붙어 온다

    재무제표에 대한 경영진과 지배기구의 책임경영진은 한국채택국제회계기준에 …

한 줄 통째로 비교하면 안 맞는다(아틀라스링크). 그래서 의견 블록의 **끝을 못
찾아** 상용문구가 블록 안에 들어오고 계속기업이 오탐됐다. 주석 제목에서 이미
겪은 것과 같은 현상이다.

## ③ 「감사의견」 제목을 놓친다

한농화성은 「감사의견근거」는 찾고 「감사의견」은 못 찾았다 — ②와 같은 원인.
⚠ 접두 매칭으로 고치되 **긴 제목을 먼저** 봐야 한다(「감사의견근거」가
「감사의견」으로 시작한다).
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp import server
from dart_risk_mcp.core.audit_report import split_audit_opinion

# 아틀라스링크 서식 — 제목이 본문과 붙어 온다
_GLUED = """감사보고서

독립된 감사인의 감사보고서

주식회사 가나다
주주 및 이사회 귀중

감사의견우리는 주식회사 가나다의 재무제표를 감사하였습니다. 우리의 의견으로는
공정하게 표시하고 있습니다.

감사의견근거우리는 대한민국의 회계감사기준에 따라 감사를 수행하였습니다.

핵심감사사항핵심감사사항은 우리의 전문가적 판단에 따라 당기 재무제표감사에서
가장 유의적인 사항들입니다.

재무제표에 대한 경영진과 지배기구의 책임경영진은 한국채택국제회계기준에 따라
이 재무제표를 작성할 책임이 있으며, 계속기업으로서의 존속능력을 평가하고
계속기업과 관련된 사항을 공시할 책임이 있습니다.

재무제표감사에 대한 감사인의 책임우리의 목적은 계속기업 가정의 적절성에 대해
결론을 내리는 것입니다.
"""

# 사업보고서 본문 — 감사의견 요약 표가 있어 낱말로는 걸린다
_BODY = """사업보고서

| 사업연도 | 감사인 | 감사의견 | 계속기업 관련중요한 불확실성 | 강조사항 |
|---|---|---|---|---|
| 제30기 | 삼일회계법인 | 적정의견 | 해당사항 없음 | 해당사항 없음 |

회사의 사업 내용은 다음과 같습니다.
"""


class TestGluedHeadings(unittest.TestCase):
    """② 제목이 본문과 붙어도 절을 찾는다."""

    def test_의견_블록의_끝을_찾는다(self):
        s = split_audit_opinion(_GLUED)
        block = _GLUED[s["opinion_block_start"]:s["opinion_block_end"]]
        self.assertNotIn("경영진과 지배기구의 책임", block)

    def test_상용문구의_계속기업이_들어오지_않는다(self):
        self.assertGreaterEqual(_GLUED.count("계속기업"), 3)
        self.assertFalse(split_audit_opinion(_GLUED)["going_concern"]["present"])

    def test_감사의견_제목을_찾는다(self):
        s = split_audit_opinion(_GLUED)
        self.assertTrue(s["opinion"]["present"])
        self.assertEqual(s["opinion"]["heading"], "감사의견")
        self.assertIn("공정하게 표시하고 있습니다", s["opinion"]["text"])

    def test_근거를_의견으로_오인하지_않는다(self):
        """⚠ 「감사의견근거」가 「감사의견」으로 시작한다 — 긴 것을 먼저 본다."""
        s = split_audit_opinion(_GLUED)
        self.assertEqual(s["basis"]["heading"], "감사의견근거")
        self.assertIn("회계감사기준에 따라", s["basis"]["text"])
        self.assertNotIn("회계감사기준에 따라", s["opinion"]["text"])

    def test_핵심감사사항도_찾는다(self):
        self.assertTrue(split_audit_opinion(_GLUED)["kam"]["present"])


class TestNonAuditDocumentIsNotJudged(unittest.TestCase):
    """① 감사보고서가 아닌 문서로 절을 판정하지 않는다."""

    def _run(self, text, periodic):
        with patch.object(server, "_api_key", return_value="k"), \
             patch.object(server, "resolve_corp",
                          return_value=("카카오", {"corp_code": "00258801",
                                                 "stock_code": "035720"})), \
             patch.object(server, "find_audit_reports", return_value=[]), \
             patch.object(server, "fetch_company_disclosures", return_value=periodic), \
             patch.object(server, "fetch_audit_report_text", return_value=text):
            return server.get_audit_opinion_text("카카오", "2024")

    _AMEND = [{"rcept_no": "20250324000901", "rcept_dt": "20250324",
               "report_nm": "[기재정정]사업보고서 (2024.12)", "flr_nm": "카카오"}]

    def test_사업보고서_본문이면_판정하지_않는다(self):
        out = self._run(_BODY, self._AMEND)
        self.assertNotIn("| 계속기업 관련 | 있음", out)

    def test_왜_판정하지_않았는지_밝힌다(self):
        out = self._run(_BODY, self._AMEND)
        self.assertIn("감사보고서", out)
        self.assertTrue("첨부" in out or "없" in out)

    def test_판본을_훑어_첨부가_있는_접수를_고른다(self):
        """정정본에 없으면 원본으로 넘어간다."""
        rows = [
            {"rcept_no": "20250324000901", "rcept_dt": "20250324",
             "report_nm": "[기재정정]사업보고서 (2024.12)", "flr_nm": "카카오"},
            {"rcept_no": "20250318001297", "rcept_dt": "20250318",
             "report_nm": "사업보고서 (2024.12)", "flr_nm": "카카오"},
        ]
        seen = []

        def _fetch(rcept_no, api_key, prefer=""):
            seen.append(rcept_no)
            return _BODY if rcept_no == "20250324000901" else _GLUED

        with patch.object(server, "_api_key", return_value="k"), \
             patch.object(server, "resolve_corp",
                          return_value=("카카오", {"corp_code": "00258801",
                                                 "stock_code": "035720"})), \
             patch.object(server, "find_audit_reports", return_value=[]), \
             patch.object(server, "fetch_company_disclosures", return_value=rows), \
             patch.object(server, "fetch_audit_report_text", side_effect=_fetch):
            out = server.get_audit_opinion_text("카카오", "2024")
        self.assertIn("20250318001297", out)
        self.assertIn("20250318001297", seen)
        self.assertIn("| 감사의견 | 있음", out)


class TestScopeLabelIsHonest(unittest.TestCase):
    """머리글이 실제로 읽은 문서와 같아야 한다."""

    def test_연결을_찾았는데_별도를_읽었으면_그렇게_적는다(self):
        rows = [{"rcept_no": "20250320000501", "rcept_dt": "20250320",
                 "report_nm": "사업보고서 (2024.12)", "flr_nm": "한농화성"}]
        with patch.object(server, "_api_key", return_value="k"), \
             patch.object(server, "resolve_corp",
                          return_value=("한농화성", {"corp_code": "00164150",
                                                  "stock_code": "011500"})), \
             patch.object(server, "find_audit_reports", return_value=[]), \
             patch.object(server, "fetch_company_disclosures", return_value=rows), \
             patch.object(server, "fetch_audit_report_text", return_value=_GLUED):
            out = server.get_audit_opinion_text("한농화성", "2024", "consolidated")
        head = out.splitlines()[0]
        self.assertNotIn("연결감사보고서", head,
                         "연결을 못 찾고 별도를 읽었는데 머리글이 연결이라 적는다")
        self.assertIn("감사보고서", head)


if __name__ == "__main__":
    unittest.main()
