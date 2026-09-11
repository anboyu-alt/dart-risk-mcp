# -*- coding: utf-8 -*-
"""get_audit_opinion_text — 감사인이 무엇이라고 썼는지.

## 상장사는 감사보고서가 독립 공시로 오지 않는다

실측(2026-09-11 · 상장 13곳): **13곳 전부** 「(연결)감사보고서 (YYYY.MM)」 형태의
독립 공시가 없고 **사업보고서 ZIP에 첨부**돼 있다. 비상장은 반대다 — 올품은
연결감사보고서가 독립 공시(20260407001504, 제출인 삼일회계법인)로 온다.
그래서 두 경로를 다 다룬다.

## ⚠ `fetch_audit_report_text`는 ZIP에서 가장 큰 파일을 고른다

사업보고서 ZIP에서는 그게 **사업보고서 본문**이라 감사보고서가 아니다.

    CSA 코스믹 20260324000035 ZIP
      20260324000035.xml        1,781,011자  ← 사업보고서 본문(가장 큼)
                                              「감사의견근거」 0건 · 「독립된 감사인」 0건
      20260324000035_00760.xml    408,892자  ← 감사보고서(별도)
      20260324000035_00761.xml    489,653자  ← 연결감사보고서

파일의 **첫 줄이 문서 종류**다(`사업보고서` · `감사보고서` · `연결감사보고서`).
그걸로 고른다.
"""
import pathlib
import unittest
from unittest.mock import patch

from dart_risk_mcp import server

_FX = pathlib.Path(__file__).resolve().parent / "fixtures" / "audit_reports"
_CSA = (_FX / "csa_cosmic_consolidated_2025_opinion.md").read_text(encoding="utf-8")
_JSCO = (_FX / "jsco_consolidated_2025_disclaimer.md").read_text(encoding="utf-8")
_OLPUM = (_FX / "olpum_consolidated_2025.md").read_text(encoding="utf-8")

_PERIODIC = [{"rcept_no": "20260324000035", "rcept_dt": "20260324",
              "report_nm": "사업보고서 (2025.12)", "flr_nm": "CSA 코스믹",
              "corp_cls": "K"}]
_AUDIT = [{"rcept_no": "20260407001504", "rcept_dt": "20260407",
           "report_nm": "연결감사보고서 (2025.12)", "flr_nm": "삼일회계법인",
           "corp_cls": "E", "fiscal_year": "2025"}]


def _run(*, audits=None, periodic=None, text=_CSA, member="cons",
         stock="083660", name="CSA 코스믹", year="2025", scope="consolidated"):
    def _pick(rcept_no, api_key, prefer=""):
        return text

    with patch.object(server, "_api_key", return_value="k"), \
         patch.object(server, "resolve_corp",
                      return_value=(name, {"corp_code": "00406037",
                                           "stock_code": stock})), \
         patch.object(server, "find_audit_reports",
                      return_value=list(audits if audits is not None else [])), \
         patch.object(server, "fetch_company_disclosures",
                      return_value=list(periodic if periodic is not None else _PERIODIC)), \
         patch.object(server, "fetch_audit_report_text", side_effect=_pick):
        return server.get_audit_opinion_text(name, year, scope)


class TestPathIsStated(unittest.TestCase):
    def test_사업보고서_첨부_경로를_밝힌다(self):
        out = _run()
        self.assertIn("사업보고서", out)
        self.assertIn("20260324000035", out)

    def test_감사보고서_공시가_있으면_그것을_쓴다(self):
        out = _run(audits=_AUDIT, text=_OLPUM, stock="", name="올품")
        self.assertIn("20260407001504", out)
        self.assertIn("삼일회계법인", out)

    def test_어느_경로인지_출력에_적는다(self):
        self.assertIn("경로", _run())

    def test_둘_다_없으면_찾지_못했다고_한다(self):
        out = _run(audits=[], periodic=[])
        self.assertIn("찾", out)
        self.assertNotIn("감사의견근거", out)


class TestSectionsAreQuoted(unittest.TestCase):
    def test_적정의견_문장을_원문대로_낸다(self):
        out = _run()
        self.assertIn("감사의견", out)
        self.assertIn("공정하게 표시하고 있습니다", out)

    def test_핵심감사사항을_낸다(self):
        self.assertIn("B2B 매출의 발생사실", _run())

    def test_의견거절도_그대로_낸다(self):
        out = _run(text=_JSCO)
        self.assertIn("의견거절", out)
        self.assertIn("의견을 표명하지 않습니다", out)


class TestAbsentVsUnknown(unittest.TestCase):
    def test_계속기업_절이_없으면_없다고_한다(self):
        out = _run()
        self.assertIn("계속기업", out)
        self.assertNotIn("확인 불가", out)

    def test_계속기업이_있으면_문단을_보여준다(self):
        out = _run(text=_JSCO)
        self.assertIn("유의적인 의문", out)

    def test_원문을_못_받으면_확인_불가로_가른다(self):
        out = _run(text="")
        self.assertIn("확인", out)
        self.assertNotIn("이 보고서에는 없습니다", out)

    def test_각_절의_유무를_표로_밝힌다(self):
        out = _run()
        for nm in ("강조사항", "핵심감사사항", "기타사항"):
            self.assertIn(nm, out)


def _our_words(out: str) -> str:
    """우리가 쓴 문장만 남긴다 — 인용 블록(`━━` 아래)은 뺀다.

    ⚠ 금지어를 출력 **전체**에 걸면 안 된다. 감사인이 쓴 문장에 「위험」이
    들어 있는 것은 정상이고(실측 CSA 핵심감사사항 「높은 위험 요소를 가진 특정
    B2B 매출」) 그걸 지우면 이 도구의 목적인 **원문 인용**이 깨진다.
    """
    keep, inside = [], False
    for ln in out.splitlines():
        if ln.startswith("━━"):
            inside = True
            continue
        if ln.startswith(("📎", "ℹ️", "|", "🧾", "접수번호", "원문 ")):
            inside = False
        if not inside:
            keep.append(ln)
    return "\n".join(keep)


class TestNoJudgement(unittest.TestCase):
    def test_우리가_쓴_문장에_위험이나_심각이_없다(self):
        for t in (_CSA, _JSCO):
            ours = _our_words(_run(text=t))
            for banned in ("위험", "심각", "매우위험", "고위험", "점수", "등급"):
                self.assertNotIn(banned, ours)

    def test_감사인이_쓴_낱말은_지우지_않는다(self):
        """인용문의 「위험」은 감사인의 말이다 — 남아야 한다."""
        self.assertIn("높은 위험 요소", _run(text=_CSA))

    def test_요약하지_않고_인용한다(self):
        out = _run(text=_JSCO)
        self.assertIn("우리는 별첨된", out)


class TestDocstringsPointAtEachOther(unittest.TestCase):
    def test_새_도구가_이력_도구를_가리킨다(self):
        self.assertIn("get_audit_opinion_history",
                      server.get_audit_opinion_text.__doc__ or "")

    def test_이력_도구가_새_도구를_가리킨다(self):
        self.assertIn("get_audit_opinion_text",
                      server.get_audit_opinion_history.__doc__ or "")


if __name__ == "__main__":
    unittest.main()
