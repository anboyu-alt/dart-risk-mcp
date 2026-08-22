# -*- coding: utf-8 -*-
"""server.py 배선 검증 — API 호출 없이 오프라인으로 확인한다.

이 테스트가 증명하는 것:
- analyze_company_risk/build_event_timeline의 신호 루프가 실제로 하는 일
  (parse_report_name → match_signals → qualify_signals → tier 분리)을
  합성 /api/list.json 형태 행에 대해 그대로 재현했을 때, observed/procedural
  분리와 pick_headline이 실측 공시 제목 기준으로 기대한 대로 동작한다는 것.
- server.py 소스에 그 배선이 실제로 존재한다는 것(문자열 검사).
- (fix round 1) 리뷰에서 확인된 4개 결함 각각이 재현·수정됐다는 것:
  1) note가 관찰된 신호 목록에 실제로 렌더링된다.
  2) observed 0건이어도 조기 반환하지 않고 절차·사후 보고 목록 + 지정된
     문구가 나온다.
  3) `_outflow_review_candidates`에 procedural로 강등된 FUND_OUTFLOW가
     섞이면(원본 signal_events) 후보에 남고, observed_events만 넘기면 빠진다.
  4) `detect_capital_churn`에 procedural 자본 이벤트가 섞이면(원본
     signal_events) CAPITAL_CHURN이 오발화하고, observed_events만 넘기면
     발화하지 않는다.
- (fix round 2) round 1 수정 자체에서 나온 결함 2개:
  A) note는 tier와 무관하게 렌더링돼야 하는데 실제로는 관찰된 신호 루프
     안에만 있었다 — procedural 루프에도 동일하게 렌더링된다.
  B) observed_events가 비어 있을 때 "관찰된 신호 (0건)" 빈 헤더가 뜨지
     않는다(헤더+루프 전체가 `if observed_events:`로 감싸짐).

이 테스트가 증명하지 못하는 것:
- analyze_company_risk/build_event_timeline을 실제로 호출했을 때 이 로직이
  똑같이 실행된다는 것(그건 DART_API_KEY가 있어야 하는 골든 재생성의 몫이다).
  아래 test_server_source_wires_observed_events가 하는 일은 "그 변수 이름이
  그 위치에 쓰였다"는 텍스트 대조이지, 런타임 동등성의 증명이 아니다.
"""
import unittest
from pathlib import Path
from unittest.mock import patch

