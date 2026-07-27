"""Vercel Python 함수 진입점.

이 파일은 **얇게** 유지한다 — HTTP 껍데기를 se_server.api의 Request/Response로
변환하는 것 외에 로직을 두지 않는다. 로직이 여기 들어가면 단위 테스트가
불가능해진다.

**import 실패를 삼키지 않고 보고한다.** 모듈 레벨 import가 죽으면 Vercel은
`FUNCTION_INVOCATION_FAILED`라는 text/plain 오류 페이지만 돌려주고 원인을
알려주지 않는다(실제로 배포 후 이 상태에 빠져 원인 추적이 막혔다). 함수가
스스로 설명하지 못하면 로그 접근 권한이 없는 사람은 진단할 수 없다.
"""
import json
import os
import platform
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# import 자체가 실패할 수 있으므로 감싼다. 실패해도 함수는 떠서 이유를 말한다.
_IMPORT_ERROR = ""
try:
    from se_server.api.handlers import build_deps, handle  # noqa: E402
    from se_server.api.types import Request, Response  # noqa: E402
except Exception as exc:  # noqa: BLE001 — 어떤 import 실패든 보고 대상이다
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


def _send_json(rh: BaseHTTPRequestHandler, status: int, body: dict) -> None:
    """Response 타입에 의존하지 않는 최소 응답기.

    import가 실패한 상황에서도 동작해야 하므로 se_server를 참조하지 않는다.
    """
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    rh.send_response(status)
    rh.send_header("Content-Type", "application/json; charset=utf-8")
    rh.send_header("Content-Length", str(len(payload)))
    # 응답을 중간 캐시에 남기지 않는다 — 사용자별 데이터다.
    rh.send_header("Cache-Control", "no-store")
    rh.end_headers()
    rh.wfile.write(payload)


def _import_failure_body() -> dict:
    """import 실패 진단 정보.

    자격증명은 담지 않는다 — 예외 메시지·파이썬 버전·모듈 존재 여부뿐이다.
    파이썬 버전을 넣는 이유: core 일부 모듈이 `X | None`(PEP 604)을 쓰므로
    런타임이 3.10 미만이면 import 시점에 TypeError로 죽는다. 버전이 보이면
    그 가설을 즉시 확인할 수 있다.
    """
    root = os.path.join(os.path.dirname(__file__), "..")
    return {
        "error": "서버 초기화에 실패했습니다",
        "detail": _IMPORT_ERROR,
        "python": platform.python_version(),
        "packages_present": {
            name: os.path.isdir(os.path.join(root, name))
            for name in ("se_server", "dart_risk_mcp")
        },
    }


def _read_body(rh: BaseHTTPRequestHandler) -> dict:
    length = int(rh.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    try:
        return json.loads(rh.rfile.read(length).decode("utf-8")) or {}
    except (ValueError, UnicodeDecodeError):
        return {}


def _dispatch(rh: BaseHTTPRequestHandler, method: str) -> None:
    if _IMPORT_ERROR:
        _send_json(rh, 500, _import_failure_body())
        return

    try:
        request = Request(
            method=method,
            path=rh.path,
            headers=dict(rh.headers.items()),
            body=_read_body(rh) if method == "POST" else {},
        )
        resp = handle(request, build_deps())
        status, body = resp.status, resp.body
    except ValueError as exc:
        # 설정 누락(SEConfig.from_env) 등. 메시지에 자격증명이 없다.
        status, body = 500, {"error": str(exc)}
    except Exception:
        # 예외 내용을 그대로 노출하면 내부 URL·자격증명이 샐 수 있다.
        status, body = 500, {"error": "서버 오류가 발생했습니다"}
    _send_json(rh, status, body)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - Vercel 규약
        _dispatch(self, "GET")

    def do_POST(self):  # noqa: N802 - Vercel 규약
        _dispatch(self, "POST")
