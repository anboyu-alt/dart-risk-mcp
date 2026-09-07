"""스위트 공통 — 가짜 키로 DART를 실제 호출하는 테스트를 잡는다 (2026-09-07).

## 왜

도구 하나가 fetcher를 여럿 부른다. 테스트가 공시 목록만 mock하고 나머지
(자금사용·채무잔액·부실 이벤트·메자닌·희석 …)를 잊으면, 도구는 패치된 가짜 키
`"k"`로 **DART에 실제 요청**을 보낸다. 전수 측정(키 없는 환경): **13개 테스트가
231회**를 보내고 있었고 그 시간이 스위트 175초 중 약 96초였다. CI는 이 요청을
매 실행마다 DART에 던지고 있었다 — 결과에는 영향이 없었지만 느리고, 분당
스로틀·키 차단의 원인이 될 수 있다.

## 무엇을 한다

`requests.Session.request`를 감싸, 호스트가 opendart이고 `crtfc_key`가 실제
env 키와 다르면(키 없는 환경에서는 전부) **DART가 등록되지 않은 키에 주는
응답과 같은 모양**(HTTP 200 · `{"status": "010", …}`)을 즉시 돌려주고 기록한다.
fetcher 쪽 동작은 실제 거절과 같으므로 도구 출력은 변하지 않고, 네트워크와
재시도 sleep만 사라진다. 테스트가 끝나면 기록이 있을 때 **그 테스트를 실패**시켜
어느 fetcher를 mock해야 하는지 알린다.

실제 키로 부르는 호출(골든 재생성·`DART_API_KEY 없음`으로 skip되는 테스트들)은
그대로 통과시킨다 — 이 가드는 「의도치 않은 호출」만 잡는다.

## 어떻게 고치나

`@pytest.mark.usefixtures("no_structured_dart")`를 붙이거나 `stub_structured_fetchers(
monkeypatch)`를 부른다. 도구가 새 fetcher를 부르게 되면 `STRUCTURED_FETCH_STUBS`에
**빈 성공 응답**을 하나 더 적는다(반환 모양이 fetcher마다 다르다 — 리스트로
뭉뚱그리면 도구가 TypeError로 죽는다).
"""

from __future__ import annotations

import json
import os
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

import dart_risk_mcp.server as srv
from dart_risk_mcp.core.dart_client import DART_BASE, FetchList

# 호스트는 코드의 상수에서 읽는다 — 손으로 적으면 틀린다(첫 판이 fss를 fsc로
# 적어 가드가 아무것도 못 잡았다. `opendart.fss.or.kr`이 맞다).
_DART_HOST = urlsplit(DART_BASE).netloc
_REAL_KEY = os.environ.get("DART_API_KEY", "")


# ---------------------------------------------------------------- 스텁 묶음

def _empty_debt_balance(*a, **k):
    # dart_client.fetch_debt_balance의 `empty`와 같은 키
    return {"year": None, "by_kind": {}, "total": 0,
            "maturity_1y_share": 0.0, "equity_ratio": None}


def _empty_mezzanine(*a, **k):
    return {"rows": [], "failed_kinds": [], "fetch_failed": False}


# 도구가 공시 목록 외에 따로 부르는 구조화 fetcher — **빈 성공 응답**.
STRUCTURED_FETCH_STUBS = {
    "fetch_fund_usage": lambda *a, **k: FetchList(),
    "fetch_financial_statements_all": lambda *a, **k: FetchList(),
    "fetch_financial_statements": lambda *a, **k: [],
    "fetch_distress_events": lambda *a, **k: [],
    "fetch_dividend_history": lambda *a, **k: [],
    "fetch_treasury_decisions": lambda *a, **k: [],
    "fetch_debt_balance": _empty_debt_balance,
    "fetch_executive_roster_detail": lambda *a, **k: [],
    "fetch_mezzanine_decisions": _empty_mezzanine,
    "fetch_stock_totals": lambda *a, **k: [],
    "fetch_issuance_history": lambda *a, **k: [],
    "fetch_affiliate_investments": lambda *a, **k: [],
    "fetch_document_text": lambda *a, **k: "",
    "extract_cb_investors": lambda *a, **k: [],
}


def stub_structured_fetchers(monkeypatch) -> None:
    """서버 모듈의 구조화 fetcher 전부를 빈 성공 응답으로 바꾼다."""
    for name, fn in STRUCTURED_FETCH_STUBS.items():
        assert hasattr(srv, name), f"server.{name}이 없다 — STRUCTURED_FETCH_STUBS를 고쳐라"
        monkeypatch.setattr(srv, name, fn)


@pytest.fixture
def no_structured_dart(monkeypatch):
    """공시 목록만 mock하는 도구 테스트에 붙인다 — 나머지 fetcher가 DART로 새지 않게."""
    stub_structured_fetchers(monkeypatch)


# ---------------------------------------------------------------- 가드

def _fake_dart_rejection(url: str) -> requests.Response:
    """DART가 등록되지 않은 키에 주는 응답 모양 — 2026-09-07 라이브 실측 그대로:
    HTTP 200 · `{"status":"010","message":"등록되지 않은 인증키입니다."}`."""
    r = requests.Response()
    r.status_code = 200
    r.url = url
    r.headers["Content-Type"] = "application/json;charset=UTF-8"
    r._content = json.dumps(
        {"status": "010", "message": "등록되지 않은 인증키입니다."},
        ensure_ascii=False,
    ).encode("utf-8")
    r.encoding = "utf-8"
    return r


def _key_of(url: str, kwargs: dict) -> str:
    params = kwargs.get("params") or {}
    if isinstance(params, dict) and params.get("crtfc_key"):
        return str(params["crtfc_key"])
    return parse_qs(urlsplit(url).query).get("crtfc_key", [""])[0]


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    leaks: list[str] = []
    real_request = requests.Session.request

    def guarded(self, method, url, *args, **kwargs):
        if _DART_HOST in urlsplit(url).netloc:
            key = _key_of(url, kwargs)
            if not _REAL_KEY or key != _REAL_KEY:
                leaks.append(urlsplit(url).path.rsplit("/", 1)[-1])
                return _fake_dart_rejection(url)
        return real_request(self, method, url, *args, **kwargs)

    requests.Session.request = guarded
    try:
        result = yield
    finally:
        requests.Session.request = real_request

    if leaks:
        from collections import Counter

        summary = ", ".join(f"{ep}×{n}" for ep, n in Counter(leaks).most_common())
        pytest.fail(
            "가짜 키로 DART를 실제 호출했다 — mock이 빠진 fetcher가 있다.\n"
            f"  엔드포인트: {summary}\n"
            "  고치는 법: @pytest.mark.usefixtures(\"no_structured_dart\") 또는 "
            "stub_structured_fetchers(monkeypatch). 새 fetcher면 "
            "tests/conftest.py의 STRUCTURED_FETCH_STUBS에 빈 성공 응답을 추가.",
            pytrace=False,
        )
    return result
