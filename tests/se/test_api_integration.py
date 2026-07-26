"""인증 경계와 전체 흐름. 실제 네트워크는 타지 않는다."""
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


def _req(method, path, body=None, user_token="T"):
    headers = {"X-DART-Key": "DARTKEY123456"}
    if user_token:
        headers["Authorization"] = f"Bearer {user_token}"
    return Request(method, path, headers, body or {})


class TestAuthBoundary(unittest.TestCase):
    """인증 없는 요청이 어떤 데이터 경로에도 닿으면 안 된다."""

    def test_every_route_rejects_missing_token(self):
        deps = Deps(store=mock.Mock(), auth=_Auth())
        for method, path in (
            ("POST", "/api/analyze"),
            ("POST", "/api/analyze/j1/step"),
            ("GET", "/api/analyze/j1"),
        ):
            with self.subTest(path=path):
                resp = handle(_req(method, path, {"company": "회사"}, user_token=""),
                              deps)
                self.assertEqual(resp.status, 401)
        deps.store.load.assert_not_called()
        deps.store.save.assert_not_called()


class TestFullFlow(unittest.TestCase):
    def test_create_then_step_until_done(self):
        store = MemoryJobStore()
        deps = Deps(store=store, auth=_Auth(), budget_seconds=1000.0)

        with mock.patch("se_server.api.handlers.resolve_corp",
                        return_value=("셀트리온", {"corp_code": "00421045"})):
            created = handle(_req("POST", "/api/analyze",
                                  {"company": "셀트리온", "lookback_years": 1}), deps)
        self.assertEqual(created.status, 201)
        job_id = created.body["job_id"]

        with mock.patch("se_server.jobs.runner.resolve_callable",
                        return_value=lambda **kw: []), \
                mock.patch("se_server.jobs.runner.fetch_disclosure_full",
                           return_value={"text": ""}):
            for _ in range(20):
                stepped = handle(_req("POST", f"/api/analyze/{job_id}/step"), deps)
                self.assertEqual(stepped.status, 200)
                if stepped.body["done"]:
                    break
            else:
                self.fail("20단계 안에 완료되지 않았습니다")

        final = handle(_req("GET", f"/api/analyze/{job_id}"), deps)
        self.assertEqual(final.body["status"], "done")
        self.assertEqual(final.body["finished"], final.body["total"])


class TestCrossUserIsolation(unittest.TestCase):
    def test_user_b_cannot_see_or_advance_user_a_job(self):
        store = MemoryJobStore()
        a = Deps(store=store, auth=_Auth("user-a"))
        b = Deps(store=store, auth=_Auth("user-b"))

        with mock.patch("se_server.api.handlers.resolve_corp",
                        return_value=("회사", {"corp_code": "0"})):
            created = handle(_req("POST", "/api/analyze", {"company": "회사"}), a)
        job_id = created.body["job_id"]

        self.assertEqual(handle(_req("GET", f"/api/analyze/{job_id}"), b).status, 404)
        self.assertEqual(
            handle(_req("POST", f"/api/analyze/{job_id}/step"), b).status, 404
        )
        # A는 여전히 접근 가능해야 한다.
        self.assertEqual(handle(_req("GET", f"/api/analyze/{job_id}"), a).status, 200)


if __name__ == "__main__":
    unittest.main()
