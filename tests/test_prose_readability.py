"""해설 문구의 **읽기 쉬움**을 기계로 잠근다(v1.21.30 후속).

제작자 피드백 — *"설명들의 난이도가 상당하다 · 회계 소양이 부족한 이용자도
이해하게 문턱을 낮추자."* 재작성 전 실측: `SIGNAL_PROSE`는 문장 평균 51.3자,
개발자 근거(실측·N건 중·측정일)가 4곳에 그대로 노출, `PATTERN_PROSE`는 문장
평균 68.0자였다. 기준선은 같은 파일 `TURNOVER_PROSE.meaning`(28자대).

⚠ **무판정 원칙(v0.8.5)과 충돌하지 않는다** — 여기서 요구하는 것은 「이 공시가
무엇인지 · 어느 방향의 뜻인지 · 다만 반대 경우도 있다」는 **유형 설명**이지
회사에 대한 단정이 아니다. 판정 어휘 금지는 `test_prose_matches_titles.py`·
`test_prose_hygiene_static.py`가 따로 잠근다.

거는 것은 문장이 아니라 **성질**이다:
  ① 문장이 짧은가(2~5문장 · 최장 71자 · 전체 평균 35자)
  ② 첫 문장이 단독으로 서는가 — `server.py`의 `track_capital_structure`가
     `meaning.split("다.")[0] + "다."`로 첫 문장만 잘라 쓴다(L7044). 첫 문장
     안에 "다."가 한 번 더 있으면 화면에 반토막이 나간다.
  ③ 마지막 문장이 양면 고지·확인 안내로 닫히는가
  ④ 전문어가 되풀이되지 않는가
  ⑤ 개발자 근거(실측·표본·측정일)가 사용자 화면에 새지 않는가

⚠ **전문어 밀도 공식과 임계의 실측 근거** — 세는 방식은 브리프의 취지
그대로 **「전문어마다 첫 등장은 무료, 되풀이되면 센다」**이다(GLOSSARY
표제어도 예외가 아니다 — 사전은 첫 등장을 풀어 줄 뿐, 같은 낱말이 네 번
나오는 문단이 쉬워지지는 않는다). 임계만 실측으로 정했다.

세 후보를 브리프가 지정한 **완성본 6개**에 대입한 결과(천자당):

    항목              브리프 문언   사전 전등장 무료   채택(첫 등장 무료)
    CB_BW                    0.0              0.0              0.0
    RCPS                     0.0              0.0              0.0
    AUDIT                   22.2              7.4              7.4
    EARNINGS_SHOCK           0.0              0.0              0.0
    MEZZ_EXERCISE            0.0              0.0              0.0
    CAPITAL_RED             16.9              0.0             16.9

브리프 문언(「출현 총수 − GLOSSARY 표제어 distinct 수」)은 `AUDIT`을 22.2로
계산해 브리프 자신의 임계 8을 넘긴다 — 사전에 없는 「부적정」 2회에 아무런
공제가 없기 때문이다. 반대로 「사전 낱말은 전 등장 무료」로 하면 `CAPITAL_RED`
의 「감자」 4회가 0.0이 되어, **사전 표제어만으로 채운 문단은 아무리 되풀이해도
0**이 된다(래칫이 무력해진다).

그래서 채택한 공식에서 **완성본이 통과하는 최소 상한은 17**이다
(`CAPITAL_RED` 16.9). 이 값은 「감자」류 필수 용어를 네 번까지 쓰는 것은
허용하되, 그 이상 되풀이되면 잡는 선이다.

⚠ **최장 문장 71자 · description 133자**도 같은 이유의 보정이다 — 브리프는
각각 70자·130자라 적었는데 지정된 완성본이 정확히 71자(`CAPITAL_RED`의 마지막
문장)·133자(`fund_diversion_chain` description)다.
"""
from __future__ import annotations

import re

import pytest

