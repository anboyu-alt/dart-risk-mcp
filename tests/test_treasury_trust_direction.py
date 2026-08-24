"""자사주 신탁계약 건이 「취득·처분」으로 설명되지 않는지 잠근다.

우리금융지주 리포트를 읽다 찾았다(2026-08-24).

    • 20260610 · 주요사항보고서(자기주식취득신탁계약**해지**결정)
      → 자사주 **취득·처분** 공시입니다. 주주 환원으로 긍정적일 수도 있지만 …

신탁계약 **해지**는 매입 프로그램을 **끝내는** 것이라 취득과 방향이 반대다.

원인은 `TREASURY`의 키워드 「자기주식취득」이 **부분 문자열**이라
「자기주식취득**신탁계약체결**결정」·「자기주식취득**신탁계약해지**결정」까지
가져오는 것이다. 1년 실측:

| 제목 | 관찰 |
|---|---:|
| 자기주식처분결정 | 733 |
| **자기주식취득신탁계약체결결정** | **292** |
| 자기주식취득결정 | 271 |
| **자기주식취득신탁계약해지결정** | **234** |

`TREASURY` 관찰 1,532건 중 **526건(34%)이 신탁계약 건**이다.

**신호는 지우지 않는다** — 신탁을 통한 우회 취득도 관찰 대상이고, 구조화
경로(`fetch_treasury_decisions`)에서는 이미 `TREASURY_TRUST`로 따로 센다.
제목 경로에서는 v1.12.3이 만든 `DIRECTION_NOTES` 방식으로 **방향만 사실로**
덧붙인다(CB_BW의 "발행이 아니라 되사기·소각"과 같은 처리).
"""
import json
import pathlib

import pytest

from dart_risk_mcp.core.qualifiers import (
    DIRECTION_NOTES, TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import match_signals

TRUST = ("주요사항보고서(자기주식취득신탁계약체결결정)",
         "주요사항보고서(자기주식취득신탁계약해지결정)")
DIRECT = ("주요사항보고서(자기주식취득결정)",
          "주요사항보고서(자기주식처분결정)")


def _qualified(nm):
    sigs = match_signals(nm)
    return list(zip(sigs, qualify_signals(sigs, parse_report_name(nm), {})))


@pytest.mark.parametrize("nm", TRUST)
def test_신탁계약_건에는_방향_안내가_붙는다(nm):
    got = [q for s, q in _qualified(nm) if s["key"] == "TREASURY"]
    assert got, "TREASURY가 매칭돼야 한다(신호를 지우지 않는다)"
    assert got[0].tier == TIER_OBSERVED
    assert "신탁계약" in (got[0].note or ""), f"방향 안내 없음: {got[0].note!r}"


@pytest.mark.parametrize("nm", DIRECT)
def test_직접_취득_처분에는_붙지_않는다(nm):
    """넓게 붙이면 안내가 아니라 잡음이 된다."""
    got = [q for s, q in _qualified(nm) if s["key"] == "TREASURY"]
    assert got and not (got[0].note or "")


def test_안내_문구가_취득_처분을_부정한다():
    rule = DIRECTION_NOTES["TREASURY"]
    assert "직접 취득·처분이 아니라" in rule["note"]
    assert set(rule["markers"]) == {"신탁계약체결", "신탁계약해지"}


def test_코퍼스에서_신탁_비중이_유지된다():
    """1년 기준 이 안내가 붙는 비중 — 크게 달라지면 서술을 다시 재야 한다."""
    corpus = json.loads(
        (pathlib.Path(__file__).parent / "fixtures" / "corpus"
         / "signal_titles_365d.json").read_text(encoding="utf-8"))
    trust = total = 0
    for t in corpus["titles"]:
        nm, n = t["nm"], t["n"]
        for s, q in _qualified(nm):
            if s["key"] != "TREASURY" or q.tier != TIER_OBSERVED:
                continue
            total += n
            if q.note:
                trust += n
    assert total > 0
    ratio = trust / total
    assert 0.20 < ratio < 0.55, f"신탁 비중 {ratio:.1%} — 서술을 다시 재세요"


def test_구조화_경로는_따로_센다():
    """`TREASURY_TRUST`는 제목이 아니라 구조화 데이터에서 온다 — 제목 경로와 별개."""
    from dart_risk_mcp.core.signals import SIGNAL_TYPES

    trust = next(s for s in SIGNAL_TYPES if s["key"] == "TREASURY_TRUST")
    assert trust["keywords"] == [], (
        "TREASURY_TRUST에 키워드가 생겼다면 TREASURY와 겹치는지 다시 보세요"
    )
