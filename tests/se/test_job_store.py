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

    def test_nested_item_dicts_are_detached(self):
        """항목의 params·result까지 분리돼야 한다.

        WorkItem.from_dict는 params·result를 참조로 대입하므로, 저장소가
        내부 dict를 그대로 넘기면 load()가 돌려준 객체의 params·result를
        제자리에서(in-place) 고치는 순간 save() 호출 전인데도 저장분이
        오염된다. 중간 결과를 항목에 채워 넣으며 여러 번 호출하는 게 이
        모듈의 존재 이유라 이 공유는 곧 재개 버그다.

        주의: params가 빈 dict({})면 `data.get("params") or {}`의 `or`가
        falsy를 매번 새 dict로 치환해버려 공유가 우연히 가려진다. 그래서
        여기서는 저장 전에 params·result를 비어있지 않은 값으로 채워
        진짜 공유 여부가 드러나게 한다.
        """
        store = MemoryJobStore()
        job = _job()
        job.items[0].params["seed"] = 1
        job.items[0].result = {"count": 1}
        store.save(job)

        loaded = store.load("j1")
        loaded.items[0].params["오염"] = True
        loaded.items[0].result["count"] = 999

        again = store.load("j1")
        self.assertNotIn("오염", again.items[0].params)
        self.assertEqual(again.items[0].result["count"], 1)

    def test_separate_loads_do_not_share_objects(self):
        """서로 다른 load() 호출은 같은 params 객체를 공유하면 안 된다.

        params가 비어있으면 `or {}`가 매번 새 dict를 만들어 이 검증을
        우연히 통과시키므로, 여기서도 비어있지 않은 params로 검증한다.
        """
        a = MemoryJobStore()
        job = _job()
        job.items[0].params["seed"] = 1
        a.save(job)
        first, second = a.load("j1"), a.load("j1")
        self.assertIsNot(first.items[0].params, second.items[0].params)

    def test_saved_job_is_detached_from_caller(self):
        """저장 후 호출자가 원본을 고쳐도 저장분이 바뀌면 안 된다."""
        store = MemoryJobStore()
        job = _job()
        store.save(job)
        job.items[0].params["나중에"] = 1
        self.assertNotIn("나중에", store.load("j1").items[0].params)

class TestNewJobId(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = {new_job_id() for _ in range(200)}
        self.assertEqual(len(ids), 200)

    def test_id_is_url_safe(self):
        import re
        self.assertRegex(new_job_id(), r"^[A-Za-z0-9_-]+$")

if __name__ == "__main__":
    unittest.main()
