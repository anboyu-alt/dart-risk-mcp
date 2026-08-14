# -*- coding: utf-8 -*-
"""server.py 배선 검증 — API 호출 없이 오프라인으로 확인한다.

이 테스트가 증명하는 것:
- analyze_company_risk/build_event_timeline의 신호 루프가 실제로 하는 일
  (parse_report_name → match_signals → qualify_signals → tier 분리)을
  합성 /api/list.json 형태 행에 대해 그대로 재현했을 때, observed/procedural
  분리와 pick_headline이 실측 공시 제목 기준으로 기대한 대로 동작한다는 것.
- server.py 소스에 그 배선이 실제로 존재한다는 것(문자열 검사).

이 테스트가 증명하지 못하는 것:
- analyze_company_risk/build_event_timeline을 실제로 호출했을 때 이 로직이
  똑같이 실행된다는 것(그건 DART_API_KEY가 있어야 하는 골든 재생성의 몫이다).
  아래 test_server_source_wires_observed_events가 하는 일은 "그 변수 이름이
  그 위치에 쓰였다"는 텍스트 대조이지, 런타임 동등성의 증명이 아니다.
"""
from pathlib import Path

from dart_risk_mcp.core import (
    SIGNAL_TYPES,
    match_signals,
)
from dart_risk_mcp.core.qualifiers import (
    Qualified,
    TIER_OBSERVED,
    parse_report_name,
    pick_headline,
    qualify_signals,
)

_SERVER_PY = Path(__file__).resolve().parent.parent / "dart_risk_mcp" / "server.py"


def _row(report_nm, flr_nm, corp_name="테스트기업", rcept_dt="20260101", rcept_no="000001"):
    """/api/list.json 형태의 합성 공시 행."""
    return {
        "corp_code": "00000001",
        "corp_name": corp_name,
        "stock_code": "000000",
        "corp_cls": "Y",
        "report_nm": report_nm,
        "rcept_no": rcept_no,
        "flr_nm": flr_nm,
        "rcept_dt": rcept_dt,
        "rm": "",
    }


def _build_signal_events(rows):
    """analyze_company_risk의 712행대 루프를 그대로 재현한다.

    (is_amendment/false-amendment 복구 분기는 합성 케이스에 정정 태그가
    없어 실질적으로 타지 않지만, 배선과 동일한 형태를 유지하기 위해 둔다.)
    """
    events = []
    for d in rows:
        report_nm = d.get("report_nm", "")
        parsed = parse_report_name(report_nm)
        matched = match_signals(report_nm)
        qualified = qualify_signals(matched, parsed, d)
        for sig, q in zip(matched, qualified):
            events.append({
                "key": sig["key"],
                "label": q.label,
                "report_nm": report_nm,
                "rcept_dt": d.get("rcept_dt", ""),
                "rcept_no": d.get("rcept_no", ""),
                "is_amendment": False,
                "tier": q.tier,
                "reason": q.reason,
                "note": q.note,
            })
    return events


def _split(events):
    observed = [e for e in events if e.get("tier", TIER_OBSERVED) == TIER_OBSERVED]
    procedural = [e for e in events if e.get("tier", TIER_OBSERVED) != TIER_OBSERVED]
    return observed, procedural


def _headline(observed_events):
    order = [s["key"] for s in sorted(SIGNAL_TYPES, key=lambda x: -x["score"])]
    cands = [
        Qualified(key=e["key"], label=e["label"], tier=TIER_OBSERVED, reason="", note="")
        for e in observed_events if not e["is_amendment"]
    ]
    return pick_headline(cands, order)


# ── 삼성전자류: 자사주 결과보고 + 대량보유상황보고(제3자) + 자사주 결정(양면) ──

SAMSUNG_ROWS = (
    [_row("자기주식취득결과보고서", "삼성전자", corp_name="삼성전자")] * 2
    + [_row("자기주식처분결과보고서", "삼성전자", corp_name="삼성전자")]
    + [_row("주식등의대량보유상황보고서(일반)", "삼성물산", corp_name="삼성전자")] * 3
    + [_row("주요사항보고서(자기주식취득결정)", "삼성전자", corp_name="삼성전자")]
    + [_row("주요사항보고서(자기주식처분결정)", "삼성전자", corp_name="삼성전자")]
)

# ── 아틀라스링크류: 최대주주변경·자금유출성거래는 남고, 대량보유상황보고만 빠진다 ──

ATLAS_ROWS = (
    [_row("최대주주변경", "아틀라스링크", corp_name="아틀라스링크")]
    + [_row("최대주주변경을수반하는주식양수도계약체결", "아틀라스링크", corp_name="아틀라스링크")]
    + [_row("금전대여결정", "아틀라스링크", corp_name="아틀라스링크")]
    + [_row("타인에대한채무보증결정(자율공시)", "아틀라스링크", corp_name="아틀라스링크")]
    + [_row("주요사항보고서(유형자산양수결정)", "아틀라스링크", corp_name="아틀라스링크")]
    + [_row("주식병합결정", "아틀라스링크", corp_name="아틀라스링크")]
    + [_row("주식등의대량보유상황보고서(일반)", "국민연금공단", corp_name="아틀라스링크")] * 3
)


