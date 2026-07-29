"""청크 실행기 — 예산·재개·실패 격리·2단 확장."""
import unittest
from unittest import mock

from se_server.jobs import runner
from se_server.jobs.model import Job, WorkItem
from se_server.jobs.store import MemoryJobStore


class _Clock:
    """호출할 때마다 step초씩 흐르는 가짜 단조 시계."""

    def __init__(self, step=1.0):
        self.t = 0.0
        self.step = step

    def __call__(self):
        value = self.t
        self.t += self.step
        return value


def _job_with(items, **kw):
    return Job(job_id="j1", company="테스트", corp_code="00126380",
               lookback_years=1, items=items, **kw)


def _stage1(key, kind="fetch_company_info"):
    return WorkItem(key=key, stage=1, kind=kind, params={"corp_code": "00126380"})


class TestCreateJob(unittest.TestCase):
    def test_creates_and_saves_stage1_items(self):
        store = MemoryJobStore()
        job = runner.create_job("셀트리온", "00421045", 3, store)
        self.assertTrue(job.items)
        self.assertTrue(all(i.stage == 1 for i in job.items))
        self.assertIsNotNone(store.load(job.job_id))

    def test_job_id_is_unique_per_call(self):
        store = MemoryJobStore()
        a = runner.create_job("A", "1", 1, store)
        b = runner.create_job("B", "2", 1, store)
        self.assertNotEqual(a.job_id, b.job_id)


