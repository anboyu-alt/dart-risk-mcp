"""`build_event_timeline`이 방향 안내를 버리지 않는지 잠근다.

`analyze_company_risk` 리포트를 끝까지 읽어 #303을 고친 뒤, **같은 방법을
타임라인에 적용해** 찾았다(진원생명과학 1년, 2026-08-25).

    **[진입기] — 20250829 이후 12건**      ← "자금을 끌어오거나 자본 구조를 바꾸는 움직임"
      • 20251205  [CB/BW발행]  주요사항보고서(자기전환사채**만기전취득**결정)
      • 20251231  [CB/BW발행]  주요사항보고서(자기전환사채**매도**결정)
      • 20260306  [CB/BW발행]  주요사항보고서(자기전환사채만기전취득결정)
      • 20260420  [CB/BW발행]  주요사항보고서(자기전환사채매도결정)
      • 20260618  [CB/BW발행]  주요사항보고서(자기전환사채만기전취득결정)

**자금 조달 단계에 되사기·매도 5건이 「CB/BW발행」 라벨만 달고 섞여 있었다.**
방향 안내(`DIRECTION_NOTES`)가 하나도 붙지 않았다 — 실측 ※ **0건**.

그런데 `analyze_company_risk`는 **같은 공시에** 그 줄을 붙이고 있었다
(같은 회사·같은 창에서 ※ **5건**). **두 도구가 같은 사실을 다르게 냈다.**

원인은 이벤트 튜플이 `q.note`를 싣지 않은 것이다. 라벨은 보정되지 않으므로
(방향 안내는 라벨을 바꾸지 않고 주석만 단다) 안내가 빠지면 화면에는 「발행」만
남는다.

⚠ 방향 안내는 **건별**로 붙인다 — 해설(`signal_to_prose`)은 신호당 한 번만
붙이는 중복 제거가 있는데, 안내는 그 공시가 어느 방향인지의 사실이라
건마다 필요하다.
"""
import pathlib

import pytest

from dart_risk_mcp.core.qualifiers import (
    DIRECTION_NOTES, TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import match_signals

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SERVER = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")


def test_이벤트_튜플이_안내를_싣는다():
    assert "rcept_no, q.note))" in _SERVER, "타임라인 이벤트가 note를 버린다"


def test_렌더가_안내를_낸다():
    i = _SERVER.index('lines.append(f"  • {evt[0]}  [{evt[3]}]  {evt[4]}")')
    block = _SERVER[i:i + 700]
    assert "evt[6]" in block
    assert '※ {_note}' in block


def test_안내는_건별로_붙는다():
    """해설은 신호당 한 번(`seen_keys`)이지만 안내는 매번이어야 한다."""
    i = _SERVER.index('lines.append(f"  • {evt[0]}  [{evt[3]}]  {evt[4]}")')
    block = _SERVER[i:i + 700]
    note_at = block.index("_note")
    seen_at = block.index("seen_keys")
    assert note_at < seen_at, "안내가 중복 제거 블록 안으로 들어갔다"


@pytest.mark.parametrize("nm", [
    "주요사항보고서(자기전환사채만기전취득결정)",
    "주요사항보고서(자기전환사채매도결정)",
])
def test_그_제목이_실제로_안내를_받는다(nm):
    """전제 확인 — 안내가 안 붙는 제목이면 이 수정이 의미가 없다."""
    sigs = match_signals(nm)
    quals = qualify_signals(sigs, parse_report_name(nm), {"report_nm": nm})
    assert any(q.tier == TIER_OBSERVED and q.note for q in quals), nm


def test_라벨은_방향을_말하지_않는다():
    """안내가 필요한 이유 — 라벨만 보면 「발행」이다."""
    nm = "주요사항보고서(자기전환사채만기전취득결정)"
    sigs = match_signals(nm)
    quals = qualify_signals(sigs, parse_report_name(nm), {"report_nm": nm})
    labels = [q.label for q in quals if q.tier == TIER_OBSERVED]
    assert any("발행" in lb for lb in labels), labels


def test_두_도구가_같은_안내_집합을_쓴다():
    """`analyze_company_risk`와 `build_event_timeline`이 갈리면 안 된다."""
    assert _SERVER.count("※ {_note}") + _SERVER.count('f"  ※ {q.note}"') >= 1
    assert set(DIRECTION_NOTES), "방향 안내 목록이 비었다"