from dart_risk_mcp.core.explain import (
    GLOSSARY,
    GLOSSARY_ALIASES,
    PATTERN_PROSE,
    SIGNAL_PROSE,
)
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS

# ── 임계 ─────────────────────────────────────────────────────────────────
_MAX_SENTENCE = 71          # 항목별 최장 문장(CAPITAL_RED 완성본 = 71)
_MAX_AVG_SENTENCE = 35      # SIGNAL_PROSE 전체 문장 평균
_MAX_JARGON = 17.0          # 전문어 밀도(천자당) — 완성본 통과 최소 상한
_PATTERN_MAX_AVG = 45       # PATTERN_PROSE 문장 평균
_PATTERN_MAX_SENTENCE = 90
_DESC_MAX_CHARS = 133      # 완성본 `fund_diversion_chain` = 133자

# ── 회귀 래칫 ────────────────────────────────────────────────────────────
# 재작성 직후 실측값. 다음 사람이 문장을 늘리거나 전문어를 되풀이하면 여기서
# 걸린다. 값을 올리려면 그럴 만한 이유를 남겨라.
#
# ⚠ **여유를 넉넉히 주면 래칫이 아니다.** 첫 판은 밀도 여유가 `+1`이라
# 재작성 전 문구(같은 공식으로 평균 2.93)를 통째로 되돌려도 통과했다.
# 여유를 `+0.3`으로 좁히고, **항목별 최댓값**도 함께 잠근다 — 평균만 잠그면
# 한 항목이 크게 나빠져도 나머지 39개에 묻힌다.
#
# 되돌림 검증(재작성 전 `SIGNAL_PROSE` 40개를 같은 공식으로):
#   문장 평균 51.3 (> 31.6+1)  · 밀도 평균 2.93 (> 1.5+0.3)
#   밀도 최댓값 24.7 (> 16.9+1) — 세 래칫 전부 실패한다.
#
# ⚠ 문장 평균 래칫은 **두 번 내려왔다** — 33.9(1차 재작성) → 31.6. 두 번째는
# 브랜치 종료 기준(≤32.0)을 맞추려고 긴 문장 13개를 **끊은** 결과다(사실을
# 덜어낸 것이 아니라 마침표를 넣었다 — 문장 165 → 178개, 총 글자는
# 5,589 → 5,632자로 오히려 늘었다). 완성본 6개는 한 글자도 건드리지 않았다.
_RATCHET_AVG_SENTENCE = 31.6   # 재작성 전 51.3 · 1차 재작성 33.9
_RATCHET_JARGON = 1.5          # 재작성 전 2.93 (평균)
_RATCHET_JARGON_MAX = 16.9     # 재작성 전 24.7 (항목별 최댓값)

# 사전이 첫 등장을 풀어 주는 전문어 — GLOSSARY 표제어·별칭.
# 그 밖의 전문어는 아래에 손으로 적는다(사전이 풀어 주지 않는다).
_UNGLOSSED = {
    "가장납입", "과대계상", "실질심사", "우발채무", "계속기업", "유동화",
    "차환", "무자본", "최대주주", "대량보유", "특수관계자", "영업양수",
    "출자", "담보", "차입", "의견거절", "부적정", "한정의견",
}
_GLOSSED = set(GLOSSARY) | set(GLOSSARY_ALIASES)
_JARGON = _GLOSSED | _UNGLOSSED

# 개발자 근거 — 화면에 나가면 안 되는 내부 측정 서술.
_EVIDENCE_RE = re.compile(r"실측|표본|\d+건 중|이 신호의 \d+%|\(20\d\d-\d\d-\d\d\)")


def _sentences(text: str) -> list[str]:
    """`다.`/`요.`를 문장 끝으로 보고 나눈다(마침표는 떨어진다)."""
    return [s.strip() for s in re.split(r"(?<=[다요])\.", text) if s.strip()]