class TestRunStepBudget(unittest.TestCase):
    def test_stops_when_budget_exhausted(self):
        store = MemoryJobStore()
        job = _job_with([_stage1(f"k{i}") for i in range(10)])
        store.save(job)
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {"ok": 1}):
            result = runner.run_step("j1", "KEY", store, budget_seconds=3.0, now=_Clock(1.0))
        self.assertFalse(result.done)
        self.assertLess(result.processed, 10)
        self.assertGreater(result.processed, 0)

    def test_resumes_from_saved_state(self):
        """두 번째 호출이 첫 호출이 남긴 항목부터 이어받는다."""
        store = MemoryJobStore()
        store.save(_job_with([_stage1(f"k{i}") for i in range(6)]))
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {"ok": 1}):
            first = runner.run_step("j1", "KEY", store, budget_seconds=3.0, now=_Clock(1.0))
            second = runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(1.0))
        self.assertEqual(first.processed + second.processed, 6)
        self.assertTrue(second.done)

    def test_oversized_item_needs_reserve(self):
        """oversized 항목은 남은 예산이 충분할 때만 시작한다.

        budget_seconds는 OVERSIZED_RESERVE보다 커야 한다(그렇지 않으면
        run_step이 ValueError를 던진다 — test_budget_at_or_below_reserve_is_rejected
        참고). 대신 시간이 흐르는 가짜 시계(step=2.0)를 써서, 이번 호출의
        remaining이 실행 도중 OVERSIZED_RESERVE 아래로 떨어지는 상황을
        재현한다 — "영원히 불가능"이 아니라 "이번 예산으로는 부족"인
        정상적인 케이스다.
        """
        store = MemoryJobStore()
        item = WorkItem(key="insider_timeline", stage=1, kind="fetch_insider_timeline",
                        params={"corp_code": "0", "lookback_years": 5})
        store.save(_job_with([item]))
        called = []
        with mock.patch.object(runner, "resolve_callable",
                               return_value=lambda **kw: called.append(1) or {"ok": 1}):
            result = runner.run_step("j1", "KEY", store,
                                     budget_seconds=runner.OVERSIZED_RESERVE + 1.0,
                                     now=_Clock(2.0))
        self.assertEqual(called, [])
        self.assertFalse(result.done)

    def test_reserve_block_reports_stalled(self):
        """예산이 작아 아무것도 시작 못 하면 정체를 알려야 한다.

        이 신호가 없으면 호출자는 "예산 소진(진행 중)"과 "영구 정지"를
        구분하지 못해 같은 예산으로 무한 반복한다.

        budget_seconds는 OVERSIZED_RESERVE보다 커야 진입 가드를 통과한다
        (test_budget_at_or_below_reserve_is_rejected 참고). step=2.0인
        가짜 시계로 이번 호출 중 remaining이 OVERSIZED_RESERVE 아래로
        떨어지는 상황을 재현해 원래 검증하려던 "정체 신호"는 그대로 살린다.
        """
        store = MemoryJobStore()
        item = WorkItem(key="insider_timeline", stage=1, kind="fetch_insider_timeline",
                        params={"corp_code": "0", "lookback_years": 5})
        store.save(_job_with([item]))
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {}):
            result = runner.run_step("j1", "KEY", store,
                                     budget_seconds=runner.OVERSIZED_RESERVE + 1.0,
                                     now=_Clock(2.0))
        self.assertTrue(result.stalled)
        self.assertEqual(result.processed, 0)

    def test_progress_is_not_reported_as_stalled(self):
        """진행이 있었으면 정체가 아니다."""
        store = MemoryJobStore()
        store.save(_job_with([_stage1("k0"), _stage1("k1")]))
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {}):
            result = runner.run_step("j1", "KEY", store, budget_seconds=1.5,
                                     now=_Clock(1.0))
        self.assertFalse(result.stalled)
        self.assertGreater(result.processed, 0)

    def test_oversized_does_not_block_smaller_items_behind_it(self):
        """앞의 oversized 항목이 뒤의 작은 항목을 막으면 안 된다.

        목록 순서를 그대로 따르면 예산이 작은 환경에서 실행 가능한 항목이
        많이 남았는데도 작업이 통째로 멈춘다(head-of-line 블로킹).
        """
        store = MemoryJobStore()
        big = WorkItem(key="insider_timeline", stage=1, kind="fetch_insider_timeline",
                       params={"corp_code": "0", "lookback_years": 5})
        store.save(_job_with([big, _stage1("small1"), _stage1("small2")]))

        # budget_seconds는 OVERSIZED_RESERVE보다 커야 진입 가드를 통과한다
        # (test_budget_at_or_below_reserve_is_rejected 참고). step=2.0인
        # 가짜 시계로 매 반복마다 remaining이 OVERSIZED_RESERVE 아래로
        # 떨어지게 해, 원래 검증하려던 head-of-line 방지 동작은 그대로 살린다.
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {}):
            result = runner.run_step("j1", "KEY", store,
                                     budget_seconds=runner.OVERSIZED_RESERVE + 1.0,
                                     now=_Clock(2.0))

        job = store.load("j1")
        self.assertEqual(result.processed, 2)   # 작은 항목 둘은 처리됐다
        self.assertFalse(result.stalled)        # 진행이 있었으므로 정체 아님
        self.assertEqual(job.items[0].status, "pending")  # oversized는 그대로 대기

    def test_budget_at_or_below_reserve_is_rejected(self):
        """예산이 RESERVE 이하면 oversized 항목을 영원히 시작할 수 없다.

        remaining = budget - elapsed 이고 elapsed > 0이므로
        remaining < budget <= RESERVE 가 항상 참이다. 조용히 고착되게 두지
        않고 설정 오류로 즉시 알린다.
        라이브 실측에서 --budget 20(=RESERVE)이 7/13에서 영구 고착되며 발견됐다.
        """
        store = MemoryJobStore()
        big = WorkItem(key="insider_timeline", stage=1, kind="fetch_insider_timeline",
                       params={"corp_code": "0", "lookback_years": 5})
        store.save(_job_with([big, _stage1("small")]))
        for bad in (runner.OVERSIZED_RESERVE, runner.OVERSIZED_RESERVE - 5.0, 1.0):
            with self.subTest(budget=bad):
                with self.assertRaises(ValueError):
                    runner.run_step("j1", "KEY", store, budget_seconds=bad,
                                    now=_Clock(0.1))

    def test_small_budget_allowed_when_no_oversized_pending(self):
        """oversized 항목이 없으면 작은 예산도 정상이다."""
        store = MemoryJobStore()
        store.save(_job_with([_stage1("small")]))
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {}):
            result = runner.run_step("j1", "KEY", store, budget_seconds=1.0,
                                     now=_Clock(0.1))
        self.assertTrue(result.done)

    def test_stalled_only_when_all_remaining_are_oversized(self):
        store = MemoryJobStore()
        big = WorkItem(key="insider_timeline", stage=1, kind="fetch_insider_timeline",
                       params={"corp_code": "0", "lookback_years": 5})
        big2 = WorkItem(key="audit_history", stage=1, kind="fetch_audit_opinion_history",
                        params={"corp_code": "0", "lookback_years": 5})
        store.save(_job_with([big, big2]))
        # budget_seconds > OVERSIZED_RESERVE로 진입 가드는 통과시키되, step=2.0
        # 가짜 시계로 이번 호출 중 remaining이 RESERVE 아래로 떨어지게 한다.
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {}):
            result = runner.run_step("j1", "KEY", store,
                                     budget_seconds=runner.OVERSIZED_RESERVE + 1.0,
                                     now=_Clock(2.0))
        self.assertTrue(result.stalled)
        self.assertEqual(result.processed, 0)

    def test_completed_job_is_not_stalled(self):
        store = MemoryJobStore()
        done_item = _stage1("k0")
        done_item.status = "done"
        store.save(_job_with([done_item], stage2_expanded=True))
        result = runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(1.0))
        self.assertTrue(result.done)
        self.assertFalse(result.stalled)

    def test_completed_job_reports_done_without_work(self):
        store = MemoryJobStore()
        store.save(_job_with([_stage1("k0")], status="done", stage2_expanded=True))
        job = store.load("j1")
        job.items[0].status = "done"
        store.save(job)
        with mock.patch.object(runner, "resolve_callable") as resolve:
            result = runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(1.0))
        resolve.assert_not_called()
        self.assertTrue(result.done)


