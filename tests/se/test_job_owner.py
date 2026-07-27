"""작업 소유권 — job_id가 유일한 자격이 되면 안 된다."""
import unittest
from unittest import mock

from se_server.config import SEConfig
from se_server.jobs import runner
from se_server.jobs.model import Job, WorkItem
from se_server.jobs.store import MemoryJobStore
from se_server.jobs.supabase_store import SupabaseJobStore

CFG = SEConfig(supabase_url="https://p.supabase.co",
               supabase_service_key="K", cache_bucket="b")


def _job(user_id="owner-1"):
    return Job(job_id="j1", company="테스트", corp_code="0", lookback_years=1,
               items=[WorkItem(key="a", stage=1, kind="fetch", params={"seed": 1})],
               user_id=user_id)


class TestModel(unittest.TestCase):
    def test_user_id_survives_roundtrip(self):
        self.assertEqual(Job.from_dict(_job().to_dict()).user_id, "owner-1")

    def test_default_is_empty(self):
        job = Job(job_id="j", company="c", corp_code="0", lookback_years=1)
        self.assertEqual(job.user_id, "")

    def test_old_records_without_user_id_still_load(self):
        """SE-2가 만든 기존 레코드에는 user_id가 없다."""
        data = _job().to_dict()
        del data["user_id"]
        self.assertEqual(Job.from_dict(data).user_id, "")


class TestMemoryStoreOwnership(unittest.TestCase):
    def test_owner_can_load(self):
        store = MemoryJobStore()
        store.save(_job())
        self.assertIsNotNone(store.load("j1", user_id="owner-1"))

    def test_other_user_gets_none(self):
        store = MemoryJobStore()
        store.save(_job())
        self.assertIsNone(store.load("j1", user_id="침입자"))

    def test_empty_user_id_skips_check(self):
        """CLI는 인증 개념이 없으므로 소유자 검사를 건너뛴다."""
        store = MemoryJobStore()
        store.save(_job())
        self.assertIsNotNone(store.load("j1"))

    def test_missing_job_still_returns_none(self):
        self.assertIsNone(MemoryJobStore().load("없음", user_id="owner-1"))


class TestSupabaseStoreOwnership(unittest.TestCase):
    def test_query_filters_by_user_id(self):
        session = mock.Mock()
        resp = mock.Mock()
        resp.status_code = 200
        resp.json.return_value = []
        session.get.return_value = resp
        SupabaseJobStore(CFG, session=session).load("j1", user_id="owner-1")
        params = session.get.call_args[1]["params"]
        self.assertEqual(params["user_id"], "eq.owner-1")

    def test_no_user_filter_when_empty(self):
        session = mock.Mock()
        resp = mock.Mock()
        resp.status_code = 200
        resp.json.return_value = []
        session.get.return_value = resp
        SupabaseJobStore(CFG, session=session).load("j1")
        self.assertNotIn("user_id", session.get.call_args[1]["params"])

    def test_save_sends_user_id(self):
        session = mock.Mock()
        resp = mock.Mock()
        resp.status_code = 201
        session.post.return_value = resp
        SupabaseJobStore(CFG, session=session).save(_job())
        self.assertEqual(session.post.call_args[1]["json"]["user_id"], "owner-1")


class TestRunStepOwner(unittest.TestCase):
    """run_step이 user_id를 store.load에 전달하는지 고정한다.

    이 한 줄이 빠지면 핸들러가 소유자를 확인한 뒤 run_step이 다시 무조건
    load해 **검사가 통째로 우회된다.** 다른 테스트는 Job·저장소·create_job만
    덮으므로 이 경로는 무방비였다(뮤테이션으로 확인 — 지워도 전부 초록).
    """

    def test_other_user_cannot_run(self):
        store = MemoryJobStore()
        job = runner.create_job("테스트", "0", 1, store, user_id="owner-1")
        with self.assertRaises(ValueError):
            runner.run_step(job.job_id, "KEY", store, user_id="침입자")

    def test_owner_can_run(self):
        store = MemoryJobStore()
        job = runner.create_job("테스트", "0", 1, store, user_id="owner-1")
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {}):
            result = runner.run_step(job.job_id, "KEY", store,
                                     budget_seconds=1000.0, user_id="owner-1")
        self.assertGreater(result.processed, 0)

    def test_empty_user_id_still_works_for_cli(self):
        """CLI는 인증 개념이 없으므로 소유자 없이도 진행할 수 있어야 한다."""
        store = MemoryJobStore()
        job = runner.create_job("테스트", "0", 1, store)
        with mock.patch.object(runner, "resolve_callable", return_value=lambda **kw: {}):
            result = runner.run_step(job.job_id, "KEY", store, budget_seconds=1000.0)
        self.assertGreater(result.processed, 0)

    def test_none_user_id_is_documented_as_skipping_check(self):
        """None은 ""와 같이 검사를 건너뛴다.

        의도된 동작이 아니라 `if user_id and ...`의 부수 효과다. 핸들러는
        절대 None을 넘기지 않아야 하며(인증 계층이 비어있지 않은 str을
        보장한다), 이 테스트는 그 사실을 명시적으로 기록해 둔다.
        """
        store = MemoryJobStore()
        job = runner.create_job("테스트", "0", 1, store, user_id="owner-1")
        self.assertIsNotNone(store.load(job.job_id, user_id=None))


class TestCreateJobOwner(unittest.TestCase):
    def test_records_owner(self):
        store = MemoryJobStore()
        job = runner.create_job("셀트리온", "00421045", 1, store, user_id="owner-1")
        self.assertEqual(job.user_id, "owner-1")
        self.assertEqual(store.load(job.job_id).user_id, "owner-1")

    def test_default_keeps_cli_working(self):
        store = MemoryJobStore()
        job = runner.create_job("셀트리온", "00421045", 1, store)
        self.assertEqual(job.user_id, "")


if __name__ == "__main__":
    unittest.main()
