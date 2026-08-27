"""구조화 fetcher가 **못 받은 것을 「없다」로 말하지 않는지** 잠근다 (2026-08-27).

`test_error_path_honesty`(2026-08-23)는 이 결함을 **공시 목록 경로**에서
닫았다. 같은 검사를 **구조화 데이터 fetcher**로 넓히니 여섯 도구가 남아
있었다 — DART가 `status` 020(한도 초과)을 HTTP 200 본문으로 주는데,
fetcher들이 그걸 빈 리스트로 접어 도구가 이렇게 말했다.

    track_insider_trading      최근 2년간 대량보유·최대주주 공시 **없음**
    track_fund_usage           등록된 공모/사모 자금사용내역이 **없습니다**
    get_audit_opinion_history  감사의견 공시를 **찾지 못했습니다**
    track_debt_balance         미상환 채무증권 잔액이 **없거나** …
    get_affiliate_investments  타법인 출자 내역을 **찾지 못했습니다**
    scan_financial_anomaly     재무제표 조회 불가(데이터 없음 **또는** 권한 부족)

전부 **회사에 대한 진술**로 읽힌다 — 한도가 찬 것뿐인데 「이 회사는
조용하다」가 된다. 마지막 것은 두 가지를 한 문장에 섞어 아무것도 알려
주지 않았다.

## 어떻게 알렸나

리스트를 돌려주는 fetcher는 `FetchList`(list 상속 + `.fetch_failed`),
dict를 돌려주는 쪽은 `fetch_failed` 키. `list`를 상속하므로 기존 호출부는
그대로 동작한다.

⚠ **못 받은 결과는 캐시하지 않는다** — 이 규칙을 넣기 전에는 일시적 실패가
10분 동안 붙들려, 한도가 풀린 뒤에도 같은 거짓말을 되풀이했다(이 테스트를
쓰다 실제로 걸렸다).
"""
from unittest.mock import patch

import pytest

import dart_risk_mcp.core.dart_client as dc
import dart_risk_mcp.server as srv
from dart_risk_mcp.core.dart_client import FetchList, fetch_failed


class _Resp:
    status_code = 200
    text = ""
    content = b""

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


_QUOTA = lambda *a, **k: _Resp({"status": "020", "message": "요청 제한 초과"})
_EMPTY = lambda *a, **k: _Resp({"status": "013"})

TOOLS = [
    ("track_insider_trading", lambda: srv.track_insider_trading("삼성전자")),
    ("track_fund_usage", lambda: srv.track_fund_usage("삼성전자")),
    ("get_audit_opinion_history", lambda: srv.get_audit_opinion_history("삼성전자")),
    ("track_debt_balance", lambda: srv.track_debt_balance("삼성전자")),
    ("get_affiliate_investments", lambda: srv.get_affiliate_investments("삼성전자")),
    ("scan_financial_anomaly", lambda: srv.scan_financial_anomaly("삼성전자")),
]
# 「없다」로 읽히는 말 — 이게 나오면 회사에 대한 거짓 진술이다.
ABSENCE = ("없음", "없습니다", "찾지 못했습니다", "조회되지 않아")


def _clear_caches():
    for c in (dc._debt_balance_cache, dc._fund_usage_cache,
              dc._audit_history_cache):
        c.clear()


def _run(call, side):
    _clear_caches()
    with patch.object(srv, "_DART_API_KEY", "k"), \
         patch.object(dc, "_retry", side_effect=side), \
         patch.object(srv, "resolve_corp",
                      return_value=("삼성전자", {"corp_code": "00126380",
                                              "stock_code": "005930"})):
        return call()


@pytest.mark.parametrize("name,call", TOOLS, ids=[t[0] for t in TOOLS])
def test_한도초과를_부재로_말하지_않는다(name, call):
    out = _run(call, _QUOTA)
    assert "자료가 없다는 뜻이 아닙니다" in out, (
        f"{name}: 못 받았는데 부재처럼 말한다 — {out.splitlines()[0][:60]!r}")
    assert not any(w in out.split("**자료가 없다는")[0] for w in ABSENCE), name


@pytest.mark.parametrize("name,call", TOOLS, ids=[t[0] for t in TOOLS])
def test_진짜_부재를_실패로_말하지_않는다(name, call):
    """013(자료 없음)은 정상 답변이다 — 그걸 실패라 하면 그것도 거짓이다."""
    out = _run(call, _EMPTY)
    assert "자료가 없다는 뜻이 아닙니다" not in out, name


class TestFetchList:
    def test_리스트처럼_동작한다(self):
        f = FetchList([1, 2], fetch_failed=True)
        assert isinstance(f, list) and len(f) == 2 and f[0] == 1
        assert list(f) == [1, 2] and bool(FetchList()) is False

    def test_기본은_실패가_아니다(self):
        assert FetchList([1]).fetch_failed is False

    @pytest.mark.parametrize("v,want", [
        (FetchList([], fetch_failed=True), True),
        (FetchList([]), False),
        ({"fetch_failed": True}, True),
        ({}, False), ([], False), (None, False),
    ])
    def test_판별_함수(self, v, want):
        assert fetch_failed(v) is want


class TestNoFailureCaching:
    """일시적 실패를 10분 붙들면 한도가 풀린 뒤에도 거짓말이 남는다."""

    def test_실패는_캐시되지_않는다(self):
        _clear_caches()
        with patch.object(dc, "_retry", side_effect=_QUOTA):
            first = dc.fetch_debt_balance("00126380", "k", "2024")
        assert first["fetch_failed"] is True
        assert not dc._debt_balance_cache, "실패가 캐시에 남았다"

    def test_성공은_캐시된다(self):
        _clear_caches()
        ok = lambda *a, **k: _Resp({"status": "013"})
        with patch.object(dc, "_retry", side_effect=ok):
            dc.fetch_debt_balance("00126380", "k", "2024")
        assert dc._debt_balance_cache, "정상 결과까지 캐시를 막으면 안 된다"
