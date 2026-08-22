"""원문 사실 블록 배선 회귀 테스트 (v1.14.0).

파서(`parse_related_party_detail`·`parse_earnings_shock_detail`)는 이미
단위 테스트가 있다(`test_related_party_and_earnings.py`). 여기서는 그 결과가
**리포트 문자열로 실제 표면화되는지**와, 신호가 없을 때 원문을 아예 열지
않는지(호출 예산 0)를 고정한다.
"""

import dart_risk_mcp.server as srv


def _ev(key, rcept_no="20260101000001", dt="20260101", nm="제목"):
    return {"key": key, "rcept_no": rcept_no, "rcept_dt": dt,
            "report_nm": nm, "is_amendment": False}


# ── 특수관계인 자금거래 ────────────────────────────────────────────

def test_related_party_block_surfaces_interest_rate(monkeypatch):
    monkeypatch.setattr(srv, "fetch_related_party_detail", lambda r, k: {
        "counterparty": "케이지에이치홀딩스", "relation": "최대주주",
        "amount": "1500000000", "interest_rate": "8.95",
        "equity_ratio": "455.0%", "kind": "borrow",
    })
    out = "\n".join(srv._related_party_detail_block([
        _ev("RELATED_PARTY", nm="특수관계인으로부터자금차입")
    ]))
    assert "특수관계인 자금거래 확인" in out
    assert "케이지에이치홀딩스" in out
    assert "최대주주" in out
    assert "이자율 8.95%" in out          # 제목만으로는 보이지 않던 값
    assert "자기자본 대비 455.0%" in out
    assert "자금차입" in out


def test_related_party_block_omitted_when_parse_fails(monkeypatch):
    monkeypatch.setattr(srv, "fetch_related_party_detail", lambda r, k: {})
    assert srv._related_party_detail_block([_ev("RELATED_PARTY")]) == []


def test_related_party_block_no_fetch_without_signal(monkeypatch):
    calls = []
    monkeypatch.setattr(srv, "fetch_related_party_detail",
                        lambda r, k: calls.append(r) or {})
    assert srv._related_party_detail_block([_ev("CB_BW"), _ev("TREASURY")]) == []
    assert calls == []                    # 호출 예산 0


def test_related_party_block_skips_amendments(monkeypatch):
    calls = []

    def _f(r, k):
        calls.append(r)
        return {"counterparty": "가", "kind": "borrow"}

    monkeypatch.setattr(srv, "fetch_related_party_detail", _f)
    e = _ev("RELATED_PARTY")
    e["is_amendment"] = True
    assert srv._related_party_detail_block([e]) == []
    assert calls == []


def test_related_party_block_respects_max_check(monkeypatch):
    calls = []

    def _f(r, k):
        calls.append(r)
        return {"counterparty": f"상대{len(calls)}", "kind": "borrow"}

    monkeypatch.setattr(srv, "fetch_related_party_detail", _f)
    evs = [_ev("RELATED_PARTY", rcept_no=f"2026010100000{i}", dt=f"2026010{i}")
           for i in range(1, 6)]
    srv._related_party_detail_block(evs, max_check=3)
    assert len(calls) == 3


def test_related_party_block_dedups_rcept(monkeypatch):
    calls = []

    def _f(r, k):
        calls.append(r)
        return {"counterparty": "가", "kind": "borrow"}

    monkeypatch.setattr(srv, "fetch_related_party_detail", _f)
    srv._related_party_detail_block([_ev("RELATED_PARTY"), _ev("RELATED_PARTY")])
    assert len(calls) == 1


def test_related_party_block_survives_network_error(monkeypatch):
    def _boom(r, k):
        raise RuntimeError("network")

    monkeypatch.setattr(srv, "fetch_related_party_detail", _boom)
    assert srv._related_party_detail_block([_ev("RELATED_PARTY")]) == []


def test_related_party_kind_labels(monkeypatch):
    for kind, label in (("borrow", "자금차입"), ("collateral", "담보 제공받음"),
                        ("investment", "출자"), ("", "거래")):
        monkeypatch.setattr(srv, "fetch_related_party_detail", lambda r, k, _c=kind: {
            "counterparty": "상대", "kind": _c,
        })
        out = "\n".join(srv._related_party_detail_block([_ev("RELATED_PARTY")]))
        assert label in out


# ── 손익구조 급변 ──────────────────────────────────────────────────

