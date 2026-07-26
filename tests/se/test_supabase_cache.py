"""SupabaseCache의 HTTP 계약. 실제 네트워크는 타지 않는다."""
import datetime as _dt
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


class TestJsonExpiryParsing(unittest.TestCase):
    """만료 시각 해석은 어떤 입력에도 예외를 밖으로 내보내지 않아야 한다.

    이 함수의 계약은 "읽기 실패는 미스로 처리"이므로, 형식이 깨졌거나
    시간대 정보가 없는 값이 와도 호출자에게 예외가 전파되면 안 된다.
    """

    def _cache_returning(self, expires_at):
        session = mock.Mock()
        session.get.return_value = _resp(
            200, json_body=[{"key": "k", "value": {"a": 1}, "expires_at": expires_at}]
        )
        return SupabaseCache(CFG, session=session)

    def test_naive_future_timestamp_is_treated_as_utc_and_valid(self):
        future = (
            _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=1)
        ).replace(tzinfo=None).isoformat()
        self.assertEqual(self._cache_returning(future).get_json("k"), {"a": 1})

    def test_naive_past_timestamp_is_expired(self):
        past = (
            _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1)
        ).replace(tzinfo=None).isoformat()
        self.assertIsNone(self._cache_returning(past).get_json("k"))

    def test_unparseable_timestamp_is_a_miss(self):
        self.assertIsNone(self._cache_returning("쓰레기값").get_json("k"))

    def test_non_string_timestamp_is_a_miss(self):
        self.assertIsNone(self._cache_returning(12345).get_json("k"))


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

    def test_repr_does_not_expose_service_key(self):
        """service_role 키는 RLS를 우회하는 최고 권한 자격증명이다.

        기본 dataclass __repr__은 모든 필드를 그대로 출력하므로, 로그나
        예외 문자열에 config 객체가 한 번만 찍혀도 키가 유출된다.
        """
        cfg = SEConfig(
            supabase_url="https://x.supabase.co",
            supabase_service_key="SUPER_SECRET_SERVICE_ROLE_KEY",
        )
        self.assertNotIn("SUPER_SECRET_SERVICE_ROLE_KEY", repr(cfg))
        self.assertNotIn("SUPER_SECRET_SERVICE_ROLE_KEY", str(cfg))

    def test_repr_still_shows_non_secret_fields(self):
        """repr=False는 service_key에만 적용돼야 하고, 다른 필드는 그대로 보여야 한다."""
        cfg = SEConfig(
            supabase_url="https://x.supabase.co",
            supabase_service_key="SECRET",
            cache_bucket="my-bucket",
        )
        self.assertIn("https://x.supabase.co", repr(cfg))
        self.assertIn("my-bucket", repr(cfg))


if __name__ == "__main__":
    unittest.main()