def _jargon_hits(text: str) -> list[tuple[int, int, str]]:
    """전문어 출현을 긴 낱말 우선·겹침 없이 센다."""
    hits: list[tuple[int, int, str]] = []
    for term in sorted(_JARGON, key=len, reverse=True):
        start = 0
        while True:
            i = text.find(term, start)
            if i < 0:
                break
            end = i + len(term)
            start = i + 1
            if any(i < h_end and end > h_start for h_start, h_end, _ in hits):
                continue
            hits.append((i, end, term))
    return hits


def jargon_density(text: str) -> float:
    """천자당 '되풀이된 전문어' 수 — 낱말마다 첫 등장은 무료(사전·문맥이 한 번
    풀어 줄 기회), 두 번째부터 센다. 근거는 파일 머리말의 대입표."""
    hits = _jargon_hits(text)
    charged = len(hits) - len({t for _, _, t in hits})
    return charged / max(1, len(text)) * 1000


def avg_sentence_len(texts) -> float:
    lens = [len(s) for t in texts for s in _sentences(t)]
    return sum(lens) / max(1, len(lens))


_SIGNAL_KEYS = sorted(SIGNAL_PROSE)
_PATTERN_KEYS = sorted(PATTERN_PROSE)
_DESC = {k: v["description"] for k, v in CROSS_SIGNAL_PATTERNS.items()}


# ── SIGNAL_PROSE ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", _SIGNAL_KEYS)
def test_해설은_짧은_문장_두세_개다(key):
    ss = _sentences(SIGNAL_PROSE[key])
    assert 2 <= len(ss) <= 5, f"{key}: 문장 {len(ss)}개 — 2~5문장으로"
    longest = max(ss, key=len)
    assert len(longest) <= _MAX_SENTENCE, (
        f"{key}: {len(longest)}자 문장 — 끊으세요\n  {longest}"
    )


@pytest.mark.parametrize("key", _SIGNAL_KEYS)
def test_첫_문장이_단독으로_선다(key):
    """server.py L7044가 첫 문장만 잘라 쓴다 — 안에 '다.'가 또 있으면 반토막."""
    text = SIGNAL_PROSE[key]
    first = _sentences(text)[0]
    assert first.endswith("입니다"), f"{key}: 첫 문장이 '입니다.'로 끝나지 않는다"
    assert text.split("다.")[0] + "다." == first + ".", (
        f"{key}: 첫 문장 안에 '다.'가 또 있어 잘라 쓰면 반토막이 난다\n"
        f"  잘린 결과: {text.split('다.')[0] + '다.'}"
    )
    assert len(first) <= 45, f"{key}: 첫 문장 {len(first)}자 — 무엇인지만 말하세요"


@pytest.mark.parametrize("key", _SIGNAL_KEYS)
def test_마지막_문장이_양면_고지나_확인_안내로_닫힌다(key):
    """단정으로 끝내지 않는다 — 반대 경우나 확인할 곳을 가리키고 닫는다."""
    last = _sentences(SIGNAL_PROSE[key])[-1]
    assert any(w in last for w in ("다만", "반대로", "원문", "안내", "확인", "함께")), (
        f"{key}: 마지막 문장에 양면 고지·확인 안내가 없다\n  {last}"
    )


@pytest.mark.parametrize("key", _SIGNAL_KEYS)
def test_전문어가_되풀이되지_않는다(key):
    d = jargon_density(SIGNAL_PROSE[key])
    assert d <= _MAX_JARGON, f"{key}: 전문어 밀도 {d:.1f}/천자"


def test_문장_평균이_짧다():
    avg = avg_sentence_len(SIGNAL_PROSE.values())
    assert avg <= _MAX_AVG_SENTENCE, f"SIGNAL_PROSE 문장 평균 {avg:.1f}자"


# ── 개발자 근거 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("key", _SIGNAL_KEYS)
def test_해설에_개발자_근거가_없다(key):
    """수치·측정일은 지우지 말고 바로 위 `#` 주석으로 옮긴다."""
    m = _EVIDENCE_RE.search(SIGNAL_PROSE[key])
    assert m is None, f"{key}: 개발자 근거 '{m.group(0)}' — 주석으로 옮기세요"


