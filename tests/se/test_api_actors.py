"""행위자 대조 — SE의 독점 자산. 실명을 다루므로 가장 조심스럽다."""
import json
import unittest
from unittest import mock

from se_server.api.auth import AuthError
from se_server.api.handlers import Deps, handle
from se_server.api.types import Request
from se_server.jobs.store import MemoryJobStore


class _Auth:
    def verify(self, bearer):
        if not bearer:
            raise AuthError(401, "인증 토큰이 없습니다")
        return "user-1"


def _req(path, token="T"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return Request("GET", path, headers, {})


def _deps():
    return Deps(store=MemoryJobStore(), auth=_Auth())


_SAMPLE = [
    ("김OO", {"status": "verified", "companies": ["A사"], "evidence": "2024 CB 인수"}),
    ("이OO", {"status": "auto_matched", "companies": ["B사"], "evidence": "자동 발굴"}),
]


class TestActors(unittest.TestCase):
    def test_returns_actors_for_company(self):
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=_SAMPLE) as f:
            resp = handle(_req("/api/se/actors?company=테스트회사"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(f.call_args[0][0], "테스트회사")
        self.assertEqual(len(resp.body["actors"]), 2)

    def test_status_is_always_present(self):
        """auto_matched는 동명이인 미확인이다. 화면이 반드시 알아야 한다."""
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=_SAMPLE):
            resp = handle(_req("/api/se/actors?company=테스트회사"), _deps())
        for actor in resp.body["actors"]:
            self.assertIn("status", actor)
            self.assertIn(actor["status"], ("verified", "maintainer_seed", "auto_matched"))

    def test_disclaimer_is_always_present(self):
        """실명을 내보내면서 면책을 빼면 안 된다."""
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=_SAMPLE):
            resp = handle(_req("/api/se/actors?company=테스트회사"), _deps())
        self.assertIn("disclaimer", resp.body)
        self.assertTrue(resp.body["disclaimer"])

    def test_requires_auth(self):
        with mock.patch("se_server.api.handlers.lookup_actors_by_company") as f:
            resp = handle(_req("/api/se/actors?company=회사", token=""), _deps())
        self.assertEqual(resp.status, 401)
        f.assert_not_called()

    def test_missing_company_is_400(self):
        with mock.patch("se_server.api.handlers.lookup_actors_by_company") as f:
            resp = handle(_req("/api/se/actors"), _deps())
        self.assertEqual(resp.status, 400)
        f.assert_not_called()

    def test_registry_unavailable_is_empty_not_error(self):
        """레지스트리는 opt-in이다. 미설정이 정상 상태다."""
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=[]):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["actors"], [])

    def test_lookup_failure_is_502(self):
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        side_effect=RuntimeError("Notion 오류")):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 502)

    def test_no_score_or_grade_in_response(self):
        """v0.8.5: 위험도를 정량화하지 않는다."""
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=_SAMPLE):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        dumped = json.dumps(resp.body, ensure_ascii=False)
        for banned in ("점수", "등급", "score", "grade", "위험도"):
            self.assertNotIn(banned, dumped)

    def test_missing_status_key_downgrades_to_auto_matched(self):
        """레코드에 status 키 자체가 없는 경우.

        `.get("status", "auto_matched")`는 이 케이스에서만 발화한다 — 즉
        가장 흔하지 않은 입력이다. 운영에서 실제로 문제가 되는 빈 문자열
        케이스는 아래 test_empty_status_downgrades_to_auto_matched.
        """
        sample = [("박OO", {"companies": ["C사"], "evidence": "근거"})]
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=sample):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.body["actors"][0]["status"], "auto_matched")

    def test_empty_status_downgrades_to_auto_matched(self):
        """Notion status select가 비어 있으면 키는 있고 값이 ''인 레코드가 된다
        (known_actors.py:439 부근). `.get(키, 기본값)`은 키가 있으면 기본값을
        쓰지 않으므로, 단순 기본값 방식은 이 케이스를 놓친다 — 바로 이 결함을
        고치는 테스트다.
        """
        sample = [("최OO", {"status": "", "companies": ["D사"], "evidence": "근거"})]
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=sample):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.body["actors"][0]["status"], "auto_matched")

    def test_unexpected_status_value_downgrades_to_auto_matched(self):
        """오타·사람이 손으로 넣은 값(예: "확인됨")도 강한 쪽으로 새면 안 된다."""
        sample = [("정OO", {"status": "확인됨", "companies": ["E사"], "evidence": "근거"})]
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=sample):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.body["actors"][0]["status"], "auto_matched")


class TestQueryParsing(unittest.TestCase):
    def test_company_is_url_decoded(self):
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=[]) as f:
            handle(_req("/api/se/actors?company=%EC%85%80%ED%8A%B8%EB%A6%AC%EC%98%A8"),
                   _deps())
        self.assertEqual(f.call_args[0][0], "셀트리온")

    def test_company_is_decoded_exactly_once(self):
        """값에 리터럴 %가 있는 경우로 이중 디코딩 여부를 실제로 검증한다.

        원문 "100%25증자"를 한 번 디코딩하면 "100%증자"가 된다. 만약
        unquote를 또 부르는 이중 디코딩이 있다면 "%25"의 "%"가 다시
        "%3" ... 처럼 잘못 해석되어 손상된 값이 나온다 — 리터럴 %가 없는
        값만으로는 이 결함을 잡아낼 수 없다.
        """
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=[]) as f:
            handle(_req("/api/se/actors?company=100%2525%EC%A6%9D%EC%9E%90"),
                   _deps())
        self.assertEqual(f.call_args[0][0], "100%25증자")


if __name__ == "__main__":
    unittest.main()
