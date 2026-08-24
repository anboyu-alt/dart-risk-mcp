"""로컬 릴레이가 뷰어의 추적 POST를 501로 되받지 않는지 잠근다.

**뷰어를 실제로 띄워 찾았다**(2026-08-24). 페이지를 열자마자 콘솔에 붉은
오류가 찍혔다.

    POST http://localhost:8787/api/track → 501 Unsupported method ('POST')

프로덕션에는 `api/track.py`가 있지만 `scripts/dev_relay.py`에는 `do_POST`가
없었다. 이 파일의 역할은 docstring에 **"로컬 개발·검증용"**이라 적혀 있는데,
매 로드마다 나는 오류는 **진짜 오류를 가린다** — 이번 세션에서 뷰어 오류
경로를 여러 번 고쳤으면서(#249) 정작 검증 환경 자체가 오류를 뿜고 있었다.

로컬에서는 받아서 **버린다**(204). 저장하지 않는 것이 이 릴레이의 계약이다.
"""
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest



@pytest.fixture(scope="module")
def server():
    # ⚠ 이름으로 고르면 import된 `SimpleHTTPRequestHandler`가 먼저 걸린다
    #   (작성 중 실제로 그래서 전부 501이 났다).
    from scripts.dev_relay import RelayHandler

    srv = ThreadingHTTPServer(("127.0.0.1", 0), RelayHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _post(base, path, body=b'{"event":"pageview"}'):
    req = urllib.request.Request(base + path, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_추적_POST가_204다(server):
    status, _ = _post(server, "/api/track")
    assert status == 204, "501이면 콘솔에 붉은 오류가 찍힌다"


def test_본문을_읽어_소켓이_어긋나지_않는다(server):
    """본문을 안 읽으면 다음 요청이 깨진다 — 연속 호출로 확인."""
    for _ in range(3):
        assert _post(server, "/api/track")[0] == 204


def test_큰_본문도_받는다(server):
    payload = json.dumps({"event": "scan", "pad": "x" * 5000}).encode()
    assert _post(server, "/api/track", payload)[0] == 204


def test_모르는_POST는_404다(server):
    """아무 POST나 삼키면 안 된다."""
    status, body = _post(server, "/api/nope")
    assert status == 404
    assert b"not found" in body


def test_OPTIONS가_POST를_허용한다(server):
    req = urllib.request.Request(server + "/api/track", method="OPTIONS")
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 204
        assert "POST" in r.headers.get("Access-Control-Allow-Methods", "")


def test_프로덕션에는_핸들러가_따로_있다():
    """로컬만 없었다는 사실을 고정 — 계약이 어긋난 게 아니다."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    assert (root / "api" / "track.py").exists()