def test_earnings_shock_block_surfaces_turn(monkeypatch):
    monkeypatch.setattr(srv, "fetch_earnings_shock_detail", lambda r, k: {
        "rows": [
            {"account": "매출액", "current": 100, "prior": 200,
             "change": -100, "change_pct": -50.0, "turn": ""},
            {"account": "당기순이익", "current": -30, "prior": 10,
             "change": -40, "change_pct": -400.0, "turn": "적자전환"},
        ],
        "turned_to_loss": True,
    })
    out = "\n".join(srv._earnings_shock_block([
        _ev("EARNINGS_SHOCK", nm="매출액또는손익구조30%(대규모법인은15%)이상변동")
    ]))
    assert "손익구조 급변 내역" in out
    assert "매출액: -50.0%" in out
    assert "적자전환" in out


def test_earnings_shock_block_handles_missing_pct(monkeypatch):
    monkeypatch.setattr(srv, "fetch_earnings_shock_detail", lambda r, k: {
        "rows": [{"account": "영업이익", "current": 1, "prior": 0,
                  "change": 1, "change_pct": None, "turn": "흑자전환"}],
        "turned_to_loss": False,
    })
    out = "\n".join(srv._earnings_shock_block([_ev("EARNINGS_SHOCK")]))
    assert "영업이익: —" in out
    assert "흑자전환" in out


def test_earnings_shock_block_no_fetch_without_signal(monkeypatch):
    calls = []
    monkeypatch.setattr(srv, "fetch_earnings_shock_detail",
                        lambda r, k: calls.append(r) or {})
    assert srv._earnings_shock_block([_ev("RELATED_PARTY")]) == []
    assert calls == []


def test_earnings_shock_block_omitted_when_no_rows(monkeypatch):
    monkeypatch.setattr(srv, "fetch_earnings_shock_detail",
                        lambda r, k: {"rows": [], "turned_to_loss": False})
    assert srv._earnings_shock_block([_ev("EARNINGS_SHOCK")]) == []


def test_earnings_shock_block_respects_max_check(monkeypatch):
    calls = []

    def _f(r, k):
        calls.append(r)
        return {"rows": [{"account": "매출액", "current": 1, "prior": 1,
                          "change": 0, "change_pct": 0.0, "turn": ""}],
                "turned_to_loss": False}

    monkeypatch.setattr(srv, "fetch_earnings_shock_detail", _f)
    evs = [_ev("EARNINGS_SHOCK", rcept_no=f"2026010100000{i}", dt=f"2026010{i}")
           for i in range(1, 5)]
    srv._earnings_shock_block(evs, max_check=2)
    assert len(calls) == 2


# ── 무판정 원칙 ────────────────────────────────────────────────────

def test_blocks_have_no_score_or_grade_vocabulary(monkeypatch):
    monkeypatch.setattr(srv, "fetch_related_party_detail", lambda r, k: {
        "counterparty": "가", "relation": "최대주주", "amount": "1000000000",
        "interest_rate": "9.0", "equity_ratio": "455.0%", "kind": "borrow",
    })
    monkeypatch.setattr(srv, "fetch_earnings_shock_detail", lambda r, k: {
        "rows": [{"account": "매출액", "current": 1, "prior": 2,
                  "change": -1, "change_pct": -50.0, "turn": "적자전환"}],
        "turned_to_loss": True,
    })
    out = "\n".join(
        srv._related_party_detail_block([_ev("RELATED_PARTY")])
        + srv._earnings_shock_block([_ev("EARNINGS_SHOCK", rcept_no="X")])
    )
    for banned in ("점수", "등급", "위험도", "고위험", "매우위험", "위험합니다"):
        assert banned not in out


def test_related_party_equity_ratio_percent_suffix(monkeypatch):
    """자기자본대비는 원문 표기 그대로 온다 — 숫자면 %를 붙이고 문자면 안 붙인다.

    라이브 실측(20260812000839 포승그린파워)은 "187.72"로 % 없이 오고,
    자본잠식 회사는 파서 주석대로 "자본잠식" 같은 문자 표기가 온다.
    """
    monkeypatch.setattr(srv, "fetch_related_party_detail", lambda r, k: {
        "counterparty": "(주)엘엑스인터내셔널", "relation": "계열회사",
        "amount": "120000000000", "interest_rate": "4.6",
        "equity_ratio": "187.72", "kind": "borrow",
    })
    assert "자기자본 대비 187.72%" in "\n".join(
        srv._related_party_detail_block([_ev("RELATED_PARTY")])
    )

    monkeypatch.setattr(srv, "fetch_related_party_detail", lambda r, k: {
        "counterparty": "가", "equity_ratio": "자본잠식", "kind": "borrow",
    })
    out = "\n".join(srv._related_party_detail_block([_ev("RELATED_PARTY")]))
    assert "자기자본 대비 자본잠식" in out
    assert "자본잠식%" not in out
