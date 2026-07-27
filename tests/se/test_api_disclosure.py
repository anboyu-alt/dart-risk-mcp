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
                        return_value={"files": ["0001.html"], "main_file": "0001.html",
                                      "text": "본문 내용", "char_count": 5,
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
        """문서는 받았으나(files 채워짐) 본문이 비어 있으면 404다.

        core의 fetch_disclosure_full은 ZIP은 받았지만 본문을 못 얻은
        경우 `{**empty, "files": all_files, "main_file": main_file}`
        형태로 files를 채워 반환한다 — 이 값이 채워져 있다는 것은
        "받기는 받았다"는 뜻이므로 502가 아니라 404가 맞다.
        """
        with mock.patch(
            "se_server.api.handlers.fetch_disclosure_full",
            return_value={
                "files": ["0001.html"], "main_file": "0001.html",
                "text": "", "char_count": 0, "truncated": False,
            },
        ):
            resp = handle(_req("/api/se/disclosure/20240301000001"), _deps())
        self.assertEqual(resp.status, 404)

    def test_zip_fetch_failure_returns_502_not_404(self):
        """실제 실패 형태: core는 예외를 던지지 않고 빈 결과 dict를 삼킨다.

        dart_risk_mcp.core.dart_client의 fetch_disclosure_full은 DART 키
        오류·네트워크 장애·DART 5xx·ZIP 안전검증 거부를 전부 내부에서
        삼키고 `{"files": [], "main_file": "", "text": "", ...}` (완전한
        빈 결과)를 반환한다 — 예외를 던지지 않는다. 이 경우를 404로
        내려버리면 장애가 "존재하지 않는 공시"로 둔갑한다. files가 비어
        있으면(=ZIP 자체를 못 받음) 502여야 한다.
        """
        with mock.patch(
            "se_server.api.handlers.fetch_disclosure_full",
            return_value={
                "files": [], "main_file": "", "text": "",
                "char_count": 0, "truncated": False,
            },
        ):
            resp = handle(_req("/api/se/disclosure/20240301000001"), _deps())
        self.assertEqual(resp.status, 502)

    def test_dart_key_is_not_echoed(self):
        import json
        key = "SECRET_DART_KEY_9999"

        def _req_with_key(path):
            return Request("GET", path,
                          {"Authorization": "Bearer T", "X-DART-Key": key}, {})

        with mock.patch("se_server.api.handlers.fetch_disclosure_full",
                        return_value={"text": "본문", "files": ["0001.html"],
                                      "main_file": "0001.html"}):
            resp = handle(_req_with_key("/api/se/disclosure/20240301000001"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertNotIn(key, json.dumps(resp.body, ensure_ascii=False))

        # 오류 경로(400·404·502)에도 키가 새지 않는지 확인한다 — 키
        # 유출 위험은 오히려 오류 메시지 조립 쪽이 더 크다.
        with mock.patch("se_server.api.handlers.fetch_disclosure_full",
                        return_value={"files": ["0001.html"], "main_file": "0001.html",
                                      "text": ""}):
            resp = handle(_req_with_key("/api/se/disclosure/20240301000001"), _deps())
        self.assertEqual(resp.status, 404)
        self.assertNotIn(key, json.dumps(resp.body, ensure_ascii=False))

        with mock.patch("se_server.api.handlers.fetch_disclosure_full",
                        return_value={"files": [], "main_file": "", "text": ""}):
            resp = handle(_req_with_key("/api/se/disclosure/20240301000001"), _deps())
        self.assertEqual(resp.status, 502)
        self.assertNotIn(key, json.dumps(resp.body, ensure_ascii=False))

        req_no_key = Request("GET", "/api/se/disclosure/20240301000001",
                              {"Authorization": "Bearer T", "X-DART-Key": ""}, {})
        resp = handle(req_no_key, _deps())
        self.assertEqual(resp.status, 400)
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