class TestFailureIsolation(unittest.TestCase):
    def test_failing_item_does_not_stop_others(self):
        store = MemoryJobStore()
        store.save(_job_with([_stage1("bad"), _stage1("good")]))

        def resolve(name):
            def fn(**kw):
                raise RuntimeError("DART 오류")
            return fn

        with mock.patch.object(runner, "resolve_callable", side_effect=resolve):
            runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(0.1))
            runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(0.1))
        job = store.load("j1")
        self.assertTrue(all(i.status == "failed" for i in job.items))

    def test_item_retries_up_to_max_attempts(self):
        store = MemoryJobStore()
        store.save(_job_with([_stage1("flaky")]))
        calls = {"n": 0}

        def fn(**kw):
            calls["n"] += 1
            raise RuntimeError("일시 오류")

        with mock.patch.object(runner, "resolve_callable", return_value=fn):
            for _ in range(5):
                runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(0.1))
        self.assertEqual(calls["n"], runner.MAX_ATTEMPTS)
        self.assertEqual(store.load("j1").items[0].status, "failed")

    def test_error_message_does_not_leak_api_key(self):
        store = MemoryJobStore()
        store.save(_job_with([_stage1("bad")]))

        def fn(**kw):
            raise RuntimeError("요청 실패: crtfc_key=SECRET_KEY_VALUE")

        with mock.patch.object(runner, "resolve_callable", return_value=fn):
            runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(0.1))
        self.assertNotIn("SECRET_KEY_VALUE", store.load("j1").items[0].error)


class TestScrub(unittest.TestCase):
    """키가 노출되는 형태는 다양하다. 정규식만으로는 대부분을 놓친다."""

    KEY = "SECRETKEY123"

    def test_removes_all_observed_shapes(self):
        shapes = [
            f'요청 실패: crtfc_key={self.KEY}',
            f'{{"crtfc_key": "{self.KEY}"}}',
            f'crtfc_key="{self.KEY}"',
            f'crtfc_key = {self.KEY}',
            f'https://opendart.fss.or.kr/api/list.json?crtfc_key={self.KEY}&corp_code=1',
            f'인증 실패 ({self.KEY})',
            self.KEY,
        ]
        for raw in shapes:
            with self.subTest(raw=raw):
                self.assertNotIn(self.KEY, runner._scrub(raw, self.KEY))

    def test_works_without_api_key_argument(self):
        """키를 모를 때도 정규식 경로는 살아 있어야 한다."""
        self.assertNotIn("OTHERKEY", runner._scrub("crtfc_key=OTHERKEY"))

    def test_short_key_is_not_substituted(self):
        """짧은 값을 치환하면 무관한 문자까지 지워 진단이 불가능해진다."""
        message = "HTTP 500 at line 1 (attempt 1)"
        self.assertEqual(runner._scrub(message, "1"), message)

    def test_preserves_useful_message(self):
        cleaned = runner._scrub(f"DART 오류 (020): crtfc_key={self.KEY}", self.KEY)
        self.assertIn("DART 오류 (020)", cleaned)


