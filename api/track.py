"""Vercel Python 함수 진입점 — 공개 뷰어 접속 이벤트 수집(/api/track).

api/doc.py와 같은 원칙:
- 껍데기는 얇게 — HTTP 파싱 외 로직은 tool_server.track.handle_track에 둔다.
- import 실패를 삼키지 않고 보고한다 (FUNCTION_INVOCATION_FAILED 진단 불가
  상태 방지 — api/index.py 주석 참고).

계약:
- POST /api/track, JSON 본문. 성공은 204(본문 없음).
- 클라이언트는 navigator.sendBeacon으로 보내고 응답을 읽지 않는다.
- 본문 상한 MAX_BODY_BYTES를 넘으면 413.

이 함수는 DART 릴레이(api/[endpoint].js)와 무관하다. 릴레이는 "저장하지
않는 무상태 통과"가 명시된 신뢰 경계라 로깅을 넣지 않았고, 수집은 전부
여기서만 일어난다.
"""
import json
import os
import platform
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_IMPORT_ERROR = ""
try:
    from tool_server.track import MAX_BODY_BYTES, handle_track  # noqa: E402
except Exception as exc:  # noqa: BLE001 — 어떤 import 실패든 보고 대상이다
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
    MAX_BODY_BYTES = 1024

# 허용 Origin. 뷰어 자기 호스트 + Vercel 프리뷰 + 로컬 개발만 통과시킨다.
# 이걸 열어두면 아무 사이트나 우리 통계를 오염시킬 수 있다.
_ALLOWED_ORIGIN_HOSTS = ("localhost", "127.0.0.1")
_ALLOWED_ORIGIN_SUFFIXES = (".vercel.app",)


def _origin_ok(origin: str, host: str) -> bool:
    """Origin이 우리 호스트이거나 허용 목록이면 True.

    Origin 헤더가 없으면(동일 출처 요청·일부 beacon 경로) 통과시킨다 —
    브라우저가 교차 출처일 때는 반드시 붙이기 때문이다.
    """
    if not origin:
        return True
    try:
        netloc = urlsplit(origin).netloc.lower()
    except ValueError:
        return False
    if not netloc:
        return False
    if host and netloc == host.lower():
        return True
    bare = netloc.split(":")[0]
    if bare in _ALLOWED_ORIGIN_HOSTS:
        return True
    return any(bare.endswith(suffix) for suffix in _ALLOWED_ORIGIN_SUFFIXES)


_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


def _send(rh: BaseHTTPRequestHandler, status: int, body: dict | None = None) -> None:
    rh.send_response(status)
    for k, v in _CORS_HEADERS.items():
        rh.send_header(k, v)
    rh.send_header("Cache-Control", "no-store")
    if status == 204:
        rh.send_header("Content-Length", "0")
        rh.end_headers()
        return
    payload = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
    rh.send_header("Content-Type", "application/json; charset=utf-8")
    rh.send_header("Content-Length", str(len(payload)))
    rh.end_headers()
    rh.wfile.write(payload)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):  # noqa: N802 - Vercel 규약
        self.send_response(204)
        for k, v in _CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_POST(self):  # noqa: N802 - Vercel 규약
        if _IMPORT_ERROR:
            _send(
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
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                _send(self, 413, {"error": "payload too large"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(body, dict):
                _send(self, 400, {"error": "bad body"})
                return
            headers = {k.lower(): v for k, v in self.headers.items()}
            ok = _origin_ok(headers.get("origin", ""), headers.get("host", ""))
            status, out = handle_track(body, headers, ok)
        except Exception:  # noqa: BLE001
            # 수집 실패가 원인을 노출해서도, 뷰어를 방해해서도 안 된다.
            status, out = 204, {}
        _send(self, status, out)
