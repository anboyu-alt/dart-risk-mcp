"""작업 자료구조와 직렬화."""
import json
import unittest

from se_server.jobs.model import Job, WorkItem


def _item(key, stage=1, status="pending"):
    return WorkItem(key=key, stage=stage, kind="fetch", params={"a": 1}, status=status)


class TestWorkItem(unittest.TestCase):
    def test_defaults(self):
        item = WorkItem(key="k", stage=1, kind="fetch", params={})
        self.assertEqual(item.status, "pending")
        self.assertIsNone(item.result)
        self.assertEqual(item.error, "")
        self.assertEqual(item.attempts, 0)

    def test_roundtrip(self):
        item = WorkItem(key="k", stage=2, kind="doc", params={"rcept_no": "1"},
                        status="done", result={"text": "x"}, attempts=2)
        restored = WorkItem.from_dict(item.to_dict())
        self.assertEqual(restored, item)

    def test_roundtrip_preserves_error(self):
        item = WorkItem(key="k", stage=1, kind="fetch", params={},
                        status="failed", error="타임아웃", attempts=3)
        self.assertEqual(WorkItem.from_dict(item.to_dict()).error, "타임아웃")


class TestJob(unittest.TestCase):
    def test_pending_items_excludes_done_and_failed(self):
        job = Job(job_id="j1", company="테스트", corp_code="0", lookback_years=1,
                  items=[_item("a"), _item("b", status="done"), _item("c", status="failed")])
        self.assertEqual([i.key for i in job.pending_items()], ["a"])

    def test_progress_counts_done_and_failed(self):
        job = Job(job_id="j1", company="테스트", corp_code="0", lookback_years=1,
                  items=[_item("a"), _item("b", status="done"), _item("c", status="failed")])
        self.assertEqual(job.progress(), (2, 3))

    def test_progress_on_empty_job(self):
        job = Job(job_id="j1", company="테스트", corp_code="0", lookback_years=1, items=[])
        self.assertEqual(job.progress(), (0, 0))

    def test_roundtrip(self):
        job = Job(job_id="j1", company="셀트리온", corp_code="00421045",
                  lookback_years=3, items=[_item("a"), _item("b", stage=2)],
                  status="running", stage2_expanded=True)
        restored = Job.from_dict(job.to_dict())
        self.assertEqual(restored, job)

    def test_to_dict_is_json_serializable(self):
        """저장소가 JSONB로 넣으므로 순수 JSON 타입만 담겨야 한다."""
        job = Job(job_id="j1", company="테스트", corp_code="0", lookback_years=1,
                  items=[_item("a")])
        json.dumps(job.to_dict())  # 예외가 나면 실패

    def test_dict_does_not_carry_api_key(self):
        """작업 레코드는 공유 저장소에 남으므로 DART 키가 섞이면 안 된다."""
        job = Job(job_id="j1", company="테스트", corp_code="0", lookback_years=1,
                  items=[_item("a")])
        self.assertNotIn("crtfc_key", json.dumps(job.to_dict()))


if __name__ == "__main__":
    unittest.main()
