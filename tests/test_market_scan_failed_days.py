"""시장 스캔에서 **조회에 실패한 날**이 조용히 빠지지 않는지 잠근다.

`search_market_disclosures`는 창을 하루 단위로 쪼개 `/list.json`을 반복
호출한다. 어느 하루가 실패해도 빈 목록이 돌아와 그날이 통째로 빠지는데,
화면에는 "전체 N건 중 관찰 신호 M건"이라 적혀 **스캔이 완전했던 것처럼**
보였다(2026-08-23 후속 감사).

같은 도구가 **절단**(하루 7,000건 상한 도달)은 이미 알리고 있었다 —
알릴 자리가 있는데 실패만 안 알리고 있었던 것이다.

⚠ 휴장일·주말은 DART가 013(자료 없음)을 준다. 실패로 세면 **주말마다**
경고가 뜬다 — `FETCH_EMPTY`와 `FETCH_ERROR`를 갈라야 하는 이유다.
"""
from unittest.mock import patch

import dart_risk_mcp.server as srv
from dart_risk_mcp.core.dart_client import FETCH_EMPTY, FETCH_ERROR, FETCH_OK

ROW = {
    "rcept_no": "20260810000001",
    "corp_name": "테스트회사",
    "rcept_dt": "20260810",
    "report_nm": "주요사항보고서(전환사채권발행결정)",
    "corp_cls": "K",
}


def _scan(day_results, **kwargs):
    """하루치 응답을 순서대로 돌려주며 스캔을 돌린다."""
    seq = list(day_results)

    def _fake(api_key, bgn, end, **kw):
        return seq.pop(0) if seq else ([], FETCH_EMPTY)

    with patch.object(srv, "_DART_API_KEY", "k"), \
         patch.object(srv, "fetch_market_disclosures_with_status", side_effect=_fake):
        fn = getattr(srv.search_market_disclosures, "fn", srv.search_market_disclosures)
        return fn(**kwargs)


def test_실패한_날을_헤더와_안내로_알린다():
    out = _scan(
        [([ROW], FETCH_OK), ([], FETCH_ERROR), ([], FETCH_EMPTY)],
        preset="cb_issue", days=3,
    )
    assert "조회 실패 1일 제외" in out, out[:300]
    assert "그날 신호가 없다는 뜻이 아닙니다" in out


def test_휴장일은_실패가_아니다():
    """013(자료 없음)까지 실패로 세면 주말마다 경고가 뜬다."""
    out = _scan(
        [([ROW], FETCH_OK), ([], FETCH_EMPTY), ([], FETCH_EMPTY)],
        preset="cb_issue", days=3,
    )
    assert "조회 실패" not in out
    assert "그날 신호가 없다는 뜻이 아닙니다" not in out


def test_결과가_0건이어도_실패했으면_체크표시로_단정하지_않는다():
    out = _scan(
        [([], FETCH_ERROR), ([ROW], FETCH_OK)],
        preset="audit_issue", days=2,   # ROW는 CB 공시라 이 preset에 안 걸린다
    )
    assert "✅ 해당 기간에" not in out
    assert "조회하지 못했습니다" in out


def test_전부_정상이고_0건이면_기존_문구_그대로():
    out = _scan([([ROW], FETCH_OK)], preset="audit_issue", days=1)
    assert "✅ 해당 기간에" in out
    assert "조회 실패" not in out


def test_옛_함수는_목록만_돌려준다():
    """하위 호환 — `fetch_market_disclosures`는 여전히 list를 반환한다."""
    from dart_risk_mcp.core.dart_client import fetch_market_disclosures

    with patch("dart_risk_mcp.core.dart_client.fetch_market_disclosures_with_status",
               return_value=([ROW], FETCH_OK)):
        rows = fetch_market_disclosures("k", "20260810", "20260810")
    assert isinstance(rows, list) and rows == [ROW]


def test_키가_없으면_실패다():
    from dart_risk_mcp.core.dart_client import fetch_market_disclosures_with_status

    assert fetch_market_disclosures_with_status("", "20260810", "20260810") == ([], FETCH_ERROR)
