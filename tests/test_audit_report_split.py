# -*- coding: utf-8 -*-
"""감사보고서 본문 분할 — 비상장 법인 조회의 토대.

OpenDART 재무제표 API는 정기보고서 제출 법인 위주라 비상장사는 「조회된 데이타가
없습니다」를 돌려준다. 그러나 **감사보고서 원문은 DART에 그대로 공시**되므로 원문
경로로 우회할 수 있다. 그러려면 원문을 재무제표 / 주석으로 가를 수 있어야 한다.

⚠ **서식은 회계법인마다 다르다.** 2026-09-11 실측(2026-04-07~08 접수 · 비상장(E)
감사보고서 · 회계법인 10곳)에서 규칙별 적중률이 갈렸다.

    주석 번호 헤딩(탐욕 증가)   10/10   ← 채택
    「과목」 표 머리             9/10   ← 재무제표 앵커로 채택
    「주석」 참조 열             1/10   ← 삼일 서식 전용. 있을 때만 보존
    재무제표 표제(단일 셀 행)     1/10   ← 삼일 서식 전용. 보조로만

그래서 분할은 **주석 헤딩**을 1순위 앵커로 삼는다.

## 마크다운 헤딩이 없다

`_html_to_structured_text`가 이 문서들에서 내는 `#` 헤딩은 **0개**다(실측
올품 연결 2025). `list_document_sections`도 6개 섹션만 내는데 그중 하나가
**623KB**라 자를 수 없다. 그래서 줄 단위 규칙이 필요하다.

## 주석 제목은 본문과 붙어 온다

    1. 일반사항주식회사 올품(이하 "회사")은 주식회사 한국바이오텍 및 …

## 번호는 건너뛴다 — 멈추면 안 된다

올품 연결 2024에서 「14. 생물자산」은 줄 시작이 아니라 본문 안에 있다. 번호가
**정확히 1씩** 늘기를 요구하면 13에서 멈춰 뒤의 주석 20여 개가 통째로 사라진다
(실측: 엄격 방식 13개 → 탐욕 방식 22개).
"""
import json
import pathlib
import unittest

from dart_risk_mcp.core.audit_report import (
    find_note_headings,
    split_audit_report,
)

_FX = pathlib.Path(__file__).resolve().parent / "fixtures" / "audit_reports"


