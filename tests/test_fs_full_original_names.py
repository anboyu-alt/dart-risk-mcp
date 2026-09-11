# -*- coding: utf-8 -*-
"""get_financial_statements_full — 회사가 쓰지 않은 계정명을 내지 않는다.

이 도구의 결과는 기사에 그대로 옮겨진다. 「파생상품평가손익 896만9358원」이라
쓰면 회사가 쓰지 않은 계정을 쓰는 것이라 정정 사유가 된다.

숫자는 **API 값 그대로** 둔다 — 단위 환산에서 값이 틀어질 수 있고 API 값은 이미
다른 도구들과 맞춰져 있다. 이 작업이 바꾸는 것은 **이름뿐**이다.
"""
import pathlib
import unittest
from unittest.mock import patch

from dart_risk_mcp import server

_FX = pathlib.Path(__file__).resolve().parent / "fixtures" / "audit_reports"
_FS = (_FX / "csa_cosmic_2025_fs_section.md").read_text(encoding="utf-8")
_AUDIT = (_FX / "csa_cosmic_consolidated_2025_opinion.md").read_text(encoding="utf-8")

_ROWS = [
    {"sj_div": "CIS", "sj_nm": "포괄손익계산서", "account_nm": "파생상품평가손익",
     "thstrm_amount": "-8969358", "frmtrm_amount": "0", "bfefrmtrm_amount": "0",
     "thstrm_nm": "제 37 기", "frmtrm_nm": "제 36 기", "currency": "KRW", "ord": "26"},
    {"sj_div": "CIS", "sj_nm": "포괄손익계산서",
     "account_nm": "해외사업장환산외환차이(세후기타포괄손익)",
     "thstrm_amount": "-6606386", "frmtrm_amount": "-39687270",
     "bfefrmtrm_amount": "-1021829", "thstrm_nm": "제 37 기",
     "frmtrm_nm": "제 36 기", "currency": "KRW", "ord": "27"},
    {"sj_div": "CIS", "sj_nm": "포괄손익계산서", "account_nm": "지분법손익",
     "thstrm_amount": "-6833892", "frmtrm_amount": "0", "bfefrmtrm_amount": "0",
     "thstrm_nm": "제 37 기", "frmtrm_nm": "제 36 기", "currency": "KRW", "ord": "10"},
    {"sj_div": "CIS", "sj_nm": "포괄손익계산서", "account_nm": "매출액",
     "thstrm_amount": "27930330148", "frmtrm_amount": "36380940773",
     "bfefrmtrm_amount": "44586544406", "thstrm_nm": "제 37 기",
     "frmtrm_nm": "제 36 기", "currency": "KRW", "ord": "34"},
    {"sj_div": "CIS", "sj_nm": "포괄손익계산서", "account_nm": "없는계정",
     "thstrm_amount": "999999999999", "frmtrm_amount": "0",
     "bfefrmtrm_amount": "0", "thstrm_nm": "제 37 기",
     "frmtrm_nm": "제 36 기", "currency": "KRW", "ord": "99"},
]

_PERIODIC = [{"rcept_no": "20260324000035", "rcept_dt": "20260324",
              "report_nm": "사업보고서 (2025.12)", "flr_nm": "CSA 코스믹"}]


def _run(statement="IS", audit_text=_AUDIT, rows=None):
    def _fsall(corp_code, api_key, yr, rt="annual", fd="CFS"):
        return list(_ROWS if rows is None else rows) if fd == "CFS" else []

    with patch.object(server, "_api_key", return_value="k"), \
         patch.object(server, "resolve_corp",
                      return_value=("CSA 코스믹", {"corp_code": "00406037",
                                                "stock_code": "083660"})), \
         patch.object(server, "fetch_financial_statements_all", side_effect=_fsall), \
         patch.object(server, "find_audit_reports", return_value=[]), \
         patch.object(server, "fetch_company_disclosures", return_value=list(_PERIODIC)), \
         patch.object(server, "fetch_audit_report_text", return_value=audit_text):
        return server.get_financial_statements_full(
            "CSA 코스믹", "2025", "annual", "CFS", statement)


class TestVerificationCase(unittest.TestCase):
    def test_지분법자본변동을_앞에_낸다(self):
        out = _run()
        self.assertIn("지분법자본변동", out)
        self.assertIn("파생상품평가손익", out, "API 표기도 괄호에 남긴다")
        self.assertLess(out.index("지분법자본변동"), out.index("파생상품평가손익"))

    def test_해외사업환산손익을_앞에_낸다(self):
        out = _run()
        self.assertLess(out.index("해외사업환산손익"),
                        out.index("해외사업장환산외환차이"))

    def test_양쪽이_같으면_하나만_낸다(self):
        out = _run()
        line = [l for l in out.splitlines() if "지분법손익" in l and "|" in l][0]
        self.assertNotIn("API:", line)

    def test_못_찾으면_그_행에_표시한다(self):
        out = _run()
        line = [l for l in out.splitlines() if "없는계정" in l][0]
        self.assertIn("대조", line)


