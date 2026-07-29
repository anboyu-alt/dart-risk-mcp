"""행위자 대조 — SE의 독점 자산. 실명을 다루므로 가장 조심스럽다."""
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from dart_risk_mcp.core import known_actors as ka
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
    없다"는 다른 사실이다. 레지스트리 로딩은 캐시·Notion이 실패해도 예외를
    던지지 않고 동봉 빈 스켈레톤으로 조용히 graceful-fallback하므로(core
    원칙), 예외를 잡는 것만으로는 이 둘을 구분할 수 없다 — 둘 다 "성공했지만
    비어 있음"으로 보인다.

    최종 리뷰 Finding 1b 이후 구분 기준은 **출처**다: opt-in인데 출처가
    `bundled`면 조회 실패. "인물 0명 = 실패"라는 추론은 진짜로 빈
    레지스트리(부트스트랩)를 실패로 오판했다.
    """

    _OPT_IN_ENV = {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}

    def test_opted_in_but_registry_fell_back_to_bundled_is_502(self):
        """opt-in인데 캐시·Notion 둘 다 실패해 동봉 스켈레톤으로 떨어지면
        "없음"(200+[])이 아니라 "조회 실패"(502)다."""
        with mock.patch.dict("os.environ", self._OPT_IN_ENV, clear=False), \
             mock.patch("se_server.api.handlers.load_known_actors_with_source",
                         return_value=({"version": 1, "actors": {}}, "bundled")), \
             mock.patch("se_server.api.handlers.lookup_actors_by_company") as lookup:
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 502)
        lookup.assert_not_called()

    def test_502_message_says_failure_not_absence(self):
        """문구가 "없음"이 아니라 "조회 실패"여야 한다 — 사용자가 "이 회사는
        깨끗하다"로 오독하면 안 된다."""
        with mock.patch.dict("os.environ", self._OPT_IN_ENV, clear=False), \
             mock.patch("se_server.api.handlers.load_known_actors_with_source",
                         return_value=({"version": 1, "actors": {}}, "bundled")):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        message = resp.body.get("error", "")
        self.assertIn("조회", message)
        self.assertNotIn("없습니다", message)

    def test_not_opted_in_and_empty_is_still_200(self):
        """opt-in 미설정(NOTION_TOKEN·DB_KNOWN_ACTORS 없음)은 빈 레지스트리가
        정상 상태다 — 기존 test_registry_unavailable_is_empty_not_error와
        같은 취지이나, 이번엔 실제 로더 반환값(동봉 빈 스켈레톤)이 새 코드
        경로를 통과하는지까지 확인한다."""
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch("se_server.api.handlers.lookup_actors_by_company",
                         return_value=[]):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["actors"], [])

    def test_opted_in_and_genuinely_empty_registry_is_200_not_502(self):
        """opt-in이고 Notion 조회는 **성공**했는데 등재 인물이 0명이면
        (부트스트랩 직후·필터가 전부 걸러낸 경우) 그건 실패가 아니다.

        예전 구현은 "opt-in + 인물 0명"을 실패로 추론해 이 경우에 502를
        냈다(Finding 1b). 출처가 notion인 이상 조회는 성공한 것이다.
        """
        with mock.patch.dict("os.environ", self._OPT_IN_ENV, clear=False), \
             mock.patch("se_server.api.handlers.load_known_actors_with_source",
                         return_value=({"version": 1, "actors": {}}, "notion")), \
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
             mock.patch("se_server.api.handlers.load_known_actors_with_source",
                         return_value=(healthy, "cache")), \
             mock.patch("se_server.api.handlers.lookup_actors_by_company",
                         return_value=[]):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["actors"], [])


class TestActorsLoadsRegistryOnce(unittest.TestCase):
    """SE-5c 최종 리뷰 Finding 1a — `GET /actors` 한 번은 주입 캐시를
    **한 번만** 읽어야 한다.

    예전 핸들러는 건강 확인용으로 한 번, `lookup_actors_by_company` 안에서
    또 한 번 레지스트리를 로드했다. 주석은 "두 번째는 첫 호출이 채운 파일
    캐시를 맞아 사실상 공짜"라고 주장했지만 사실이 아니었다 — 주입 캐시
    적중 경로는 `_CACHE_FILE`을 쓰지 않고 반환하므로 두 번째 로드도 실제
    Supabase 왕복이었다. Vercel에는 영속 $HOME이 없어 매 요청이 캐시
    지연을 두 배로 물었다.

    이 테스트는 실제 core 로더를 통과시키되 주입 캐시만 가짜로 바꿔
    `get_json` 호출 횟수를 센다 — 핸들러가 두 번 읽는 구현으로 돌아가면
    즉시 깨진다.
    """

    _OPT_IN_ENV = {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}

    def setUp(self):
        self.calls = []
        registry = {"version": 1, "actors": {
            "홍길동": [{"status": "verified", "companies": ["회사"],
                      "evidence": "e"}]}}
        calls = self.calls

        class _CountingCache:
            def get_json(self, key):
                calls.append(key)
                return registry

            def put_json(self, key, value, ttl_seconds):  # pragma: no cover
                raise AssertionError("적중 경로에서 쓰기가 일어나면 안 된다")

        self._tmp = tempfile.TemporaryDirectory()
        # 파일 캐시가 먼저 맞으면 주입 캐시를 아예 안 읽어 이 테스트가
        # 무의미해진다 — 존재하지 않는 경로로 돌려 파일 캐시를 확실히 끈다.
        self._file_patch = mock.patch.object(
            ka, "_CACHE_FILE",
            pathlib.Path(self._tmp.name) / "absent" / "known_actors.json")
        self._file_patch.start()
        ka.set_registry_cache(_CountingCache())

    def tearDown(self):
        ka.set_registry_cache(None)
        self._file_patch.stop()
        self._tmp.cleanup()

    def test_single_request_reads_injected_cache_exactly_once(self):
        with mock.patch.dict("os.environ", self._OPT_IN_ENV, clear=False):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual([a["name"] for a in resp.body["actors"]], ["홍길동"])
        self.assertEqual(len(self.calls), 1, f"캐시 조회 {len(self.calls)}회")


