"""Vercel Python 함수 진입점.

이 파일은 **얇게** 유지한다 — HTTP 껍데기를 se_server.api의 Request/Response로
변환하는 것 외에 로직을 두지 않는다. 로직이 여기 들어가면 단위 테스트가
불가능해진다.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from se_server.api.handlers import build_deps, handle  # noqa: E402
from se_server.api.types import Request, Response  # noqa: E402


def _respond(rh: BaseHTTPRequestHandler, resp: Response) -> None:
    payload = json.dumps(resp.body, ensure_ascii=False).encode("utf-8")
    rh.send_response(resp.status)
    rh.send_header("Content-Type", "application/json; charset=utf-8")
    rh.send_header("Content-Length", str(len(payload)))
    # 응답을 중간 캐시에 남기지 않는다 — 사용자별 데이터다.
    rh.send_header("Cache-Control", "no-store")
    rh.end_headers()
    rh.wfile.write(payload)


def _read_body(rh: BaseHTTPRequestHandler) -> dict:
    length = int(rh.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    try:
        return json.loads(rh.rfile.read(length).decode("utf-8")) or {}
    except (ValueError, UnicodeDecodeError):
        return {}


def _dispatch(rh: BaseHTTPRequestHandler, method: str) -> None:
    try:
        request = Request(
            method=method,
            path=rh.path,
            headers=dict(rh.headers.items()),
            body=_read_body(rh) if method == "POST" else {},
        )
        resp = handle(request, build_deps())
    except ValueError as exc:
        # 설정 누락(SEConfig.from_env) 등. 메시지에 자격증명이 없다.
        resp = Response.error(500, str(exc))
    except Exception:
        # 예외 내용을 그대로 노출하면 내부 URL·자격증명이 샐 수 있다.
        resp = Response.error(500, "서버 오류가 발생했습니다")
    _respond(rh, resp)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - Vercel 규약
        _dispatch(self, "GET")

    def do_POST(self):  # noqa: N802 - Vercel 규약
        _dispatch(self, "POST")
