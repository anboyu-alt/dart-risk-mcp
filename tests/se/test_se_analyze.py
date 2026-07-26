"""작업 실행 CLI의 순수 로직. DART 호출은 스텁한다."""
import unittest
from unittest import mock

from scripts import se_analyze
from se_server.jobs.store import MemoryJobStore


class TestRunToCompletion(unittest.TestCase):
    def test_loops_until_done(self):
        store = MemoryJobStore()
        with mock.patch.object(
            se_analyze, "resolve_corp",
            return_value=("테스트회사", {"corp_code": "0", "stock_code": "0"}),
        ), mock.patch.object(
            se_analyze.runner, "resolve_callable", return_value=lambda **kw: []
        ), mock.patch.object(
            se_analyze.runner, "fetch_disclosure_full", return_value={"text": ""}
        ):
            job_id, steps = se_analyze.run_to_completion(
                "테스트회사", "KEY", 1, store, budget_seconds=1000.0
            )
        self.assertTrue(steps)
        self.assertTrue(steps[-1].done)
        self.assertEqual(store.load(job_id).status, "done")

    def test_small_budget_needs_multiple_steps(self):
        """예산을 잘게 주면 여러 단계로 나뉘고, 그래도 끝까지 간다.

        브리프 작성 시점에는 없었던 OVERSIZED_RESERVE(20초) 게이트를 0으로
        낮춰 둔다 — 그렇지 않으면 예산 6초로는 oversized 항목(실제
        STAGE1_SPECS 13개 중 6개)에 영원히 도달하지 못해 stalled=True가
        고착되고, 이 테스트가 검증하려는 "결국 끝까지 간다"는 성립하지
        않는다. 이 게이트 자체의 동작은 tests/se/test_job_runner.py가
        별도로 검증한다.
        """
        store = MemoryJobStore()
        clock = {"t": 0.0}

        def tick():
            clock["t"] += 5.0
            return clock["t"]

        with mock.patch.object(
            se_analyze, "resolve_corp",
            return_value=("테스트회사", {"corp_code": "0", "stock_code": "0"}),
        ), mock.patch.object(
            se_analyze.runner, "resolve_callable", return_value=lambda **kw: []
        ), mock.patch.object(
            se_analyze.runner, "fetch_disclosure_full", return_value={"text": ""}
        ), mock.patch.object(
            se_analyze.runner, "OVERSIZED_RESERVE", 0.0
        ):
            job_id, steps = se_analyze.run_to_completion(
                "테스트회사", "KEY", 1, store, budget_seconds=6.0, now=tick
            )
        self.assertGreater(len(steps), 1)
        self.assertTrue(steps[-1].done)

    def test_unresolved_company_raises(self):
        with mock.patch.object(se_analyze, "resolve_corp", return_value=(None, None)):
            with self.assertRaises(ValueError):
                se_analyze.run_to_completion("없는회사", "KEY", 1, MemoryJobStore(), 100.0)

    def test_guards_against_infinite_loop(self):
        """진행이 없는데 done도 아니면 무한 루프에 빠지지 않고 중단해야 한다."""
        store = MemoryJobStore()
        stuck = se_analyze.runner.StepResult(done=False, processed=0, finished=0, total=3)
        with mock.patch.object(
            se_analyze, "resolve_corp",
            return_value=("테스트회사", {"corp_code": "0", "stock_code": "0"}),
        ), mock.patch.object(se_analyze.runner, "run_step", return_value=stuck):
            with self.assertRaises(RuntimeError):
                se_analyze.run_to_completion("테스트회사", "KEY", 1, store, 100.0)


if __name__ == "__main__":
    unittest.main()
