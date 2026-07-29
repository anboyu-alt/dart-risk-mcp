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

    def test_unhashable_status_list_does_not_500(self):
        """`value in frozenset(...)`는 value가 리스트면 TypeError를 던진다.
        레코드 하나가 이런 값을 가지면 엔드포인트 전체가 500이 됐다 —
        isinstance(str) 선검사로 막는다."""
        sample = [("최OO", {"status": ["verified"], "companies": ["F사"], "evidence": "근거"})]
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=sample):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["actors"][0]["status"], "auto_matched")

    def test_unhashable_status_dict_does_not_500(self):
        sample = [("최OO", {"status": {"a": 1}, "companies": ["F사"], "evidence": "근거"})]
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=sample):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["actors"][0]["status"], "auto_matched")

    def test_non_string_status_int_downgrades_to_auto_matched(self):
        sample = [("최OO", {"status": 123, "companies": ["F사"], "evidence": "근거"})]
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=sample):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["actors"][0]["status"], "auto_matched")


class TestRegistryUnavailableVsEmpty(unittest.TestCase):
    """SE-5c Task 2 — "레지스트리를 못 가져왔다"와 "이 회사에 등재 인물이
    없다"는 다른 사실이다. load_known_actors()는 캐시·Notion이 실패해도
    예외를 던지지 않고 동봉 빈 스켈레톤으로 조용히 graceful-fallback하므로
    (core 원칙), 예외를 잡는 것만으로는 이 둘을 구분할 수 없다 — 둘 다
    "성공했지만 비어 있음"으로 보인다. opt-in 여부(NOTION_TOKEN +
    DB_KNOWN_ACTORS)를 함께 봐야 구분된다.
    """

    _OPT_IN_ENV = {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}

    def test_opted_in_but_registry_totally_empty_is_502_not_empty_list(self):
        """opt-in인데 캐시·Notion 둘 다 실패해 레지스트리 전체가 비면
        "없음"(200+[])이 아니라 "조회 실패"(502)다."""
        with mock.patch.dict("os.environ", self._OPT_IN_ENV, clear=False), \
             mock.patch("se_server.api.handlers.load_known_actors",
                         return_value={"version": 1, "actors": {}}), \
             mock.patch("se_server.api.handlers.lookup_actors_by_company") as lookup:
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 502)
        lookup.assert_not_called()

    def test_502_message_says_failure_not_absence(self):
        """문구가 "없음"이 아니라 "조회 실패"여야 한다 — 사용자가 "이 회사는
        깨끗하다"로 오독하면 안 된다."""
        with mock.patch.dict("os.environ", self._OPT_IN_ENV, clear=False), \
             mock.patch("se_server.api.handlers.load_known_actors",
                         return_value={"version": 1, "actors": {}}):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        message = resp.body.get("error", "")
        self.assertIn("조회", message)
        self.assertNotIn("없습니다", message)

    def test_not_opted_in_and_empty_is_still_200(self):
        """opt-in 미설정(NOTION_TOKEN·DB_KNOWN_ACTORS 없음)은 빈 레지스트리가
        정상 상태다 — 기존 test_registry_unavailable_is_empty_not_error와
        같은 취지이나, 이번엔 load_known_actors() 실제 반환값(동봉 빈
        스켈레톤)이 새 코드 경로를 통과하는지까지 확인한다."""
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch("se_server.api.handlers.lookup_actors_by_company",
                         return_value=[]):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["actors"], [])

    def test_registry_healthy_but_company_has_no_actors_is_200_empty(self):
        """레지스트리는 정상 로드됐는데(비어 있지 않음) 그 회사에 등재
        인물이 없으면 200 + 빈 목록이다 — 이게 진짜 "없음"이다."""
        healthy = {"version": 1, "actors": {
            "다른사람": [{"status": "verified", "companies": ["다른회사"],
                        "evidence": "e"}]}}
        with mock.patch.dict("os.environ", self._OPT_IN_ENV, clear=False), \
             mock.patch("se_server.api.handlers.load_known_actors",
                         return_value=healthy), \
             mock.patch("se_server.api.handlers.lookup_actors_by_company",
                         return_value=[]):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["actors"], [])


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
