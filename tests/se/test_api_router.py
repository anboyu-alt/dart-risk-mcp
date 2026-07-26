"""경로 파싱과 디스패치."""
import unittest

from se_server.api.router import match
from se_server.api.types import Request, Response


class TestMatch(unittest.TestCase):
    def test_create_job(self):
        self.assertEqual(match("POST", "/api/analyze"), ("create", {}))

    def test_run_step(self):
        self.assertEqual(
            match("POST", "/api/analyze/abc123/step"), ("step", {"job_id": "abc123"})
        )

    def test_get_job(self):
        self.assertEqual(match("GET", "/api/analyze/abc123"), ("get", {"job_id": "abc123"}))

    def test_trailing_slash_is_tolerated(self):
        self.assertEqual(match("POST", "/api/analyze/"), ("create", {}))

    def test_query_string_is_ignored(self):
        self.assertEqual(match("GET", "/api/analyze/abc?x=1"), ("get", {"job_id": "abc"}))

    def test_unknown_path_returns_none(self):
        self.assertIsNone(match("GET", "/api/없는경로"))

    def test_wrong_method_returns_none(self):
        self.assertIsNone(match("DELETE", "/api/analyze/abc"))

    def test_job_id_with_url_safe_chars(self):
        """new_job_id()는 secrets.token_urlsafe라 - 와 _ 를 포함할 수 있다."""
        name, vars_ = match("GET", "/api/analyze/aB3-_xY")
        self.assertEqual(vars_["job_id"], "aB3-_xY")

    def test_path_traversal_is_not_matched(self):
        self.assertIsNone(match("GET", "/api/analyze/../../etc/passwd"))

    def test_empty_job_id_is_not_matched(self):
        self.assertIsNone(match("GET", "/api/analyze//step"))


class TestRequestHeaders(unittest.TestCase):
    def test_header_lookup_is_case_insensitive(self):
        req = Request(method="GET", path="/", headers={"X-DART-Key": "K"}, body={})
        self.assertEqual(req.header("x-dart-key"), "K")
        self.assertEqual(req.header("X-DART-KEY"), "K")

    def test_missing_header_returns_empty_string(self):
        self.assertEqual(Request("GET", "/", {}, {}).header("없음"), "")


class TestResponse(unittest.TestCase):
    def test_error_shape(self):
        resp = Response.error(401, "인증이 필요합니다")
        self.assertEqual(resp.status, 401)
        self.assertEqual(resp.body, {"error": "인증이 필요합니다"})


if __name__ == "__main__":
    unittest.main()
