"""DART CORS 릴레이 — 로컬/셀프호스트 구현 (relay/worker.js와 동일 계약).

역할 두 가지:
1. /api/<endpoint>.json → opendart.fss.or.kr 통과 프록시 (+ CORS 헤더)
2. 그 외 경로 → docs/tool/ 정적 파일 서빙 (로컬 개발·검증용)

키·파라미터·응답을 저장하거나 로그로 남기지 않는다 (요청 라인 로그도 억제).

사용:
    python scripts/dev_relay.py            # http://127.0.0.1:8787/
    python scripts/dev_relay.py --port 9000
"""
import argparse
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tool_server.corp import handle_corp  # noqa: E402
from tool_server.doc import handle_doc  # noqa: E402

ALLOWED_ENDPOINTS = {"list.json", "company.json",
                     "fnlttSinglAcnt.json", "accnutAdtorNmNdAdtOpinion.json",
                     "exctvSttus.json", "elestock.json",
                     "alotMatter.json", "pssrpCptalUseDtls.json",
                     "prvsrpCptalUseDtls.json", "otrCprInvstmntSttus.json",
                     "fnlttSinglAcntAll.json"}
DART_BASE = "https://opendart.fss.or.kr/api/"
TOOL_DIR = os.path.join(os.path.dirname(__file__), "..", "docs", "tool")


class RelayHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.abspath(TOOL_DIR), **kwargs)

    def log_message(self, fmt, *args):  # 무로그 (키가 쿼리스트링에 있음)
        pass

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_OPTIONS(self):  # X-DART-Key 커스텀 헤더 preflight (api/doc.py와 동일 계약)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-DART-Key")
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
        if parts.path == "/api/doc":
            query = dict(parse_qsl(parts.query))
            api_key = (self.headers.get("X-DART-Key") or "").strip()
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
            api_key = (self.headers.get("X-DART-Key") or "").strip()
            status, body = handle_corp(query, api_key)
            payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")  # 로컬은 캐시 불필요
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
                r = requests.get(DART_BASE + endpoint + "?" + parts.query,
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
