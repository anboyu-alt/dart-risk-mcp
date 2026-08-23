"""해설(`SIGNAL_PROSE`)이 **실제 발화 제목**과 어긋나지 않는지 코퍼스로 잠근다.

v1.16.0이 이 대조로 해설 4종의 오류를 찾았고 그중 둘(`INSOLVENCY`·
`GOING_CONCERN`)은 **서로 뒤바뀌어** 있었다. 그 뒤로 키워드가 여러 번 바뀌었고
(ASSET_TRANSFER·RELATED_PARTY·EARNINGS_SHOCK·DELISTING_RISK·WATCH_ISSUE·
AUDIT·THEME_STOCK), 2026-08-24 재대조에서 다섯 종이 더 나왔다.

| 신호 | 무엇이 어긋났나 |
|---|---|
| `DEBT_RESTR` | 해설은 워크아웃·출자전환인데 발화 **21/21이 채무면제** |
| `3PCA` | 라벨은 「배정방식 미상」인데 해설은 "제3자 배정"이라 단정 |
| `REVERSE_SPLIT` | 해설은 액면병합만 설명, 발화의 **45%가 감자** |
| `CB_BW`·`EB`·`RCPS` | 해설은 "발행", 방향 안내는 "발행이 아니라 되사기·소각" |
| `EQUITY_SPLIT` | **해설 자체가 없었다**(46건이 설명 없이 나갔다) |

여기서 거는 것은 문장 자체가 아니라 **깨지기 쉬운 성질**이다 — 해설이
단정하는 사건이 실제 발화의 다수와 맞는가, 해설 있는 신호가 빠지지 않는가.
"""
import json
import pathlib
from collections import Counter

import pytest

from dart_risk_mcp.core.explain import SIGNAL_PROSE
from dart_risk_mcp.core.qualifiers import (
    TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import NON_TITLE_SIGNALS, SIGNAL_TYPES, match_signals

_CORPUS = (pathlib.Path(__file__).parent / "fixtures" / "corpus"
           / "signal_titles_365d.json")
_ROWS = [(t["nm"], t["n"]) for t in
         json.loads(_CORPUS.read_text(encoding="utf-8"))["titles"]]


def _titles_by_key():
    out: dict[str, Counter] = {}
    for nm, n in _ROWS:
        sigs = match_signals(nm)
        for s, q in zip(sigs, qualify_signals(sigs, parse_report_name(nm), {})):
            if q.tier == TIER_OBSERVED:
                out.setdefault(s["key"], Counter())[nm] += n
    return out


_BY_KEY = _titles_by_key()
_LIVE = [s["key"] for s in SIGNAL_TYPES
         if s["keywords"] and s["key"] not in NON_TITLE_SIGNALS]


@pytest.mark.parametrize("key", _LIVE)
def test_발화하는_신호에는_해설이_있다(key):
    """설명 없이 나가는 신호가 없어야 한다 — EQUITY_SPLIT이 그랬다."""
    if not _BY_KEY.get(key):
        pytest.skip("이 코퍼스에서 관찰되지 않음")
    assert SIGNAL_PROSE.get(key, "").strip(), f"{key}: 해설이 비어 있다"


# 해설이 단정하면 안 되는 신호 — 제목이 그 방향/방식을 확정해 주지 않는다.
# (단어, 그 단어가 맞는 제목의 비율 상한)
MUST_NOT_ASSERT = {
    "CB_BW": "발행입니다",
    "EB": "발행입니다",
    "RCPS": "발행입니다",
    "3PCA": "제3자 배정 유상증자 공시입니다",
}


@pytest.mark.parametrize("key,phrase", sorted(MUST_NOT_ASSERT.items()))
def test_확정할_수_없는_것을_단정하지_않는다(key, phrase):
    """방향 안내·라벨 보정이 있는데 해설만 단정하면 한 화면이 모순된다."""
    assert not SIGNAL_PROSE.get(key, "").startswith(phrase.split()[0] + " "), key
    assert phrase not in SIGNAL_PROSE.get(key, ""), f"{key}: '{phrase}'로 단정한다"


def test_채무조정_해설이_채무면제를_가리킨다():
    """1년 발화 21건이 전부 채무면제다 — 워크아웃·출자전환은 0건이었다."""
    prose = SIGNAL_PROSE["DEBT_RESTR"]
    assert "채무면제" in prose or "면제" in prose
    for wrong in ("워크아웃", "출자전환"):
        assert wrong not in prose, f"실측 0건인 '{wrong}'을 설명하고 있다"
    titles = _BY_KEY.get("DEBT_RESTR") or Counter()
    if titles:
        assert all("채무면제" in t for t in titles), \
            "채무면제 아닌 제목이 생겼다 — 해설을 다시 확인하세요"


def test_감자와_병합을_둘_다_설명한다():
    prose = SIGNAL_PROSE["REVERSE_SPLIT"]
    assert "감자" in prose and "병합" in prose
    titles = _BY_KEY.get("REVERSE_SPLIT") or Counter()
    n_gamja = sum(n for t, n in titles.items() if "감자" in t or "자본감소" in t)
    assert n_gamja > 0, "감자가 하나도 없으면 서술을 다시 재세요"


def test_유상증자_해설이_배정방식을_단정하지_않는다():
    """라벨(`LABEL_OVERRIDES`)이 「배정방식 미상」으로 보정하는 것과 맞춘다."""
    prose = SIGNAL_PROSE["3PCA"]
    assert "확정되지 않습니다" in prose or "미상" in prose


def test_해설에_점수_등급_어휘가_없다():
    """v0.8.5 원칙 — 해설은 사용자 화면에 그대로 나간다."""
    banned = ("매우위험", "고위험", "위험도", "점수", "등급", "HIGH", "CRITICAL", "MEDIUM")
    for key, prose in SIGNAL_PROSE.items():
        for w in banned:
            assert w not in prose, f"{key}: 금칙어 '{w}'"
