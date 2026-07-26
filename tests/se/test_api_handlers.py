"""엔드포인트 로직. DART·Supabase 호출은 전부 스텁한다."""
import unittest
from unittest import mock

from se_server.api.auth import AuthError
from se_server.api.handlers import Deps, handle
from se_server.api.types import Request
from se_server.jobs import runner
from se_server.jobs.store import MemoryJobStore


class _Auth:
    def __init__(self, user_id="user-1", error=None):
        self.user_id = user_id
        self.error = error

    def verify(self, bearer):
        if self.error:
            raise self.error
        return self.user_id


def _deps(auth=None, store=None):
    return Deps(store=store or MemoryJobStore(), auth=auth or _Auth())


def _req(method, path, body=None, token="T", dart_key="DARTKEY123456"):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if dart_key:
        headers["X-DART-Key"] = dart_key
    return Request(method=method, path=path, headers=headers, body=body or {})


class TestAuthGate(unittest.TestCase):
    def test_missing_token_is_401(self):
        resp = handle(_req("POST", "/api/analyze", {"company": "셀트리온"}, token=""),
                      _deps(auth=_Auth(error=AuthError(401, "인증 토큰이 없습니다"))))
        self.assertEqual(resp.status, 401)

    def test_auth_error_status_is_preserved(self):
        """Supabase 장애(503)를 401로 뭉개면 사용자가 자기 탓으로 오해한다."""
        resp = handle(_req("POST", "/api/analyze", {"company": "셀트리온"}),
                      _deps(auth=_Auth(error=AuthError(503, "인증 서버 연결 불가"))))
        self.assertEqual(resp.status, 503)

    def test_unauthenticated_never_touches_store(self):
        store = mock.Mock()
        handle(_req("GET", "/api/analyze/j1"),
               Deps(store=store, auth=_Auth(error=AuthError(401, "x"))))
        store.load.assert_not_called()


class TestCreate(unittest.TestCase):
    def test_creates_job(self):
        store = MemoryJobStore()
        with mock.patch("se_server.api.handlers.resolve_corp",
                        return_value=("셀트리온", {"corp_code": "00421045"})):
            resp = handle(_req("POST", "/api/analyze",
                               {"company": "셀트리온", "lookback_years": 1}),
                          _deps(store=store))
        self.assertEqual(resp.status, 201)
        self.assertIn("job_id", resp.body)
        self.assertEqual(store.load(resp.body["job_id"]).user_id, "user-1")

    def test_missing_company_is_400(self):
        resp = handle(_req("POST", "/api/analyze", {}), _deps())
        self.assertEqual(resp.status, 400)

    def test_missing_dart_key_is_400(self):
        resp = handle(_req("POST", "/api/analyze", {"company": "셀트리온"}, dart_key=""),
                      _deps())
        self.assertEqual(resp.status, 400)

    def test_unknown_company_is_404(self):
        # resolve_corp는 실패 시 None을 반환한다. (None, None)으로 모킹하면
        # 실제와 다른 형태라 언패킹 버그를 놓친다(SE-2에서 실제로 놓쳤다).
        with mock.patch("se_server.api.handlers.resolve_corp", return_value=None):
            resp = handle(_req("POST", "/api/analyze", {"company": "없는회사"}), _deps())
        self.assertEqual(resp.status, 404)

    def test_lookback_years_is_clamped(self):
        store = MemoryJobStore()
        with mock.patch("se_server.api.handlers.resolve_corp",
                        return_value=("회사", {"corp_code": "0"})):
            resp = handle(_req("POST", "/api/analyze",
                               {"company": "회사", "lookback_years": 99}),
                          _deps(store=store))
        self.assertEqual(store.load(resp.body["job_id"]).lookback_years, 5)


class TestStep(unittest.TestCase):
    def _make_job(self, store, user_id="user-1"):
        with mock.patch("se_server.api.handlers.resolve_corp",
                        return_value=("회사", {"corp_code": "0"})):
            resp = handle(_req("POST", "/api/analyze", {"company": "회사"}),
                          Deps(store=store, auth=_Auth(user_id=user_id)))
        return resp.body["job_id"]

    def test_runs_a_step(self):
        store = MemoryJobStore()
        job_id = self._make_job(store)
        with mock.patch("se_server.jobs.runner.resolve_callable",
                        return_value=lambda **kw: {}):
            resp = handle(_req("POST", f"/api/analyze/{job_id}/step"), _deps(store=store))
        self.assertEqual(resp.status, 200)
        self.assertIn("processed", resp.body)

    def test_other_user_gets_404(self):
        """소유자 불일치를 403으로 알리면 job_id 존재 여부가 새어나간다."""
        store = MemoryJobStore()
        job_id = self._make_job(store, user_id="owner")
        resp = handle(_req("POST", f"/api/analyze/{job_id}/step"),
                      Deps(store=store, auth=_Auth(user_id="침입자")))
        self.assertEqual(resp.status, 404)

    def test_unknown_job_is_404(self):
        resp = handle(_req("POST", "/api/analyze/없는작업/step"), _deps())
        self.assertEqual(resp.status, 404)

    def test_missing_dart_key_is_400(self):
        store = MemoryJobStore()
        job_id = self._make_job(store)
        resp = handle(_req("POST", f"/api/analyze/{job_id}/step", dart_key=""),
                      _deps(store=store))
        self.assertEqual(resp.status, 400)


