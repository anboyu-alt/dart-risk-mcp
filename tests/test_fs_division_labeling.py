"""재무제표 출력이 **연결과 별도를 섞지 않는지** 잠근다 (2026-08-27).

## 머리글이 거짓말을 하고 있었다

`get_financial_summary`는 `items[0]`의 구분 하나만 보고 머리글에
「연결재무제표」라 적은 뒤, **응답 전체**를 이어 붙였다. DART는 연결(CFS)과
별도(OFS)를 한 덩어리로 준다.

    사업연도: 2024 | 연결재무제표
    • 자산총계: 514,531,948,000,000     ← 연결
    • 매출액:   300,870,903,000,000     ← 연결
    …
    • 자산총계: 324,966,127,000,000     ← 별도인데 라벨이 없다
    • 매출액:   209,052,241,000,000     ← 뒤엣것을 연결로 믿으면 30% 틀린다

`compare_financials`도 같은 문제에 더해 머리글이 **종목코드**였다
(「━━ 005930 ━━」) — 응답에 `corp_name`이 **없어서** 폴백이 항상 걸렸다.
여러 회사를 나란히 보는 도구인데 이름이 없었다.

## 같은 계정이 두 번 오는 것

`fnlttSinglAcnt`는 「당기순이익(손실)」을 **ord만 다르게 두 번** 준다
(삼성전자 CFS ord 29·61, OFS ord 30·62 — 값은 완전히 같다).
"""
import pytest

import dart_risk_mcp.server as srv
from dart_risk_mcp.server import _fs_div_label


def _row(div, nm, amt, prev="1", fs_nm=None, code="00126380"):
    return {"fs_div": div, "fs_nm": fs_nm if fs_nm is not None else
            ("연결재무제표" if div == "CFS" else "재무제표"),
            "account_nm": nm, "thstrm_amount": amt, "frmtrm_amount": prev,
            "bsns_year": "2024", "corp_code": code, "stock_code": "005930"}


_ITEMS = [
    _row("CFS", "자산총계", "514,531,948,000,000"),
    _row("CFS", "당기순이익(손실)", "34,451,351,000,000"),
    _row("CFS", "당기순이익(손실)", "34,451,351,000,000"),   # ord만 다른 중복
    _row("OFS", "자산총계", "324,966,127,000,000"),
    _row("OFS", "당기순이익(손실)", "23,582,565,000,000"),
    _row("OFS", "당기순이익(손실)", "23,582,565,000,000"),
]


def _summary(items=None):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(srv, "_DART_API_KEY", "k")
        mp.setattr(srv, "resolve_corp",
                   lambda q, k: ("삼성전자", {"corp_code": "00126380",
                                           "stock_code": "005930"}))
        mp.setattr(srv, "fetch_financial_statements",
                   lambda *a, **kw: items if items is not None else _ITEMS)
        return srv.get_financial_summary("삼성전자", "2024")


def _compare(items=None):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(srv, "_DART_API_KEY", "k")
        mp.setattr(srv, "resolve_corp",
                   lambda q, k: (q, {"corp_code": {"삼성전자": "00126380"}.get(q, "00001"),
                                     "stock_code": "005930"}))
        mp.setattr(srv, "fetch_multi_financial",
                   lambda *a, **kw: items if items is not None else _ITEMS)
        return srv.compare_financials(["삼성전자", "셀트리온"], "2024")


class TestLabel:
    @pytest.mark.parametrize("div,fs_nm,want", [
        ("CFS", "연결재무제표", "연결재무제표"),
        ("OFS", "재무제표", "별도재무제표"),   # DART 표기가 모호한 유일한 경우
        ("OFS", "", "별도재무제표"),
        ("CFS", "", "연결재무제표"),
        ("", "", "구분 미상"),
    ])
    def test_구분_라벨(self, div, fs_nm, want):
        assert _fs_div_label(div, fs_nm) == want


class TestSummary:
    def test_머리글이_실제_구분을_적는다(self):
        assert "연결재무제표 · 별도재무제표" in _summary()

    def test_본문이_구분별로_갈린다(self):
        out = _summary()
        assert "[연결재무제표]" in out and "[별도재무제표]" in out
        i, j = out.index("[연결재무제표]"), out.index("[별도재무제표]")
        assert out.index("514,531,948,000,000") > i
        assert out.index("324,966,127,000,000") > j

    def test_같은_계정_중복을_접는다(self):
        assert _summary().count("34,451,351,000,000") == 1

    def test_구분이_하나면_섹션_머리를_붙이지_않는다(self):
        only = [r for r in _ITEMS if r["fs_div"] == "CFS"]
        out = _summary(only)
        assert "[연결재무제표]" not in out
        assert "| 연결재무제표" in out


class TestCompare:
    def test_머리글이_회사명이다(self):
        """응답에 `corp_name`이 없어 옛 코드는 종목코드를 냈다."""
        out = _compare()
        assert "━━ 삼성전자 ━━" in out
        assert "━━ 005930 ━━" not in out

    def test_구분이_라벨된다(self):
        out = _compare()
        assert "[연결재무제표]" in out and "[별도재무제표]" in out

    def test_중복을_접는다(self):
        assert _compare().count("34,451,351,000,000") == 1


def test_없는_필드를_다시_읽지_않는다():
    import pathlib
    import re

    src = pathlib.Path(srv.__file__).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    # fnlttMultiAcnt 응답에는 corp_name이 없다 — 폴백으로 감춰선 안 된다.
    assert not re.search(r'item\.get\("corp_name"', code)
