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
        store, job_id, _, _ = _seeded_store()
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
        store, job_id, _, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}"),
                      Deps(store=store, auth=_Auth()))
        job = store.load(job_id)
        pending = [i.key for i in job.items if i.status == "pending"]
        # pending이 비면 아래 루프가 안 돌아 공허하게 통과한다 —
        # 실제로 미완료 섹션이 있다는 전제를 명시적으로 검증한다.
        self.assertTrue(pending, "미완료 섹션이 없어 이 테스트가 아무것도 검증하지 못합니다")
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
        """라우팅은 통과하는 ASCII 키인데 job.items에 없는 경우를 검증한다.

        한글 등 `_SECTION_KEY`(`[A-Za-z0-9_:-]+`) 밖의 문자를 쓰면 라우터
        단계에서부터 매칭 실패해 `_section` 핸들러에 도달하지 못한다 —
        그러면 이 테스트는 라우터 404만 우연히 재확인할 뿐, `_section`의
        "키를 못 찾으면 404" 분기는 전혀 검증하지 못하는 false-safe가 된다.
        """
        store, job_id, _, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}/section/nonexistent_key"),
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

    def test_percent_encoded_document_section_key_matches(self):
        """프론트엔드가 encodeURIComponent(key)를 쓰면 `doc:...`이
        `doc%3A...`가 된다. 라우터가 이 형태도 받아들여야 한다."""
        from se_server.api.router import match
        name, vars_ = match(
            "GET", "/api/se/analyze/abc/section/doc%3A20240301000001")
        self.assertEqual(name, "section")
        self.assertEqual(vars_["key"], "doc%3A20240301000001")

    def test_malformed_percent_encoding_is_rejected(self):
        """`%` 뒤에 유효한 16진수 2자리가 없으면 라우터 단계에서부터 거부한다."""
        from se_server.api.router import match
        self.assertIsNone(match("GET", "/api/se/analyze/abc/section/doc%3"))
        self.assertIsNone(match("GET", "/api/se/analyze/abc/section/doc%zz"))

    def test_encoded_path_traversal_chars_still_match_router(self):
        """`%2F`·`%2E%2E`는 문자 집합상 라우터를 통과한다(유효한 percent
        인코딩이므로) — 하지만 실제 위험 여부는 핸들러가 결정한다
        (test_api_sections.TestSectionEndpoint 쪽에서 확인)."""
        from se_server.api.router import match
        name, vars_ = match("GET", "/api/se/analyze/abc/section/x%2Fy")
        self.assertEqual(name, "section")
        self.assertEqual(vars_["key"], "x%2Fy")


def _seeded_store_with_doc_key(user_id="user-1"):
    """`doc:<rcept_no>` 형태 키(콜론 포함)로 완료된 섹션을 만들어 둔다.

    `_seeded_store`의 registry 키(`company_info` 등)는 인코딩해도 문자가
    안 바뀌므로 percent-encoding 왕복 검증에 쓸모가 없다 — 실제로
    `runner.py`가 만드는 `doc:` 키(콜론)로 재현해야 인코딩·디코딩 경로가
    실제로 발화한다.
    """
    from se_server.jobs.model import WorkItem
    store, job_id, _, _ = _seeded_store(user_id)
    job = store.load(job_id)
    doc_key = "doc:20240301000001"
    job.items.append(WorkItem(
        key=doc_key, stage=2, kind="fetch_disclosure_full",
        params={"rcept_no": "20240301000001"},
        status="done", result={"value": {"text": "공시 원문"}},
    ))
    store.save(job)
    return store, job_id, doc_key


class TestSectionKeyDecoding(unittest.TestCase):
    """`_section`은 인코딩된 키와 원문 키 둘 다 같은 섹션을 돌려줘야 한다."""

    def test_percent_encoded_key_returns_same_section_as_plain_key(self):
        store, job_id, doc_key = _seeded_store_with_doc_key()
        plain = handle(_req("GET", f"/api/se/analyze/{job_id}/section/{doc_key}"),
                       Deps(store=store, auth=_Auth()))
        from urllib.parse import quote
        encoded = handle(
            _req("GET", f"/api/se/analyze/{job_id}/section/{quote(doc_key, safe='')}"),
            Deps(store=store, auth=_Auth()))
        self.assertEqual(plain.status, 200)
        self.assertEqual(encoded.status, 200)
        self.assertEqual(plain.body, encoded.body)

    def test_double_encoded_key_does_not_match(self):
        """이중 디코딩 금지 — 두 번 인코딩한 키를 넣으면 원문과 일치하지
        않아야 한다(한 번만 디코딩했다는 증거)."""
        store, job_id, doc_key = _seeded_store_with_doc_key()
        from urllib.parse import quote
        double_encoded = quote(quote(doc_key, safe=""), safe="")
        resp = handle(
            _req("GET", f"/api/se/analyze/{job_id}/section/{double_encoded}"),
            Deps(store=store, auth=_Auth()))
        self.assertEqual(resp.status, 404)

    def test_percent_encoded_traversal_chars_do_not_reach_filesystem(self):
        """`%2F`·`%2E%2E`가 디코딩으로 `/`·`..`가 되어도 job.items 비교에만
        쓰이므로 그런 item.key는 존재하지 않아 안전하게 404가 된다."""
        store, job_id, _, _ = _seeded_store()
        for encoded_key in ("x%2Fy", "%2E%2E", "..%2F..%2Fetc"):
            resp = handle(
                _req("GET", f"/api/se/analyze/{job_id}/section/{encoded_key}"),
                Deps(store=store, auth=_Auth()))
            self.assertEqual(resp.status, 404, f"key={encoded_key}")


if __name__ == "__main__":
    unittest.main()
