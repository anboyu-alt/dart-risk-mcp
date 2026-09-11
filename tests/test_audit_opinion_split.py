# -*- coding: utf-8 -*-
"""감사의견 절 분할 — 감사인이 **무엇이라고 썼는지** 읽는다.

`get_audit_opinion_history`가 담는 것은 year·opinion·auditor 셋뿐이다.
「적정의견」이라는 결과만 나오고 그 의견에 딸린 강조사항·계속기업 문단은 빠진다.
상장폐지로 가는 회사 상당수가 「적정의견 + 계속기업 불확실성」 상태를 몇 해
거치는데, 그 구간이 통째로 비어 있었다.

## ⚠ 「계속기업」은 상용문구에 **항상** 나온다

감사보고서의 「재무제표에 대한 경영진과 지배기구의 책임」·「감사인의 책임」
단락은 계속기업 존속능력 평가를 **정형 문구로** 언급한다. 낱말로 세면 모든
회사가 걸린다.

    CSA 코스믹 연결감사보고서: 문서 전체 「계속기업」 7건
                              → **의견 블록 안에는 0건**
    올품     연결감사보고서: 문서 전체 6건 → 의견 블록 안 0건

그래서 **「경영진과 지배기구의 책임」 앞**을 의견 블록으로 자르고 그 안에서만
센다.

## ⚠ 의견 제목이 「감사의견」이 아닐 수 있다

제이스코홀딩스 2025 연결감사보고서는 **의견거절**이다.

    의견거절          ← 「감사의견」이 아니다
    의견거절근거       ← 「감사의견근거」가 아니다

그리고 계속기업 불확실성이 **그 근거 단락 안**에 있다(별도 절 제목이 없다).
절 제목만 찾으면 이 회사를 놓친다.

## 실측 — 계속기업이 의견 블록에 나오는 회사

상장 13곳(2026-09-11): 있음 7곳(제이스코홀딩스·코아스·진원생명과학·STX·
KR모터스·이오플로우·다원시스) · 없음 6곳(헬릭스미스·오르비텍·유티아이·
CSA 코스믹·HLB·셀트리온). 강조사항은 코아스 1곳뿐이다.
"""
import json
import pathlib
import unittest

from dart_risk_mcp.core.audit_report import split_audit_opinion

_FX = pathlib.Path(__file__).resolve().parent / "fixtures" / "audit_reports"


def _fx(name):
    return (_FX / name).read_text(encoding="utf-8")


_CSA = _fx("csa_cosmic_consolidated_2025_opinion.md")
_JSCO = _fx("jsco_consolidated_2025_disclaimer.md")
_OLPUM = _fx("olpum_consolidated_2025.md")


class TestFixtures(unittest.TestCase):
    def test_픽스처_메타가_실제와_맞는다(self):
        meta = json.loads(_fx("README.json"))
        for n in ("csa_cosmic_consolidated_2025_opinion.md",
                  "jsco_consolidated_2025_disclaimer.md"):
            self.assertEqual(len(_fx(n)), meta[n]["chars"])
            self.assertRegex(meta[n]["rcept_no"], r"^\d{14}$")


class TestOpinionBlockBoundary(unittest.TestCase):
    def test_경영진_책임_앞에서_자른다(self):
        s = split_audit_opinion(_CSA)
        self.assertGreater(s["opinion_block_end"], 0)
        self.assertNotIn("경영진과 지배기구의 책임",
                         _CSA[s["opinion_block_start"]:s["opinion_block_end"]])

    def test_목차의_제목에_걸리지_않는다(self):
        """「독립된 감사인의 감사보고서」는 목차 표 행에도 있다."""
        s = split_audit_opinion(_CSA)
        block = _CSA[s["opinion_block_start"]:s["opinion_block_end"]]
        self.assertNotIn("....", block, "목차가 블록에 들어왔다")

    def test_상용문구의_계속기업을_세지_않는다(self):
        """문서 전체 7건이지만 의견 블록 안에는 0건이다."""
        self.assertGreaterEqual(_CSA.count("계속기업"), 5)
        self.assertFalse(split_audit_opinion(_CSA)["going_concern"]["present"])

    def test_올품도_상용문구뿐이다(self):
        self.assertGreaterEqual(_OLPUM.count("계속기업"), 5)
        self.assertFalse(split_audit_opinion(_OLPUM)["going_concern"]["present"])


