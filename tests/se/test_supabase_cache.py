"""SupabaseCache의 HTTP 계약. 실제 네트워크는 타지 않는다."""
import unittest
from unittest import mock

from se_server.cache.supabase import SupabaseCache
from se_server.config import SEConfig

CFG = SEConfig(
    supabase_url="https://proj.supabase.co",
    supabase_service_key="SERVICE_KEY",
    cache_bucket="se-cache",
)


def _resp(status=200, content=b"", json_body=None):
    r = mock.Mock()
    r.status_code = status
    r.content = content
    r.json.return_value = json_body if json_body is not None else []
    return r


class TestBlob(unittest.TestCase):
    def test_get_blob_hit(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, b"ZIPDATA")
        cache = SupabaseCache(CFG, session=session)
        self.assertEqual(cache.get_blob("document.xml/abc"), b"ZIPDATA")
        url = session.get.call_args[0][0]
        self.assertEqual(
            url, "https://proj.supabase.co/storage/v1/object/se-cache/document.xml/abc"
        )

    def test_get_blob_miss_returns_none(self):
        session = mock.Mock()
        session.get.return_value = _resp(404)
        cache = SupabaseCache(CFG, session=session)
        self.assertIsNone(cache.get_blob("document.xml/abc"))

    def test_put_blob_uses_upsert_header(self):
        session = mock.Mock()
        session.post.return_value = _resp(200)
        cache = SupabaseCache(CFG, session=session)
        cache.put_blob("document.xml/abc", b"ZIPDATA")
        headers = session.post.call_args[1]["headers"]
        self.assertEqual(headers["x-upsert"], "true")
        self.assertEqual(headers["Authorization"], "Bearer SERVICE_KEY")

    def test_blob_write_failure_does_not_propagate(self):
        """캐시 쓰기 실패가 분석 전체를 중단시키면 안 된다.

        캐시는 성능 최적화이지 정확성의 일부가 아니다. 저장에 실패하면
        조용히 포기하고 호출자는 계속 진행해야 한다.
        """
        session = mock.Mock()
        session.post.side_effect = RuntimeError("네트워크 오류")
        cache = SupabaseCache(CFG, session=session)

        try:
            cache.put_blob("k", b"x")
        except Exception as exc:  # pragma: no cover - 실패 시 진단용
            self.fail(f"put_blob이 예외를 전파했습니다: {exc!r}")

        self.assertEqual(session.post.call_count, 1)

    def test_blob_read_failure_is_a_miss(self):
        session = mock.Mock()
        session.get.side_effect = RuntimeError("네트워크 오류")
        cache = SupabaseCache(CFG, session=session)
        self.assertIsNone(cache.get_blob("k"))


class TestJson(unittest.TestCase):
    def test_get_json_hit(self):
        session = mock.Mock()
        session.get.return_value = _resp(
            200, json_body=[{"key": "k", "value": {"status": 200}, "expires_at": None}]
        )
        cache = SupabaseCache(CFG, session=session)
        self.assertEqual(cache.get_json("k"), {"status": 200})

    def test_get_json_empty_result_is_miss(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, json_body=[])
        cache = SupabaseCache(CFG, session=session)
        self.assertIsNone(cache.get_json("k"))

    def test_put_json_sends_merge_duplicates(self):
        session = mock.Mock()
        session.post.return_value = _resp(201)
        cache = SupabaseCache(CFG, session=session)
        cache.put_json("k", {"status": 200}, ttl_seconds=60)
        headers = session.post.call_args[1]["headers"]
        self.assertIn("resolution=merge-duplicates", headers["Prefer"])

    def test_put_json_without_ttl_sends_null_expiry(self):
        session = mock.Mock()
        session.post.return_value = _resp(201)
        cache = SupabaseCache(CFG, session=session)
        cache.put_json("k", {"a": 1}, ttl_seconds=None)
        payload = session.post.call_args[1]["json"]
        self.assertIsNone(payload["expires_at"])


class TestConfig(unittest.TestCase):
    def test_from_env_reads_variables(self):
        env = {
            "SUPABASE_URL": "https://x.supabase.co",
            "SUPABASE_SERVICE_KEY": "KEY",
            "SE_CACHE_BUCKET": "bucket",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = SEConfig.from_env()
        self.assertEqual(cfg.supabase_url, "https://x.supabase.co")
        self.assertEqual(cfg.cache_bucket, "bucket")

    def test_from_env_missing_required_raises(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                SEConfig.from_env()

    def test_trailing_slash_stripped(self):
        env = {"SUPABASE_URL": "https://x.supabase.co/", "SUPABASE_SERVICE_KEY": "K"}
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = SEConfig.from_env()
        self.assertEqual(cfg.supabase_url, "https://x.supabase.co")


if __name__ == "__main__":
    unittest.main()
