"""제목 신호가 **관찰(observed)**로 한 번이라도 발화하는지 코퍼스로 잰다.

기존 불변식은 `match_signals` 매칭까지만 봤다. 그런데 패턴·헤드라인·집계는
전부 **observed**만 먹는다 — 매칭은 되는데 한정층이 전부 강등하는 신호는
있으나 마나다. 그 간극에서 `THEME_STOCK`이 발견됐다(2026-08-23).

    THEME_STOCK: 매칭 1건 / 관찰 **0건**
    유일한 매칭이 「…지속가능글로벌테마주증권투자신탁…」 — 펀드 상품명이고
    R1c가 강등한다. 나머지 4개 키워드(작전주·테마편승·정치테마주·핀플루언서)는
    1년 270,882건에서 0건이다.

그 여파가 더 컸다 — taxonomy 7.2의 소유 신호가 그것뿐이라, 7.2를 요구하는
`reverse_split_spiral`·`fake_new_biz`도 **전부일치가 구조적으로 불가능**했다.
v1.13.3이 "정확히 두 패턴"이라 적은 것을 **다섯 패턴**으로 정정하게 된
경위다 — 자동화하니 v1.13.4가 놓친 `related_party_hollowing`(2.5)도 함께 나왔다.

이 파일은 그 계산을 자동화한다 — 새 신호가 관찰 0건으로 들어오거나, 기존
신호가 관찰 0건으로 떨어지면 여기서 걸린다.
"""
import json
import pathlib

import pytest

from dart_risk_mcp.core.qualifiers import (
    TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import (
    NON_TITLE_SIGNALS, SIGNAL_KEY_TO_TAXONOMY, SIGNAL_TYPES, match_signals,
)
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS

_CORPUS = (pathlib.Path(__file__).parent / "fixtures" / "corpus"
           / "signal_titles_365d.json")
_ROWS = [(t["nm"], t["n"]) for t in
         json.loads(_CORPUS.read_text(encoding="utf-8"))["titles"]]

# 키워드를 가진 신호 = 제목으로 발화할 것으로 선언된 신호.
# 키워드가 빈 것은 detect_*가 만드는 합성 플래그라 제목 매칭 대상이 아니다.
_TITLE_KEYS = [s["key"] for s in SIGNAL_TYPES
               if s["keywords"] and s["key"] not in NON_TITLE_SIGNALS]
# ⚠ "키워드 없음"만으로는 부족하다 — `NON_TITLE_SIGNALS`에 선언된 신호도
# 키워드가 비어 있다(absent 정리). 그것들은 합성 플래그가 아니라 **발화하지
# 않는다고 선언된** 신호이므로 taxonomy를 켜 주지 못한다. 이 구분을 빠뜨리면
# 막힌 패턴이 열려 있는 것처럼 보인다(이 파일을 쓰다 실제로 겪었다).
_SYNTHETIC = {s["key"] for s in SIGNAL_TYPES
              if not s["keywords"] and s["key"] not in NON_TITLE_SIGNALS}


def _counts():
    matched, observed = {}, {}
    for nm, n in _ROWS:
        sigs = match_signals(nm)
        for s, q in zip(sigs, qualify_signals(sigs, parse_report_name(nm), {})):
            matched[s["key"]] = matched.get(s["key"], 0) + n
            if q.tier == TIER_OBSERVED:
                observed[s["key"]] = observed.get(s["key"], 0) + n
    return matched, observed


_MATCHED, _OBSERVED = _counts()


@pytest.mark.parametrize("key", _TITLE_KEYS)
def test_선언된_제목_신호는_관찰로_발화한다(key):
    """매칭만 되고 전부 강등되는 신호는 `NON_TITLE_SIGNALS`에 선언해야 한다."""
    assert _OBSERVED.get(key, 0) > 0, (
        f"{key}: 1년 코퍼스에서 매칭 {_MATCHED.get(key, 0)}건 / 관찰 0건. "
        "키워드를 고치거나 NON_TITLE_SIGNALS에 근거와 함께 선언하세요."
    )


def _reachable(tid):
    owners = [k for k, v in SIGNAL_KEY_TO_TAXONOMY.items()
              if tid in (v if isinstance(v, list) else [v])]
    return [k for k in owners
            if _OBSERVED.get(k, 0) > 0 or k in _SYNTHETIC]


# 관찰 불가 taxonomy를 요구해 전부일치가 구조적으로 불가능한 패턴.
# 값은 (막는 taxonomy, 그 taxonomy를 소유한 신호).
BLOCKED = {
    "zombie_ma": ("1.2", "CB_REPAY"),
    "founder_fade": ("4.1", "MEETING_VIOL"),
    # v1.13.4에서 RIGHTS_UNDER를 absent로 정리하면서 2.5의 소유 신호가
    # 사라졌는데, 그때 **패턴 영향은 기록되지 않았다** — 이 계산을 자동화하니
    # 바로 드러났다. CLAUDE.md의 1년 실측표에 이 패턴이 겹침 23곳·전부일치
    # 0곳으로 적혀 있던 이유가 이것이다(사례가 없어서가 아니었다).
    "related_party_hollowing": ("2.5", "RIGHTS_UNDER"),
    "reverse_split_spiral": ("7.2", "THEME_STOCK"),
    "fake_new_biz": ("7.2", "THEME_STOCK"),
}


@pytest.mark.parametrize("pattern", sorted(CROSS_SIGNAL_PATTERNS))
def test_패턴의_도달_가능성이_기록과_일치한다(pattern):
    """막힌 패턴이 늘거나 줄면 CLAUDE.md 서술도 함께 고쳐야 한다."""
    dead = [t for t in CROSS_SIGNAL_PATTERNS[pattern]["signal_sequence"]
            if not _reachable(t)]
    if pattern in BLOCKED:
        tid, owner = BLOCKED[pattern]
        assert tid in dead, f"{pattern}이 더는 {tid}에 막히지 않는다 — 기록 갱신"
        assert tid in SIGNAL_KEY_TO_TAXONOMY[owner]
    else:
        assert not dead, (
            f"{pattern}이 새로 막혔다: {dead}. 전부일치가 불가능해졌다는 뜻이라 "
            "BLOCKED와 CLAUDE.md에 근거를 남기세요."
        )


def test_막힌_패턴은_한_taxonomy_때문만이_아닐_수_있다():
    """`fake_new_biz`를 놓친 이유 — **한 패턴의 모든 taxonomy**를 봐야 한다.

    5.4가 MGMT로 커버된다는 사실은 맞았지만, 같은 패턴의 7.2는 안 봤다.
    """
    seq = CROSS_SIGNAL_PATTERNS["fake_new_biz"]["signal_sequence"]
    assert "5.4" in seq and "7.2" in seq
    assert _reachable("5.4"), "5.4는 MGMT가 켜 준다"
    assert not _reachable("7.2"), "7.2는 켤 신호가 없다"


def test_합성_플래그는_제목_검사_대상이_아니다():
    """detect_*가 만드는 플래그(CAPITAL_CHURN·AR_SURGE 등)는 제목에 없다."""
    assert _SYNTHETIC, "합성 플래그가 하나는 있어야 한다"
    for key in _SYNTHETIC:
        assert _MATCHED.get(key, 0) == 0, f"{key}는 키워드가 없는데 매칭됐다"
