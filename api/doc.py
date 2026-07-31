"""Vercel Python 함수 진입점 — 공개 뷰어 공시 원문 추출(/api/doc).

api/index.py와 같은 원칙:
- 껍데기는 얇게 — HTTP 파싱 외 로직은 tool_server.doc.handle_doc에 둔다.
- import 실패를 삼키지 않고 보고한다 (FUNCTION_INVOCATION_FAILED 진단 불가
  상태 방지 — api/index.py 주석 참고).

계약:
- GET /api/doc?rcept_no=<14자리>&max_chars=<선택>
- DART 키는 X-DART-Key 헤더로만 받는다. 쿼리에 넣으면 URL이 로그·CDN
  캐시 키에 남는다. 키가 URL에 없으므로 200 응답은 CDN에 공유 캐시해도
  안전하다(공시 원문은 불변 공개 데이터).
"""
import json
import os
import platform
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_IMPORT_ERROR = ""
try:
    from tool_server.doc import handle_doc  # noqa: E402
except Exception as exc:  # noqa: BLE001 — 어떤 import 실패든 보고 대상이다
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    # 커스텀 헤더(X-DART-Key)를 쓰므로 preflight가 발생한다.
    "Access-Control-Allow-Headers": "Content-Type, X-DART-Key",
    "Access-Control-Max-Age": "86400",
}


def _send_json(rh: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    rh.send_response(status)
    rh.send_header("Content-Type", "application/json; charset=utf-8")
    rh.send_header("Content-Length", str(len(payload)))
    for k, v in _CORS_HEADERS.items():
        rh.send_header(k, v)
    if status == 200:
        # 공시 원문은 불변 공개 데이터 + 키가 URL에 없어 캐시 키가 안전.
        # CDN 공유 캐시 하루 — DART 호출량 관리의 핵심.
        rh.send_header("Cache-Control", "public, s-maxage=86400")
    else:
        rh.send_header("Cache-Control", "no-store")
    rh.end_headers()
    rh.wfile.write(payload)


def _import_failure_body() -> dict:
    root = os.path.join(os.path.dirname(__file__), "..")
    return {
        "error": "서버 초기화에 실패했습니다",
        "detail": _IMPORT_ERROR,
        "python": platform.python_version(),
        "packages_present": {
            name: os.path.isdir(os.path.join(root, name))
            for name in ("tool_server", "dart_risk_mcp")
        },
    }


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):  # noqa: N802 - Vercel 규약
        self.send_response(204)
        for k, v in _CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):  # noqa: N802 - Vercel 규약
        if _IMPORT_ERROR:
            _send_json(self, 500, _import_failure_body())
            return
        try:
            query = dict(parse_qsl(urlsplit(self.path).query))
            api_key = (self.headers.get("X-DART-Key") or "").strip()
            status, body = handle_doc(query, api_key)
        except Exception:
            # 예외 내용을 그대로 노출하면 내부 정보가 샐 수 있다.
            status, body = 500, {"error": "서버 오류가 발생했습니다"}
        _send_json(self, status, body)