@pytest.mark.parametrize("pid", sorted(_DESC))
def test_description에_개발자_근거가_없다(pid):
    m = _EVIDENCE_RE.search(_DESC[pid])
    assert m is None, f"{pid}: 개발자 근거 '{m.group(0)}'"


@pytest.mark.parametrize("pid", _PATTERN_KEYS)
def test_패턴_해설에_실측_표기가_없다(pid):
    """`PATTERN_PROSE`는 금감원 집계 인용을 담는 자리라 수치 자체는 허용한다 —
    우리 내부 측정을 뜻하는 「실측」만 막는다."""
    assert "실측" not in PATTERN_PROSE[pid], f"{pid}: '실측'은 내부 측정 표기"


# ── PATTERN_PROSE ────────────────────────────────────────────────────────

@pytest.mark.parametrize("pid", _PATTERN_KEYS)
def test_패턴_해설_문장이_길지_않다(pid):
    longest = max(_sentences(PATTERN_PROSE[pid]), key=len)
    assert len(longest) <= _PATTERN_MAX_SENTENCE, (
        f"{pid}: {len(longest)}자 문장\n  {longest}"
    )


def test_패턴_해설_문장_평균이_짧다():
    avg = avg_sentence_len(PATTERN_PROSE.values())
    assert avg <= _PATTERN_MAX_AVG, f"PATTERN_PROSE 문장 평균 {avg:.1f}자"


# ── description ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("pid", sorted(_DESC))
def test_description은_두세_문장_짧은_단락이다(pid):
    """뷰어 패턴 카드의 머리 한 단락이 된다(MCP 출력에는 나가지 않는다)."""
    text = _DESC[pid]
    ss = _sentences(text)
    assert 2 <= len(ss) <= 3, f"{pid}: 문장 {len(ss)}개"
    assert len(text) <= _DESC_MAX_CHARS, f"{pid}: {len(text)}자"


@pytest.mark.parametrize("pid", sorted(_DESC))
def test_description에_기호_연쇄가_없다(pid):
    """「A → B + C」식 도식은 개발 메모지 읽는 글이 아니다."""
    text = _DESC[pid]
    for mark, why in (("→", "화살표 연쇄"), (" + ", "덧셈 연쇄"), ("%", "퍼센트")):
        assert mark not in text, f"{pid}: {why} '{mark}'"


# ── 회귀 래칫 ────────────────────────────────────────────────────────────

def test_문장_평균이_다시_늘지_않는다():
    avg = avg_sentence_len(SIGNAL_PROSE.values())
    assert avg <= _RATCHET_AVG_SENTENCE + 1, (
        f"문장 평균 {avg:.1f}자 — 래칫({_RATCHET_AVG_SENTENCE})을 넘었다"
    )


def test_전문어_밀도가_다시_오르지_않는다():
    densities = [jargon_density(t) for t in SIGNAL_PROSE.values()]
    avg = sum(densities) / len(densities)
    assert avg <= _RATCHET_JARGON + 0.3, (
        f"전문어 밀도 평균 {avg:.2f}/천자 — 래칫({_RATCHET_JARGON})을 넘었다"
    )


def test_가장_나쁜_항목도_다시_나빠지지_않는다():
    """평균만 잠그면 한 항목이 크게 나빠져도 나머지 39개에 묻힌다."""
    worst = max(SIGNAL_PROSE, key=lambda k: jargon_density(SIGNAL_PROSE[k]))
    d = jargon_density(SIGNAL_PROSE[worst])
    assert d <= _RATCHET_JARGON_MAX + 1, (
        f"{worst}: 전문어 밀도 {d:.1f}/천자 — "
        f"항목별 래칫({_RATCHET_JARGON_MAX})을 넘었다"
    )
