# -*- coding: utf-8 -*-
"""list_disclosures_by_stock — 종목코드가 없는 회사도 공시 목록을 낸다.

2026-11-06 실측: 상장을 준비하는 비상장사(데스틴파워 01135039)의 증권신고서는
접수번호만 알면 `list_disclosure_sections`·`view_disclosure`로 읽히는데, 그
접수번호를 **찾을 길이 없었다** — 이 도구가 6자리 종목코드만 받아
「데스틴파워」를 넣으면 「종목코드는 6자리 숫자여야 합니다」로 거절했다.
다른 도구(`analyze_company_risk`·`get_company_info`)는 이미 회사명을 받는다.

인자 이름 `stock_code`는 그대로다(하위 호환). 받는 값만 넓힌다 —
종목코드 6자리 · 회사명 · DART 기업코드 8자리.

동명 법인은 `get_unlisted_financials`와 같은 태도다 — 어느 쪽인지 알 수
없으면 고르지 않고 되묻는다(실측 '올품' 00442385는 공시 0건). 동명 중
상장사가 하나뿐이면 `resolve_corp`의 기존 선택(상장 우선)을 따르고 나머지를
알린다.
"""
from unittest.mock import patch

from dart_risk_mcp import server as srv
from dart_risk_mcp.core import FETCH_OK

_ROWS = [
    {"rcept_no": "20261028000434", "rcept_dt": "20261028",
     "report_nm": "증권신고서(지분증권)", "corp_name": "데스틴파워"},
]


def _run(query, *, resolve=None, cands=None, name_by_code="", rows=None):
    captured = {}

    def _fetch(corp_code, api_key, lookback_days, max_pages=10, bgn_de="", end_de=""):
        captured["corp_code"] = corp_code
        return list(_ROWS if rows is None else rows), FETCH_OK

    with patch.object(srv, "_DART_API_KEY", "k"), \
         patch.object(srv, "resolve_corp", return_value=resolve) as m_resolve, \
         patch.object(srv, "find_corp_candidates", return_value=cands or []), \
         patch.object(srv, "corp_name_by_code", return_value=name_by_code), \
         patch.object(srv, "fetch_company_disclosures_with_status", side_effect=_fetch):
        out = srv.list_disclosures_by_stock(query)
    captured["resolve_called"] = m_resolve.called
    return out, captured


def test_회사명으로_비상장사_공시_목록을_낸다():
    out, cap = _run(
        "데스틴파워",
        resolve=("데스틴파워", {"corp_code": "01135039", "stock_code": ""}),
        cands=[{"corp_code": "01135039", "stock_code": "", "modify_date": ""}],
    )
    assert cap["corp_code"] == "01135039"
    assert "20261028000434" in out
    assert "**데스틴파워**" in out
    # 종목코드가 없다는 사실과, 다시 부를 수 있는 기업코드를 머리에 적는다
    assert "종목코드 없음 · 기업코드 01135039" in out
    assert "6자리 숫자여야" not in out


def test_기업코드_8자리를_그대로_받는다():
    out, cap = _run(
        "01135039", name_by_code="데스틴파워",
        cands=[{"corp_code": "01135039", "stock_code": "", "modify_date": ""}],
    )
    assert cap["corp_code"] == "01135039"
    assert cap["resolve_called"] is False  # 이름 해석을 거치지 않는다
    assert "**데스틴파워**" in out
    assert "기업코드 01135039" in out


def test_기업코드로_찾은_상장사는_종목코드를_적는다():
    out, _ = _run(
        "00126380", name_by_code="삼성전자",
        cands=[{"corp_code": "00126380", "stock_code": "005930", "modify_date": ""}],
    )
    assert "**삼성전자** (005930)" in out


def test_명부에_없는_기업코드는_거절한다():
    out, cap = _run("09999999", name_by_code="")
    assert out.startswith("❌")
    assert "09999999" in out
    assert "corp_code" not in cap  # 공시 목록을 조회하지 않았다


def test_비상장_동명_법인은_고르지_않고_되묻는다():
    out, cap = _run(
        "올품",
        resolve=("올품", {"corp_code": "00455750", "stock_code": ""}),
        cands=[{"corp_code": "00455750", "stock_code": "", "modify_date": "20240101"},
               {"corp_code": "00442385", "stock_code": "", "modify_date": "20170101"}],
    )
    assert "corp_code" not in cap
    assert "00455750" in out and "00442385" in out
    assert "조회하지 않았습니다" in out
    # 다시 부르는 법은 이 도구의 것이어야 한다
    assert "list_disclosures_by_stock" in out
    assert "get_unlisted_financials" not in out


def test_동명_중_상장사가_하나면_그쪽을_조회하고_나머지를_알린다():
    out, cap = _run(
        "앤로보틱스",
        resolve=("앤로보틱스", {"corp_code": "00808068", "stock_code": "138360"}),
        cands=[{"corp_code": "00808068", "stock_code": "138360", "modify_date": "20260115"},
               {"corp_code": "01358296", "stock_code": "", "modify_date": "20230101"}],
    )
    assert cap["corp_code"] == "00808068"
    assert "**앤로보틱스** (138360)" in out
    assert "01358296" in out  # 동명의 다른 법인을 숨기지 않는다


def test_종목코드_경로의_머리글은_그대로다():
    out, cap = _run(
        "005930",
        resolve=("삼성전자", {"corp_code": "00126380", "stock_code": "005930"}),
    )
    assert cap["corp_code"] == "00126380"
    assert out.startswith("📋 **삼성전자** (005930) 공시 접수번호 목록")


def test_빈_입력은_거절한다():
    for q in ("", "   ", None):
        out, cap = _run(q)
        assert out.startswith("❌"), q
        assert "corp_code" not in cap


def test_못_찾은_이름은_종목코드_형식_탓을_하지_않는다():
    out, _ = _run("없는회사이름", resolve=None)
    assert out.startswith("❌")
    assert "없는회사이름" in out
    assert "6자리 숫자여야" not in out


def test_없는_종목코드_안내는_그대로다():
    out, _ = _run("999999", resolve=None)
    assert "종목코드 '999999'에 해당하는 기업을 DART에서 찾을 수 없습니다" in out


def test_비상장_재무_도구의_되물음이_옛_제약을_말하지_않는다():
    """`get_unlisted_financials`의 동명 안내가 「list_disclosures_by_stock은
    종목코드 전용」이라 적고 있었다 — 이제 사실이 아니다."""
    blk = srv._unlisted_candidate_block(
        "올품",
        [{"corp_code": "00455750", "stock_code": "", "modify_date": "20240101"},
         {"corp_code": "00442385", "stock_code": "", "modify_date": "20170101"}],
    )
    assert "종목코드 전용" not in blk
    assert "get_unlisted_financials" in blk
