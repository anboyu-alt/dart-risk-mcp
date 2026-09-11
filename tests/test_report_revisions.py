# -*- coding: utf-8 -*-
"""list_report_revisions — 「내가 본 숫자는 어느 판본인가」.

`detect_restatement`는 다른 질문에 답한다 — 「전기 숫자가 바뀌었나」. 빠진 것은
「이 보고서에 판본이 몇 개이고 재무 API가 내주는 건 그중 어느 것인가」다.

## 묶는 키는 제목 괄호의 사업연도다

실측(2026-09-11 · 10개사 · 1,100일): 정기보고서 제목에 사업연도가 **100%**
적힌다(`사업보고서 (2023.12)` — CSA 코스믹 13/13). 그래서 원본↔정정본 묶기가
애매하지 않다.

    20240320 20240320001364 | 사업보고서 (2023.12)
    20240326 20240326000792 | [기재정정]사업보고서 (2023.12)

## 어느 판본을 보고 있는지는 대조로 확정한다

재무제표 응답의 각 행에 `rcept_no`가 실려 온다. 그 값이 곧 **DART가 그
사업연도에 대해 내주는 판본**이다. 실측 4건 중 **3건이 원본이 아니라 정정본**
이었다.

    CSA 코스믹 2023 → 20240326000792  = [기재정정]사업보고서
    두산       2024 → 20250814002379  (정기 접수 시점이 아니다)
    제이스코   2023 → 20240718000409  (같음)

## 정정 비율은 정기보고서만 따로 봐야 한다

CSA 코스믹은 공시 252건 중 정정 86건(34.1%)이지만 **정기보고서 정정은 13건 중
1건**이다. 나머지는 주요사항보고서·지분공시다 — 재무 숫자와 무관하다.

⚠ **어느 판본이 「옳다」고 판정하지 않는다.** 존재하는 판본을 늘어놓고 선택
규칙만 밝힌다. ⚠ 정정본이 오히려 최종 확정 정보를 담는 경우가 있어
(`core/signals.py`에 같은 취지가 적혀 있다) 「정정 = 오류」로 읽히는 문구를
쓰지 않는다.
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp import server

_ROWS = [
    {"rcept_no": "20231114002968", "rcept_dt": "20231114",
     "report_nm": "분기보고서 (2023.09)", "flr_nm": "CSA 코스믹"},
    {"rcept_no": "20240320001364", "rcept_dt": "20240320",
     "report_nm": "사업보고서 (2023.12)", "flr_nm": "CSA 코스믹"},
    {"rcept_no": "20240326000792", "rcept_dt": "20240326",
     "report_nm": "[기재정정]사업보고서 (2023.12)", "flr_nm": "CSA 코스믹"},
    {"rcept_no": "20250317000884", "rcept_dt": "20250317",
     "report_nm": "사업보고서 (2024.12)", "flr_nm": "CSA 코스믹"},
    {"rcept_no": "20260324000035", "rcept_dt": "20260324",
     "report_nm": "사업보고서 (2025.12)", "flr_nm": "CSA 코스믹"},
    {"rcept_no": "20260515001699", "rcept_dt": "20260515",
     "report_nm": "분기보고서 (2026.03)", "flr_nm": "CSA 코스믹"},
]


def _fs(served="20240326000792"):
    return [{"rcept_no": served, "account_nm": "매출액", "thstrm_amount": "1"}]


def _run(year="2023", report_type="annual", rows=None, fs=None):
    with patch.object(server, "_api_key", return_value="k"), \
         patch.object(server, "resolve_corp",
                      return_value=("CSA 코스믹", {"corp_code": "00406037",
                                                "stock_code": "083660"})), \
         patch.object(server, "fetch_company_disclosures",
                      return_value=list(_ROWS if rows is None else rows)), \
         patch.object(server, "fetch_financial_statements",
                      return_value=(_fs() if fs is None else fs)):
        return server.list_report_revisions("CSA 코스믹", year, report_type)


class TestPairing(unittest.TestCase):
    def test_같은_사업연도의_원본과_정정본을_함께_낸다(self):
        out = _run("2023")
        self.assertIn("20240320001364", out)
        self.assertIn("20240326000792", out)

    def test_다른_사업연도는_섞지_않는다(self):
        out = _run("2023")
        self.assertNotIn("20250317000884", out)

    def test_다른_보고서_종류는_섞지_않는다(self):
        out = _run("2023", "annual")
        self.assertNotIn("20231114002968", out)

    def test_접수일_순으로_늘어놓는다(self):
        out = _run("2023")
        self.assertLess(out.index("20240320001364"), out.index("20240326000792"))

    def test_원본과_정정본을_구분해_적는다(self):
        out = _run("2023")
        self.assertIn("기재정정", out)
        self.assertIn("원본", out)


class TestWhichVersionIsServed(unittest.TestCase):
    def test_재무_API가_내주는_판본을_표시한다(self):
        out = _run("2023", fs=_fs("20240326000792"))
        line = [l for l in out.splitlines() if "20240326000792" in l][0]
        self.assertIn("재무", line)

    def test_원본이_제공될_수도_있다(self):
        out = _run("2023", fs=_fs("20240320001364"))
        line = [l for l in out.splitlines() if "20240320001364" in l][0]
        self.assertIn("재무", line)

    def test_목록에_없는_접수를_내주면_그렇게_밝힌다(self):
        """조회 창 밖의 판본일 수 있다 — 조용히 아무것도 표시하지 않으면 안 된다."""
        out = _run("2023", fs=_fs("20990101000001"))
        self.assertIn("20990101000001", out)

    def test_재무를_못_받으면_모른다고_한다(self):
        out = _run("2023", fs=[])
        self.assertIn("확인하지 못", out)
        self.assertNotIn("❌", out.splitlines()[0])

    def test_선택_규칙을_출력에_밝힌다(self):
        out = _run("2023")
        self.assertIn("규칙", out)


class TestNoJudgement(unittest.TestCase):
    def test_정정을_오류라고_쓰지_않는다(self):
        out = _run("2023")
        for banned in ("오류", "잘못", "틀린", "부정확"):
            self.assertNotIn(banned, out)

    def test_어느_판본이_옳다고_하지_않는다(self):
        out = _run("2023")
        for banned in ("옳", "정확한 판본", "맞는 판본", "써야 합니다"):
            self.assertNotIn(banned, out)

    def test_점수나_등급을_붙이지_않는다(self):
        out = _run("2023")
        for banned in ("매우위험", "고위험", "위험도", "점수", "등급"):
            self.assertNotIn(banned, out)


class TestEdges(unittest.TestCase):
    def test_판본이_하나뿐이면_그렇게_말한다(self):
        out = _run("2025", fs=_fs("20260324000035"))
        self.assertIn("20260324000035", out)
        self.assertIn("1", out)

    def test_그_해_보고서가_없으면_밝힌다(self):
        out = _run("2019")
        self.assertIn("2019", out)
        self.assertNotIn("20240320001364", out)

    def test_분기보고서도_고를_수_있다(self):
        out = _run("2026", "q1", fs=_fs("20260515001699"))
        self.assertIn("20260515001699", out)

    def test_공시목록을_못_받으면_실패라고_말한다(self):
        from dart_risk_mcp.core.dart_client import FetchList
        with patch.object(server, "_api_key", return_value="k"), \
             patch.object(server, "resolve_corp",
                          return_value=("CSA 코스믹", {"corp_code": "00406037",
                                                    "stock_code": "083660"})), \
             patch.object(server, "fetch_company_disclosures",
                          return_value=FetchList(fetch_failed=True)), \
             patch.object(server, "fetch_financial_statements", return_value=[]):
            out = server.list_report_revisions("CSA 코스믹", "2023")
        self.assertIn("조회", out)


if __name__ == "__main__":
    unittest.main()
