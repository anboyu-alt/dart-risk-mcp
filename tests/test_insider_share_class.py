"""보통주식과 종류주식을 한 시계열에 섞지 않는지 잠근다 (2026-08-27).

## 어떻게 찾았나

임원 보수 ④가 ②와 **같은 숫자 묶음**을 내던 것(#332)이 단서였으니, 같은
검사를 골드 전수로 돌렸다 — 한 리포트 안에서 다른 두 섹션이 같은 값들을
내는 곳. `두산_insider.txt`의 박형원·박인원이 걸렸다.

    ▶ 박형원
        2025  2.03%  [최대주주]
        2025  0.07% (Δ-1.96%)  [최대주주]     ← 판 적이 없다
        2025  1.99% (Δ+1.92%)  [최대주주]     ← 산 적이 없다
        2025  0.07% (Δ-1.92%)  [최대주주]
        …열두 줄

원자료를 열어 보니 두 사람 다 **보통주식 328,479주(1.99%)**와
**종류주식 3,621주(0.07%)**를 따로 보고하고 있었다. 두 줄을 한 시계열에
섞으니 비율이 튀고 그 사이의 Δ가 **전부 거짓**이 됐다.

거짓 Δ는 보기 나쁜 데서 끝나지 않는다 — 매수·매도 클러스터 판정
(0.5%p/30일)과 `detect_insider_pre_disclosure`의 **입력**이다.

## 왜 `hyslr`에서만 문제인가

주식 종류를 주는 것은 `hyslrSttus`뿐이다 — `elestock`·`hyslr_chg`·
`majorstock` 응답에는 `stock_knd`가 없다(실측 키 대조). 없으면 빈
문자열이라 기존 묶음이 그대로 유지된다.
"""
import pytest

import dart_risk_mcp.server as srv


def _rec(nm, rate, dt, kind, src="hyslr"):
    return {"source": src, "nm": nm, "trmend_posesn_stock_qota_rt": rate,
            "rcept_dt": dt, "stock_knd": kind}


def _render(records, years=2):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(srv, "_DART_API_KEY", "k")
        mp.setattr(srv, "resolve_corp",
                   lambda q, k: ("테스트", {"corp_code": "00117212",
                                          "stock_code": "000150"}))
        mp.setattr(srv, "fetch_insider_timeline", lambda *a, **kw: records)
        mp.setattr(srv, "fetch_company_disclosures",
                   lambda *a, **kw: [])
        return srv.track_insider_trading("테스트", years)


_TODAY = "20260801"
_MIX = [
    _rec("박형원", "2.03", "20260101", "보통주식"),
    _rec("박형원", "0.07", "20260101", "종류주식"),
    _rec("박형원", "1.99", "20260401", "보통주식"),
    _rec("박형원", "0.07", "20260401", "종류주식"),
    _rec("박형원", "2.03", _TODAY, "보통주식"),
]


def test_거짓_델타가_사라진다():
    out = _render(_MIX)
    assert "Δ-1.96" not in out and "Δ+1.92" not in out
    assert "Δ-0.04" in out or "Δ+0.04" in out, "진짜 변동은 남아야 한다"


def test_종류가_둘이면_밝힌다():
    out = _render(_MIX)
    assert "박형원 · 보통주식" in out
    assert "박형원 · 종류주식" in out


def test_종류가_하나면_군더더기를_붙이지_않는다():
    only = [_rec("김보통", "5.00", "20260101", "보통주식"),
            _rec("김보통", "5.40", "20260401", "보통주식")]
    out = _render(only)
    assert "▶ 김보통\n" in out + "\n"
    assert "김보통 · 보통주식" not in out


def test_종류를_안_주는_소스는_묶음이_그대로다():
    """`elestock`은 `stock_knd`가 없다 — 한 사람이 한 시계열로 남는다."""
    rows = [{"source": "elestock", "repror": "이임원",
             "sp_stock_lmp_rate": "1.00", "rcept_dt": "20260101"},
            {"source": "elestock", "repror": "이임원",
             "sp_stock_lmp_rate": "1.60", "rcept_dt": "20260401"}]
    out = _render(rows)
    assert "▶ 이임원" in out
    assert "이임원 ·" not in out
    assert "Δ+0.60" in out


def test_거짓_델타가_클러스터를_켜지_않는다():
    """0.5%p/30일 임계는 이 거짓 Δ를 그대로 먹는다 — 그게 진짜 피해다."""
    same_month = [
        _rec("박형원", "2.03", "20260401", "보통주식"),
        _rec("박형원", "0.07", "20260410", "종류주식"),
    ]
    out = _render(same_month)
    assert "매도 클러스터" not in out


def test_주식_종류가_묶음_키에_들어간다():
    import pathlib

    src = pathlib.Path(srv.__file__).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "_hk = (_holder_key(holder), kind)" in code
