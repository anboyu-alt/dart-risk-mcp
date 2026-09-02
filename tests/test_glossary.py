"""용어 사전(`core/explain.py`의 `GLOSSARY`/`GLOSSARY_ALIASES`) 검증.

뷰어·MCP 해설 곳곳에 「전환사채」·「리픽싱」·「희석」 같은 전문어가 설명
없이 쓰인다. 이 사전은 그 용어를 한 문장으로 풀어 주는 단일 출처다 —
뷰어는 `signals-data.json`의 `glossary`로 받고, MCP는 이후 과제에서
`glossary_footer`로 리포트 말미에 붙인다. 이 파일은 `tests/test_turnover_prose.py`
의 구조(완결성 → 판정 어휘 → 모순 방지 → export 일치)를 본보기로 삼아
GLOSSARY 쪽을 잠근다.

  ① 완결성 — 표제어 ≥15, 값은 정확히 한 문장(`"다."` count == 1)·60자
     이하·표제어로 시작하지 않는다, 별칭의 값은 전부 GLOSSARY 표제어다.
  ② 판정 어휘 — v0.8.5 무판정 원칙의 금지 낱말이 표제어·풀이·별칭
     어디에도 없다. `test_golden_output_hygiene`의 `_SCORE_GRADE_PATTERNS`·
     `_SEVERITY_EMOJI`도 그대로 적용한다.
  ③ 고아 금지 — 모든 표제어가(별칭 포함 어느 형태로든) 기존 해설
     사전(SIGNAL_PROSE ∪ PATTERN_PROSE ∪ TURNOVER_PROSE ∪
     CROSS_SIGNAL_PATTERNS[*].description ∪ PATTERN_CHECKPOINTS ∪
     FLAG_PROSE) 어딘가에 부분 문자열로 등장한다. 지금 문구 기준으로
     실패하는 표제어는 `_PENDING_REWRITE`로 명시 제외한다(아래 참고).
  ④ 역방향 — 테스트가 고정한 필수 전문어 목록이 전부 GLOSSARY에 있다.
  ⑤ 모순 방지 — 전환사채·교환사채·상환전환우선주 풀이에 "발행입니다"가
     없고(`SIGNAL_PROSE`의 CB_BW/EB/RCPS 문구와 충돌 방지), 매입채무
     풀이에 "높을수록 좋다"류 단정이 없다(`TURNOVER_PROSE.payable.caveat`
     와 충돌 방지).
  ⑥ export 일치 — `build_signals_data()["glossary"]`와 커밋된
     `docs/tool/signals-data.json`의 `glossary`/`glossary_aliases`가
     core와 완전히 같다.
  ⑦ 헬퍼 — `glossary_terms_in`/`glossary_footer`의 빈 입력·긴 표제어
     우선·별칭 정규화·첫 등장 순·중복 제거·limit 상한·출력 줄 형식을
     검증한다.
"""
import json
import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from dart_risk_mcp.core.explain import (  # noqa: E402
    GLOSSARY,
    GLOSSARY_ALIASES,
    glossary_terms_in,
    glossary_footer,
    SIGNAL_PROSE,
    PATTERN_PROSE,
    TURNOVER_PROSE,
    FLAG_PROSE,
    PATTERN_CHECKPOINTS,
)
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS  # noqa: E402
from tests.test_golden_output_hygiene import (  # noqa: E402
    _SCORE_GRADE_PATTERNS,
    _SEVERITY_EMOJI,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# v0.8.5 무판정 원칙 — GLOSSARY 전체(표제어·풀이·별칭)에서 금지되는 낱말.
_BANNED_VERDICT_WORDS = (
    "위험", "양호", "우수", "나쁨", "점수", "등급", "위험도", "스코어",
    "매우위험", "고위험", "중위험", "저위험",
    "CRITICAL", "HIGH", "MEDIUM", "LOW", "base_score", "confidence",
)

# ③ 고아 금지 검사가 지금 문구 기준으로 실패하는 표제어. 표제어를 지우지
# 않고 사유를 남긴 채 제외한다 — 문구 재작성이 그 낱말을 쓰게 되면 이
# 목록에서 뺀다.
#
# **지금은 비어 있다.** 마지막까지 남아 있던 "연결/별도"는 해설 재작성에서
# `SIGNAL_PROSE["DEMERGER"]`가 별칭 "연결·별도"를 쓰면서 해소됐다 — 회사를
# 쪼개면 연결·별도 재무제표에 잡히는 범위가 달라진다는, 그 자리에서 실제로
# 필요한 사실이다. 「고아를 없애려고 억지로 끼워 넣지 않는다」는 원칙 그대로.
_PENDING_REWRITE: set[str] = set()

_MUST_DEFINE = {
    "전환사채", "리픽싱", "전환가액", "희석", "감자", "자본잠식",
    "특수관계인", "매출채권", "매입채무", "운전자본", "종속회사",
}


def _collect_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _collect_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _collect_strings(v)


def _existing_prose_blob() -> str:
    texts = []
    texts.extend(_collect_strings(SIGNAL_PROSE))
    texts.extend(_collect_strings(PATTERN_PROSE))
    texts.extend(_collect_strings(TURNOVER_PROSE))
    texts.extend(_collect_strings(FLAG_PROSE))
    texts.extend(_collect_strings(PATTERN_CHECKPOINTS))
    for pat in CROSS_SIGNAL_PATTERNS.values():
        texts.append(pat.get("description", ""))
    return " ".join(texts)


class TestGlossaryContent(unittest.TestCase):
    def test_표제어가_15개_이상이다(self):
        self.assertGreaterEqual(len(GLOSSARY), 15)

    def test_모든_풀이가_정확히_한_문장이고_60자_이하다(self):
        for term, prose in GLOSSARY.items():
            self.assertIsInstance(prose, str)
            self.assertTrue(prose.strip(), f"{term}의 풀이가 비어 있다")
            self.assertEqual(
                prose.count("다."), 1,
                f"{term}의 풀이가 한 문장이 아니다(다. 개수 {prose.count('다.')}): {prose!r}",
            )
            self.assertLessEqual(
                len(prose), 60, f"{term}의 풀이가 60자를 넘는다({len(prose)}자): {prose!r}"
            )

    def test_풀이가_표제어_자체로_시작하지_않는다(self):
        for term, prose in GLOSSARY.items():
            self.assertFalse(
                prose.startswith(term),
                f"{term}의 풀이가 표제어로 시작한다(동어반복): {prose!r}",
            )

    def test_별칭의_값은_전부_GLOSSARY_표제어다(self):
        for alias, canonical in GLOSSARY_ALIASES.items():
            self.assertIn(
                canonical, GLOSSARY,
                f"별칭 {alias!r}이 가리키는 {canonical!r}가 GLOSSARY에 없다",
            )


class TestNoVerdictVocabulary(unittest.TestCase):
    def test_금지_낱말이_표제어_풀이_별칭_어디에도_없다(self):
        haystacks = []
        for term, prose in GLOSSARY.items():
            haystacks.append(("GLOSSARY 표제어", term))
            haystacks.append((f"GLOSSARY[{term!r}]", prose))
        for alias, canonical in GLOSSARY_ALIASES.items():
            haystacks.append(("GLOSSARY_ALIASES 키", alias))
            haystacks.append(("GLOSSARY_ALIASES 값", canonical))

        for label, text in haystacks:
            for banned in _BANNED_VERDICT_WORDS:
                self.assertNotIn(
                    banned, text, f"{label} {text!r}에 금지 낱말 {banned!r}가 있다"
                )

    def test_영문_약어가_풀이_문장_안에_없다(self):
        for term, prose in GLOSSARY.items():
            for abbrev in ("CB", "BW", "EB"):
                self.assertNotIn(
                    abbrev, prose,
                    f"{term}의 풀이에 영문 약어 {abbrev!r}가 있다: {prose!r}",
                )

    def test_hygiene_score_grade_patterns가_없다(self):
        import re

        for term, prose in GLOSSARY.items():
            text = f"{term} {prose}"
            for pattern, desc in _SCORE_GRADE_PATTERNS:
                self.assertIsNone(
                    re.search(pattern, text),
                    f"{term}의 풀이가 hygiene 패턴({desc})에 걸린다: {prose!r}",
                )

    def test_hygiene_severity_emoji가_없다(self):
        for term, prose in GLOSSARY.items():
            text = f"{term} {prose}"
            for emoji in _SEVERITY_EMOJI:
                self.assertNotIn(emoji, text, f"{term}의 풀이에 등급 이모지 {emoji!r}가 있다")


class TestNoOrphanHeadwords(unittest.TestCase):
    """모든 표제어가(별칭 포함 어느 형태로든) 기존 해설 사전 어딘가에
    부분 문자열로 등장해야 한다 — 아무도 안 쓰는 용어를 사전에만 정의해
    두면 설명이 필요했던 자리를 못 찾는다."""

    def test_모든_표제어가_기존_해설에_등장한다(self):
        blob = _existing_prose_blob()
        aliases_by_canonical: dict[str, list[str]] = {}
        for alias, canonical in GLOSSARY_ALIASES.items():
            aliases_by_canonical.setdefault(canonical, []).append(alias)

        orphans = []
        for term in GLOSSARY:
            if term in _PENDING_REWRITE:
                continue
            forms = [term] + aliases_by_canonical.get(term, [])
            if not any(form in blob for form in forms):
                orphans.append(term)

        self.assertFalse(
            orphans,
            f"기존 해설 어디에도 등장하지 않는 표제어(고아): {orphans} — "
            f"_PENDING_REWRITE에 넣거나 등장하는 문구를 확인하라",
        )

    def test_PENDING_REWRITE_목록이_실제로_고아다(self):
        """예외 목록이 더 이상 고아가 아닌데 방치되면(다음 과제가 이미
        그 낱말을 썼는데) 이 사실을 놓친다 — 반대 방향도 고정한다."""
        blob = _existing_prose_blob()
        aliases_by_canonical: dict[str, list[str]] = {}
        for alias, canonical in GLOSSARY_ALIASES.items():
            aliases_by_canonical.setdefault(canonical, []).append(alias)

        for term in _PENDING_REWRITE:
            self.assertIn(term, GLOSSARY, f"{term}이 더 이상 GLOSSARY에 없다")
            forms = [term] + aliases_by_canonical.get(term, [])
            still_orphan = not any(form in blob for form in forms)
            self.assertTrue(
                still_orphan,
                f"{term}은 이제 고아가 아니다 — _PENDING_REWRITE에서 빼라",
            )


class TestMustDefine(unittest.TestCase):
    def test_필수_전문어가_전부_GLOSSARY에_있다(self):
        missing = _MUST_DEFINE - set(GLOSSARY)
        self.assertFalse(missing, f"GLOSSARY에 없는 필수 전문어: {missing}")


class TestNoContradiction(unittest.TestCase):
    def test_메자닌_상품군_풀이에_발행입니다가_없다(self):
        for term in ("전환사채", "교환사채", "상환전환우선주"):
            self.assertNotIn(
                "발행입니다", GLOSSARY[term],
                f"{term}의 풀이가 '발행입니다'로 단정한다 — SIGNAL_PROSE의 "
                f"CB_BW/EB/RCPS 방향 안내(만기전취득·소각 등)와 모순된다",
            )

    def test_매입채무_풀이에_높을수록_좋다류_단정이_없다(self):
        prose = GLOSSARY["매입채무"]
        self.assertNotIn("높을수록 좋다", prose)
        self.assertNotIn("높을수록 좋", prose)


class TestExportWiring(unittest.TestCase):
    def test_build_signals_data가_core와_완전히_같은_glossary를_낸다(self):
        from export_tool_data import build_signals_data  # noqa: E402

        data = build_signals_data()
        self.assertIn("glossary", data)
        self.assertIn("glossary_aliases", data)
        self.assertEqual(data["glossary"], dict(GLOSSARY))
        self.assertEqual(data["glossary_aliases"], dict(GLOSSARY_ALIASES))

    def test_배포된_signals_data_json이_core와_완전히_같다(self):
        json_path = _ROOT / "docs" / "tool" / "signals-data.json"
        self.assertTrue(json_path.exists(), "signals-data.json이 없다")
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertIn(
            "glossary", data,
            "signals-data.json에 glossary가 없다 — "
            "scripts/export_tool_data.py 재실행 필요",
        )
        self.assertEqual(data["glossary"], dict(GLOSSARY))
        self.assertEqual(data.get("glossary_aliases"), dict(GLOSSARY_ALIASES))


class TestGlossaryTermsIn(unittest.TestCase):
    def test_빈_입력은_빈_리스트다(self):
        self.assertEqual(glossary_terms_in(""), [])
        self.assertEqual(glossary_terms_in(None), [])

    def test_긴_표제어가_우선한다(self):
        text = "이번 발행은 신주인수권부사채 형태입니다."
        terms = glossary_terms_in(text)
        self.assertIn("신주인수권부사채", terms)
        # 그 안에 다른 표제어가 오인돼 함께 잡히지 않는다. 현재 20개
        # 표제어 사이에는 실제 부분 문자열 겹침이 없어(우연) 이 검사는
        # 통과가 보장돼 있다 — 실제 겹침 배제 로직은 아래
        # test_겹치는_구간은_긴_표제어가_차지하고_짧은_쪽은_배제된다가 잠근다.
        for term in GLOSSARY:
            if term != "신주인수권부사채":
                self.assertNotIn(
                    term, terms,
                    f"{term!r}이 '신주인수권부사채' 안에서 오인 매칭됐다: {terms}",
                )

    def test_겹치는_구간은_긴_표제어가_차지하고_짧은_쪽은_배제된다(self):
        """길이 정렬만으로는 겹침 배제를 검증할 수 없다 — 현재 20개
        표제어는 우연히 서로 부분 문자열 관계가 아니기 때문이다. GLOSSARY에
        실제로 "전환사채"를 포함하는 상위어("전환사채권")를 임시로 얹어,
        같은 자리에서 짧은 표제어가 별도로 다시 잡히지 않는지 직접 검증한다."""
        patched = dict(GLOSSARY)
        patched["전환사채권"] = "테스트 전용 임시 표제어입니다."
        with mock.patch("dart_risk_mcp.core.explain.GLOSSARY", patched):
            terms = glossary_terms_in("이번 발행은 전환사채권 형태입니다.")
        self.assertIn("전환사채권", terms)
        self.assertNotIn(
            "전환사채", terms,
            f"짧은 표제어 '전환사채'가 '전환사채권'과 같은 구간에서 중복 매칭됐다: {terms}",
        )

    def test_별칭이_표제어로_정규화된다(self):
        self.assertEqual(glossary_terms_in("자사주 매입 공시입니다"), ["자기주식"])
        self.assertEqual(glossary_terms_in("CB 발행 결정"), ["전환사채"])

    def test_부분_일치를_허용한다(self):
        # "전환사채권"·"희석성"처럼 조사·접미가 붙어도 표제어를 잡는다.
        self.assertIn("전환사채", glossary_terms_in("전환사채권을 발행했다"))
        self.assertIn("희석", glossary_terms_in("희석성 우려가 있다"))

    def test_첫_등장_순으로_정렬되고_중복이_없다(self):
        text = "희석 우려가 있고, 나중에 다시 희석 이야기가 나오며, 그전에 감자 이야기도 있었다"
        terms = glossary_terms_in(text)
        self.assertEqual(terms, ["희석", "감자"])
        self.assertEqual(len(terms), len(set(terms)))

    def test_limit_초과분은_잘린다(self):
        nine_terms = [
            "전환사채", "신주인수권부사채", "교환사채", "메자닌", "리픽싱",
            "전환가액", "희석", "상환전환우선주", "감자",
        ]
        self.assertGreaterEqual(len(nine_terms), 9)
        text = " · ".join(nine_terms)
        all_terms = glossary_terms_in(text)
        self.assertEqual(all_terms, nine_terms)  # 첫 등장 순 = 입력 순
        self.assertEqual(len(all_terms), 9)

        footer = glossary_footer([text], limit=8)
        lines = [ln for ln in footer.splitlines() if ln.startswith("- ")]
        self.assertEqual(len(lines), 8)
        # 잘린 것이 몇 건인지뿐 아니라 어느 표제어가 남고 어느 것이
        # 빠졌는지도 확인한다 — 첫 등장 순이므로 마지막 아홉 번째("감자")
        # 만 빠져야 한다.
        kept = [ln.split(" — ", 1)[0][2:] for ln in lines]
        self.assertEqual(kept, nine_terms[:8])
        self.assertNotIn("감자", kept)
        self.assertNotIn(f"- 감자 — {GLOSSARY['감자']}", footer)


class TestGlossaryFooter(unittest.TestCase):
    def test_빈_입력은_빈_문자열이다(self):
        self.assertEqual(glossary_footer([]), "")
        self.assertEqual(glossary_footer(["아무 전문어도 없는 문장입니다."]), "")

    def test_출력_줄_형식이_정확하다(self):
        footer = glossary_footer(["전환사채와 감자 이야기입니다."])
        self.assertIn("**이 리포트에 나온 용어**", footer)
        self.assertIn(f"- 전환사채 — {GLOSSARY['전환사채']}", footer)
        self.assertIn(f"- 감자 — {GLOSSARY['감자']}", footer)

    def test_여러_texts를_이어_붙여서_찾는다(self):
        footer = glossary_footer(["전환사채", "이야기와 리픽싱 이야기"])
        self.assertIn("전환사채", footer)
        self.assertIn("리픽싱", footer)


if __name__ == "__main__":
    unittest.main()
