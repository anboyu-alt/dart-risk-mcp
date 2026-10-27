"""임원 명부 fetcher `fetch_executive_roster_rows` + `periodic_report_code` (이사회 이해상충 점검 Task 3).

네트워크 계층만 본다 — 000(행)·013(없음, 캐시)·020(실패, 캐시 안 함)·예외.
"""
import pytest

import dart_risk_mcp.core.dart_client as dc
from dart_risk_mcp.core.dart_client import (
    FetchList,
    fetch_executive_roster_rows,
    periodic_report_code,
)


class _Resp:
    status_code = 200
    text = ""
    content = b""

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


_ROW = {
    "nm": "홍길동", "birth_ym": "1970년 01월", "ofcps": "사내이사",
    "rgist_exctv_at": "등기임원", "chrg_job": "경영총괄",
    "main_career": "前 ㈜가나다 대표", "mxmm_shrholdr_relate": "본인",
    "hffc_pd": "3년", "fte_at": "상근",
    # 아래는 읽지 않는 키 — 결과에 실리면 안 된다
    "rcept_no": "20260101000001", "corp_code": "00126380", "sexdstn": "남",
}
_NINE = {"nm", "birth_ym", "ofcps", "rgist_exctv_at", "chrg_job",
         "main_career", "mxmm_shrholdr_relate", "hffc_pd", "fte_at"}


@pytest.fixture(autouse=True)
def _clean_cache():
    dc._roster_rows_cache.clear()
    yield
    dc._roster_rows_cache.clear()


def _patch(monkeypatch, fn):
    calls = []

    def _wrapped(*a, **k):
        calls.append((a, k))
        return fn(*a, **k)

    monkeypatch.setattr(dc, "_retry", _wrapped)
    return calls


def test_000_아홉_키만_담고_계_합계는_뺀다(monkeypatch):
    payload = {"status": "000", "list": [
        dict(_ROW),
        {"nm": "계", "ofcps": ""},
        {"nm": "합계"},
        {"nm": "  ", "ofcps": "x"},
    ]}
    _patch(monkeypatch, lambda *a, **k: _Resp(payload))
    out = fetch_executive_roster_rows("00126380", "K", "2025")
    assert isinstance(out, FetchList) and out.fetch_failed is False
    assert len(out) == 1
    assert set(out[0]) == _NINE
    assert out[0]["nm"] == "홍길동" and out[0]["main_career"] == "前 ㈜가나다 대표"


def test_요청_파라미터와_기본_보고서코드(monkeypatch):
    calls = _patch(monkeypatch, lambda *a, **k: _Resp({"status": "000", "list": []}))
    fetch_executive_roster_rows("00126380", "KEY", "2025")
    (a, k), = calls
    assert a[0] == "GET" and a[1].endswith("/exctvSttus.json")
    assert k["params"] == {"crtfc_key": "KEY", "corp_code": "00126380",
                           "bsns_year": "2025", "reprt_code": "11011"}


def test_013은_빈_성공이고_캐시된다(monkeypatch):
    calls = _patch(monkeypatch, lambda *a, **k: _Resp({"status": "013"}))
    r1 = fetch_executive_roster_rows("c", "K", "2025")
    r2 = fetch_executive_roster_rows("c", "K", "2025")
    assert list(r1) == [] and r1.fetch_failed is False
    assert r2.fetch_failed is False
    assert len(calls) == 1
    assert ("roster_rows", "c", "2025", "11011") in dc._roster_rows_cache


def test_020은_실패이고_캐시하지_않는다(monkeypatch):
    calls = _patch(monkeypatch, lambda *a, **k: _Resp({"status": "020"}))
    r1 = fetch_executive_roster_rows("c", "K", "2025")
    assert list(r1) == [] and r1.fetch_failed is True
    fetch_executive_roster_rows("c", "K", "2025")
    assert len(calls) == 2
    assert not dc._roster_rows_cache


def test_예외는_실패이고_캐시하지_않는다(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    calls = _patch(monkeypatch, boom)
    r = fetch_executive_roster_rows("c", "K", "2025")
    assert list(r) == [] and r.fetch_failed is True
    fetch_executive_roster_rows("c", "K", "2025")
    assert len(calls) == 2


def test_응답_없음_None도_실패(monkeypatch):
    _patch(monkeypatch, lambda *a, **k: None)
    assert fetch_executive_roster_rows("c", "K", "2025").fetch_failed is True


def test_보고서코드별로_캐시가_갈린다(monkeypatch):
    calls = _patch(monkeypatch, lambda *a, **k: _Resp({"status": "000", "list": [dict(_ROW)]}))
    fetch_executive_roster_rows("c", "K", "2025", "11011")
    fetch_executive_roster_rows("c", "K", "2025", "11012")
    assert len(calls) == 2


def test_키_또는_회사코드가_없으면_실패가_아니라_빈_결과(monkeypatch):
    calls = _patch(monkeypatch, lambda *a, **k: _Resp({"status": "000"}))
    assert list(fetch_executive_roster_rows("", "K", "2025")) == []
    assert list(fetch_executive_roster_rows("c", "", "2025")) == []
    assert calls == []


@pytest.mark.parametrize("title,expected", [
    ("사업보고서 (2025.12)", ("2025", "11011")),
    ("[기재정정]사업보고서 (2025.12)", ("2025", "11011")),
    ("반기보고서 (2026.06)", ("2026", "11012")),
    ("분기보고서 (2026.03)", ("2026", "11013")),
    ("분기보고서 (2026.09)", ("2026", "11014")),
    ("주요사항보고서(전환사채권발행결정)", None),
])
def test_periodic_report_code(title, expected):
    assert periodic_report_code(title) == expected
