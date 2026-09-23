"""DART CORS 릴레이 — 로컬/셀프호스트 구현 (relay/worker.js와 동일 계약).

역할 두 가지:
1. /api/<endpoint>.json → opendart.fss.or.kr 통과 프록시 (+ CORS 헤더)
2. 그 외 경로 → docs/tool/ 정적 파일 서빙 (로컬 개발·검증용)

키·파라미터·응답을 저장하거나 로그로 남기지 않는다 (요청 라인 로그도 억제).

**로컬 전용 편의**: 브라우저가 키를 보내지 않았을 때만 환경변수 `DART_API_KEY`로
채운다. 개발자가 이미 MCP 서버용으로 가진 키를 브라우저에 다시 붙여넣지 않아도
되게 하려는 것이다. `relay/worker.js`·`api/[endpoint].js`(공용 배포)에는 **넣지
않는다** — 거기서 서버 키를 주입하면 그 주소를 아는 누구나 제작자의 한도를 쓴다.
이 스크립트는 기본이 127.0.0.1 바인딩이라 그 위험이 없다.

사용:
    python scripts/dev_relay.py            # http://127.0.0.1:8787/
    python scripts/dev_relay.py --port 9000
"""
import argparse
import json
import os
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlencode, urlsplit

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dart_risk_mcp.core.krx_client import (  # noqa: E402
    KRX_API_IDS,
    KRX_BASE,
    KRX_INDEX_API_IDS,
    KRX_INDEX_BASE,
    KRX_INDEX_NAMES,
    _normalize_index_row,
    _normalize_row,
)
from tool_server.corp import handle_corp  # noqa: E402
from tool_server.doc import handle_doc  # noqa: E402

ALLOWED_ENDPOINTS = {"list.json", "company.json",
                     "fnlttSinglAcnt.json", "accnutAdtorNmNdAdtOpinion.json",
                     "exctvSttus.json", "elestock.json",
                     "alotMatter.json", "pssrpCptalUseDtls.json",
                     "prvsrpCptalUseDtls.json", "otrCprInvstmntSttus.json",
                     "fnlttSinglAcntAll.json", "irdsSttus.json",
                     "stockTotqySttus.json", "cvbdIsDecsn.json",
                     "bdwtIsDecsn.json", "exbdIsDecsn.json",
                     "cprndNrdmpBlce.json", "srtpdPsndbtNrdmpBlce.json",
                     "entrprsBilScritsNrdmpBlce.json",
                     "newCaplScritsNrdmpBlce.json",
                     "cndlCaplScritsNrdmpBlce.json",
                     "adtServcCnclsSttus.json",
                     "accnutAdtorNonAdtServcCnclsSttus.json"}
DART_BASE = "https://opendart.fss.or.kr/api/"
TOOL_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "tool")

# core dart_risk_mcp/core/krx_client.py의 KRX_API_IDS.values()·
# KRX_INDEX_API_IDS.values()와 같아야 한다(tests/test_viewer_krx_relay.py가 대조).
_KRX_INDEX_APIS = set(KRX_INDEX_API_IDS.values())
_KRX_ALLOWED_APIS = set(KRX_API_IDS.values()) | _KRX_INDEX_APIS
_KRX_BASDD_RE = re.compile(r"\d{8}")
_KRX_ISU_RE = re.compile(r"\d{6}")


def _env_key() -> str:
    """환경변수의 DART 키. 없으면 빈 문자열(오류가 아니다)."""
    return (os.environ.get("DART_API_KEY") or "").strip()


def _with_key(query: str) -> str:
    """`crtfc_key`가 비어 있으면 환경변수로 채운 쿼리 문자열을 돌려준다.

    브라우저가 보낸 키가 있으면 **그것을 그대로 쓴다** — 환경변수가 사용자의
    선택을 덮어쓰지 않는다.
    """
    pairs = parse_qsl(query, keep_blank_values=True)
    if any(k == "crtfc_key" and v for k, v in pairs):
        return query
    key = _env_key()
    if not key:
        return query
    pairs = [(k, v) for k, v in pairs if k != "crtfc_key"]
    pairs.append(("crtfc_key", key))
    return urlencode(pairs)


def _krx_relay(query: dict, key: str) -> "tuple[int, dict]":
    """GET /api/krx 몸통 — `api/krx.js`·`relay/worker.js`와 같은 계약.

    사용자 본인 KRX 키 전용. 서버 키 폴백·캐시·쿼터가 없다(약관 제11조 ②).
    행 정규화는 core `krx_client._normalize_row`/`_normalize_index_row`/
    `_to_number`를 그대로 재사용한다(JS 릴레이 둘은 같은 규칙을 각자 옮겨
    적었다 — 언어가 달라 import를 공유할 수 없다).

    지수(코스피·코스닥)는 종목과 경로가 다르고(`KRX_INDEX_BASE`) `isu`를
    받지 않는다 — `IDX_NM`이 그 시장 이름과 정확히 같은 행 하나만 고른다
    (하루 응답에 「코스피 (외국주포함)」 같은 다른 지수도 함께 오므로).
    """
    key = (key or "").strip()
    if not key:
        return 400, {"ok": False, "error": "missing_key"}
    api = query.get("api", "")
    is_index = api in _KRX_INDEX_APIS
    bas_dd = query.get("basDd", "")
    isu = query.get("isu", "")
    if (
        api not in _KRX_ALLOWED_APIS
        or not _KRX_BASDD_RE.fullmatch(bas_dd or "")
        or (not is_index and not _KRX_ISU_RE.fullmatch(isu or ""))
    ):
        return 400, {"ok": False, "error": "bad_params"}

    base = KRX_INDEX_BASE if is_index else KRX_BASE
    try:
        resp = requests.get(
            f"{base}/{api}",
            params={"basDd": bas_dd},
            headers={"AUTH_KEY": key},
            timeout=15,
        )
    except requests.RequestException:
        return 502, {"ok": False, "error": "upstream"}

    if resp.status_code == 401:
        return 401, {"ok": False, "error": "unauthorized"}
    if resp.status_code != 200:
        return 502, {"ok": False, "error": "upstream"}

    try:
        data = resp.json()
    except ValueError:
        return 502, {"ok": False, "error": "upstream"}

    out_block = data.get("OutBlock_1") if isinstance(data, dict) else None
    if not isinstance(out_block, list):
        return 502, {"ok": False, "error": "upstream"}
    if not out_block:
        return 200, {"ok": True, "found": False, "empty": True}

    if is_index:
        name = KRX_INDEX_NAMES.get(api)
        row = next((r for r in out_block if r.get("IDX_NM") == name), None)
        if row is None:
            return 200, {"ok": True, "found": False, "empty": False}
        return 200, {"ok": True, "found": True, "row": _normalize_index_row(bas_dd, row)}

    row = next((r for r in out_block if str(r.get("ISU_CD")) == isu), None)
    if row is None:
        return 200, {"ok": True, "found": False, "empty": False}
    return 200, {"ok": True, "found": True, "row": _normalize_row(bas_dd, row)}


class RelayHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.abspath(TOOL_DIR), **kwargs)

    def log_message(self, fmt, *args):  # 무로그 (키가 쿼리스트링에 있음)
        pass

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_OPTIONS(self):  # X-DART-Key·X-KRX-Key 커스텀 헤더 preflight
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, X-DART-Key, X-KRX-Key")
        self.end_headers()

    def do_POST(self):
        """뷰어의 `POST /api/track`을 받아 **버린다**.

        프로덕션에는 `api/track.py`가 있지만 이 로컬 릴레이에는 없어서,
        페이지를 열 때마다 `501 Unsupported method ('POST')`가 콘솔에 붉게
        찍혔다(2026-08-24, 뷰어를 실제로 띄워 확인). 이 파일의 역할이
        **로컬 개발·검증용**인데 매 로드마다 나는 오류는 진짜 오류를 가린다.

        본문은 읽어서 버린다 — 저장하지 않는 것이 이 릴레이의 계약이고,
        읽지 않으면 다음 요청에서 소켓이 어긋난다.
        """
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        if urlsplit(self.path).path == "/api/track":
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(404)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"error":"not found"}')

    def do_GET(self):
        parts = urlsplit(self.path)
        if parts.path == "/api/health":
            # 로컬 릴레이가 환경변수 키를 갖고 있는지만 알린다 — **값은 절대
            # 내보내지 않는다**. 뷰어는 이 신호를 보고 브라우저에 키가 없어도
            # 검색 화면을 연다. 공용 배포(api/health.js)도 같은 모양을 준다.
            #
            # `free_scans: 0`은 **무제한**이다 — 로컬 개발에서까지 하루 5곳에
            # 막히면 손볼 때마다 키를 넣어야 한다. 공용 배포는 5를 준다.
            _body = {"ok": True, "server_key": bool(_env_key()), "free_scans": 0}
            # `?quota=1`은 공용 배포(api/health.js)가 쿼터 상태를 싣는 자리다.
            # 로컬 릴레이에는 쿼터 저장소가 없으므로 **그 사실을 명시**한다 —
            # 필드가 아예 없으면 운영자가 "쿼터가 죽었나"와 구분할 수 없다.
            if "quota=1" in (parts.query or ""):
                _body["quota"] = {"configured": False, "reachable": False,
                                  "today_calls": None, "daily_cap": None}
            payload = json.dumps(_body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        if parts.path == "/api/doc":
            query = dict(parse_qsl(parts.query))
            api_key = (self.headers.get("X-DART-Key") or "").strip() or _env_key()
            status, body = handle_doc(query, api_key)
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")  # 로컬은 캐시 불필요
            self.end_headers()
            self.wfile.write(payload)
            return
        if parts.path == "/api/corp":
            query = dict(parse_qsl(parts.query))
            api_key = (self.headers.get("X-DART-Key") or "").strip() or _env_key()
            status, body = handle_corp(query, api_key)
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")  # 로컬은 캐시 불필요
            self.end_headers()
            self.wfile.write(payload)
            return
        if parts.path == "/api/krx":
            # 사용자 본인 KRX 키 전용 — 환경변수 폴백 없음(약관 제11조 ②,
            # DART 경로의 `_with_key`와 다른 지점).
            query = dict(parse_qsl(parts.query))
            key = (self.headers.get("X-KRX-Key") or "").strip()
            status, body = _krx_relay(query, key)
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        if parts.path.startswith("/api/"):
            endpoint = parts.path[len("/api/"):]
            if endpoint not in ALLOWED_ENDPOINTS:
                self.send_response(403)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "forbidden"}')
                return
            try:
                r = requests.get(DART_BASE + endpoint + "?" + _with_key(parts.query),
                                 timeout=30)
                body = r.content
                self.send_response(r.status_code)
                self.send_header("Content-Type",
                                 r.headers.get("Content-Type",
                                               "application/json"))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "upstream"}')
            return
        super().do_GET()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), RelayHandler)
    print(f"dev relay: http://127.0.0.1:{args.port}/  "
          f"(정적: docs/tool, 프록시: /api/{{{', '.join(sorted(ALLOWED_ENDPOINTS))}}})")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