class TestExpandStage2(unittest.TestCase):
    def _job_with_disclosures(self, disclosures):
        item = _stage1("disclosures", kind="fetch_company_disclosures")
        item.status = "done"
        item.result = {"value": disclosures}
        return _job_with([item])

    def test_adds_items_only_for_signal_matched(self):
        job = self._job_with_disclosures([
            {"rcept_no": "1", "report_nm": "전환사채권 발행결정"},
            {"rcept_no": "2", "report_nm": "임원ㆍ주요주주특정증권등소유상황보고서"},
        ])
        added = runner.expand_stage2(job)
        self.assertEqual(added, 1)
        stage2 = [i for i in job.items if i.stage == 2]
        self.assertEqual(stage2[0].params["rcept_no"], "1")

    def test_is_idempotent(self):
        job = self._job_with_disclosures([{"rcept_no": "1", "report_nm": "전환사채권 발행결정"}])
        runner.expand_stage2(job)
        self.assertEqual(runner.expand_stage2(job), 0)
        self.assertEqual(len([i for i in job.items if i.stage == 2]), 1)

    def test_sets_expanded_flag(self):
        job = self._job_with_disclosures([])
        runner.expand_stage2(job)
        self.assertTrue(job.stage2_expanded)

    def test_does_not_expand_while_stage1_pending(self):
        """1단이 진행 중이면 공시 목록이 확정되지 않았으므로 확장하지 않는다."""
        job = _job_with([_stage1("disclosures", kind="fetch_company_disclosures")])
        self.assertEqual(runner.expand_stage2(job), 0)
        self.assertFalse(job.stage2_expanded)

    def test_marks_expanded_when_disclosures_missing(self):
        """공시 조회가 실패해도 확장 패스는 끝난 것으로 표시해야 한다.

        표시하지 않으면 추가할 항목이 없는데도 job.status가 영원히 running에
        머물러 호출자가 무한 루프에 빠진다.
        """
        item = _stage1("company_info")
        item.status = "done"
        item.result = {"value": {}}
        job = _job_with([item])  # disclosures 항목 자체가 없다
        self.assertEqual(runner.expand_stage2(job), 0)
        self.assertTrue(job.stage2_expanded)

    def test_marks_expanded_when_disclosures_failed(self):
        item = _stage1("disclosures", kind="fetch_company_disclosures")
        item.status = "failed"
        item.error = "DART 오류"
        job = _job_with([item])
        self.assertEqual(runner.expand_stage2(job), 0)
        self.assertTrue(job.stage2_expanded)

    def test_deduplicates_repeated_rcept_no(self):
        job = self._job_with_disclosures([
            {"rcept_no": "1", "report_nm": "전환사채권 발행결정"},
            {"rcept_no": "1", "report_nm": "전환사채권 발행결정"},
        ])
        self.assertEqual(runner.expand_stage2(job), 1)


class TestRegistryCoupling(unittest.TestCase):
    """expand_stage2가 찾는 키가 registry와 어긋나면 2단이 조용히 죽는다."""

    def test_disclosures_key_exists_in_registry(self):
        from se_server.jobs.registry import STAGE1_SPECS

        self.assertIn(runner.DISCLOSURES_KEY, {s.key for s in STAGE1_SPECS})

    def test_expand_uses_the_registry_key(self):
        """리터럴이 아니라 상수를 통해 결합돼 있는지 확인한다."""
        from se_server.jobs.registry import build_stage1_items

        items = build_stage1_items("00126380", 1)
        target = [i for i in items if i.key == runner.DISCLOSURES_KEY]
        self.assertEqual(len(target), 1)


