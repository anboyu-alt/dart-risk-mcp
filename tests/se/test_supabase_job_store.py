"""SupabaseJobStore의 HTTP 계약. 실제 네트워크는 타지 않는다."""
import unittest
from unittest import mock

from se_server.config import SEConfig
from se_server.jobs.model import Job, WorkItem
from se_server.jobs.supabase_store import SupabaseJobStore

CFG = SEConfig(
    supabase_url="https://proj.supabase.co",
    supabase_service_key="SERVICE_KEY",
    cache_bucket="se-cache",
)


def _resp(status=200, json_body=None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = json_body if json_body is not None else []
    return r


def _job():
    return Job(job_id="j1", company="테스트", corp_code="0", lookback_years=1,
               items=[WorkItem(key="a", stage=1, kind="fetch", params={})])


class TestSave(unittest.TestCase):
    def test_upserts_with_merge_duplicates(self):
        session = mock.Mock()
        session.post.return_value = _resp(201)
        SupabaseJobStore(CFG, session=session).save(_job())
        headers = session.post.call_args[1]["headers"]
        self.assertIn("resolution=merge-duplicates", headers["Prefer"])
        self.assertEqual(headers["Authorization"], "Bearer SERVICE_KEY")

    def test_payload_carries_job_id_and_state(self):
        session = mock.Mock()
        session.post.return_value = _resp(201)
        SupabaseJobStore(CFG, session=session).save(_job())
        payload = session.post.call_args[1]["json"]
        self.assertEqual(payload["job_id"], "j1")
        self.assertEqual(payload["state"]["company"], "테스트")

    def test_failure_raises(self):
        """작업 상태 저장 실패는 삼키면 안 된다 — 진행이 유실된다."""
        session = mock.Mock()
        session.post.return_value = _resp(500)
        with self.assertRaises(RuntimeError):
            SupabaseJobStore(CFG, session=session).save(_job())

    def test_network_error_propagates(self):
        session = mock.Mock()
        session.post.side_effect = RuntimeError("네트워크 오류")
        with self.assertRaises(RuntimeError):
            SupabaseJobStore(CFG, session=session).save(_job())

    def test_service_key_not_in_payload(self):
        session = mock.Mock()
        session.post.return_value = _resp(201)
        SupabaseJobStore(CFG, session=session).save(_job())
        import json
        self.assertNotIn("SERVICE_KEY", json.dumps(session.post.call_args[1]["json"]))


class TestLoad(unittest.TestCase):
    def test_returns_job(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, json_body=[{"state": _job().to_dict()}])
        loaded = SupabaseJobStore(CFG, session=session).load("j1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.company, "테스트")

    def test_empty_result_returns_none(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, json_body=[])
        self.assertIsNone(SupabaseJobStore(CFG, session=session).load("없음"))

    def test_query_filters_by_job_id(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, json_body=[])
        SupabaseJobStore(CFG, session=session).load("j1")
        self.assertEqual(session.get.call_args[1]["params"]["job_id"], "eq.j1")

    def test_http_error_raises(self):
        """조회 실패와 '작업 없음'은 다르게 다뤄야 한다."""
        session = mock.Mock()
        session.get.return_value = _resp(500)
        with self.assertRaises(RuntimeError):
            SupabaseJobStore(CFG, session=session).load("j1")


if __name__ == "__main__":
    unittest.main()