class TestAmountsAreUntouched(unittest.TestCase):
    def test_숫자는_API_값_그대로다(self):
        out = _run()
        for v in ("-8,969,358", "-6,606,386", "-6,833,892", "27,930,330,148"):
            self.assertIn(v, out)

    def test_원문에서_숫자를_가져오지_않는다(self):
        """원문은 「(8,969,358)」 괄호 표기 — 그걸 그대로 쓰면 안 된다."""
        self.assertNotIn("| (8,969,358) |", _run())


class TestMatchRateIsStated(unittest.TestCase):
    def test_몇_행이_대조됐는지_적는다(self):
        """몇 줄이 대조됐는지 모르면 사용자가 결과를 믿을 수 없다."""
        out = _run()
        self.assertRegex(out, r"\d+행 중 \*{0,2}\d+행")
        self.assertIn("같음", out)
        self.assertIn("다름", out)

    def test_대조_경로를_밝힌다(self):
        out = _run()
        self.assertIn("20260324000035", out)


class TestNoAuditText(unittest.TestCase):
    def test_원문을_못_받으면_표_머리에_밝힌다(self):
        out = _run(audit_text="")
        self.assertIn("대조", out)
        self.assertIn("DART 재무 API", out)

    def test_원문이_없어도_숫자는_그대로_낸다(self):
        out = _run(audit_text="")
        self.assertIn("-8,969,358", out)
        self.assertIn("파생상품평가손익", out)

    def test_원문이_없으면_괄호_병기를_하지_않는다(self):
        self.assertNotIn("(API:", _run(audit_text=""))


class TestAmbiguous(unittest.TestCase):
    def test_같은_금액에_이름이_둘이면_후보를_적는다(self):
        fs = ("| 포 괄 손 익 계 산 서 |\n|---|\n| 과 목 | 당기 |\n|---|---|\n"
              "| 가나항목 | 777 |\n| 다라항목 | 777 |\n")
        audit = "연결감사보고서\n\n| 연 결 포 괄 손 익 계 산 서 |\n|---|\n" + fs
        rows = [{"sj_div": "CIS", "sj_nm": "포괄손익계산서", "account_nm": "어떤계정",
                 "thstrm_amount": "777", "frmtrm_amount": "0",
                 "bfefrmtrm_amount": "0", "thstrm_nm": "제 1 기",
                 "frmtrm_nm": "제 0 기", "currency": "KRW", "ord": "1"}]
        out = _run(audit_text=audit, rows=rows)
        self.assertIn("2곳", out)
        self.assertIn("어떤계정", out)


class TestStatementOfChangesInEquity(unittest.TestCase):
    """자본변동표는 계정명이 행이 아니라 **열**에 있다.

    실측 8개사 2,144행 중 SCE가 1,101행(51%)이고 대조율이 28.4%다 — 나머지
    넷은 77~89%. 원문에 그 이름이 없어서가 아니라 표 구조가 달라서다.
    침묵하면 사용자는 「원문에 없다」로 읽는다(「없다」와 「못 찾았다」를 가른다).
    """

    def test_자본변동표가_섞이면_구조를_밝힌다(self):
        rows = [{"sj_div": "SCE", "sj_nm": "자본변동표", "account_nm": "기초",
                 "thstrm_amount": "555", "frmtrm_amount": "0",
                 "bfefrmtrm_amount": "0", "thstrm_nm": "제 37 기",
                 "frmtrm_nm": "제 36 기", "currency": "KRW", "ord": "1"}]
        out = _run(statement="SCE", rows=rows)
        self.assertIn("자본변동표", out)
        self.assertIn("열", out)

    def test_자본변동표가_없으면_그_안내를_하지_않는다(self):
        self.assertNotIn("계정명이 행이 아니라", _run())


class TestFooterIsHonest(unittest.TestCase):
    def test_공시_원문_그대로라고_단정하지_않는다(self):
        out = _run()
        self.assertNotIn("DART 응답 원문 그대로", out)

    def test_무엇의_원문인지_밝힌다(self):
        out = _run()
        self.assertIn("감사보고서 원문", out)
        self.assertIn("API", out)


if __name__ == "__main__":
    unittest.main()
