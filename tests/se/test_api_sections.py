"""진행률 폴링과 섹션 조회의 분리.

GET이 완료된 섹션을 통째로 돌려주면 폴링마다 같은 데이터를 다시 받는다.
프로덕션 실측: 최종 응답 737KB, 4회 폴링 누적 1.4MB.
"""
import unittest
from unittest import mock

from se_server.api.handlers import Deps, handle
from se_server.api.types import Request
from se_server.jobs.store import MemoryJobStore


class _Auth:
    def __init__(self, user_id="user-1"):
        self.user_id = user_id

    def verify(self, bearer):
        from se_server.api.auth import AuthError
        if not bearer:
            raise AuthError(401, "인증 토큰이 없습니다")
        return self.user_id


def _req(method, path, token="T", dart_key="DARTKEY123456", body=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if dart_key:
        headers["X-DART-Key"] = dart_key
    return Request(method, path, headers, body or {})


def _seeded_store(user_id="user-1"):
    """섹션 2개가 완료된 작업을 만들어 둔다."""
    from se_server.jobs import runner
    store = MemoryJobStore()
    with mock.patch("se_server.api.handlers.resolve_corp",
                    return_value=("회사", {"corp_code": "0"})):
        created = handle(_req("POST", "/api/se/analyze", body={"company": "회사"}),
                         Deps(store=store, auth=_Auth(user_id)))
    job_id = created.body["job_id"]
    job = store.load(job_id)
    job.items[0].status = "done"
    job.items[0].result = {"value": {"큰": "x" * 5000}}
    job.items[1].status = "done"
    job.items[1].result = {"value": [1, 2, 3]}
    store.save(job)
    return store, job_id, job.items[0].key, job.items[1].key


class TestProgressIsLightweight(unittest.TestCase):
    def test_get_omits_section_bodies(self):
        store, job_id, key0, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}"),
                      Deps(store=store, auth=_Auth()))
        self.assertEqual(resp.status, 200)
        self.assertNotIn("sections", resp.body)

    def test_get_lists_completed_section_keys(self):
        store, job_id, key0, key1 = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}"),
                      Deps(store=store, auth=_Auth()))
        self.assertIn(key0, resp.body["section_keys"])
        self.assertIn(key1, resp.body["section_keys"])

    def test_incomplete_sections_are_not_listed(self):
        store, job_id, key0, key1 = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}"),
                      Deps(store=store, auth=_Auth()))
        job = store.load(job_id)
        pending = [i.key for i in job.items if i.status == "pending"]
        for key in pending:
            self.assertNotIn(key, resp.body["section_keys"])

    def test_progress_response_stays_small(self):
        """5,000자짜리 섹션이 있어도 진행률 응답은 작아야 한다."""
        import json
        store, job_id, _, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}"),
                      Deps(store=store, auth=_Auth()))
        size = len(json.dumps(resp.body, ensure_ascii=False))
        self.assertLess(size, 2000, f"진행률 응답이 {size}B로 큽니다")

    def test_keeps_progress_fields(self):
        store, job_id, _, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}"),
                      Deps(store=store, auth=_Auth()))
        for field in ("job_id", "company", "status", "finished", "total", "failed"):
            self.assertIn(field, resp.body)


class TestSectionEndpoint(unittest.TestCase):
    def test_returns_single_section(self):
        store, job_id, key0, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}/section/{key0}"),
                      Deps(store=store, auth=_Auth()))
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["key"], key0)
        self.assertEqual(resp.body["value"], {"큰": "x" * 5000})

    def test_unknown_section_is_404(self):
        store, job_id, _, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}/section/없는섹션"),
                      Deps(store=store, auth=_Auth()))
        self.assertEqual(resp.status, 404)

    def test_incomplete_section_is_404(self):
        """미완료 섹션을 완성된 것처럼 주면 안 된다."""
        store, job_id, _, _ = _seeded_store()
        job = store.load(job_id)
        pending = [i.key for i in job.items if i.status == "pending"][0]
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}/section/{pending}"),
                      Deps(store=store, auth=_Auth()))
        self.assertEqual(resp.status, 404)

    def test_other_user_gets_404(self):
        store, job_id, key0, _ = _seeded_store(user_id="owner")
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}/section/{key0}"),
                      Deps(store=store, auth=_Auth("침입자")))
        self.assertEqual(resp.status, 404)

    def test_requires_auth(self):
        store, job_id, key0, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}/section/{key0}", token=""),
                      Deps(store=store, auth=_Auth()))
        self.assertEqual(resp.status, 401)

    def test_unauthenticated_never_touches_store(self):
        store = mock.Mock()
        handle(_req("GET", "/api/se/analyze/j1/section/k", token=""),
               Deps(store=store, auth=_Auth()))
        store.load.assert_not_called()


class TestSectionKeyRouting(unittest.TestCase):
    """섹션 키는 registry 키와 `doc:<rcept_no>` 두 형태다."""

    def test_document_section_key_matches(self):
        from se_server.api.router import match
        name, vars_ = match("GET", "/api/se/analyze/abc/section/doc:20240301000001")
        self.assertEqual(name, "section")
        self.assertEqual(vars_["key"], "doc:20240301000001")

    def test_plain_section_key_matches(self):
        from se_server.api.router import match
        name, vars_ = match("GET", "/api/se/analyze/abc/section/insider_timeline")
        self.assertEqual(name, "section")
        self.assertEqual(vars_["key"], "insider_timeline")

    def test_path_traversal_in_key_is_rejected(self):
        from se_server.api.router import match
        self.assertIsNone(match("GET", "/api/se/analyze/abc/section/../../etc"))


if __name__ == "__main__":
    unittest.main()