class TestUserIdGuard(unittest.TestCase):
    """빈 user_id는 저장소의 소유자 검사를 통째로 끈다.

    Deps.auth가 덕 타이핑이라 계약이 강제되지 않으므로 핸들러가 방어한다.
    """

    def test_empty_user_id_is_rejected(self):
        for bad in ("", None, 123):
            with self.subTest(user_id=bad):
                resp = handle(_req("GET", "/api/analyze/j1"),
                              _deps(auth=_Auth(user_id=bad)))
                self.assertEqual(resp.status, 401)

    def test_empty_user_id_never_touches_store(self):
        store = mock.Mock()
        handle(_req("GET", "/api/analyze/j1"),
               Deps(store=store, auth=_Auth(user_id="")))
        store.load.assert_not_called()


class TestMalformedBody(unittest.TestCase):
    """JSON 배열·null·문자열 본문이 500이 되면 안 된다."""

    def test_non_dict_body_is_400_not_500(self):
        for body in (None, ["x"], "문자열", 42):
            with self.subTest(body=body):
                req = Request("POST", "/api/analyze",
                              {"Authorization": "Bearer T", "X-DART-Key": "K12345678"},
                              body)
                resp = handle(req, _deps())
                self.assertEqual(resp.status, 400)


class TestStepOwnershipIsPassedThrough(unittest.TestCase):
    """핸들러의 사전 확인만으로는 부족하다 — run_step에도 user_id가 가야 한다.

    저장소가 user_id를 무시하도록 만든 더블로, 사전 확인이 통과한 뒤
    run_step이 소유자를 다시 확인하는지 본다.
    """

    class _IgnoresOwner(MemoryJobStore):
        def load(self, job_id, user_id=""):
            return super().load(job_id)  # 소유자 검사를 일부러 건너뛴다

    def test_run_step_receives_user_id(self):
        store = self._IgnoresOwner()
        with mock.patch("se_server.api.handlers.resolve_corp",
                        return_value=("회사", {"corp_code": "0"})):
            created = handle(_req("POST", "/api/analyze", {"company": "회사"}),
                             Deps(store=store, auth=_Auth(user_id="owner")))
        job_id = created.body["job_id"]

        captured = {}
        real_run_step = runner.run_step

        def spy(*args, **kwargs):
            captured["user_id"] = kwargs.get("user_id")
            return real_run_step(*args, **kwargs)

        with mock.patch.object(runner, "run_step", side_effect=spy), \
                mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {}):
            handle(_req("POST", f"/api/analyze/{job_id}/step"),
                   Deps(store=store, auth=_Auth(user_id="침입자")))
        self.assertEqual(captured.get("user_id"), "침입자")


class TestGet(unittest.TestCase):
    def test_returns_progress(self):
        store = MemoryJobStore()
        with mock.patch("se_server.api.handlers.resolve_corp",
                        return_value=("회사", {"corp_code": "0"})):
            created = handle(_req("POST", "/api/analyze", {"company": "회사"}),
                             _deps(store=store))
        resp = handle(_req("GET", f"/api/analyze/{created.body['job_id']}"),
                      _deps(store=store))
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["company"], "회사")
        self.assertIn("sections", resp.body)

    def test_other_user_gets_404(self):
        store = MemoryJobStore()
        with mock.patch("se_server.api.handlers.resolve_corp",
                        return_value=("회사", {"corp_code": "0"})):
            created = handle(_req("POST", "/api/analyze", {"company": "회사"}),
                             Deps(store=store, auth=_Auth(user_id="owner")))
        resp = handle(_req("GET", f"/api/analyze/{created.body['job_id']}"),
                      Deps(store=store, auth=_Auth(user_id="침입자")))
        self.assertEqual(resp.status, 404)


class TestRouting(unittest.TestCase):
    def test_unknown_path_is_404(self):
        self.assertEqual(handle(_req("GET", "/api/없는것"), _deps()).status, 404)


class TestSecrets(unittest.TestCase):
    def test_dart_key_never_appears_in_response(self):
        store = MemoryJobStore()
        key = "SECRET_DART_KEY_123"
        with mock.patch("se_server.api.handlers.resolve_corp",
                        return_value=("회사", {"corp_code": "0"})):
            resp = handle(Request("POST", "/api/analyze",
                                  {"Authorization": "Bearer T", "X-DART-Key": key},
                                  {"company": "회사"}),
                          _deps(store=store))
        import json
        self.assertNotIn(key, json.dumps(resp.body, ensure_ascii=False))

    def test_dart_key_is_not_stored_in_job(self):
        store = MemoryJobStore()
        key = "SECRET_DART_KEY_123"
        with mock.patch("se_server.api.handlers.resolve_corp",
                        return_value=("회사", {"corp_code": "0"})):
            resp = handle(Request("POST", "/api/analyze",
                                  {"Authorization": "Bearer T", "X-DART-Key": key},
                                  {"company": "회사"}),
                          _deps(store=store))
        import json
        job = store.load(resp.body["job_id"])
        self.assertNotIn(key, json.dumps(job.to_dict(), ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