class TestEndToEnd(unittest.TestCase):
    """1단 → 2단 확장 → 2단 실행 → done이 실제로 이어지는지 확인한다.

    다른 2단 테스트는 stage2_expanded=True를 선주입하므로 이 경로를 밟지 않는다.
    """

    def test_full_cycle_reaches_done(self):
        store = MemoryJobStore()
        disc = _stage1("disclosures", kind="fetch_company_disclosures")
        store.save(_job_with([disc]))

        def fake_list(**kw):
            return [{"rcept_no": "1", "report_nm": "전환사채권 발행결정"}]

        with mock.patch.object(runner, "resolve_callable", return_value=fake_list), \
                mock.patch.object(runner, "fetch_disclosure_full",
                                  return_value={"text": "본문"}) as fetch:
            result = runner.run_step("j1", "KEY", store, budget_seconds=100.0,
                                     now=_Clock(0.1))

        self.assertTrue(result.done)
        fetch.assert_called_once()
        job = store.load("j1")
        self.assertTrue(job.stage2_expanded)
        self.assertEqual(len([i for i in job.items if i.stage == 2]), 1)
        self.assertTrue(all(i.status == "done" for i in job.items))


class TestJsonable(unittest.TestCase):
    """core 반환 타입은 제각각이라 JSONB에 넣기 전 정규화가 필요하다."""

    def test_converts_set_of_strings(self):
        """fetch_executive_roster는 dict[str, set[str]]을 돌려준다."""
        self.assertEqual(runner._jsonable({"홍길동": {"2024", "2023"}}),
                         {"홍길동": ["2023", "2024"]})

    def test_result_is_json_serializable(self):
        import json
        value = runner._jsonable({"a": {"2024"}, "b": [(1, 2)], "c": None})
        json.dumps(value)  # 예외가 나면 실패

    def test_non_string_dict_keys_become_strings(self):
        import json
        json.dumps(runner._jsonable({(1, 2): "값"}))

    def test_unknown_type_degrades_to_str(self):
        """저장 직전에 터지면 진행이 통째로 유실되므로 낮춰서라도 살린다."""
        import json

        class Odd:
            def __str__(self):
                return "odd"

        json.dumps(runner._jsonable({"x": Odd()}))

    def test_executive_roster_detail_row_list_survives_jsonable(self):
        """SE-6 Task 2b: registry.py의 executive_roster 스펙이
        fetch_executive_roster_detail(사람 단위 행 목록)을 가리키게 바뀐다.
        이 함수는 fetch_executive_roster와 달리 dict[str, set[str]]이 아니라
        list[dict]를 돌려주므로, _jsonable의 set 특수 처리(위
        test_converts_set_of_strings)가 걸리는 경로가 아니다 — 일반
        list/dict 재귀 경로로 값이 그대로 통과해야 한다(섹션 페이로드가
        조용히 깨지지 않는다는 증거)."""
        rows = [
            {"nm": "이승호", "corp_name": "엔켐", "birth_ym": "197203",
             "ofcps": "사내이사", "rgist_exctv_at": "등기", "years": ["2025", "2026"]},
        ]
        self.assertEqual(runner._jsonable(rows), rows)


class TestExecutiveRosterSpecPointsToDetailFunction(unittest.TestCase):
    """registry.py의 executive_roster Stage1Spec이 SE-6 Task 2b의 새
    함수를 가리켜야 birth_ym·ofcps·rgist_exctv_at이 화면까지 도착한다.
    기존 fetch_executive_roster(dict[str, set[str]])는 find_actor_overlap과
    이 파일의 겸직 판정에 그대로 묶여 있으므로 손대지 않는다.
    """

    def test_spec_func_name_is_detail_variant(self):
        from se_server.jobs.registry import STAGE1_SPECS

        by_key = {s.key: s for s in STAGE1_SPECS}
        self.assertEqual(
            by_key["executive_roster"].func_name, "fetch_executive_roster_detail"
        )

    def test_new_func_name_resolves_and_old_func_untouched(self):
        from dart_risk_mcp.core import dart_client
        from se_server.jobs.registry import resolve_callable

        self.assertIs(
            resolve_callable("fetch_executive_roster_detail"),
            dart_client.fetch_executive_roster_detail,
        )
        # 기존 겸직 판정(find_actor_overlap·이 파일의 특수 처리)이 의존하는
        # 옛 함수는 여전히 개별적으로 호출 가능해야 한다.
        self.assertTrue(callable(dart_client.fetch_executive_roster))


