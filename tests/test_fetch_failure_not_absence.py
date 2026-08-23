"""조회 **실패**가 "신호 없음"으로 퇴화하지 않는지 잠근다.

v1.17.0이 `check_disclosure_risk`에서 고치고, 2026-08-23 에러 경로 감사가
`fetch_company_disclosures_with_status`를 만들어 4개 도구에 배선한 결함이다.
같은 감사의 후속에서 **두 곳이 남아 있었다**:

| 도구 | 실패 시 나오던 화면 |
|---|---|
| `track_capital_structure` | "자본 주무르기로 볼 만한 리듬은 없습니다" |
| `find_actor_overlap` | "2곳 이상에 동시에 등장한 인수자는 발견되지 않았습니다" |

둘 다 **단정문**이다. 리스크를 알리는 도구에서 "못 받았다"와 "없다"가
같은 화면이면 안 된다.

⚠ `track_insider_trading`(4204)은 같은 호출을 하지만 결과를 `if pre_flags:`로만
쓴다 — 부재를 주장하지 않으므로 이 목록에 없다(감사에서 확인하고 안 고쳤다).
"""
import pytest

import dart_risk_mcp.server as srv
from dart_risk_mcp.core.dart_client import FETCH_EMPTY, FETCH_ERROR, FETCH_OK

# 부재를 **단정**하는 문구 — 실패 화면에 절대 나오면 안 된다
ABSENCE_CLAIMS = (
    "리듬은 없습니다",
    "발견되지 않았습니다",
    "감지되지 않았습니다",
)

FAILURE_MARK = "자료가 없다는 뜻이 아닙니다"


@pytest.fixture
def _stub(monkeypatch):
    """모든 조회가 실패하는 세상을 만든다."""
    monkeypatch.setattr(srv, "_DART_API_KEY", "TESTKEY", raising=False)
    monkeypatch.setattr(
        srv, "resolve_corp",
        lambda q, k: ("테스트회사", {"corp_code": "00000000", "stock_code": "000000"}),
    )
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: ([], FETCH_ERROR),
    )
    monkeypatch.setattr(srv, "fetch_company_disclosures", lambda *a, **kw: [])
    for name in ("fetch_executive_roster", "extract_cb_investors",
                 "fetch_treasury_decisions"):
        if hasattr(srv, name):
            monkeypatch.setattr(srv, name, lambda *a, **kw: [])
    # 반환 모양이 다르다 — 리스트로 스텁하면 도구가 TypeError로 죽는다
    monkeypatch.setattr(
        srv, "fetch_debt_balance",
        lambda *a, **kw: {"total": 0, "year": None, "by_type": {}, "within_1y_ratio": None},
    )


def _call(fn, *args, **kwargs):
    """MCP 도구 데코레이터를 벗겨 원 함수를 부른다."""
    return getattr(fn, "fn", fn)(*args, **kwargs)


def test_자본구조_도구가_실패를_부재로_말하지_않는다(_stub):
    out = _call(srv.track_capital_structure, "테스트회사", lookback_years=3)
    assert FAILURE_MARK in out, out[:400]
    for claim in ABSENCE_CLAIMS:
        assert claim not in out, f"실패 화면에 단정문이 있다: {claim}"


def test_겸직비교_도구가_실패를_부재로_말하지_않는다(_stub):
    out = _call(srv.find_actor_overlap, ["가회사", "나회사"], lookback_years=1)
    assert FAILURE_MARK in out, out[:400]
    assert "발견되지 않았습니다" not in out


def test_일부만_실패하면_빠진_회사를_알린다(monkeypatch, _stub):
    """한 회사만 실패 — 비교는 하되 **무엇이 빠졌는지** 말해야 한다."""
    calls = {"n": 0}

    def _mixed(corp_code, api_key, **kw):
        calls["n"] += 1
        return ([], FETCH_ERROR) if calls["n"] == 1 else ([], FETCH_OK)

    monkeypatch.setattr(srv, "fetch_company_disclosures_with_status", _mixed)
    out = _call(srv.find_actor_overlap, ["가회사", "나회사"], lookback_years=1)
    assert "비교에서 빠진 기업" in out
    assert "가회사" in out
    assert "신호가 없다는 뜻이 아닙니다" in out


def test_자료가_정말_없으면_부재를_말해도_된다(monkeypatch, _stub):
    """FETCH_EMPTY는 실패가 아니다 — 이 경우엔 단정해도 맞다.

    실패 안내를 넓게 깔아 "자료 없음"까지 덮으면 반대 방향의 거짓이 된다.
    """
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status", lambda *a, **kw: ([], FETCH_EMPTY)
    )
    out = _call(srv.track_capital_structure, "테스트회사", lookback_years=3)
    assert FAILURE_MARK not in out
    assert "리듬은 없습니다" in out


def test_상태값_세_개가_구분된다():
    assert len({FETCH_OK, FETCH_EMPTY, FETCH_ERROR}) == 3


def test_부재_단정_도구는_전부_상태를_본다():
    """새 도구가 단정문을 쓰면서 상태를 안 보면 여기서 걸린다."""
    import inspect

    src = inspect.getsource(srv)
    for name in ("track_capital_structure", "find_actor_overlap"):
        fn = getattr(srv, name)
        body = inspect.getsource(getattr(fn, "fn", fn))
        assert "FETCH_ERROR" in body, f"{name}이 조회 실패를 구분하지 않는다"
    assert "fetch_company_disclosures_with_status" in src
