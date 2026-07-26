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
        """oversized 항목은 남은 예산이 충분할 때만 시작한다."""
        store = MemoryJobStore()
        item = WorkItem(key="insider_timeline", stage=1, kind="fetch_insider_timeline",
                        params={"corp_code": "0", "lookback_years": 5})
        store.save(_job_with([item]))
        called = []
        with mock.patch.object(runner, "resolve_callable",
                               return_value=lambda **kw: called.append(1) or {"ok": 1}):
            result = runner.run_step("j1", "KEY", store,
                                     budget_seconds=runner.OVERSIZED_RESERVE - 1.0,
                                     now=_Clock(0.0))
        self.assertEqual(called, [])
        self.assertFalse(result.done)

    def test_reserve_block_reports_stalled(self):
        """예산이 작아 아무것도 시작 못 하면 정체를 알려야 한다.

        이 신호가 없으면 호출자는 "예산 소진(진행 중)"과 "영구 정지"를
        구분하지 못해 같은 예산으로 무한 반복한다.
        """
        store = MemoryJobStore()
        item = WorkItem(key="insider_timeline", stage=1, kind="fetch_insider_timeline",
                        params={"corp_code": "0", "lookback_years": 5})
        store.save(_job_with([item]))
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {}):
            result = runner.run_step("j1", "KEY", store,
                                     budget_seconds=runner.OVERSIZED_RESERVE - 1.0,
                                     now=_Clock(0.0))
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

        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {}):
            result = runner.run_step("j1", "KEY", store,
                                     budget_seconds=runner.OVERSIZED_RESERVE - 1.0,
                                     now=_Clock(0.1))

        job = store.load("j1")
        self.assertEqual(result.processed, 2)   # 작은 항목 둘은 처리됐다
        self.assertFalse(result.stalled)        # 진행이 있었으므로 정체 아님
        self.assertEqual(job.items[0].status, "pending")  # oversized는 그대로 대기

    def test_stalled_only_when_all_remaining_are_oversized(self):
        store = MemoryJobStore()
        big = WorkItem(key="insider_timeline", stage=1, kind="fetch_insider_timeline",
                       params={"corp_code": "0", "lookback_years": 5})
        big2 = WorkItem(key="audit_history", stage=1, kind="fetch_audit_opinion_history",
                        params={"corp_code": "0", "lookback_years": 5})
        store.save(_job_with([big, big2]))
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {}):
            result = runner.run_step("j1", "KEY", store,
                                     budget_seconds=runner.OVERSIZED_RESERVE - 1.0,
                                     now=_Clock(0.1))
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


if __name__ == "__main__":
    unittest.main()