class TestStage2Execution(unittest.TestCase):
    def test_stage2_item_calls_document_fetch(self):
        store = MemoryJobStore()
        item = WorkItem(key="doc:1", stage=2, kind="fetch_disclosure_full",
                        params={"rcept_no": "1"})
        store.save(_job_with([item], stage2_expanded=True))
        with mock.patch.object(runner, "fetch_disclosure_full",
                               return_value={"text": "본문"}) as fetch:
            runner.run_step("j1", "KEY", store, budget_seconds=100.0, now=_Clock(0.1))
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args[0][0], "1")
        self.assertEqual(store.load("j1").items[0].status, "done")


class TestResultScrubbing(unittest.TestCase):
    """core 함수가 실패를 예외가 아니라 값으로 돌려줄 때도 키가 새면 안 된다.

    dart_client.fetch_major_decision 같은 함수는
    {"error": f"DART 조회 실패: {e}"}를 예외가 아니라 **반환값**으로 돌려주며,
    requests 예외의 str(e)에는 crtfc_key가 박힌 요청 URL 전체가 들어간다.
    _execute가 item.error뿐 아니라 반환값 자체도 스크럽하지 않으면, 나중에
    DS005 계열 spec을 registry에 하나 추가하는 순간 공유 state JSONB에
    DART API 키가 그대로 남는다.
    """

    KEY = "SECRETRESULTKEY99"

    def test_key_in_error_value_field_is_scrubbed(self):
        store = MemoryJobStore()
        store.save(_job_with([_stage1("bad")]))
        leaking = {
            "error": (
                "DART 조회 실패: https://opendart.fss.or.kr/api/list.json?"
                f"crtfc_key={self.KEY}&corp_code=1"
            ),
        }
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: leaking):
            runner.run_step("j1", self.KEY, store, budget_seconds=100.0, now=_Clock(0.1))
        result = store.load("j1").items[0].result
        self.assertNotIn(self.KEY, str(result))

    def test_key_nested_inside_list_of_dicts_is_scrubbed(self):
        """dict 안 list 안 dict처럼 여러 겹 중첩돼도 재귀적으로 스크럽돼야 한다."""
        store = MemoryJobStore()
        store.save(_job_with([_stage1("bad")]))
        leaking = {
            "rows": [
                {"note": "정상"},
                {"note": f"crtfc_key={self.KEY} 조회 실패"},
            ]
        }
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: leaking):
            runner.run_step("j1", self.KEY, store, budget_seconds=100.0, now=_Clock(0.1))
        result = store.load("j1").items[0].result
        self.assertNotIn(self.KEY, str(result))
        # 스크럽이 구조를 통째로 지우는 게 아니라 문자열만 치환했는지도 확인한다.
        self.assertEqual(result["value"]["rows"][0]["note"], "정상")

    def test_key_in_list_of_dicts_at_top_level_is_scrubbed(self):
        store = MemoryJobStore()
        store.save(_job_with([_stage1("bad")]))
        leaking = [{"error": f"crtfc_key={self.KEY}"}, {"ok": True}]
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: leaking):
            runner.run_step("j1", self.KEY, store, budget_seconds=100.0, now=_Clock(0.1))
        result = store.load("j1").items[0].result
        self.assertNotIn(self.KEY, str(result))