def _fx(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


class TestFixturesArePresent(unittest.TestCase):
    def test_픽스처가_실문서다(self):
        meta = json.loads(_fx("README.json"))
        self.assertIn("olpum_consolidated_2025.md", meta)
        for name, m in meta.items():
            self.assertRegex(m["rcept_no"], r"^\d{14}$")
            self.assertEqual(len(_fx(name)), m["chars"])


class TestNoteHeadings(unittest.TestCase):
    def test_올품_연결_2025는_주석_39개다(self):
        notes = find_note_headings(_fx("olpum_consolidated_2025.md"))
        self.assertEqual([n["no"] for n in notes], list(range(1, 40)))
        self.assertTrue(notes[0]["title"].startswith("일반사항"))
        self.assertEqual(notes[-1]["title"][:4], "영업부문")

    def test_제목이_본문과_붙어도_잡는다(self):
        notes = find_note_headings(_fx("olpum_consolidated_2025.md"))
        first = notes[0]
        self.assertIn("일반사항", first["title"])
        # 제목만 잘라 담고 본문을 제목에 통째로 싣지 않는다
        self.assertLessEqual(len(first["title"]), 60)

    def test_번호를_건너뛰어도_멈추지_않는다(self):
        """올품 연결 2024 — 「14. 생물자산」이 줄 시작이 아니다."""
        notes = find_note_headings(_fx("olpum_consolidated_2024_notes_gap.md"))
        nos = [n["no"] for n in notes]
        self.assertIn(13, nos)
        self.assertIn(15, nos, "13에서 멈췄다 — 뒤의 주석이 통째로 사라진다")
        self.assertIn(19, nos)
        self.assertNotIn(14, nos, "이 문서에서 14는 줄 시작이 아니다(사실)")

    def test_다른_회계법인_서식에서도_잡는다(self):
        notes = find_note_headings(_fx("hyundai_remicon_2025.md"))
        self.assertGreaterEqual(len(notes), 15)
        self.assertEqual(notes[0]["no"], 1)

    def test_구간이_겹치지_않고_이어진다(self):
        notes = find_note_headings(_fx("olpum_consolidated_2025.md"))
        for a, b in zip(notes, notes[1:]):
            self.assertEqual(a["end"], b["offset"])
            self.assertLess(a["offset"], a["end"])

    def test_빈_문서는_빈_목록이다(self):
        self.assertEqual(find_note_headings(""), [])

    def test_표_행의_번호는_주석이_아니다(self):
        """`| 1. 매출 | 100 |`은 표 내용이지 주석 제목이 아니다."""
        txt = "| 1. 매출 | 100 |\n| 2. 매출원가 | 50 |\n"
        self.assertEqual(find_note_headings(txt), [])


class TestSplitAuditReport(unittest.TestCase):
    def test_재무제표와_주석이_갈린다(self):
        txt = _fx("olpum_consolidated_2025.md")
        s = split_audit_report(txt)
        self.assertIsNotNone(s["notes_start"])
        self.assertLess(s["fs_start"], s["notes_start"])
        self.assertEqual(len(s["notes"]), 39)

    def test_재무제표_구간에_네_표가_들어온다(self):
        txt = _fx("olpum_consolidated_2025.md")
        s = split_audit_report(txt)
        fs = txt[s["fs_start"]:s["notes_start"]]
        for needle in ("534,796,185,759", "47,851,127,752", "1,384,173,296,748"):
            self.assertIn(needle, fs, f"{needle}이 재무제표 구간 밖이다")

    def test_주석_구간에_일반사항이_들어온다(self):
        txt = _fx("olpum_consolidated_2025.md")
        s = split_audit_report(txt)
        notes = txt[s["notes_start"]:s["notes_end"]]
        self.assertIn("김준영", notes)
        self.assertIn("한국바이오텍", notes)

    def test_외부감사_실시내용은_주석_밖이다(self):
        txt = _fx("olpum_consolidated_2025.md")
        s = split_audit_report(txt)
        self.assertIsNotNone(s["tail_start"])
        self.assertLessEqual(s["notes_end"], s["tail_start"])

    def test_앵커_근거를_밝힌다(self):
        """무엇으로 잘랐는지 말하지 않으면 사용자가 검증할 수 없다."""
        s = split_audit_report(_fx("olpum_consolidated_2025.md"))
        self.assertIn(s["fs_basis"], ("과목표", "재무제표표제", "문서앞부터"))

    def test_다른_서식도_자른다(self):
        s = split_audit_report(_fx("hyundai_remicon_2025.md"))
        self.assertIsNotNone(s["notes_start"])
        self.assertGreaterEqual(len(s["notes"]), 15)

    def test_주석이_없으면_없다고_한다(self):
        s = split_audit_report("| 과 목 | 금액 |\n|---|---|\n| 매출 | 10 |\n")
        self.assertIsNone(s["notes_start"])
        self.assertEqual(s["notes"], [])


class TestNoteReferenceColumnSurvives(unittest.TestCase):
    def test_주석_참조열을_버리지_않는다(self):
        """숫자에서 주석으로 건너뛰는 통로다 — 있는 문서에서는 남아야 한다."""
        txt = _fx("olpum_consolidated_2025.md")
        s = split_audit_report(txt)
        fs = txt[s["fs_start"]:s["notes_start"]]
        self.assertIn("| 매출액 | 28 | 534,796,185,759", fs)


if __name__ == "__main__":
    unittest.main()
