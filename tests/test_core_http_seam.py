"""core _retry의 선택적 HTTP 캐시 시임 계약.

이 시임은 se_server가 캐시를 주입하는 유일한 지점이다. 기본값은 None이며
MCP 서버는 이를 설정하지 않으므로 기존 동작이 그대로 유지되어야 한다.
"""
import unittest
from unittest import mock

from dart_risk_mcp.core import dart_client


class FakeCache:
    def __init__(self, preload=None):
        self.preload = preload
        self.puts = []
        self.gets = []

    def get(self, url, params):
        self.gets.append((url, params))
        return self.preload

    def put(self, url, params, status, headers, body):
        self.puts.append((url, params, status, headers, body))


def _fake_response(status=200, body=b"{}", headers=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.content = body
    resp.headers = headers or {"Content-Type": "application/json"}
    return resp


class TestHttpSeamDefault(unittest.TestCase):
    def tearDown(self):
        dart_client.set_http_cache(None)

    def test_default_cache_is_none(self):
        self.assertIsNone(dart_client.get_http_cache())

    def test_without_cache_calls_network(self):
        with mock.patch.object(
            dart_client.requests, "request", return_value=_fake_response()
        ) as req:
            dart_client._retry("GET", "https://example.test/api/list.json",
                               params={"crtfc_key": "K"})
        self.assertEqual(req.call_count, 1)


class TestHttpSeamWithCache(unittest.TestCase):
    def tearDown(self):
        dart_client.set_http_cache(None)

    def test_hit_skips_network(self):
        cache = FakeCache(preload=(200, {"Content-Type": "application/json"}, b'{"status":"000"}'))
        dart_client.set_http_cache(cache)
        with mock.patch.object(dart_client.requests, "request") as req:
            resp = dart_client._retry("GET", "https://example.test/api/list.json",
                                      params={"corp_code": "001"})
        req.assert_not_called()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b'{"status":"000"}')
        self.assertEqual(resp.json(), {"status": "000"})

    def test_miss_calls_network_then_stores(self):
        cache = FakeCache(preload=None)
        dart_client.set_http_cache(cache)
        with mock.patch.object(
            dart_client.requests, "request",
            return_value=_fake_response(body=b'{"status":"000"}')
        ):
            dart_client._retry("GET", "https://example.test/api/list.json",
                               params={"corp_code": "001"})
        self.assertEqual(len(cache.puts), 1)
        url, params, status, headers, body = cache.puts[0]
        self.assertEqual(url, "https://example.test/api/list.json")
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"status":"000"}')

    def test_non_200_is_not_stored(self):
        cache = FakeCache(preload=None)
        dart_client.set_http_cache(cache)
        with mock.patch.object(
            dart_client.requests, "request", return_value=_fake_response(status=404)
        ):
            dart_client._retry("GET", "https://example.test/api/list.json", params={})
        self.assertEqual(cache.puts, [])

    def test_non_get_is_not_cached(self):
        cache = FakeCache(preload=None)
        dart_client.set_http_cache(cache)
        with mock.patch.object(
            dart_client.requests, "request", return_value=_fake_response()
        ):
            dart_client._retry("POST", "https://example.test/api/list.json", params={})
        self.assertEqual(cache.gets, [])
        self.assertEqual(cache.puts, [])


if __name__ == "__main__":
    unittest.main()