class TestIntermediateSave(unittest.TestCase):
    """중간 저장이 없으면 함수가 죽었을 때 그 단계 전체가 유실된다.

    store.save가 루프 종료 후 1회뿐이면, Vercel이 마지막 항목의 예산
    초과분에서 함수를 죽였을 때 그 단계의 결과가 전부 사라지고 attempts조차
    남지 않아 같은 지점에서 영구 반복한다.
    """

    def test_store_save_called_more_than_once_when_interval_elapses(self):
        store = MemoryJobStore()
        store.save(_job_with([_stage1(f"k{i}") for i in range(6)]))

        calls = {"n": 0}
        original_save = store.save

        def counting_save(job):
            calls["n"] += 1
            original_save(job)

        store.save = counting_save

        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {"ok": 1}):
            runner.run_step("j1", "KEY", store, budget_seconds=100.0,
                            now=_Clock(2.0), save_interval_seconds=3.0)

        # 루프 도중 저장이 최소 한 번 + 루프 종료 후 마지막 저장 한 번,
        # 최소 2회는 있어야 "1회뿐"이라는 결함이 재현되지 않는다.
        self.assertGreater(calls["n"], 1)

    def test_default_save_interval_matches_module_constant(self):
        """save_interval_seconds를 안 넘겨도 SAVE_INTERVAL 기본값이 적용된다."""
        store = MemoryJobStore()
        store.save(_job_with([_stage1(f"k{i}") for i in range(10)]))

        calls = {"n": 0}
        original_save = store.save

        def counting_save(job):
            calls["n"] += 1
            original_save(job)

        store.save = counting_save

        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {"ok": 1}):
            runner.run_step("j1", "KEY", store, budget_seconds=1000.0,
                            now=_Clock(runner.SAVE_INTERVAL))

        self.assertGreater(calls["n"], 1)


class TestStalledSimplification(unittest.TestCase):
    """stalled = processed == 0 and not done 단순화 이후의 경계값들.

    이전 구현은 blocked_by_reserve 플래그가 설 때만 stalled=True였다.
    budget_seconds<=0이고 남은 항목이 oversized가 아니면, remaining<=0으로
    루프가 즉시 break하며 blocked_by_reserve는 한 번도 세팅되지 않아
    processed=0인데도 stalled=False로 조용히 반환됐다.
    """

    def test_zero_budget_reports_stalled(self):
        store = MemoryJobStore()
        store.save(_job_with([_stage1("k0")]))  # oversized 아님 → ValueError 가드 미발동
        result = runner.run_step("j1", "KEY", store, budget_seconds=0.0, now=_Clock(1.0))
        self.assertEqual(result.processed, 0)
        self.assertFalse(result.done)
        self.assertTrue(result.stalled)

    def test_negative_budget_reports_stalled(self):
        store = MemoryJobStore()
        store.save(_job_with([_stage1("k0")]))
        result = runner.run_step("j1", "KEY", store, budget_seconds=-5.0, now=_Clock(1.0))
        self.assertEqual(result.processed, 0)
        self.assertTrue(result.stalled)

    def test_reserve_block_stalled_semantics_preserved(self):
        """단순화 이후에도 예약분 부족으로 인한 정체는 여전히 True로 남아야 한다."""
        store = MemoryJobStore()
        item = WorkItem(key="insider_timeline", stage=1, kind="fetch_insider_timeline",
                        params={"corp_code": "0", "lookback_years": 5})
        store.save(_job_with([item]))
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {}):
            result = runner.run_step("j1", "KEY", store,
                                     budget_seconds=runner.OVERSIZED_RESERVE + 1.0,
                                     now=_Clock(2.0))
        self.assertEqual(result.processed, 0)
        self.assertTrue(result.stalled)

    def test_zero_budget_with_pending_oversized_still_raises(self):
        """budget<=0이어도 대기 중인 oversized 항목이 있으면 여전히 ValueError다.

        stalled 단순화가 이 가드를 우회하는 새 구멍을 만들지 않는지 확인한다.
        """
        store = MemoryJobStore()
        item = WorkItem(key="insider_timeline", stage=1, kind="fetch_insider_timeline",
                        params={"corp_code": "0", "lookback_years": 5})
        store.save(_job_with([item]))
        with self.assertRaises(ValueError):
            runner.run_step("j1", "KEY", store, budget_seconds=0.0, now=_Clock(1.0))


if __name__ == "__main__":
    unittest.main()
