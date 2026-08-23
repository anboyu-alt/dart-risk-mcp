"""core _retry의 선택적 HTTP 캐시 시임 계약.

이 시임은 외부 소비자가 캐시를 주입하는 유일한 지점이다(SE 폐기 후
주입하는 곳은 없지만 계약은 유지한다). 기본값은 None이며
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


class TestRetrySemanticsUnchanged(unittest.TestCase):
    """캐시 훅을 달면서 기존 재시도·예외 동작이 바뀌지 않았는지 고정한다.

    _retry는 거의 모든 core 함수가 쓰므로 이 계약이 깨지면 광범위한 회귀가 난다.
    """

    def tearDown(self):
        dart_client.set_http_cache(None)

    def test_4xx_is_returned_not_raised(self):
        """404 등 비재시도 4xx는 예외 없이 그대로 반환된다.

        _fetch_document_zip을 비롯한 호출자들이 `resp.status_code != 200`으로
        분기하므로, 여기서 raise하면 그 분기가 죽는다.
        """
        resp404 = _fake_response(status=404)
        with mock.patch.object(dart_client.requests, "request", return_value=resp404) as req:
            result = dart_client._retry("GET", "https://example.test/api/list.json", params={})
        self.assertEqual(result.status_code, 404)
        self.assertEqual(req.call_count, 1)  # 4xx는 재시도하지 않는다
        resp404.raise_for_status.assert_not_called()

    def test_4xx_not_retried_with_cache_enabled(self):
        """캐시가 켜져 있어도 4xx 동작은 같아야 한다."""
        dart_client.set_http_cache(FakeCache(preload=None))
        resp403 = _fake_response(status=403)
        with mock.patch.object(dart_client.requests, "request", return_value=resp403):
            result = dart_client._retry("GET", "https://example.test/api/list.json", params={})
        self.assertEqual(result.status_code, 403)
        resp403.raise_for_status.assert_not_called()

    def test_persistent_5xx_exhausts_retries_then_raises(self):
        """재시도를 모두 소진한 5xx는 기존대로 raise_for_status를 호출한다."""
        resp500 = _fake_response(status=500)
        resp500.raise_for_status.side_effect = RuntimeError("500")
        with mock.patch.object(dart_client.requests, "request", return_value=resp500) as req, \
                mock.patch.object(dart_client.time, "sleep"):
            with self.assertRaises(RuntimeError):
                dart_client._retry("GET", "https://example.test/api/list.json", params={})
        self.assertEqual(req.call_count, 3)

    def test_429_is_retried_then_succeeds(self):
        """429 후 200이 오면 재시도해서 성공 응답을 반환한다."""
        responses = [_fake_response(status=429), _fake_response(status=200, body=b'{"ok":1}')]
        with mock.patch.object(
            dart_client.requests, "request", side_effect=responses
        ) as req, mock.patch.object(dart_client.time, "sleep"):
            result = dart_client._retry("GET", "https://example.test/api/list.json", params={})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(req.call_count, 2)


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

    def test_missing_params_kwarg_falls_back_to_empty_dict(self):
        """params kwarg 자체를 생략해도(`or {}` 분기) 캐시 경로가 정상 동작한다."""
        cache = FakeCache(preload=None)
        dart_client.set_http_cache(cache)
        with mock.patch.object(
            dart_client.requests, "request",
            return_value=_fake_response(body=b'{"status":"000"}')
        ) as req:
            resp = dart_client._retry("GET", "https://example.test/api/list.json")
        req.assert_called_once()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(cache.gets, [("https://example.test/api/list.json", {})])
        self.assertEqual(len(cache.puts), 1)
        self.assertEqual(cache.puts[0][1], {})

    def test_cache_hit_restores_headers(self):
        """캐시 히트 시 저장돼 있던 headers가 합성 응답에 복원된다."""
        cache = FakeCache(preload=(200, {"X-Custom": "abc", "Content-Type": "text/xml"}, b"<xml/>"))
        dart_client.set_http_cache(cache)
        with mock.patch.object(dart_client.requests, "request") as req:
            resp = dart_client._retry("GET", "https://example.test/api/list.json", params={})
        req.assert_not_called()
        self.assertEqual(resp.headers.get("X-Custom"), "abc")
        self.assertEqual(resp.headers.get("Content-Type"), "text/xml")


class MutatingCache:
    """캐시 키 계산 중 전달받은 params를 실수로 변형하는 캐시 구현을 흉내낸다.

    Important 1 회귀 고정용: 이런 구현이 붙어도 requests.request에 넘어가는
    kwargs["params"]는 온전해야 한다(예: crtfc_key가 제거되면 안 된다).
    """

    def __init__(self):
        self.get_seen = []
        self.put_seen = []

    def get(self, url, params):
        self.get_seen.append(dict(params))
        params.pop("crtfc_key", None)  # 방어 복사가 없었다면 원본을 오염시킨다
        return None

    def put(self, url, params, status, headers, body):
        self.put_seen.append(dict(params))
        params.pop("crtfc_key", None)


class TestCacheParamsIsolation(unittest.TestCase):
    def tearDown(self):
        dart_client.set_http_cache(None)

    def test_cache_mutation_does_not_leak_into_request_params(self):
        cache = MutatingCache()
        dart_client.set_http_cache(cache)
        captured = {}

        def fake_request(method, url, **kwargs):
            captured["params"] = kwargs.get("params")
            return _fake_response(body=b'{"status":"000"}')

        with mock.patch.object(dart_client.requests, "request", side_effect=fake_request):
            dart_client._retry(
                "GET", "https://example.test/api/list.json",
                params={"crtfc_key": "SECRET", "corp_code": "001"},
            )

        # 캐시 구현이 get()에서 params를 변형했더라도, requests.request에
        # 실제로 전달된 params 객체는 crtfc_key를 그대로 유지해야 한다.
        self.assertEqual(captured["params"], {"crtfc_key": "SECRET", "corp_code": "001"})
        # 캐시가 관찰한 값도(변형 이전 시점 기준) crtfc_key를 포함해야 한다.
        self.assertEqual(cache.get_seen[0], {"crtfc_key": "SECRET", "corp_code": "001"})
        self.assertEqual(cache.put_seen[0], {"crtfc_key": "SECRET", "corp_code": "001"})


class RaisingGetCache:
    def get(self, url, params):
        raise RuntimeError("cache backend down")

    def put(self, url, params, status, headers, body):
        pass


class RaisingPutCache:
    def get(self, url, params):
        return None

    def put(self, url, params, status, headers, body):
        raise RuntimeError("cache backend down")


class BadShapeGetCache:
    """cache.get이 예외 대신 계약과 다른 형태(3-튜플이 아님)를 반환하는 구현.

    머지 전 지적 ③ 회귀 고정용: get()의 반환값이 튜플이 아니거나 언팩이
    실패해도 _retry는 예외를 전파하지 않고 네트워크 호출로 폴백해야 한다.
    """

    def get(self, url, params):
        return (200, {"Content-Type": "application/json"})  # 3-튜플이 아니라 2-튜플

    def put(self, url, params, status, headers, body):
        pass


class TestCacheFailuresDoNotBreakRequests(unittest.TestCase):
    def tearDown(self):
        dart_client.set_http_cache(None)

    def test_get_exception_falls_back_to_network(self):
        """cache.get이 예외를 던져도 네트워크 호출로 폴백해 정상 응답을 반환한다."""
        dart_client.set_http_cache(RaisingGetCache())
        with mock.patch.object(
            dart_client.requests, "request",
            return_value=_fake_response(body=b'{"status":"000"}')
        ) as req:
            resp = dart_client._retry("GET", "https://example.test/api/list.json", params={})
        req.assert_called_once()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b'{"status":"000"}')

    def test_put_exception_still_returns_response(self):
        """cache.put이 예외를 던져도 응답은 정상적으로 반환된다."""
        dart_client.set_http_cache(RaisingPutCache())
        with mock.patch.object(
            dart_client.requests, "request",
            return_value=_fake_response(body=b'{"status":"000"}')
        ):
            resp = dart_client._retry("GET", "https://example.test/api/list.json", params={})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b'{"status":"000"}')

    def test_get_returns_wrong_shape_falls_back_to_network(self):
        """머지 전 지적 ③: cache.get이 3-튜플이 아닌 값을 반환해도

        (예: 2-튜플) ValueError가 호출자에게 전파되지 않고 캐시 미스로
        처리되어 네트워크 호출로 폴백해 정상 응답을 반환해야 한다.
        """
        dart_client.set_http_cache(BadShapeGetCache())
        with mock.patch.object(
            dart_client.requests, "request",
            return_value=_fake_response(body=b'{"status":"000"}')
        ) as req:
            resp = dart_client._retry("GET", "https://example.test/api/list.json", params={})
        req.assert_called_once()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b'{"status":"000"}')


class TestCacheFailureLogging(unittest.TestCase):
    """머지 전 지적 ④: 캐시 실패는 warning 레벨로 로그를 남기되,

    params(사용자 DART API 키 crtfc_key를 담고 있음)는 절대 로그에
    포함하지 않는다.
    """

    def tearDown(self):
        dart_client.set_http_cache(None)

    def test_get_failure_logs_warning_without_api_key(self):
        dart_client.set_http_cache(RaisingGetCache())
        with self.assertLogs(dart_client.log.name, level="WARNING") as cm:
            with mock.patch.object(
                dart_client.requests, "request",
                return_value=_fake_response(body=b'{"status":"000"}')
            ):
                dart_client._retry(
                    "GET", "https://example.test/api/list.json",
                    params={"crtfc_key": "SECRET_API_KEY_VALUE_GET"},
                )
        combined = "\n".join(cm.output)
        self.assertNotIn("SECRET_API_KEY_VALUE_GET", combined)
        self.assertTrue(any("캐시" in line for line in cm.output))

    def test_put_failure_logs_warning_without_api_key(self):
        dart_client.set_http_cache(RaisingPutCache())
        with self.assertLogs(dart_client.log.name, level="WARNING") as cm:
            with mock.patch.object(
                dart_client.requests, "request",
                return_value=_fake_response(body=b'{"status":"000"}')
            ):
                dart_client._retry(
                    "GET", "https://example.test/api/list.json",
                    params={"crtfc_key": "SECRET_API_KEY_VALUE_PUT"},
                )
        combined = "\n".join(cm.output)
        self.assertNotIn("SECRET_API_KEY_VALUE_PUT", combined)
        self.assertTrue(any("캐시" in line for line in cm.output))

    def test_bad_shape_get_logs_warning_without_api_key(self):
        dart_client.set_http_cache(BadShapeGetCache())
        with self.assertLogs(dart_client.log.name, level="WARNING") as cm:
            with mock.patch.object(
                dart_client.requests, "request",
                return_value=_fake_response(body=b'{"status":"000"}')
            ):
                dart_client._retry(
                    "GET", "https://example.test/api/list.json",
                    params={"crtfc_key": "SECRET_API_KEY_VALUE_SHAPE"},
                )
        combined = "\n".join(cm.output)
        self.assertNotIn("SECRET_API_KEY_VALUE_SHAPE", combined)


if __name__ == "__main__":
    unittest.main()
