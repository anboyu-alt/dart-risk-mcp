"""Vercel Python 함수 진입점 — 운영 대시보드 집계(/api/stats).

api/doc.py와 같은 원칙: 껍데기는 얇게, import 실패는 삼키지 않고 보고한다.

계약:
- GET /api/stats?view=corps&days=30
- 인증은 X-Ops-Token 헤더. 토큰을 쿼리에 넣지 않는다 — URL은 로그·리퍼러·
  CDN 캐시 키에 남는다(api/doc.py가 DART 키를 헤더로만 받는 것과 같은 이유).
- 응답은 어떤 캐시에도 남기지 않는다(운영 데이터).
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
    from tool_server.stats import handle_stats  # noqa: E402
except Exception as exc:  # noqa: BLE001 — 어떤 import 실패든 보고 대상이다
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    # 커스텀 헤더(X-Ops-Token)를 쓰므로 preflight가 발생한다.
    "Access-Control-Allow-Headers": "Content-Type, X-Ops-Token",
    "Access-Control-Max-Age": "86400",
}


def _send_json(rh: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    # default=str: PostgREST가 돌려주는 날짜·시각 문자열 외에 예기치 않은
    # 타입이 섞여도 직렬화가 500으로 죽지 않게 한다.
    payload = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
    rh.send_response(status)
    rh.send_header("Content-Type", "application/json; charset=utf-8")
    rh.send_header("Content-Length", str(len(payload)))
    # 운영 데이터는 어떤 캐시에도 남기지 않는다.
    rh.send_header("Cache-Control", "no-store")
    rh.send_header("X-Robots-Tag", "noindex, nofollow")
    for k, v in _CORS_HEADERS.items():
        rh.send_header(k, v)
    rh.end_headers()
    rh.wfile.write(payload)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):  # noqa: N802 - Vercel 규약
        self.send_response(204)
        for k, v in _CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):  # noqa: N802 - Vercel 규약
        if _IMPORT_ERROR:
            _send_json(
                self,
                500,
                {
                    "error": "서버 초기화에 실패했습니다",
                    "detail": _IMPORT_ERROR,
                    "python": platform.python_version(),
                },
            )
            return
        try:
            query = dict(parse_qsl(urlsplit(self.path).query))
            token = (self.headers.get("X-Ops-Token") or "").strip()
            status, body = handle_stats(query, token)
        except Exception:  # noqa: BLE001
            # 예외 내용을 그대로 노출하면 내부 정보가 샐 수 있다.
            status, body = 500, {"error": "서버 오류가 발생했습니다"}
        _send_json(self, status, body)
