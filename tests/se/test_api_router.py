"""경로 파싱과 디스패치."""
import unittest

from se_server.api.router import match
from se_server.api.types import Request, Response


class TestMatch(unittest.TestCase):
    def test_create_job(self):
        self.assertEqual(match("POST", "/api/se/analyze"), ("create", {}))

    def test_run_step(self):
        self.assertEqual(
            match("POST", "/api/se/analyze/abc123/step"), ("step", {"job_id": "abc123"})
        )

    def test_get_job(self):
        self.assertEqual(
            match("GET", "/api/se/analyze/abc123"), ("get", {"job_id": "abc123"})
        )

    def test_trailing_slash_is_tolerated(self):
        self.assertEqual(match("POST", "/api/se/analyze/"), ("create", {}))

    def test_query_string_is_ignored(self):
        self.assertEqual(
            match("GET", "/api/se/analyze/abc?x=1"), ("get", {"job_id": "abc"})
        )

    def test_unknown_path_returns_none(self):
        self.assertIsNone(match("GET", "/api/없는경로"))

    def test_wrong_method_returns_none(self):
        self.assertIsNone(match("DELETE", "/api/se/analyze/abc"))

    def test_job_id_with_url_safe_chars(self):
        """new_job_id()는 secrets.token_urlsafe라 - 와 _ 를 포함할 수 있다."""
        name, vars_ = match("GET", "/api/se/analyze/aB3-_xY")
        self.assertEqual(vars_["job_id"], "aB3-_xY")

    def test_path_traversal_is_not_matched(self):
        self.assertIsNone(match("GET", "/api/se/analyze/../../etc/passwd"))

    def test_empty_job_id_is_not_matched(self):
        self.assertIsNone(match("GET", "/api/se/analyze//step"))

    def test_single_segment_analyze_is_not_matched(self):
        """`/api/analyze`(옛 경로)는 더 이상 매칭되지 않아야 한다.

        기존 CORS 릴레이(api/[endpoint].js)가 그 단일 세그먼트 경로를
        차지하므로, 라우터가 실수로 되돌아가면 비대칭 실패가 재발한다.
        """
        self.assertIsNone(match("POST", "/api/analyze"))
        self.assertIsNone(match("GET", "/api/analyze/abc123"))
        self.assertIsNone(match("POST", "/api/analyze/abc123/step"))

    def test_trailing_newline_is_not_matched(self):
        """Python re의 `$`는 줄바꿈 직전에서도 매치된다.

        `match` + `$`를 쓰면 "/api/se/analyze/abc\n"이 통과한다. 라우터는
        보안 경계이므로 fullmatch로 이 함정을 막는다.
        """
        self.assertIsNone(match("GET", "/api/se/analyze/abc\n"))
        self.assertIsNone(match("POST", "/api/se/analyze\n"))

    def test_embedded_newline_is_not_matched(self):
        self.assertIsNone(match("GET", "/api/se/analyze/ab\ncd"))


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
