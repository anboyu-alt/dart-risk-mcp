"""작업 저장소 기본 동작."""
import unittest

from se_server.jobs.model import Job, WorkItem
from se_server.jobs.store import MemoryJobStore, new_job_id

def _job(job_id="j1"):
    return Job(job_id=job_id, company="테스트", corp_code="0", lookback_years=1,
               items=[WorkItem(key="a", stage=1, kind="fetch", params={})])

class TestMemoryJobStore(unittest.TestCase):
    def test_load_missing_returns_none(self):
        self.assertIsNone(MemoryJobStore().load("없음"))

    def test_save_then_load(self):
        store = MemoryJobStore()
        store.save(_job())
        loaded = store.load("j1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.company, "테스트")

    def test_save_overwrites(self):
        store = MemoryJobStore()
        store.save(_job())
        job = store.load("j1")
        job.status = "done"
        store.save(job)
        self.assertEqual(store.load("j1").status, "done")

    def test_loaded_job_is_detached_copy(self):
        """저장소가 돌려준 객체를 고쳐도 저장분이 바뀌면 안 된다.

        실제 저장소(Postgres)는 항상 새 객체를 만들어 돌려주므로, 인메모리
        구현이 참조를 공유하면 테스트가 실서비스와 다르게 동작한다.
        """
        store = MemoryJobStore()
        store.save(_job())
        loaded = store.load("j1")
        loaded.status = "오염"
        self.assertEqual(store.load("j1").status, "running")

class TestNewJobId(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = {new_job_id() for _ in range(200)}
        self.assertEqual(len(ids), 200)

    def test_id_is_url_safe(self):
        import re
        self.assertRegex(new_job_id(), r"^[A-Za-z0-9_-]+$")

if __name__ == "__main__":
    unittest.main()