from dart_risk_mcp.core import (
    SIGNAL_TYPES,
    detect_capital_churn,
    find_pattern_match,
    is_amendment_disclosure,
    match_signals,
)
from dart_risk_mcp.core.signals import (
    SIGNAL_KEY_TO_TAXONOMY,
    strip_amendment_prefix,
)
from dart_risk_mcp.core.qualifiers import (
    Qualified,
    TIER_OBSERVED,
    TIER_PROCEDURAL,
    is_false_amendment,
    parse_report_name,
    pick_headline,
    qualify_signals,
)
from dart_risk_mcp.server import _outflow_review_candidates

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

    false-amendment 복구 분기까지 그대로 옮긴다 — 복구가 발화하면
    is_amendment를 내린다(리뷰 C2). 이 플래그를 True로 남기면 신호를
    되살려 놓고도 non_amend_events·sig_keys·헤드라인에서 다시 빠진다.
    """
    events = []
    for d in rows:
        report_nm = d.get("report_nm", "")
        parsed = parse_report_name(report_nm)
        is_amendment = is_amendment_disclosure(report_nm)
        matched = match_signals(report_nm)
        if not matched and is_amendment and is_false_amendment(parsed):
            matched = match_signals(strip_amendment_prefix(report_nm))
            is_amendment = False
        qualified = qualify_signals(matched, parsed, d)
        for sig, q in zip(matched, qualified):
            events.append({
                "key": sig["key"],
                "label": q.label,
                "report_nm": report_nm,
                "rcept_dt": d.get("rcept_dt", ""),
                "rcept_no": d.get("rcept_no", ""),
                "is_amendment": is_amendment,
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
    assert 'sig_keys = list({e["key"] for e in observed_events' in src
    assert "_head = pick_headline(_cands, _order)" in src
    assert "for e in observed_events if not e[\"is_amendment\"]" in src
    assert 'f"━━ 관찰된 신호 ({len(observed_events)}건) ━━"' in src
    assert "if procedural_events:" in src

    # build_event_timeline: tier가 TIER_OBSERVED가 아닌 신호는 건너뛴다.
    assert "if q.tier != TIER_OBSERVED:" in src


def test_server_source_removes_dead_early_return():
    """fix round 1, finding 2 — observed 0건 조기 반환이 삭제됐다.

    조기 반환이 남아 있으면 절차·사후 보고 절과 지정 문구("이 기간 공시에서는
    관찰 신호가 없습니다"/"공시 외 지표(재무·감사의견·연속적자)는 아래 블록에서
    확인하세요")로 도달하는 elif/else 분기가 죽은 코드로 남는다.
    """
    src = _SERVER_PY.read_text(encoding="utf-8")
    assert "탐지된 의심 공시가 없습니다" not in src
    assert "이 기간 공시에서는 관찰 신호가 없습니다." in src
    assert "공시 외 지표(재무·감사의견·연속적자)는 아래 블록에서 확인하세요." in src

    # detect_capital_churn·_confirm_outflow_counterparties는 이제 observed_events를 받는다.
    assert "detect_capital_churn(observed_events, lookback_years=1)" in src
    assert (
        "outflow_confirmations = _confirm_outflow_counterparties(\n"
        "            observed_events, disclosures, corp_code, _decisions_by_rcept\n"
        "        )"
    ) in src

    # note 렌더 라인은 observed 루프와 procedural 루프 양쪽에 있어야 한다
    # (fix round 2, finding A — round 1은 observed 루프에만 넣어 "tier와
    # 무관하게"라는 지시를 어겼다).
    assert src.count('lines.append(f"  ※ {e[\'note\']}")') == 2

    # observed_events가 비면 "관찰된 신호" 헤더·루프 자체를 건너뛴다
    # (fix round 2, finding B).
    assert "if observed_events:" in src


# ── fix round 1, finding 1: note가 관찰된 신호 목록에 실제로 렌더링되는가 ──


def test_cb_direction_note_attached_to_observed_signal():
    """제이스코홀딩스 실측: 자기전환사채매도결정은 CB_BW observed + 방향 주석."""
    row = _row(
        "주요사항보고서(자기전환사채매도결정)", "제이스코홀딩스",
        corp_name="제이스코홀딩스",
    )
    events = _build_signal_events([row])
    assert len(events) == 1
    e = events[0]
    assert e["key"] == "CB_BW"
    assert e["tier"] == TIER_OBSERVED
    assert e["note"] == "발행이 아니라 사채 취득·매도·소각 건입니다"


def _render_observed_note_lines(observed_events):
    """server.py '관찰된 신호' 루프의 note 렌더링 부분만 재현한다."""
    out = []
    for e in observed_events:
        if e.get("note"):
            out.append(f"  ※ {e['note']}")
    return out


def test_note_line_rendered_for_observed_signal():
    row = _row(
        "주요사항보고서(자기전환사채매도결정)", "제이스코홀딩스",
        corp_name="제이스코홀딩스",
    )
    events = _build_signal_events([row])
    observed, _ = _split(events)
    rendered = _render_observed_note_lines(observed)
    assert rendered == ["  ※ 발행이 아니라 사채 취득·매도·소각 건입니다"]


# ── fix round 1, finding 2: observed 0건에서 지정 문구 + 절차 목록 노출 ──


def test_zero_observed_path_wording_and_procedural_list():
    """헬릭스미스 실측: 대량보유상황보고서 1건 → observed 0, procedural 1.

    server.py의 s3 3분기(if top_signal / elif observed_events / else)를
    그대로 재현한다 — observed_events가 비면 else 분기(지정 문구)로
    떨어지고, procedural_events는 별도로 여전히 렌더링 대상이어야 한다.
    """
    row = _row(
        "주식등의대량보유상황보고서(일반)", "국민연금공단",
        corp_name="헬릭스미스",
    )
    events = _build_signal_events([row])
    observed, procedural = _split(events)
    assert observed == []
    assert len(procedural) == 1

    top_signal = None  # observed가 비어 있으니 pick_headline도 항상 None
    if top_signal:
        s3 = "unreachable"
    elif observed:
        s3 = "unreachable"
    else:
        s3 = (
            "이 기간 공시에서는 관찰 신호가 없습니다. "
            "공시 외 지표(재무·감사의견·연속적자)는 아래 블록에서 확인하세요."
        )
    assert s3 == (
        "이 기간 공시에서는 관찰 신호가 없습니다. "
        "공시 외 지표(재무·감사의견·연속적자)는 아래 블록에서 확인하세요."
    )

    # 절차·사후 보고 절은 observed가 0이어도 procedural_events가 있으면 나온다
    # (이전 버그: observed가 비면 함수 전체가 조기 반환해 이 목록 자체가
    # 사라졌다).
    assert procedural[0]["reason"]


# ── fix round 1, finding 3: 강등된 FUND_OUTFLOW는 자금유출 후보에서 빠져야 한다 ──


def test_demoted_fund_outflow_excluded_from_outflow_candidates():
    """리뷰 실측 사례: 타인에대한채무보증결정(종속회사의주요경영사항)은 R3로 강등.

    _confirm_outflow_counterparties가 signal_events(분리 전)를 받으면 이
    procedural 건이 4개 후보 슬롯 하나를 차지해 더 오래된 observed 건을
    밀어낼 수 있다 — observed_events만 넘기면 애초에 후보에 들지 않는다.
    """
    rows = [
        _row(
            "금전대여결정", "동일산업", corp_name="동일산업",
            rcept_dt="20260110", rcept_no="OBS001",
        ),
        _row(
            "타인에대한채무보증결정(종속회사의주요경영사항)", "동일산업",
            corp_name="동일산업", rcept_dt="20260210", rcept_no="PROC001",
        ),
    ]
    events = _build_signal_events(rows)
    assert {e["key"] for e in events} == {"FUND_OUTFLOW"}
    observed, procedural = _split(events)
    assert [e["rcept_no"] for e in observed] == ["OBS001"]
    assert [e["rcept_no"] for e in procedural] == ["PROC001"]
    assert all(e["tier"] == TIER_PROCEDURAL for e in procedural)

    # 버그 재현: 분리 전 원본을 넘기면 강등된 건도 후보에 남는다.
    raw_candidates = _outflow_review_candidates(events, [])
    assert {c[0] for c in raw_candidates} == {"OBS001", "PROC001"}

    # 수정 후 배선과 동일: observed_events만 넘기면 강등된 건이 빠진다.
    fixed_candidates = _outflow_review_candidates(observed, [])
    assert {c[0] for c in fixed_candidates} == {"OBS001"}


# ── fix round 1, finding 4: procedural 자본 이벤트는 churn 집계에서 빠져야 한다 ──


def test_procedural_capital_events_excluded_from_churn():
    """셀트리온류 실측: 유상증자결정(종속회사의주요경영사항)은 R3로 강등되는 3PCA.

    희석성 자본 이벤트(3PCA) 4건이 12개월 안에 몰리면 detect_capital_churn의
    규칙(A) 희석성 ≥3건을 만족해 CAPITAL_CHURN이 뜬다. 그중 2건이 procedural
    강등 건이면, observed만 셌을 때는(희석성 2건) 임계를 못 채워야 한다.
    """
    rows = [
        _row(
            "제3자배정유상증자결정", "처칠전자", corp_name="처칠전자",
            rcept_dt="20260101", rcept_no="C1",
        ),
        _row(
            "제3자배정유상증자결정", "처칠전자", corp_name="처칠전자",
            rcept_dt="20260201", rcept_no="C2",
        ),
        _row(
            "유상증자결정(종속회사의주요경영사항)", "처칠전자", corp_name="처칠전자",
            rcept_dt="20260301", rcept_no="C3",
        ),
        _row(
            "유상증자결정(종속회사의주요경영사항)", "처칠전자", corp_name="처칠전자",
            rcept_dt="20260401", rcept_no="C4",
        ),
    ]
    events = _build_signal_events(rows)
    assert {e["key"] for e in events} == {"3PCA"}
    observed, procedural = _split(events)
    assert len(observed) == 2
    assert len(procedural) == 2

    # 버그 재현: 분리 전 원본으로 판정하면 희석성 4건 → CAPITAL_CHURN 오발화.
    raw_churn = detect_capital_churn(events, lookback_years=1)
    assert "CAPITAL_CHURN" in raw_churn["flags"]

    # 수정 후 배선과 동일: observed_events만 넘기면(희석성 2건) 발화하지 않는다.
    observed_churn = detect_capital_churn(observed, lookback_years=1)
    assert "CAPITAL_CHURN" not in observed_churn["flags"]


# ── fix round 2, finding A: note는 procedural 신호에도(tier와 무관하게) 렌더링돼야 한다 ──


def _render_signal_block_lines(observed_events, procedural_events):
    """server.py의 '관찰된 신호'/'절차·사후 보고' 두 블록 렌더링을 재현한다.

    real 함수는 observed_events가 비면 헤더·루프 자체를 건너뛴다(fix round 2,
    finding B) — 그 분기도 그대로 재현한다.
    """
    lines = []
    if observed_events:
        lines.append(f"━━ 관찰된 신호 ({len(observed_events)}건) ━━")
        for e in observed_events:
            lines.append(f"• {e['rcept_dt']} · {e['report_nm']}")
            if e.get("note"):
                lines.append(f"  ※ {e['note']}")
    if procedural_events:
        lines.append(f"━━ 절차·사후 보고 ({len(procedural_events)}건) ━━")
        for e in procedural_events:
            lines.append(f"• {e['rcept_dt']} · {e['report_nm']}")
            lines.append(f"  → {e.get('reason', '')}")
            if e.get("note"):
                lines.append(f"  ※ {e['note']}")
    return lines


def test_procedural_note_is_rendered():
    """리뷰 실측 사례: 전환사채취득결과보고서는 R2로 강등되는 CB_BW인데,
    같은 제목이 '사채취득' 마커도 포함해 note(_direction_note)도 함께 붙는다.

    demotion reason(R2)과 note(_direction_note)는 qualifiers.py에서 독립적으로
    계산되므로 한 신호에 둘 다 있을 수 있다 — round 1은 이 note를 procedural
    루프에서 렌더링하지 않아 조용히 버렸다.
    """
    row = _row(
        "전환사채취득결과보고서", "리뷰테스트기업", corp_name="리뷰테스트기업",
    )
    events = _build_signal_events([row])
    assert len(events) == 1
    e = events[0]
    assert e["key"] == "CB_BW"
    assert e["tier"] == TIER_PROCEDURAL
    assert e["reason"]  # R2(결과보고서) 강등 사유가 있어야 한다
    assert e["note"] == "발행이 아니라 사채 취득·매도·소각 건입니다"

    observed, procedural = _split(events)
    assert observed == []
    assert len(procedural) == 1

    rendered = _render_signal_block_lines(observed, procedural)
    assert "  ※ 발행이 아니라 사채 취득·매도·소각 건입니다" in rendered
    # reason과 note가 같은 항목에 함께 나와야 한다(하나가 다른 하나를 가리면 안 됨).
    reason_idx = rendered.index("  → " + e["reason"])
    note_idx = rendered.index("  ※ " + e["note"])
    assert note_idx == reason_idx + 1


# ── fix round 2, finding B: observed 0건이면 "관찰된 신호" 헤더 자체가 없어야 한다 ──


def test_no_observed_header_when_observed_empty_but_procedural_section_present():
    """헬릭스미스 실측: observed 0, procedural 1.

    "관찰된 신호 (0건)" 같은 빈 헤더가 뜨면 안 되고, 절차·사후 보고 절은
    여전히 나와야 한다(fix round 1, finding 2와 겹치지 않게 유지되는지 확인).
    """
    row = _row(
        "주식등의대량보유상황보고서(일반)", "국민연금공단",
        corp_name="헬릭스미스",
    )
    events = _build_signal_events([row])
    observed, procedural = _split(events)
    assert observed == []
    assert len(procedural) == 1

    rendered = _render_signal_block_lines(observed, procedural)
    assert not any("관찰된 신호" in line for line in rendered)
    assert any("절차·사후 보고 (1건)" in line for line in rendered)


# ── 리뷰 C1: 거래소가 제출한 공시는 배선 수준에서도 observed로 남는다 ──
#
# 실측(2026-08-14, /list.json pblntf_ty=I): 거래소 원천 공시의 flr_nm은
# 회사명이 아니라 시장본부다 — 코스닥시장본부·유가증권시장본부·코넥스시장.
# filing=None으로만 검증하면 프로덕션 경로를 전혀 덮지 못한다.

_JSCO_ROWS = [
    _row("조회공시요구(풍문또는보도)              (감사의견 비적정설)",
         "코스닥시장본부", corp_name="제이스코홀딩스",
         rcept_dt="20260701", rcept_no="20260701900001"),
    _row("불성실공시법인지정              (공시번복)",
         "코스닥시장본부", corp_name="제이스코홀딩스",
         rcept_dt="20260710", rcept_no="20260710900002"),
    _row("주권매매거래정지              (조회공시 답변)",
         "코스닥시장본부", corp_name="제이스코홀딩스",
         rcept_dt="20260712", rcept_no="20260712900003"),
]


def test_exchange_filed_rows_stay_observed_through_the_wiring():
    """합성 공시 목록의 거래소 제출 행이 observed 집계에 남는다."""
    events = _build_signal_events(_JSCO_ROWS)
    observed, procedural = _split(events)
    assert procedural == [], [e["reason"] for e in procedural]
    assert {e["key"] for e in observed} == {"INQUIRY", "DISCLOSURE_VIOL"}


def test_exchange_filed_rows_feed_sig_keys_and_pattern_matching():
    """observed에서 빠지면 capital_churn_anomaly(4.3 요구)와 탈출기 서사가
    무너진다 — sig_keys·taxonomy 집합까지 실제로 흘러가는지 확인한다."""
    events = _build_signal_events(_JSCO_ROWS)
    observed, _ = _split(events)

    sig_keys = {e["key"] for e in observed if not e["is_amendment"]}
    assert "DISCLOSURE_VIOL" in sig_keys and "INQUIRY" in sig_keys

    tax_ids = set()
    for k in sig_keys:
        tax_ids.update(SIGNAL_KEY_TO_TAXONOMY.get(k, []))
    assert "4.3" in tax_ids  # 공시의무 위반 — capital_churn_anomaly의 필수 축

    # 자본 이벤트(2.7)를 얹으면 실제로 패턴이 잡힌다. 거래소 행이 강등되면
    # 4.3이 사라져 이 패턴은 영원히 매칭되지 않는다.
    assert find_pattern_match(sorted(tax_ids | {"2.7"})) is not None


def test_exchange_filer_exception_does_not_revive_third_party_reports():
    """거래소 예외가 R1 전체를 무력화하지 않는다 — 제3자 제출은 그대로 강등."""
    rows = _JSCO_ROWS + [
        _row("주식등의대량보유상황보고서(일반)", "국민연금공단",
             corp_name="제이스코홀딩스", rcept_dt="20260715",
             rcept_no="20260715900004"),
    ]
    observed, procedural = _split(_build_signal_events(rows))
    assert len(procedural) == 1
    assert "국민연금공단" in procedural[0]["reason"]
    assert {e["key"] for e in observed} == {"INQUIRY", "DISCLOSURE_VIOL"}


# ── 리뷰 C2: false-amendment 복구가 발화하면 is_amendment도 내려간다 ──

def test_false_amendment_recovery_clears_the_amendment_flag():
    """'[정정명령부과]주요사항보고서(유상증자결정)'은 정정공시가 아니다.

    플래그가 True로 남으면 헤더 건수에는 들어가면서 non_amend_events·
    sig_keys·헤드라인에서는 빠져 두 층이 어긋난다.
    """
    row = _row("[정정명령부과]주요사항보고서(유상증자결정)",
               "테스트기업", corp_name="테스트기업")
    events = _build_signal_events([row])
    assert events, "false-amendment 복구가 신호를 되살리지 못했습니다"
    assert all(e["is_amendment"] is False for e in events)

    observed, _ = _split(events)
    non_amend = [e for e in observed if not e["is_amendment"]]
    assert len(non_amend) == len(observed)
    assert _headline(observed) is not None


def test_real_amendment_still_keeps_the_flag_and_is_demoted():
    """진짜 정정공시([기재정정])의 기존 동작은 바뀌지 않는다."""
    row = _row("[기재정정]주요사항보고서(유상증자결정)",
               "테스트기업", corp_name="테스트기업")
    events = _build_signal_events([row])
    # match_signals가 정정공시를 걸러 신호가 없거나, 있어도 R5로 강등된다.
    for e in events:
        assert e["is_amendment"] is True
        assert e["tier"] == TIER_PROCEDURAL


class TestCheckDisclosureRiskQualification(unittest.TestCase):
    """check_disclosure_risk 배선 — 제목만 주는 경로는 R1b~R5만 적용된다."""

    def test_ownership_report_is_demoted(self):
        from dart_risk_mcp.server import check_disclosure_risk
        out = check_disclosure_risk(report_name="주식등의대량보유상황보고서(일반)")
        self.assertIn("절차·사후 보고", out)
        self.assertIn("지분", out)
        self.assertNotIn("🎯", out)

    def test_cb_issuance_stays_observed(self):
        """과잉 강등 방지 — 회사가 낸 실제 결정은 관찰 신호로 남는다."""
        from dart_risk_mcp.server import check_disclosure_risk
        out = check_disclosure_risk(
            report_name="주요사항보고서(전환사채권발행결정)"
        )
        self.assertIn("🎯", out)
        self.assertNotIn("절차·사후 보고", out)

    def test_exchange_inquiry_stays_observed_without_filing(self):
        """filing이 없으면 R1은 적용되지 않는다 — 거래소 조회공시가 남아야 한다."""
        from dart_risk_mcp.server import check_disclosure_risk
        out = check_disclosure_risk(
            report_name="조회공시요구(풍문또는보도)(감사의견비적정설)"
        )
        self.assertIn("🎯", out)

    def test_result_report_is_demoted(self):
        from dart_risk_mcp.server import check_disclosure_risk
        out = check_disclosure_risk(report_name="자기주식취득결과보고서")
        self.assertIn("절차·사후 보고", out)

    def test_label_softened_when_allocation_absent(self):
        from dart_risk_mcp.server import check_disclosure_risk
        out = check_disclosure_risk(report_name="주요사항보고서(유상증자결정)")
        self.assertIn("배정방식 미상", out)


class TestCheckDisclosureRiskRcertPath(unittest.TestCase):
    """rcept_no 경로 — 행 복원 성공/실패 양쪽."""

    _ROW = {
        "rcept_no": "20260731000779",
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "report_nm": "주식등의대량보유상황보고서(일반)",
        "flr_nm": "삼성물산",
        "rcept_dt": "20260731",
    }

    @patch("dart_risk_mcp.server._DART_API_KEY", "testkey")
    @patch("dart_risk_mcp.server.fetch_document_text", return_value="")
    @patch("dart_risk_mcp.server.resolve_corp_code_from_rcept_no", return_value="")
    @patch("dart_risk_mcp.server.resolve_disclosure_row_with_status")
    def test_row_found_uses_real_title_and_filer(self, mock_row, _cc, _doc):
        from dart_risk_mcp.server import check_disclosure_risk
        mock_row.return_value = (dict(self._ROW), "found")
        out = check_disclosure_risk(rcept_no="20260731000779")
        self.assertIn("주식등의대량보유상황보고서(일반)", out)
        self.assertIn("삼성물산", out)
        self.assertNotIn("공시: 접수번호", out)
        self.assertIn("절차·사후 보고", out)

    @patch("dart_risk_mcp.server._DART_API_KEY", "testkey")
    @patch("dart_risk_mcp.server.fetch_document_text", return_value="")
    @patch("dart_risk_mcp.server.resolve_corp_code_from_rcept_no", return_value="")
    @patch("dart_risk_mcp.server.resolve_disclosure_row_with_status")
    def test_row_missing_degrades_to_current_behaviour(self, mock_row, _cc, _doc):
        """행 복원 실패는 회귀가 아니다 — 지금과 같은 출력이어야 한다."""
        from dart_risk_mcp.server import check_disclosure_risk
        mock_row.return_value = (None, "not_found")
        out = check_disclosure_risk(rcept_no="20260731000816")
        self.assertIn("공시: 접수번호 20260731000816", out)
        self.assertNotIn("제출인:", out)


class TestMarketScanFilter(unittest.TestCase):
    """시장 스캔 필터 — 네트워크 없이 합성 행으로 검증한다."""

    @staticmethod
    def _row(nm, flr, corp="테스트회사", rc="20260731000001"):
        return {
            "rcept_no": rc, "corp_name": corp, "report_nm": nm,
            "flr_nm": flr, "rcept_dt": "20260731", "corp_code": "00000001",
        }

    def test_third_party_rows_are_counted_not_listed(self):
        from dart_risk_mcp.server import _filter_market_rows
        raw = [
            self._row("주식등의대량보유상황보고서(일반)", "국민연금공단", rc="1" * 14),
            self._row("주식등의대량보유상황보고서(일반)", "국민연금공단", rc="2" * 14),
            self._row("주식등의대량보유상황보고서(일반)", "국민연금공단", rc="3" * 14),
            self._row("주요사항보고서(전환사채권발행결정)", "테스트회사", rc="4" * 14),
            self._row("주요사항보고서(전환사채권발행결정)", "테스트회사", rc="5" * 14),
        ]
        filtered, procedural = _filter_market_rows(raw, set())
        self.assertEqual(len(filtered), 2)
        self.assertEqual(procedural, 3)

    def test_preset_filter_applies_to_observed_only(self):
        """강등된 신호가 preset을 통과시키면 제외의 의미가 없다."""
        from dart_risk_mcp.server import _filter_market_rows
        raw = [
            self._row("주식등의대량보유상황보고서(일반)", "국민연금공단"),
        ]
        filtered, procedural = _filter_market_rows(raw, {"SHAREHOLDER"})
        self.assertEqual(len(filtered), 0)
        self.assertEqual(procedural, 1)

    def test_observed_row_passes_matching_preset(self):
        from dart_risk_mcp.server import _filter_market_rows
        raw = [self._row("주요사항보고서(전환사채권발행결정)", "테스트회사")]
        filtered, procedural = _filter_market_rows(raw, {"CB_BW"})
        self.assertEqual(len(filtered), 1)
        self.assertEqual(procedural, 0)

    def test_no_signal_row_counts_as_neither(self):
        from dart_risk_mcp.server import _filter_market_rows
        raw = [self._row("사업보고서 (2025.12)", "테스트회사")]
        filtered, procedural = _filter_market_rows(raw, set())
        self.assertEqual(len(filtered), 0)
        self.assertEqual(procedural, 0)

    def test_filtered_elements_carry_qualified_objects(self):
        from dart_risk_mcp.server import _filter_market_rows
        raw = [self._row("주요사항보고서(유상증자결정)", "테스트회사")]
        filtered, _ = _filter_market_rows(raw, set())
        self.assertEqual(len(filtered), 1)
        _row, quals = filtered[0]
        self.assertEqual(quals[0].label, "유상증자(배정방식 미상)")

    # -- fix round 1: procedural_count는 preset(target_keys) 범위로 스코프한다 --
    # 강등된 행이라도 그 신호 키가 요청한 preset과 무관하면 세지 않는다.
    # "관찰 신호 M건"은 preset 범위인데 "절차·사후 보고 K건"은 시장 전체
    # 범위가 되어 한 문장 안에서 서로 다른 모집단을 말하던 버그의 재현.

    def test_demoted_row_outside_preset_is_not_counted(self):
        """강등된 행의 키가 target_keys와 무관하면 procedural에도 안 잡힌다."""
        from dart_risk_mcp.server import _filter_market_rows
        # 자기주식취득결과보고서 → TREASURY, R2(결과보고서)로 procedural 강등.
        raw = [self._row("자기주식취득결과보고서", "테스트회사")]
        filtered, procedural = _filter_market_rows(raw, {"FUND_OUTFLOW"})
        self.assertEqual(len(filtered), 0)
        self.assertEqual(procedural, 0)

    def test_demoted_row_inside_preset_is_counted(self):
        """강등된 행의 키가 target_keys에 있으면 procedural로 잡힌다."""
        from dart_risk_mcp.server import _filter_market_rows
        raw = [self._row("자기주식취득결과보고서", "테스트회사")]
        filtered, procedural = _filter_market_rows(raw, {"TREASURY"})
        self.assertEqual(len(filtered), 0)
        self.assertEqual(procedural, 1)

    def test_empty_target_keys_counts_every_demoted_row(self):
        """target_keys가 비어 있으면(all_risk) 기존처럼 모든 강등 행을 센다."""
        from dart_risk_mcp.server import _filter_market_rows
        raw = [self._row("자기주식취득결과보고서", "테스트회사")]
        filtered, procedural = _filter_market_rows(raw, set())
        self.assertEqual(len(filtered), 0)
        self.assertEqual(procedural, 1)

    def test_mixed_preset_scan_only_counts_matching_demotions(self):
        """coordinator 리포트의 재현 — asset-transfer 계열 preset 스캔에서
        무관한 강등 건(대량보유보고·자기주식취득)은 procedural에 섞이지 않는다."""
        from dart_risk_mcp.server import _filter_market_rows
        raw = [
            self._row("주식등의대량보유상황보고서(일반)", "국민연금공단", rc="1" * 14),
            self._row("주식등의대량보유상황보고서(일반)", "국민연금공단", rc="2" * 14),
            self._row("자기주식취득결과보고서", "테스트회사", rc="3" * 14),
            self._row("주요사항보고서(유형자산양수결정)", "테스트회사", rc="4" * 14),
        ]
        filtered, procedural = _filter_market_rows(raw, {"FUND_OUTFLOW", "ACQ_REVIEW"})
        self.assertEqual(len(filtered), 1)
        self.assertEqual(procedural, 0)


# ── 최종 리뷰 수정 (2026-08-16) ─────────────────────────────────────────────


class TestProceduralWordingIsNotCategoricallyFalse(unittest.TestCase):
    """수정 1 — 강등 덧붙임 문장이 R2~R5에서 사유와 모순되면 안 된다."""

    _FALSE = "회사가 낸 사건 공시가 아닙니다"

    def test_result_report_does_not_claim_company_did_not_file(self):
        """자기주식취득결과보고서는 회사가 낸 공시다 — 단정하면 거짓이다."""
        from dart_risk_mcp.server import check_disclosure_risk
        out = check_disclosure_risk(report_name="자기주식취득결과보고서")
        self.assertIn("절차·사후 보고", out)
        self.assertNotIn(self._FALSE, out)
        self.assertIn("이미 끝난 건의 사후 보고", out)

    def test_hedged_wording_matches_analyze_company_risk(self):
        """analyze_company_risk(server.py)와 같은 한정 표현을 쓴다."""
        from dart_risk_mcp.server import check_disclosure_risk
        out = check_disclosure_risk(report_name="주식등의대량보유상황보고서(일반)")
        self.assertIn(
            "회사가 낸 사건 자체의 공시가 아니거나 이미 끝난 건의 사후 보고입니다",
            out,
        )
        self.assertNotIn(self._FALSE, out)

    def test_wording_is_absent_from_server_source(self):
        """소스에서 단정 문장이 완전히 사라졌는지 기계적으로 확인한다."""
        src = (
            Path(__file__).resolve().parents[1]
            / "dart_risk_mcp" / "server.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn(self._FALSE, src)


class TestCatalogExcerptFollowsTheDemotion(unittest.TestCase):
    """수정 2 — 카탈로그 발췌는 observed 신호에만 붙는다."""

    # 실제 load_catalog_excerpt는 빈 입력에 ""를 반환한다(실측) — 마커도 같은
    # 계약을 지켜야 발췌 유무가 입력 때문임을 검증할 수 있다.
    _CAT = staticmethod(lambda ids: "CATALOG-MARKER" if ids else "")

    def test_fully_demoted_disclosure_gets_no_excerpt(self):
        from dart_risk_mcp import server
        with patch.object(
            server, "load_catalog_excerpt", side_effect=self._CAT
        ) as mock_cat:
            out = server.check_disclosure_risk(
                report_name="주식등의대량보유상황보고서(일반)"
            )
        self.assertNotIn("CATALOG-MARKER", out)
        # 호출은 되되 입력이 비어 있어야 한다(관찰 신호 0건)
        mock_cat.assert_called_once()
        self.assertEqual(list(mock_cat.call_args.args[0]), [])

    def test_observed_disclosure_still_gets_the_excerpt(self):
        """과잉 축소 방지 — 관찰 신호가 남으면 발췌는 그대로 나온다."""
        from dart_risk_mcp import server
        with patch.object(
            server, "load_catalog_excerpt", side_effect=self._CAT
        ) as mock_cat:
            out = server.check_disclosure_risk(
                report_name="주요사항보고서(전환사채권발행결정)"
            )
        self.assertIn("CATALOG-MARKER", out)
        self.assertTrue(list(mock_cat.call_args.args[0]))


class TestRcertPlusTitleStillResolvesTheRow(unittest.TestCase):
    """수정 3 — 접수번호+제목 동시 호출도 행을 복원해 R1이 발화한다."""

    _ROW = {
        "rcept_no": "20260731000779",
        "corp_code": "00126380",
        "corp_name": "테스트회사",
        "report_nm": "주요사항보고서(전환사채권발행결정)",
        "flr_nm": "다른제출인",
        "rcept_dt": "20260731",
    }

    @patch("dart_risk_mcp.server._DART_API_KEY", "testkey")
    @patch("dart_risk_mcp.server.fetch_document_text", return_value="")
    @patch("dart_risk_mcp.server.resolve_corp_code_from_rcept_no", return_value="")
    @patch("dart_risk_mcp.server.resolve_disclosure_row_with_status")
    def test_row_is_resolved_and_r1_fires(self, mock_row, _cc, _doc):
        from dart_risk_mcp.server import check_disclosure_risk
        mock_row.return_value = (dict(self._ROW), "found")
        out = check_disclosure_risk(
            rcept_no="20260731000779",
            report_name="주요사항보고서(전환사채권발행결정)",
        )
        mock_row.assert_called_once_with("20260731000779", "testkey")
        self.assertIn("절차·사후 보고", out)
        self.assertIn("다른제출인", out)
        self.assertNotIn("🎯", out)

    @patch("dart_risk_mcp.server._DART_API_KEY", "testkey")
    @patch("dart_risk_mcp.server.fetch_document_text", return_value="")
    @patch("dart_risk_mcp.server.resolve_corp_code_from_rcept_no", return_value="")
    @patch("dart_risk_mcp.server.resolve_disclosure_row_with_status")
    def test_same_rcept_no_alone_reaches_the_same_verdict(self, mock_row, _cc, _doc):
        """같은 공시가 호출 형태에 따라 다른 판정을 받지 않는다."""
        from dart_risk_mcp.server import check_disclosure_risk
        mock_row.return_value = (dict(self._ROW), "found")
        alone = check_disclosure_risk(rcept_no="20260731000779")
        mock_row.return_value = (dict(self._ROW), "found")
        with_title = check_disclosure_risk(
            rcept_no="20260731000779",
            report_name="주요사항보고서(전환사채권발행결정)",
        )
        for out in (alone, with_title):
            self.assertIn("절차·사후 보고", out)
            self.assertNotIn("🎯", out)

    @patch("dart_risk_mcp.server._DART_API_KEY", "testkey")
    @patch("dart_risk_mcp.server.fetch_document_text", return_value="")
    @patch("dart_risk_mcp.server.resolve_corp_code_from_rcept_no", return_value="")
    @patch("dart_risk_mcp.server.resolve_disclosure_row_with_status")
    def test_supplied_title_wins_over_row_title(self, mock_row, _cc, _doc):
        """제목을 직접 넘긴 호출자는 그 제목을 본다 — 표시만, 판정 입력은 행."""
        from dart_risk_mcp.server import check_disclosure_risk
        mock_row.return_value = (dict(self._ROW), "found")
        out = check_disclosure_risk(
            rcept_no="20260731000779", report_name="사용자지정제목"
        )
        self.assertIn("공시: 사용자지정제목", out)

    # extract_cb_investors도 패치한다 — 제목이 CB_BW로 관찰 판정되면 인수자
    # 추출이 원문 ZIP을 내려받아 이 단위 테스트가 실제 DART를 때린다.
    @patch("dart_risk_mcp.server._DART_API_KEY", "testkey")
    @patch("dart_risk_mcp.server.extract_cb_investors", return_value=[])
    @patch("dart_risk_mcp.server.fetch_document_text", return_value="")
    @patch("dart_risk_mcp.server.resolve_corp_code_from_rcept_no", return_value="")
    @patch("dart_risk_mcp.server.resolve_disclosure_row_with_status",
           return_value=(None, "not_found"))
    def test_filer_line_absent_when_row_unresolved(self, _row, _cc, _doc, _cb):
        from dart_risk_mcp.server import check_disclosure_risk
        out = check_disclosure_risk(
            rcept_no="20260731000816",
            report_name="주요사항보고서(전환사채권발행결정)",
        )
        self.assertNotIn("제출인:", out)
        self.assertIn("공시: 주요사항보고서(전환사채권발행결정)", out)


class TestRowLookupNegativeCache(unittest.TestCase):
    """수정 5 — 실패도 캐시하고, 페이지 사이에 간격을 둔다."""

    RC = "20260731000999"

    def setUp(self):
        from dart_risk_mcp.core import dart_client as dc
        dc._rcept_row_cache.clear()

    def tearDown(self):
        from dart_risk_mcp.core import dart_client as dc
        dc._rcept_row_cache.clear()

    def test_miss_is_cached_so_repeat_costs_nothing(self):
        from dart_risk_mcp.core import dart_client as dc

        class _Resp:
            @staticmethod
            def json():
                return {"status": "000", "list": [], "total_page": 3}

        with patch.object(dc, "_retry", return_value=_Resp()) as mock_retry, \
                patch.object(dc.time, "sleep") as mock_sleep:
            first = dc.resolve_disclosure_row_from_rcept_no(self.RC, "k")
            calls_after_first = mock_retry.call_count
            second = dc.resolve_disclosure_row_from_rcept_no(self.RC, "k")

        self.assertIsNone(first)
        self.assertIsNone(second)
        self.assertEqual(calls_after_first, 3)          # total_page까지만
        self.assertEqual(mock_retry.call_count, 3)      # 재조회는 0회 추가
        # 2026-08-22: 2페이지부터는 배치로 동시에 받는다(동시성 4). 3페이지면
        # page 1 → 배치(2,3) 하나라 배치 사이 간격은 1회다. 옛 구현은 페이지
        # 사이마다 쉬어 2회였다 — 호출 수는 같고 대기 시간만 줄었다.
        self.assertEqual(mock_sleep.call_count, 1)

    def test_transient_failure_is_not_cached(self):
        """네트워크 오류·비정상 status는 일시적일 수 있어 캐시하지 않는다."""
        from dart_risk_mcp.core import dart_client as dc

        with patch.object(dc, "_retry", side_effect=RuntimeError("net")) as m:
            self.assertIsNone(dc.resolve_disclosure_row_from_rcept_no(self.RC, "k"))
            self.assertIsNone(dc.resolve_disclosure_row_from_rcept_no(self.RC, "k"))
        self.assertEqual(m.call_count, 2)

    def test_cached_miss_does_not_shadow_a_later_hit_of_another_key(self):
        """센티널이 다른 접수번호의 정상 조회를 오염시키지 않는다."""
        from dart_risk_mcp.core import dart_client as dc
        row = {"rcept_no": "20260731000001", "report_nm": "테스트"}

        class _Miss:
            @staticmethod
            def json():
                return {"status": "000", "list": [], "total_page": 1}

        class _Hit:
            @staticmethod
            def json():
                return {"status": "000", "list": [row], "total_page": 1}

        with patch.object(dc, "_retry", return_value=_Miss()):
            self.assertIsNone(dc.resolve_disclosure_row_from_rcept_no(self.RC, "k"))
        with patch.object(dc, "_retry", return_value=_Hit()):
            got = dc.resolve_disclosure_row_from_rcept_no("20260731000001", "k")
        self.assertEqual(got, row)
        self.assertIsNone(dc.resolve_disclosure_row_from_rcept_no(self.RC, "k"))