def test_samsung_like_set_counts():
    assert len(SAMSUNG_ROWS) == 8
    events = _build_signal_events(SAMSUNG_ROWS)
    observed, procedural = _split(events)
    # 결과보고서 3건(R2) + 대량보유상황보고 3건(R1) = 6건 procedural.
    # 자기주식취득/처분결정 2건은 회사 자신이 낸 사건 공시라 observed.
    assert len(procedural) == 6
    assert len(observed) == 2
    assert {e["key"] for e in observed} == {"TREASURY"}


def test_samsung_like_set_has_no_headline():
    events = _build_signal_events(SAMSUNG_ROWS)
    observed, _ = _split(events)
    assert _headline(observed) is None


def test_samsung_procedural_shareholder_events_do_not_leak_into_observed_keys():
    """대량보유상황보고 3건은 SHAREHOLDER 키로 매칭되지만 전부 procedural.

    패턴 매칭·집계에 쓰이는 '관찰된 신호 키' 집합(server.py의 sig_keys와
    동일한 산식)에는 SHAREHOLDER가 전혀 등장하면 안 된다 — 원본
    signal_events에는 SHAREHOLDER가 3건 존재하지만 전부 procedural이기
    때문이다.
    """
    events = _build_signal_events(SAMSUNG_ROWS)
    observed, procedural = _split(events)
    assert any(e["key"] == "SHAREHOLDER" for e in procedural)

    # server.py:865와 동일한 산식 — observed_events만 사용해야 한다.
    sig_keys = {e["key"] for e in observed if not e["is_amendment"]}
    assert "SHAREHOLDER" not in sig_keys

    # 대조군: signal_events(분리 전 원본) 기준으로 같은 산식을 돌리면
    # SHAREHOLDER가 섞여 들어온다 — observed_events로 바꾼 것이 실제로
    # 결과를 바꾸는 변경이었음을 보여준다.
    raw_sig_keys = {e["key"] for e in events if not e["is_amendment"]}
    assert "SHAREHOLDER" in raw_sig_keys


def test_atlas_like_set_counts():
    assert len(ATLAS_ROWS) == 9
    events = _build_signal_events(ATLAS_ROWS)
    observed, procedural = _split(events)
    # '최대주주변경을수반하는주식양수도계약체결'은 SHAREHOLDER("최대주주변경")와
    # MGMT("주식양수도") 두 신호에 동시 매칭돼 신호 이벤트 수(10)가 행 수(9)보다
    # 하나 많다 — match_signals의 실제 동작이며 한정층이 만든 차이가 아니다.
    assert len(events) == 10
    assert len(observed) == 7
    assert len(procedural) == 3
    assert all(e["key"] == "SHAREHOLDER" for e in procedural)


def test_atlas_like_set_survives_as_observed():
    events = _build_signal_events(ATLAS_ROWS)
    observed, _ = _split(events)
    observed_keys = {e["key"] for e in observed}
    # 실제 사건 신호(최대주주변경·경영권변동·자금유출성거래·자본구조 변경)는
    # 전부 남는다.
    assert observed_keys == {"SHAREHOLDER", "MGMT", "FUND_OUTFLOW", "REVERSE_SPLIT"}


def test_atlas_like_set_has_headline():
    events = _build_signal_events(ATLAS_ROWS)
    observed, _ = _split(events)
    head = _headline(observed)
    assert head is not None
    # FUND_OUTFLOW는 AMBIGUOUS_SIGNAL_KEYS라 헤드라인 후보가 될 수 없다.
    assert head.key != "FUND_OUTFLOW"
    assert head.key in ("SHAREHOLDER", "REVERSE_SPLIT")


# ── 소스 배선 검증 — 텍스트 대조. 런타임 동등성은 증명하지 않는다(위 docstring 참고) ──


def test_server_source_wires_observed_events():
    src = _SERVER_PY.read_text(encoding="utf-8")

    # 두 도구 모두 qualify_signals로 신호를 한정한다.
    assert src.count("qualify_signals(matched, parsed, d)") == 2

    # analyze_company_risk: observed/procedural 분리가 존재하고, 집계·헤드라인·
    # 절차 섹션이 signal_events가 아니라 observed_events/procedural_events를 쓴다.
    assert "observed_events = [" in src
    assert "procedural_events = [" in src
    assert "if not observed_events:" in src
    assert 'sig_keys = list({e["key"] for e in observed_events' in src
    assert "_head = pick_headline(_cands, _order)" in src
    assert "for e in observed_events if not e[\"is_amendment\"]" in src
    assert 'f"━━ 관찰된 신호 ({len(observed_events)}건) ━━"' in src
    assert "if procedural_events:" in src

    # build_event_timeline: tier가 TIER_OBSERVED가 아닌 신호는 건너뛴다.
    assert "if q.tier != TIER_OBSERVED:" in src
