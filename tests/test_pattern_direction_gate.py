"""방향이 뒤집힌 이벤트가 복합 패턴의 근거로 서지 않는지 잠근다.

사용자 제보(2026-08-25) — *"SK하이닉스에 부채악순환·무자본M&A가 잡히는데
이런 게 잡히면 안 된다"*.

「부채 악순환」(CRITICAL)의 근거가 이랬다:

    1.3  Exchange Bond (EB) **Issuance** to Related Parties
         ← 실제 공시: 「자기교환사채**만기전취득**결정」(2026-04-28)
    2.6  Treasury Stock Buyback + Reissue
         ← 「주요사항보고서(자기주식취득결정)」

**사채를 갚은 건이 부채가 늘어나는 패턴의 근거로 세어졌다.** 방향이 정반대다.

한정층은 이미 알고 있었다 — `DIRECTION_NOTES["EB"]`가 그 공시에
"발행이 아니라 사채 취득·매도·소각 건입니다"를 붙인다. 자본 이벤트 집계도
`CHURN_NON_DILUTIVE_MARKS`로 같은 판단을 한다(v1.20.10). **패턴 층만
그 판단을 버리고 있었다** — 오늘 세 번째로 나온 같은 모양의 결함이다.

`DIRECTION_NOTES` 7종 전부에 같은 논리가 성립한다:

    CB_BW·EB   되사기·소각      ↔ 1.1/1.3/1.5는 **발행**을 요구
    RCPS       소각            ↔ 1.4는 **발행**
    TREASURY   신탁 체결·해지    ↔ 2.6은 **직접 취득·재매각**
    RELATED_PARTY  회사가 준 출자 ↔ 4.2는 회사로 흘러드는 거래
    DEBT_RESTR 회사가 해 준 면제  ↔ 8.2는 회사가 받는 출자전환
    GOING_CONCERN  회생 **종결**  ↔ 8.4는 개시·폐지(부실 진입)

⚠ 신호를 지우지 않는다 — 관찰 목록·타임라인·집계에 그대로 남고 **패턴
근거로만** 서지 못한다. 방향 안내는 사용자에게 계속 보인다.
"""
import pathlib

import pytest

from dart_risk_mcp.core.qualifiers import (
    DIRECTION_NOTES, TIER_OBSERVED, TIER_PROCEDURAL,
    parse_report_name, qualify_signals, supports_pattern,
)
from dart_risk_mcp.core.signals import SIGNAL_KEY_TO_TAXONOMY, match_signals
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _qual(nm):
    sigs = match_signals(nm)
    return list(zip(sigs, qualify_signals(sigs, parse_report_name(nm),
                                          {"report_nm": nm})))


def test_되사기는_패턴_근거가_아니다():
    """SK하이닉스 실물 제목."""
    rows = _qual("자기교환사채만기전취득결정")
    assert rows, "신호가 안 붙는다"
    for m, q in rows:
        assert q.tier == TIER_OBSERVED, "관찰에서 빼는 것이 아니다"
        assert q.note, "방향 안내가 없다 — 이 수정의 전제가 무너진다"
        ev = {"key": m["key"], "tier": q.tier, "note": q.note,
              "is_amendment": False}
        assert not supports_pattern(ev)


def test_발행은_그대로_패턴_근거다():
    """반대로 넓게 막으면 진짜 패턴을 잃는다."""
    rows = _qual("주요사항보고서(교환사채권발행결정)")
    assert rows
    for m, q in rows:
        ev = {"key": m["key"], "tier": q.tier, "note": q.note,
              "is_amendment": False}
        assert supports_pattern(ev), f"{m['key']}가 근거에서 빠졌다"


@pytest.mark.parametrize("key", sorted(DIRECTION_NOTES))
def test_방향_안내_신호는_패턴_taxonomy를_소유한다(key):
    """소유 taxonomy가 없으면 이 게이트는 그 신호에 무의미하다 — 근거 확인."""
    assert SIGNAL_KEY_TO_TAXONOMY.get(key), key


def test_강등된_이벤트도_당연히_근거가_아니다():
    ev = {"key": "EB", "tier": TIER_PROCEDURAL, "note": "", "is_amendment": False}
    assert not supports_pattern(ev)


def test_정정공시도_근거가_아니다():
    ev = {"key": "EB", "tier": TIER_OBSERVED, "note": "", "is_amendment": True}
    assert not supports_pattern(ev)