_SAMPLE_RECORDS = [
    {"status": "auto_matched", "companies": ["FSN", "위노바"], "evidence": "자동 발굴"},
]


class TestActorsByName(unittest.TestCase):
    """Task 1(SE-6) — 이름 단위 조회. `?name=`은 `?company=`와 같은 라우트,
    같은 응답 껍데기를 쓰되 name/actors 형태로 낸다."""

    def test_returns_actors_for_name(self):
        with mock.patch("se_server.api.handlers.lookup_actor",
                        return_value=_SAMPLE_RECORDS) as f:
            resp = handle(_req("/api/se/actors?name=이승호"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(f.call_args[0][0], "이승호")
        self.assertEqual(resp.body["name"], "이승호")
        self.assertEqual(len(resp.body["actors"]), 1)
        actor = resp.body["actors"][0]
        self.assertEqual(actor["status"], "auto_matched")
        self.assertEqual(actor["companies"], ["FSN", "위노바"])

    def test_unknown_name_is_empty_not_404(self):
        """없는 이름은 오류가 아니다 — 200 + 빈 목록."""
        with mock.patch("se_server.api.handlers.lookup_actor", return_value=[]):
            resp = handle(_req("/api/se/actors?name=존재안함"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["actors"], [])

    def test_name_and_company_together_is_400(self):
        with mock.patch("se_server.api.handlers.lookup_actor") as la, \
             mock.patch("se_server.api.handlers.lookup_actors_by_company") as lc:
            resp = handle(_req("/api/se/actors?name=이승호&company=엔켐"), _deps())
        self.assertEqual(resp.status, 400)
        la.assert_not_called()
        lc.assert_not_called()

    def test_neither_name_nor_company_is_400(self):
        with mock.patch("se_server.api.handlers.lookup_actor") as la:
            resp = handle(_req("/api/se/actors"), _deps())
        self.assertEqual(resp.status, 400)
        la.assert_not_called()

    def test_registry_unavailable_is_502_not_empty(self):
        """bundled + opt-in = 조회 실패. 문구가 "없음"이 아니라 "조회 실패"."""
        with mock.patch.dict("os.environ",
                             {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}, clear=False), \
             mock.patch("se_server.api.handlers.load_known_actors_with_source",
                         return_value=({"version": 1, "actors": {}}, "bundled")), \
             mock.patch("se_server.api.handlers.lookup_actor") as la:
            resp = handle(_req("/api/se/actors?name=이승호"), _deps())
        self.assertEqual(resp.status, 502)
        la.assert_not_called()
        message = resp.body.get("error", "")
        self.assertIn("조회", message)
        self.assertNotIn("없습니다", message)

    def test_disclaimer_is_always_present(self):
        with mock.patch("se_server.api.handlers.lookup_actor",
                        return_value=_SAMPLE_RECORDS):
            resp = handle(_req("/api/se/actors?name=이승호"), _deps())
        self.assertIn("disclaimer", resp.body)
        self.assertTrue(resp.body["disclaimer"])

    def test_requires_auth(self):
        with mock.patch("se_server.api.handlers.lookup_actor") as la:
            resp = handle(_req("/api/se/actors?name=이승호", token=""), _deps())
        self.assertEqual(resp.status, 401)
        la.assert_not_called()

    def test_empty_status_downgrades_to_auto_matched(self):
        """actor_status를 경유해야 한다 — `== "auto_matched"` 동등비교로 짜면
        빈 문자열이 그대로 새어나가 이 테스트가 실패한다."""
        sample = [{"status": "", "companies": ["FSN"], "evidence": "e"}]
        with mock.patch("se_server.api.handlers.lookup_actor", return_value=sample):
            resp = handle(_req("/api/se/actors?name=이승호"), _deps())
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
