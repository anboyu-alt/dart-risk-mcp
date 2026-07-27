"""브라우저용 공개 설정. service_role 키가 새면 안 된다."""
import json
import unittest
from unittest import mock

from se_server.api.handlers import Deps, handle
from se_server.api.types import Request
from se_server.config import SEConfig
from se_server.jobs.store import MemoryJobStore

CFG = SEConfig(
    supabase_url="https://proj.supabase.co",
    supabase_service_key="SERVICE_KEY_MUST_NOT_LEAK",
    cache_bucket="se-cache",
    supabase_anon_key="ANON_KEY_IS_PUBLIC",
)


class _Auth:
    def verify(self, bearer):
        raise AssertionError("config 엔드포인트는 인증을 호출하면 안 된다")


def _deps():
    return Deps(store=MemoryJobStore(), auth=_Auth(), config=CFG)


class TestConfigEndpoint(unittest.TestCase):
    def test_returns_public_config_without_auth(self):
        resp = handle(Request("GET", "/api/se/config", {}, {}), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["supabase_url"], "https://proj.supabase.co")
        self.assertEqual(resp.body["supabase_anon_key"], "ANON_KEY_IS_PUBLIC")

    def test_never_leaks_service_key(self):
        resp = handle(Request("GET", "/api/se/config", {}, {}), _deps())
        dumped = json.dumps(resp.body, ensure_ascii=False)
        self.assertNotIn("SERVICE_KEY_MUST_NOT_LEAK", dumped)
        self.assertNotIn("service", dumped.lower())

    def test_never_touches_store(self):
        store = mock.Mock()
        handle(Request("GET", "/api/se/config", {}, {}),
               Deps(store=store, auth=_Auth(), config=CFG))
        store.load.assert_not_called()
        store.save.assert_not_called()

    def test_missing_anon_key_is_empty_not_error(self):
        """anon 키 미설정은 설정 실수다. 500이 아니라 빈 값으로 알린다."""
        cfg = SEConfig(supabase_url="https://p.supabase.co",
                       supabase_service_key="K", cache_bucket="b")
        resp = handle(Request("GET", "/api/se/config", {}, {}),
                      Deps(store=MemoryJobStore(), auth=_Auth(), config=cfg))
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["supabase_anon_key"], "")


class TestConfigFromEnv(unittest.TestCase):
    def test_reads_anon_key(self):
        env = {"SUPABASE_URL": "https://x.supabase.co",
               "SUPABASE_SERVICE_KEY": "K", "SUPABASE_ANON_KEY": "A"}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertEqual(SEConfig.from_env().supabase_anon_key, "A")

    def test_anon_key_is_optional(self):
        env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": "K"}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertEqual(SEConfig.from_env().supabase_anon_key, "")

    def test_anon_key_is_not_in_repr(self):
        """공개 키지만 repr에 굳이 담을 이유가 없다."""
        self.assertNotIn("ANON_KEY_IS_PUBLIC", repr(CFG))


if __name__ == "__main__":
    unittest.main()