def test_빈_입력에_예외를_던지지_않는다():
    for bad in (None, "", 0, []):
        assert supports_pattern(bad) is False


def test_debt_spiral이_되사기만으로_서지_않는다():
    """SK하이닉스 재현 — 되사기 1건 + 자사주 1건으로 카드가 떴었다."""
    from dart_risk_mcp.core.taxonomy import find_pattern_overlaps

    events = [("자기교환사채만기전취득결정", "20260428"),
              ("주요사항보고서(자기주식취득결정)", "20260819")]
    tax, dates = set(), {}
    for nm, dt in events:
        for m, q in _qual(nm):
            ev = {"key": m["key"], "tier": q.tier, "note": q.note,
                  "is_amendment": False}
            if not supports_pattern(ev):
                continue
            for t in SIGNAL_KEY_TO_TAXONOMY.get(m["key"], []):
                tax.add(t)
                dates.setdefault(t, []).append(dt)
    names = {o["name"] for o in
             find_pattern_overlaps(sorted(tax), min_overlap=2, taxonomy_dates=dates)}
    assert "debt_spiral" not in names, f"부채 악순환이 아직 뜬다: {names}"


def test_서버가_두_도구_모두에_배선했다():
    src = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    assert src.count("_supports_pattern(") >= 3, "배선이 빠진 호출부가 있다"
    assert "supports_pattern as _supports_pattern" in src


def test_뷰어도_같은_규칙을_쓴다():
    html = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
    assert "const patSigs = (e) =>" in html
    assert "patSigs(e).flatMap((s) => s.taxonomies" in html
    assert "for (const sg of patSigs(e))" in html
    assert "obs(e).flatMap((s) => s.taxonomies || [])" not in html, (
        "뷰어가 아직 원시 관찰 신호로 taxonomy를 모은다"
    )


def test_게이트가_taxonomy를_전멸시키지_않는다():
    """`debt_spiral`의 5개 taxonomy는 **전부** 방향 안내를 가질 수 있는 신호
    소유다(RCPS·CB_BW·EB·TREASURY·DEBT_RESTR). 그래서 "안내가 붙을 수 있다"가
    "항상 붙는다"가 되면 이 패턴은 영영 못 뜬다 — CLAUDE.md v1.20.2가 기록한
    '요구 신호가 관찰 불가라 패턴이 조용히 죽는' 실패 모드다.

    1년 코퍼스로 **각 신호마다 안내 없는(정방향) 제목이 실제로 있는지** 확인해
    그 실패 모드에 빠지지 않았음을 고정한다.
    """
    import collections
    import json

    corpus = json.loads((_ROOT / "tests" / "fixtures" / "corpus"
                         / "signal_titles_365d.json").read_text(encoding="utf-8"))
    clean = collections.Counter()
    for t in corpus["titles"]:
        nm, n = t["nm"], t.get("n", 1)
        for m, q in _qual(nm):
            if m["key"] not in DIRECTION_NOTES or q.tier != TIER_OBSERVED:
                continue
            if not q.note:
                clean[m["key"]] += n
    missing = sorted(set(DIRECTION_NOTES) - set(clean))
    assert not missing, (
        f"정방향 제목이 1년 코퍼스에 하나도 없는 신호: {missing} — "
        f"이 신호가 소유한 taxonomy는 패턴에서 도달 불가가 된다"
    )


def test_debt_spiral의_모든_요구_신호가_도달_가능하다():
    """이 패턴이 가장 위험하다 — 5개 전부 방향 안내 대상 신호 소유다."""
    import collections
    import json

    corpus = json.loads((_ROOT / "tests" / "fixtures" / "corpus"
                         / "signal_titles_365d.json").read_text(encoding="utf-8"))
    reach = collections.Counter()
    for t in corpus["titles"]:
        nm, n = t["nm"], t.get("n", 1)
        for m, q in _qual(nm):
            if q.tier != TIER_OBSERVED or q.note:
                continue
            for tid in SIGNAL_KEY_TO_TAXONOMY.get(m["key"], []):
                reach[tid] += n
    seq = CROSS_SIGNAL_PATTERNS["debt_spiral"]["signal_sequence"]
    dead = [t for t in seq if not reach[t]]
    assert len(dead) < len(seq), f"debt_spiral의 요구 신호가 전멸했다: {dead}"
