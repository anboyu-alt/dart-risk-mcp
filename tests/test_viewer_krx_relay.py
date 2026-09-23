"""KRX 릴레이 3곳(`api/krx.js`·`relay/worker.js`·`scripts/dev_relay.py`)의 계약 대조.

설계: docs/superpowers/specs/2026-09-23-viewer-krx-panel-design.md
「릴레이 계약 (3곳 동일)」절.

이 라우트는 DART 경로(`api/[endpoint].js`)와 완전히 별개다 — 키가 헤더
`X-KRX-Key` → 업스트림 `AUTH_KEY`로 가고, 서버 키 주입·쿼터·CDN 캐시가
**없다**(KRX Open API 약관 제11조 ② — 운영자 키로 받은 시세를 방문자에게
보여 줄 수 없다). 세 파일이 복제 유지하는 화이트리스트·정규화 규칙이
어긋나면 어떤 환경에서만 조회가 실패하거나, 더 나쁘게는 서로 다른 값을
낸다 — `test_relay_whitelist_sync.py`·`test_viewer_twin_parity.py`와 같은
부류의 위험이다.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import subprocess

import pytest
import requests

from dart_risk_mcp.core.krx_client import (
    KRX_API_IDS,
    KRX_INDEX_API_IDS,
    KRX_INDEX_NAMES,
    _normalize_index_row,
    _normalize_row,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_API_KRX_JS = _ROOT / "api" / "krx.js"
_WORKER_JS = _ROOT / "relay" / "worker.js"
_DEV_RELAY_PY = _ROOT / "scripts" / "dev_relay.py"

_CORE_APIS = set(KRX_API_IDS.values())
_CORE_INDEX_APIS = set(KRX_INDEX_API_IDS.values())
_CORE_ALL_APIS = _CORE_APIS | _CORE_INDEX_APIS


def _src(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_dev_relay():
    spec = importlib.util.spec_from_file_location("dev_relay_krx_probe", _DEV_RELAY_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dev_relay_krx_block(src: str) -> str:
    """`_krx_relay` 정의부 + `/api/krx` 핸들러 분기만 떼어낸다.

    파일 전체(그리고 그 사이의 `/api/health`·`/api/doc`·`/api/corp` 분기)에는
    DART 경로의 `_env_key()`가 정당하게 있으므로, 「서버 키 없음」 검사는
    KRX 전용 구간 둘로 좁혀야 한다 — 함수 정의부와 라우팅 분기는 파일에서
    떨어져 있어 하나의 연속 구간으로 못 뗀다.
    """
    fn_start = src.index("def _krx_relay(")
    fn_end = src.index("class RelayHandler(")
    branch_start = src.index('if parts.path == "/api/krx":')
    branch_end = src.index('if parts.path.startswith("/api/"):')
    return src[fn_start:fn_end] + "\n" + src[branch_start:branch_end]


def _worker_krx_block(src: str) -> str:
    start = src.index("KRX Open API 릴레이")
    end = src.index("export default {")
    return src[start:end]


# ── ① 경로·헤더·no-store ────────────────────────────────────────

@pytest.mark.parametrize("path", [_API_KRX_JS, _WORKER_JS, _DEV_RELAY_PY],
                        ids=["api/krx.js", "relay/worker.js", "scripts/dev_relay.py"])
def test_세_파일_모두_krx_경로와_헤더를_갖는다(path):
    src = _src(path)
    assert "/api/krx" in src, f"{path}에 /api/krx 경로가 없다"
    assert "X-KRX-Key" in src, f"{path}에 X-KRX-Key 헤더가 없다"
    assert "AUTH_KEY" in src, f"{path}가 업스트림에 AUTH_KEY를 넘기지 않는다"
    assert "no-store" in src, f"{path}에 no-store 캐시 헤더가 없다"


# ── ② 서버 키·쿼터·캐시 부재 ─────────────────────────────────────

def test_Vercel_krx_라우트에_서버_키나_쿼터가_없다():
    src = _src(_API_KRX_JS)
    for bad in ("DART_API_KEY", "KRX_API_KEY", "checkQuota", "s-maxage", "process.env"):
        assert bad not in src, f"api/krx.js에 금지된 참조가 있다: {bad}"


def test_Cloudflare_krx_분기에_서버_키나_쿼터가_없다():
    block = _worker_krx_block(_src(_WORKER_JS))
    for bad in ("DART_API_KEY", "KRX_API_KEY", "checkQuota", "s-maxage"):
        assert bad not in block, f"relay/worker.js의 KRX 분기에 금지된 참조가 있다: {bad}"


def test_로컬_릴레이_krx_분기에_서버_키나_쿼터가_없다():
    block = _dev_relay_krx_block(_src(_DEV_RELAY_PY))
    for bad in ("KRX_API_KEY", "checkQuota", "s-maxage", "_env_key"):
        assert bad not in block, f"scripts/dev_relay.py의 KRX 분기에 금지된 참조가 있다: {bad}"


# ── ③ 허용 api 값이 core와 같다 ──────────────────────────────────

def test_core_KRX_API_IDS가_두_값이다():
    """정규식이 잘못 걸리면 아래 대조가 공집합끼리 비교해 조용히 통과한다."""
    assert _CORE_APIS == {"stk_bydd_trd", "ksq_bydd_trd"}


def test_core_KRX_INDEX_API_IDS가_두_값이다():
    assert _CORE_INDEX_APIS == {"kospi_dd_trd", "kosdaq_dd_trd"}


def test_core_KRX_INDEX_NAMES가_예상과_같다():
    assert KRX_INDEX_NAMES == {"kospi_dd_trd": "코스피", "kosdaq_dd_trd": "코스닥"}


def test_Vercel_허용_api가_core와_같다():
    src = _src(_API_KRX_JS)
    assert 'new Set(["stk_bydd_trd", "ksq_bydd_trd"])' in src.replace("\n", " ") or (
        "stk_bydd_trd" in src and "ksq_bydd_trd" in src
    )
    for api_id in _CORE_APIS:
        assert f'"{api_id}"' in src


def test_Cloudflare_허용_api가_core와_같다():
    block = _worker_krx_block(_src(_WORKER_JS))
    for api_id in _CORE_APIS:
        assert f'"{api_id}"' in block


def test_로컬_릴레이_허용_api가_core와_같다(monkeypatch):
    mod = _load_dev_relay()
    assert mod._KRX_ALLOWED_APIS == _CORE_ALL_APIS


# ── ③b 허용 api에 지수 2종도 포함된다 (종목 화이트리스트는 불변) ────

@pytest.mark.parametrize("path", [_API_KRX_JS, _WORKER_JS],
                        ids=["api/krx.js", "relay/worker.js"])
def test_JS_릴레이_허용_api에_지수_2종이_있다(path):
    src = _src(path)
    for api_id in _CORE_INDEX_APIS:
        assert f'"{api_id}"' in src, f"{path}에 {api_id}가 없다"


def test_로컬_릴레이_허용_api에_지수_2종이_있다():
    mod = _load_dev_relay()
    assert _CORE_INDEX_APIS <= mod._KRX_ALLOWED_APIS


def test_로컬_릴레이_허용_api_전체가_core_전체와_같다():
    mod = _load_dev_relay()
    assert mod._KRX_ALLOWED_APIS == _CORE_ALL_APIS


@pytest.mark.parametrize("path", [_API_KRX_JS, _WORKER_JS],
                        ids=["api/krx.js", "relay/worker.js"])
def test_JS_릴레이가_지수_경로_접두를_쓴다(path):
    """지수는 `svc/apis/idx/...`, 종목은 `svc/apis/sto/...` — 접두가 다르다."""
    src = _src(path)
    assert "svc/apis/idx" in src, f"{path}에 지수 경로 접두(idx)가 없다"
    assert "svc/apis/sto" in src, f"{path}에 종목 경로 접두(sto)가 없다"


# ── ④ 로컬 릴레이 — 400/401/200/502 (핸들러 클래스가 아니라 순수 함수를
#     직접 부른다: test_tool_server_doc.py·test_dev_relay_env_key.py의 관례) ──

@pytest.fixture()
def relay():
    return _load_dev_relay()


class _FakeResp:
    def __init__(self, status_code, payload=None, json_error=False):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("not json")
        return self._payload


def test_키가_없으면_400(relay):
    status, body = relay._krx_relay({"api": "stk_bydd_trd", "basDd": "20260101",
                                      "isu": "005930"}, "")
    assert status == 400
    assert body == {"ok": False, "error": "missing_key"}


@pytest.mark.parametrize("query", [
    {"api": "bogus", "basDd": "20260101", "isu": "005930"},
    {"api": "stk_bydd_trd", "basDd": "2026-01-01", "isu": "005930"},
    {"api": "stk_bydd_trd", "basDd": "20260101", "isu": "5930"},
    {"api": "stk_bydd_trd", "basDd": "20260101", "isu": ""},
])
def test_잘못된_파라미터는_400(relay, query):
    status, body = relay._krx_relay(query, "userkey")
    assert status == 400
    assert body == {"ok": False, "error": "bad_params"}


def test_업스트림_401은_401(relay, monkeypatch):
    monkeypatch.setattr(relay.requests, "get",
                        lambda *a, **k: _FakeResp(401))
    status, body = relay._krx_relay(
        {"api": "stk_bydd_trd", "basDd": "20260101", "isu": "005930"}, "userkey")
    assert status == 401
    assert body == {"ok": False, "error": "unauthorized"}


def test_업스트림_비200은_502(relay, monkeypatch):
    monkeypatch.setattr(relay.requests, "get",
                        lambda *a, **k: _FakeResp(500))
    status, body = relay._krx_relay(
        {"api": "stk_bydd_trd", "basDd": "20260101", "isu": "005930"}, "userkey")
    assert status == 502
    assert body == {"ok": False, "error": "upstream"}


def test_비JSON_응답은_502(relay, monkeypatch):
    monkeypatch.setattr(relay.requests, "get",
                        lambda *a, **k: _FakeResp(200, json_error=True))
    status, body = relay._krx_relay(
        {"api": "stk_bydd_trd", "basDd": "20260101", "isu": "005930"}, "userkey")
    assert status == 502
    assert body == {"ok": False, "error": "upstream"}


def test_OutBlock_1이_없으면_502(relay, monkeypatch):
    monkeypatch.setattr(relay.requests, "get",
                        lambda *a, **k: _FakeResp(200, {"unexpected": "shape"}))
    status, body = relay._krx_relay(
        {"api": "stk_bydd_trd", "basDd": "20260101", "isu": "005930"}, "userkey")
    assert status == 502
    assert body == {"ok": False, "error": "upstream"}


def test_요청_예외는_502(relay, monkeypatch):
    def boom(*a, **k):
        raise requests.RequestException("boom")
    monkeypatch.setattr(relay.requests, "get", boom)
    status, body = relay._krx_relay(
        {"api": "stk_bydd_trd", "basDd": "20260101", "isu": "005930"}, "userkey")
    assert status == 502
    assert body == {"ok": False, "error": "upstream"}


def test_빈_배열은_200_empty(relay, monkeypatch):
    """휴장일 또는 발표 전 — `found:false, empty:true`."""
    monkeypatch.setattr(relay.requests, "get",
                        lambda *a, **k: _FakeResp(200, {"OutBlock_1": []}))
    status, body = relay._krx_relay(
        {"api": "stk_bydd_trd", "basDd": "20260101", "isu": "005930"}, "userkey")
    assert status == 200
    assert body == {"ok": True, "found": False, "empty": True}


def test_그날_그_종목이_없으면_200_notempty(relay, monkeypatch):
    """시장 전체는 왔지만 그 종목이 없다 — 다른 시장(코스닥/유가)일 수 있다."""
    other_row = {"ISU_CD": "000660", "TDD_CLSPRC": "100000"}
    monkeypatch.setattr(relay.requests, "get",
                        lambda *a, **k: _FakeResp(200, {"OutBlock_1": [other_row]}))
    status, body = relay._krx_relay(
        {"api": "stk_bydd_trd", "basDd": "20260101", "isu": "005930"}, "userkey")
    assert status == 200
    assert body == {"ok": True, "found": False, "empty": False}


_SAMPLE_RAW = {
    "ISU_CD": "005930",
    "TDD_CLSPRC": "71,900",
    "FLUC_RT": "-1.23",
    "ACC_TRDVOL": "12,345,678",
    "ACC_TRDVAL": "888,000,000,000",
    "MKTCAP": "429,000,000,000,000",
    "LIST_SHRS": "5,969,782,550",
    "SECT_TP_NM": "  관리종목(소속부없음)  ",
}


def test_찾은_행이_core_normalize_row와_일치(relay, monkeypatch):
    monkeypatch.setattr(
        relay.requests, "get",
        lambda *a, **k: _FakeResp(200, {"OutBlock_1": [_SAMPLE_RAW]}),
    )
    status, body = relay._krx_relay(
        {"api": "stk_bydd_trd", "basDd": "20260101", "isu": "005930"}, "userkey")
    assert status == 200
    assert body["ok"] is True and body["found"] is True
    assert body["row"] == _normalize_row("20260101", _SAMPLE_RAW)


def test_AUTH_KEY_헤더로_사용자_키를_넘긴다(relay, monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen["url"] = url
        seen["params"] = params
        seen["headers"] = headers
        return _FakeResp(200, {"OutBlock_1": []})

    monkeypatch.setattr(relay.requests, "get", fake_get)
    relay._krx_relay(
        {"api": "ksq_bydd_trd", "basDd": "20260101", "isu": "005930"}, "MYUSERKEY")
    assert seen["headers"] == {"AUTH_KEY": "MYUSERKEY"}
    assert seen["params"] == {"basDd": "20260101"}
    assert "ksq_bydd_trd" in seen["url"]


# ── ④b 로컬 릴레이 — 지수(코스피·코스닥) 분기 ────────────────────────

def test_지수_요청은_isu_없이_통과한다(relay, monkeypatch):
    monkeypatch.setattr(relay.requests, "get",
                        lambda *a, **k: _FakeResp(200, {"OutBlock_1": []}))
    status, body = relay._krx_relay(
        {"api": "kospi_dd_trd", "basDd": "20260918"}, "userkey")
    assert status == 200
    assert body == {"ok": True, "found": False, "empty": True}


def test_지수_요청에_isu가_있어도_무시한다(relay, monkeypatch):
    """지수는 isu 필터를 쓰지 않는다 — 있어도 400이 되면 안 된다."""
    monkeypatch.setattr(relay.requests, "get",
                        lambda *a, **k: _FakeResp(200, {"OutBlock_1": []}))
    status, body = relay._krx_relay(
        {"api": "kospi_dd_trd", "basDd": "20260918", "isu": "005930"}, "userkey")
    assert status == 200
    assert body == {"ok": True, "found": False, "empty": True}


def test_지수_요청도_basDd_형식은_검증한다(relay):
    status, body = relay._krx_relay(
        {"api": "kospi_dd_trd", "basDd": "2026-09-18"}, "userkey")
    assert status == 400
    assert body == {"ok": False, "error": "bad_params"}


_IDX_KOSPI_FOREIGN = {
    "BAS_DD": "20260918", "IDX_CLSS": "KOSPI", "IDX_NM": "코스피 (외국주포함)",
    "CLSPRC_IDX": "9999.99", "CMPPREVDD_IDX": "1.00", "FLUC_RT": "0.01",
    "OPNPRC_IDX": "1", "HGPRC_IDX": "1", "LWPRC_IDX": "1",
    "ACC_TRDVOL": "1", "ACC_TRDVAL": "1", "MKTCAP": "1",
}
_IDX_KOSPI = {
    "BAS_DD": "20260918", "IDX_CLSS": "KOSPI", "IDX_NM": "코스피",
    "CLSPRC_IDX": "6894.23", "CMPPREVDD_IDX": "178.82", "FLUC_RT": "2.66",
    "OPNPRC_IDX": "6885.70", "HGPRC_IDX": "6914.08", "LWPRC_IDX": "6830.95",
    "ACC_TRDVOL": "346573461", "ACC_TRDVAL": "28104555485673",
    "MKTCAP": "5683776067592413",
}
_IDX_KOSDAQ = {
    "BAS_DD": "20260918", "IDX_CLSS": "KOSDAQ", "IDX_NM": "코스닥",
    "CLSPRC_IDX": "827.12", "CMPPREVDD_IDX": "4.94", "FLUC_RT": "0.60",
    "OPNPRC_IDX": "832.72", "HGPRC_IDX": "833.57", "LWPRC_IDX": "824.73",
    "ACC_TRDVOL": "700399865", "ACC_TRDVAL": "7484629421174",
    "MKTCAP": "459756151241984",
}


def test_지수는_IDX_NM_정확일치로_고른다(relay, monkeypatch):
    """실측대로 첫 행이 「코스피 (외국주포함)」이지만 그 행을 고르면 안 된다."""
    monkeypatch.setattr(
        relay.requests, "get",
        lambda *a, **k: _FakeResp(200, {"OutBlock_1": [_IDX_KOSPI_FOREIGN, _IDX_KOSPI]}),
    )
    status, body = relay._krx_relay({"api": "kospi_dd_trd", "basDd": "20260918"}, "userkey")
    assert status == 200
    assert body["ok"] is True and body["found"] is True
    assert body["row"] == _normalize_index_row("20260918", _IDX_KOSPI)
    assert body["row"]["close"] != _normalize_index_row("20260918", _IDX_KOSPI_FOREIGN)["close"]


def test_찾는_지수가_그날_응답에_없으면_200_notempty(relay, monkeypatch):
    """코스닥 api인데 응답에 코스피 행만 있다 — 다른 지수일 수 있다."""
    monkeypatch.setattr(
        relay.requests, "get",
        lambda *a, **k: _FakeResp(200, {"OutBlock_1": [_IDX_KOSPI]}),
    )
    status, body = relay._krx_relay({"api": "kosdaq_dd_trd", "basDd": "20260918"}, "userkey")
    assert status == 200
    assert body == {"ok": True, "found": False, "empty": False}


def test_지수_행이_core_normalize_index_row와_일치(relay, monkeypatch):
    monkeypatch.setattr(
        relay.requests, "get",
        lambda *a, **k: _FakeResp(200, {"OutBlock_1": [_IDX_KOSDAQ]}),
    )
    status, body = relay._krx_relay({"api": "kosdaq_dd_trd", "basDd": "20260918"}, "userkey")
    assert status == 200
    assert body["ok"] is True and body["found"] is True
    assert body["row"] == _normalize_index_row("20260918", _IDX_KOSDAQ)
    # 종목 행과 키 이름이 다르다 — volume·value·list_shrs·sect가 없다.
    assert set(body["row"]) == {"date", "close", "fluc_rt", "mktcap"}


def test_지수_요청은_AUTH_KEY와_idx_경로를_쓴다(relay, monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen["url"] = url
        seen["params"] = params
        seen["headers"] = headers
        return _FakeResp(200, {"OutBlock_1": []})

    monkeypatch.setattr(relay.requests, "get", fake_get)
    relay._krx_relay({"api": "kospi_dd_trd", "basDd": "20260918"}, "MYUSERKEY")
    assert seen["headers"] == {"AUTH_KEY": "MYUSERKEY"}
    assert seen["params"] == {"basDd": "20260918"}
    assert "svc/apis/idx" in seen["url"]
    assert "kospi_dd_trd" in seen["url"]


# ── ⑤ JS 두 릴레이의 정규화가 core와 같다 (쌍둥이 대조) ──────────────

def _extract_js_fn(src: str, marker: str) -> str:
    i = src.index(marker)
    body = src[i:]
    end = body.index("\n}") + 2
    return body[:end]


_JS_SAMPLES = [
    {
        "TDD_CLSPRC": "71,900", "FLUC_RT": "-1.23", "ACC_TRDVOL": "12,345,678",
        "ACC_TRDVAL": "888,000,000,000", "MKTCAP": "429,000,000,000,000",
        "LIST_SHRS": "5,969,782,550", "SECT_TP_NM": "  관리종목(소속부없음)  ",
    },
    {
        "TDD_CLSPRC": "0", "FLUC_RT": "0.00", "ACC_TRDVOL": "0",
        "ACC_TRDVAL": "0", "MKTCAP": "0", "LIST_SHRS": "0", "SECT_TP_NM": "",
    },
    {
        "TDD_CLSPRC": None, "FLUC_RT": "", "ACC_TRDVOL": "-",
        "ACC_TRDVAL": "12345", "MKTCAP": "12345.6", "LIST_SHRS": "1000000",
        "SECT_TP_NM": None,
    },
]


def _node_normalize(fn_src: str, to_num_src: str, fn_name: str,
                     samples: "list[dict]") -> "list[dict]":
    payload = json.dumps(samples)
    script = (
        to_num_src + "\n" + fn_src + "\n"
        + f"const samples = {payload};\n"
        + f'console.log(JSON.stringify(samples.map((s) => {fn_name}("20260101", s))));'
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True,
                        encoding="utf-8", timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _py_normalize(samples: "list[dict]") -> "list[dict]":
    return [_normalize_row("20260101", s) for s in samples]


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_Vercel_정규화가_core와_같다():
    src = _src(_API_KRX_JS)
    to_num = _extract_js_fn(src, "function toNumber(")
    norm = _extract_js_fn(src, "function normalizeRow(")
    got = _node_normalize(norm, to_num, "normalizeRow", _JS_SAMPLES)
    assert got == _py_normalize(_JS_SAMPLES)


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_Cloudflare_정규화가_core와_같다():
    src = _src(_WORKER_JS)
    to_num = _extract_js_fn(src, "function krxToNumber(")
    norm = _extract_js_fn(src, "function krxNormalizeRow(")
    got = _node_normalize(norm, to_num, "krxNormalizeRow", _JS_SAMPLES)
    assert got == _py_normalize(_JS_SAMPLES)


# ── ⑤b JS 두 릴레이의 지수 정규화가 core와 같다 ─────────────────────

_JS_INDEX_SAMPLES = [
    {
        "CLSPRC_IDX": "6,894.23", "FLUC_RT": "2.66",
        "MKTCAP": "5,683,776,067,592,413",
    },
    {
        "CLSPRC_IDX": "0", "FLUC_RT": "0.00", "MKTCAP": "0",
    },
    {
        "CLSPRC_IDX": None, "FLUC_RT": "", "MKTCAP": "12345.6",
    },
]


def _py_normalize_index(samples: "list[dict]") -> "list[dict]":
    return [_normalize_index_row("20260101", s) for s in samples]


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_Vercel_지수_정규화가_core와_같다():
    src = _src(_API_KRX_JS)
    to_num = _extract_js_fn(src, "function toNumber(")
    norm = _extract_js_fn(src, "function normalizeIndexRow(")
    got = _node_normalize(norm, to_num, "normalizeIndexRow", _JS_INDEX_SAMPLES)
    assert got == _py_normalize_index(_JS_INDEX_SAMPLES)


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_Cloudflare_지수_정규화가_core와_같다():
    src = _src(_WORKER_JS)
    to_num = _extract_js_fn(src, "function krxToNumber(")
    norm = _extract_js_fn(src, "function krxNormalizeIndexRow(")
    got = _node_normalize(norm, to_num, "krxNormalizeIndexRow", _JS_INDEX_SAMPLES)
    assert got == _py_normalize_index(_JS_INDEX_SAMPLES)


# ── 부수 — 세 파일 모두 GET만 허용, KRX_API_KEY 서버 키를 두지 않는다 ──

@pytest.mark.parametrize("path", [_API_KRX_JS, _WORKER_JS, _DEV_RELAY_PY])
def test_KRX_API_KEY_환경변수를_참조하지_않는다(path):
    """서버 키 폴백은 약관 제11조 ②로 금지된다 — 세 파일 전체에서 확인."""
    assert "KRX_API_KEY" not in _src(path)
