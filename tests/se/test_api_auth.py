"""Supabase Auth 가드. 실제 네트워크는 타지 않는다."""
import unittest
from unittest import mock

from se_server.api.auth import AuthError, SupabaseAuth, extract_bearer
from se_server.config import SEConfig

CFG = SEConfig(
    supabase_url="https://proj.supabase.co",
    supabase_service_key="SERVICE_KEY",
    cache_bucket="se-cache",
)


def _resp(status=200, json_body=None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = json_body if json_body is not None else {}
    return r


class TestExtractBearer(unittest.TestCase):
    def test_extracts_token(self):
        self.assertEqual(extract_bearer("Bearer abc.def.ghi"), "abc.def.ghi")

    def test_is_case_insensitive_on_scheme(self):
        self.assertEqual(extract_bearer("bearer abc"), "abc")

    def test_rejects_other_schemes(self):
        self.assertEqual(extract_bearer("Basic abc"), "")

    def test_rejects_missing_token(self):
        self.assertEqual(extract_bearer("Bearer"), "")
        self.assertEqual(extract_bearer("Bearer "), "")

    def test_rejects_empty(self):
        self.assertEqual(extract_bearer(""), "")


class TestVerify(unittest.TestCase):
    def test_returns_user_id(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, {"id": "user-1", "email": "a@b.c"})
        auth = SupabaseAuth(CFG, session=session)
        self.assertEqual(auth.verify("TOKEN"), "user-1")

    def test_sends_bearer_and_apikey(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, {"id": "user-1"})
        SupabaseAuth(CFG, session=session).verify("TOKEN")
        headers = session.get.call_args[1]["headers"]
        self.assertEqual(headers["Authorization"], "Bearer TOKEN")
        self.assertIn("apikey", headers)

    def test_calls_auth_user_endpoint(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, {"id": "user-1"})
        SupabaseAuth(CFG, session=session).verify("TOKEN")
        self.assertEqual(session.get.call_args[0][0],
                         "https://proj.supabase.co/auth/v1/user")

    def test_401_raises_auth_error(self):
        session = mock.Mock()
        session.get.return_value = _resp(401)
        auth = SupabaseAuth(CFG, session=session)
        with self.assertRaises(AuthError) as ctx:
            auth.verify("BAD")
        self.assertEqual(ctx.exception.status, 401)

    def test_missing_id_raises(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, {"email": "a@b.c"})
        with self.assertRaises(AuthError):
            SupabaseAuth(CFG, session=session).verify("TOKEN")

    def test_network_error_raises_503_not_401(self):
        """Supabase 장애를 인증 실패로 보고하면 사용자가 자기 탓으로 오해한다."""
        session = mock.Mock()
        session.get.side_effect = RuntimeError("네트워크 오류")
        with self.assertRaises(AuthError) as ctx:
            SupabaseAuth(CFG, session=session).verify("TOKEN")
        self.assertEqual(ctx.exception.status, 503)

    def test_empty_token_raises_without_network(self):
        session = mock.Mock()
        with self.assertRaises(AuthError):
            SupabaseAuth(CFG, session=session).verify("")
        session.get.assert_not_called()


class TestCache(unittest.TestCase):
    def _clock(self, start=0.0):
        state = {"t": start}
        return state, (lambda: state["t"])

    def test_second_call_uses_cache(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, {"id": "user-1"})
        state, now = self._clock()
        auth = SupabaseAuth(CFG, session=session, ttl_seconds=60.0, now=now)
        auth.verify("TOKEN")
        auth.verify("TOKEN")
        self.assertEqual(session.get.call_count, 1)

    def test_cache_expires(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, {"id": "user-1"})
        state, now = self._clock()
        auth = SupabaseAuth(CFG, session=session, ttl_seconds=60.0, now=now)
        auth.verify("TOKEN")
        state["t"] = 61.0
        auth.verify("TOKEN")
        self.assertEqual(session.get.call_count, 2)

    def test_different_tokens_are_not_shared(self):
        session = mock.Mock()
        session.get.side_effect = [_resp(200, {"id": "u1"}), _resp(200, {"id": "u2"})]
        auth = SupabaseAuth(CFG, session=session)
        self.assertEqual(auth.verify("T1"), "u1")
        self.assertEqual(auth.verify("T2"), "u2")

    def test_failures_are_not_cached(self):
        """실패를 캐시하면 계정이 복구돼도 TTL 동안 막힌다."""
        session = mock.Mock()
        session.get.side_effect = [_resp(401), _resp(200, {"id": "u1"})]
        auth = SupabaseAuth(CFG, session=session)
        with self.assertRaises(AuthError):
            auth.verify("TOKEN")
        self.assertEqual(auth.verify("TOKEN"), "u1")

    def test_cache_key_is_not_the_raw_token(self):
        """캐시 키가 토큰 원문이면 메모리 덤프에 자격증명이 남는다."""
        session = mock.Mock()
        session.get.return_value = _resp(200, {"id": "u1"})
        auth = SupabaseAuth(CFG, session=session)
        auth.verify("SECRET_TOKEN")
        self.assertNotIn("SECRET_TOKEN", repr(auth._cache))


if __name__ == "__main__":
    unittest.main()
