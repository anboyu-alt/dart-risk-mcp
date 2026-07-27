"""원문 조회 — 우측 패널이 공시를 열 때 쓴다."""
import unittest
from unittest import mock

from se_server.api.auth import AuthError
from se_server.api.handlers import Deps, handle
from se_server.api.types import Request
from se_server.jobs.store import MemoryJobStore


class _Auth:
    def __init__(self, user_id="user-1"):
        self.user_id = user_id

    def verify(self, bearer):
        if not bearer:
            raise AuthError(401, "인증 토큰이 없습니다")
        return self.user_id


def _req(path, token="T", dart_key="DARTKEY123456"):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if dart_key:
        headers["X-DART-Key"] = dart_key
    return Request("GET", path, headers, {})


def _deps():
    return Deps(store=MemoryJobStore(), auth=_Auth())


class TestDisclosure(unittest.TestCase):
    def test_returns_text(self):
        with mock.patch("se_server.api.handlers.fetch_disclosure_full",
                        return_value={"text": "본문 내용", "char_count": 5,
                                      "truncated": False}) as f:
            resp = handle(_req("/api/se/disclosure/20240301000001"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["rcept_no"], "20240301000001")
        self.assertEqual(resp.body["text"], "본문 내용")
        self.assertEqual(f.call_args[0][0], "20240301000001")

    def test_requires_auth(self):
        with mock.patch("se_server.api.handlers.fetch_disclosure_full") as f:
            resp = handle(_req("/api/se/disclosure/20240301000001", token=""), _deps())
        self.assertEqual(resp.status, 401)
        f.assert_not_called()

    def test_requires_dart_key(self):
        with mock.patch("se_server.api.handlers.fetch_disclosure_full") as f:
            resp = handle(_req("/api/se/disclosure/20240301000001", dart_key=""),
                          _deps())
        self.assertEqual(resp.status, 400)
        f.assert_not_called()

    def test_empty_result_is_404(self):
        """원문을 못 받으면 빈 본문을 성공처럼 주지 않는다."""
        with mock.patch("se_server.api.handlers.fetch_disclosure_full",
                        return_value={"text": ""}):
            resp = handle(_req("/api/se/disclosure/20240301000001"), _deps())
        self.assertEqual(resp.status, 404)

    def test_dart_key_is_not_echoed(self):
        import json
        key = "SECRET_DART_KEY_9999"
        req = Request("GET", "/api/se/disclosure/20240301000001",
                      {"Authorization": "Bearer T", "X-DART-Key": key}, {})
        with mock.patch("se_server.api.handlers.fetch_disclosure_full",
                        return_value={"text": "본문"}):
            resp = handle(req, _deps())
        self.assertNotIn(key, json.dumps(resp.body, ensure_ascii=False))

    def test_fetch_failure_is_502_not_500(self):
        """DART 쪽 실패와 우리 쪽 오류를 구분한다."""
        with mock.patch("se_server.api.handlers.fetch_disclosure_full",
                        side_effect=RuntimeError("DART 오류")):
            resp = handle(_req("/api/se/disclosure/20240301000001"), _deps())
        self.assertEqual(resp.status, 502)


class TestRcptNoRouting(unittest.TestCase):
    def test_only_digits_match(self):
        from se_server.api.router import match
        name, vars_ = match("GET", "/api/se/disclosure/20240301000001")
        self.assertEqual(name, "disclosure")
        self.assertEqual(vars_["rcept_no"], "20240301000001")

    def test_non_numeric_is_rejected(self):
        from se_server.api.router import match
        self.assertIsNone(match("GET", "/api/se/disclosure/abc"))
        self.assertIsNone(match("GET", "/api/se/disclosure/../../etc/passwd"))


if __name__ == "__main__":
    unittest.main()
