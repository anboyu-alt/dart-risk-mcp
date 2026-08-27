"""`build_event_timeline`의 세 단계 배치가 **모든 신호를 덮는지** 잠근다.

`_PHASE_MAP.get(key, "심화기")`의 기본값은 조용하다 — 신호를 새로 만들고
여기 안 적으면 그 신호는 사라지지 않고 **심화기로 들어간다**. 사라지면
눈에 띄지만 잘못된 칸에 들어가면 안 띈다.

2026-08-28 실측: v1.6.0 이후 신설된 10종이 전부 빠져 있었고, 1년 코퍼스에서
그렇게 떨어진 것이 관찰 이벤트의 **36.9%**(6,228건) · **심화기의 64.2%**였다.
그래서 도구가 내는 「가장 많이 몰려 있는 단계는 심화기」라는 요약 문장은
회사에 대한 관측이 아니라 이 표의 누락을 읽고 있었다. 특히 상장폐지 절차
867건 · 관리종목 218건은 *"감사·수사·부실 등 위기가 드러나는 움직임"*
(탈출기)인데 *"경영권·지배구조가 흔들리는 움직임"*(심화기)으로 표기됐고,
그 둘을 합친 1,085건은 탈출기 전체(1,095건)와 맞먹는다.
"""
import json
import pathlib

from dart_risk_mcp.core.qualifiers import (
    TIER_OBSERVED,
    parse_report_name,
    qualify_signals,
)
from dart_risk_mcp.core.signals import SIGNAL_TYPES, match_signals
from dart_risk_mcp.server import _PHASE_MAP

_PHASES = ("진입기", "심화기", "탈출기")


def test_모든_신호에_단계가_있다():
    missing = [s["key"] for s in SIGNAL_TYPES if s["key"] not in _PHASE_MAP]
    assert not missing, (
        "이 신호들은 타임라인에서 기본값(심화기)으로 떨어진다 — 어느 단계인지 "
        "판단해 `_PHASE_MAP`에 적으세요(판단이 안 서면 그 이유를 주석으로): "
        + ", ".join(missing)
    )


def test_단계_이름이_셋뿐이다():
    bad = {k: v for k, v in _PHASE_MAP.items() if v not in _PHASES}
    assert not bad, f"렌더 루프가 세 이름만 훑는다 — 나머지는 출력되지 않는다: {bad}"


def test_없는_신호를_적어두지_않았다():
    keys = {s["key"] for s in SIGNAL_TYPES}
    stale = sorted(k for k in _PHASE_MAP if k not in keys)
    assert not stale, f"SIGNAL_TYPES에 없는 키가 남아 있다: {stale}"


def test_퇴출_절차는_탈출기다():
    """단계 설명이 *"위기가 드러나는 움직임"*이라고 적어 둔 것들.

    이 셋이 심화기로 돌아가면 요약 문장이 다시 누락을 읽는다.
    """
    for key in ("DELISTING_RISK", "WATCH_ISSUE", "DISTRESS_EVENT"):
        assert _PHASE_MAP.get(key) == "탈출기", (
            f"{key}는 상장 자격·존속이 걸린 사실이라 탈출기다 "
            f"(지금 {_PHASE_MAP.get(key)!r})"
        )


def test_기본값이_단계_분포를_지배하지_않는다():
    """1년 코퍼스로 실제 분포를 재서, 기본값 비중이 되살아나면 잡는다."""
    rows = json.loads(
        (pathlib.Path(__file__).resolve().parents[1]
         / "tests" / "fixtures" / "corpus" / "signal_titles_365d.json")
        .read_text(encoding="utf-8")
    )["titles"]

    total = fallback = 0
    for r in rows:
        title, n = r["nm"], r.get("n", 1)
        sigs = match_signals(title)
        if not sigs:
            continue
        quals = qualify_signals(sigs, parse_report_name(title), {})
        for s, q in zip(sigs, quals):
            if q.tier != TIER_OBSERVED:
                continue
            total += n
            if s["key"] not in _PHASE_MAP:
                fallback += n

    assert total > 10_000, f"코퍼스에서 {total}건만 셌다 — 검사가 헛돈다"
    assert fallback == 0, (
        f"관찰 이벤트 {total:,}건 중 {fallback:,}건({fallback / total * 100:.1f}%)이 "
        "단계 없이 기본값으로 떨어진다"
    )