class TestOpinionKind(unittest.TestCase):
    def test_적정의견을_읽는다(self):
        s = split_audit_opinion(_CSA)
        self.assertEqual(s["opinion"]["heading"], "감사의견")
        self.assertTrue(s["opinion"]["present"])

    def test_의견거절도_읽는다(self):
        """제목이 「감사의견」이 아니다 — 그것만 찾으면 놓친다."""
        s = split_audit_opinion(_JSCO)
        self.assertEqual(s["opinion"]["heading"], "의견거절")
        self.assertIn("의견을 표명하지 않습니다", s["opinion"]["text"])

    def test_근거_절도_제목을_따라간다(self):
        self.assertEqual(split_audit_opinion(_JSCO)["basis"]["heading"], "의견거절근거")
        self.assertEqual(split_audit_opinion(_CSA)["basis"]["heading"], "감사의견근거")


class TestGoingConcern(unittest.TestCase):
    def test_근거_단락_안의_계속기업을_잡는다(self):
        """제이스코는 별도 절 제목이 없고 의견거절근거 안에 있다."""
        gc = split_audit_opinion(_JSCO)["going_concern"]
        self.assertTrue(gc["present"])
        self.assertIn("계속기업", gc["text"])
        self.assertIn("유의적인 의문", gc["text"])

    def test_절_제목이_아니면_어디서_나왔는지_밝힌다(self):
        gc = split_audit_opinion(_JSCO)["going_concern"]
        self.assertFalse(gc["own_section"])
        self.assertIn("의견거절근거", gc["found_in"])

    def test_없으면_없다고_한다(self):
        gc = split_audit_opinion(_CSA)["going_concern"]
        self.assertFalse(gc["present"])
        self.assertEqual(gc["text"], "")


class TestOtherSections(unittest.TestCase):
    def test_핵심감사사항을_잡는다(self):
        kam = split_audit_opinion(_CSA)["kam"]
        self.assertTrue(kam["present"])
        self.assertIn("B2B 매출의 발생사실", kam["text"])

    def test_핵심감사사항이_없는_보고서도_있다(self):
        """비상장은 KAM 의무가 없다 — 올품 실측 0건."""
        self.assertFalse(split_audit_opinion(_OLPUM)["kam"]["present"])

    def test_기타사항을_잡는다(self):
        other = split_audit_opinion(_JSCO)["other_matters"]
        self.assertTrue(other["present"])
        self.assertIn("정진세림회계법인", other["text"])

    def test_강조사항이_없으면_없다고_한다(self):
        self.assertFalse(split_audit_opinion(_CSA)["emphasis"]["present"])


class TestQuotesAreVerbatim(unittest.TestCase):
    def test_의견_문장을_원문_그대로_담는다(self):
        s = split_audit_opinion(_JSCO)
        self.assertIn(s["opinion"]["text"][:60], _JSCO)

    def test_계속기업_문단도_원문_그대로다(self):
        gc = split_audit_opinion(_JSCO)["going_concern"]
        self.assertIn(gc["text"][:60], _JSCO)


class TestEmptyAndBroken(unittest.TestCase):
    def test_빈_문서는_전부_없음이다(self):
        s = split_audit_opinion("")
        for key in ("opinion", "basis", "going_concern", "kam", "emphasis"):
            self.assertFalse(s[key]["present"])

    def test_감사보고서가_아닌_글은_없음이다(self):
        s = split_audit_opinion("사업보고서\n회사 개요\n매출이 늘었습니다.\n")
        self.assertFalse(s["opinion"]["present"])


if __name__ == "__main__":
    unittest.main()
