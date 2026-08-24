"""자본 이벤트 집중 판정의 **희석성 계수**가 부풀지 않는지 잠근다.

사용자 질문에서 시작했다 — *"SK하이닉스는 역대급 시총을 기록하는 건실한
회사인데 신호가 잡힌다"*. 리포트의 헤드라인이 「자본 이벤트 과다 반복」이었다.

파 보니 **희석성 카운트가 분류 오류로 부풀어** 있었다.

| 회사 | 희석으로 세어진 3건 | 실제 희석 |
|---|---|---|
| SK하이닉스 | 유상증자결정 + **유상증자…발행결과**(같은 건) + EB **만기전취득** | **1** |
| 한탑 | 유상증자결정 + 주식병합 + CB **만기전취득** | **1** |

두 가지를 고쳤다.
  ① **결과보고 제외** — 「…발행결과」·「…결과보고서」는 이미 센 결정의 사후
     보고다. 그대로 세면 같은 증자가 두 번 잡힌다.
  ② **되사기·소각은 희석이 아니다** — 회사가 사채를 되사면 주식 수가 늘지
     않는다. 자본 구조를 건드린 사건이므로 **이벤트로는 세되** 희석성
     카운트에서만 뺀다.

실측(대형주 12곳 · 부실·소형 6곳): 대형주 발화 **1곳 → 0곳**,
부실·소형 5곳 → 4곳. 빠진 한탑은 실제 희석이 1건뿐이라 **빠지는 것이 맞다**.

⚠ 임계를 맞추려 조정한 것이 아니다 — 되사기가 희석이 아니라는 것은 뜻의
문제이고, 어느 회사가 걸리는지는 그 결과다.
"""
import inspect

import pytest

from dart_risk_mcp.core.dart_client import (
    CHURN_NON_DILUTIVE_MARKS, CHURN_RESULT_MARKS, DILUTIVE_CAPITAL_EVENTS,
    detect_capital_churn,
)
from dart_risk_mcp.core.qualifiers import DIRECTION_NOTES


def _ev(date, key, nm):
    return {"key": key, "label": key, "score": 5, "report_nm": nm,
            "rcept_dt": date, "rcept_no": date + "000001", "is_amendment": False}


def test_되사기는_희석으로_세지_않는다():
    """SK하이닉스형 — 증자 1건 + EB 되사기 1건 + 자사주 다수."""
    events = [
        _ev("20260624", "3PCA", "주요사항보고서(유상증자결정)"),
        _ev("20260428", "EB", "자기교환사채만기전취득결정"),
    ] + [_ev(f"2026{m:02d}01", "TREASURY", "주요사항보고서(자기주식처분결정)")
         for m in (1, 3, 4, 5, 8)]
    r = detect_capital_churn(events, 1)
    assert r["max_dilutive_12m"] == 1, "되사기가 희석으로 세어졌다"
    assert "CAPITAL_CHURN" not in r["flags"]


def test_발행_결과보고는_결정과_따로_세지_않는다():
    events = [
        _ev("20260624", "3PCA", "주요사항보고서(유상증자결정)"),
        _ev("20260715", "3PCA", "유상증자또는주식관련사채등의발행결과(자율공시)"),
    ]
    r = detect_capital_churn(events, 1)
    assert r["max_dilutive_12m"] == 1, "같은 증자가 두 번 세어졌다"


def test_진짜_증자는_그대로_센다():
    """반대 방향으로 넓게 빼면 진짜 사례를 잃는다."""
    events = [_ev(f"2026{m:02d}01", "3PCA", "주요사항보고서(유상증자결정)")
              for m in (1, 4, 7)]
    r = detect_capital_churn(events, 1)
    assert r["max_dilutive_12m"] == 3
    assert "CAPITAL_CHURN" in r["flags"]


def test_되사기도_자본_이벤트로는_센다():
    """희석이 아닐 뿐, 자본 구조를 건드린 사건이다."""
    events = [_ev("20260428", "EB", "자기교환사채만기전취득결정")]
    r = detect_capital_churn(events, 1)
    assert r["total_events"] == 1
    assert r["max_dilutive_12m"] == 0
    assert r["max_non_dilutive_12m"] == 1


def test_비희석_두_건과_희석_두_건이_겹치면_발화한다():
    """규칙 (B)는 그대로다 — 이번 수정이 규칙을 바꾸지는 않았다."""
    events = [
        _ev("20260101", "3PCA", "주요사항보고서(유상증자결정)"),
        _ev("20260401", "CB_BW", "주요사항보고서(전환사채권발행결정)"),
        _ev("20260501", "TREASURY", "주요사항보고서(자기주식취득결정)"),
        _ev("20260601", "TREASURY", "주요사항보고서(자기주식처분결정)"),
    ]
    r = detect_capital_churn(events, 1)
    assert (r["max_dilutive_12m"], r["max_non_dilutive_12m"]) == (2, 2)
    assert "CAPITAL_CHURN" in r["flags"]


def test_마커가_방향_안내와_같은_뜻이다():
    """`DIRECTION_NOTES`의 되사기 마커와 어긋나면 두 화면이 갈린다."""
    note_marks = set()
    for key in ("CB_BW", "EB", "RCPS"):
        note_marks |= set(DIRECTION_NOTES[key]["markers"])
    assert note_marks <= set(CHURN_NON_DILUTIVE_MARKS), (
        f"방향 안내에만 있는 마커: {note_marks - set(CHURN_NON_DILUTIVE_MARKS)}"
    )


@pytest.mark.parametrize("mark", CHURN_RESULT_MARKS)
def test_결과보고_마커가_실제_표기다(mark):
    import json
    import pathlib

    corpus = json.loads(
        (pathlib.Path(__file__).parent / "fixtures" / "corpus"
         / "signal_titles_365d.json").read_text(encoding="utf-8"))
    hit = [t for t in corpus["titles"] if mark in t["nm"].replace(" ", "")]
    assert hit, f"'{mark}'가 1년 코퍼스에 없다 — 표기를 다시 확인하세요"


def test_설명이_실제_규칙을_말한다():
    """옛 문구는 '자본 구조 변경 3건 이상'이라 적어 자사주만 많아도 걸리는
    것처럼 읽혔다. 삼성전자는 자사주 10건인데 발화하지 않는다."""
    from dart_risk_mcp.core.explain import FLAG_PROSE

    body = FLAG_PROSE["CAPITAL_CHURN"]["body"]
    assert "희석성" in body
    assert "자사주만 자주 사고파는 것으로는" in body
    assert "정상적인 기업은 자본 구조를 자주 건드리지 않습니다" not in body


def test_미발화_안내가_희석성_기준을_말한다():
    """전체 카운트를 인용해 '3건 기준 미달'이라 적으면 자기모순이 된다."""
    import dart_risk_mcp.server as srv

    src = inspect.getsource(srv)
    assert "'3건 이상 몰림' 기준(자본 이벤트 집중 판정)에는 미치지 못했습니다" not in src
    assert "희석성 3건 이상이거나" in src
