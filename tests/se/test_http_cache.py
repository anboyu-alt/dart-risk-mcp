"""CachingHttp의 키 계산과 blob/json 정책 분기."""
import unittest

from se_server.cache.base import MemoryCache
from se_server.http_cache import CachingHttp

DOC_URL = "https://opendart.fss.or.kr/api/document.xml"
LIST_URL = "https://opendart.fss.or.kr/api/list.json"


class TestCacheKey(unittest.TestCase):
    def test_api_key_excluded(self):
        """crtfc_key는 사용자 식별자이므로 키에서 제외한다 — 전 사용자가 캐시를 공유한다."""
        http = CachingHttp(MemoryCache())
        a = http.cache_key(LIST_URL, {"crtfc_key": "AAA", "corp_code": "001"})
        b = http.cache_key(LIST_URL, {"crtfc_key": "BBB", "corp_code": "001"})
        self.assertEqual(a, b)

    def test_api_key_value_not_in_key(self):
        http = CachingHttp(MemoryCache())
        key = http.cache_key(LIST_URL, {"crtfc_key": "SECRET123", "corp_code": "001"})
        self.assertNotIn("SECRET123", key)

    def test_param_order_does_not_matter(self):
        http = CachingHttp(MemoryCache())
        a = http.cache_key(LIST_URL, {"corp_code": "001", "bgn_de": "20240101"})
        b = http.cache_key(LIST_URL, {"bgn_de": "20240101", "corp_code": "001"})
        self.assertEqual(a, b)

    def test_different_params_differ(self):
        http = CachingHttp(MemoryCache())
        a = http.cache_key(LIST_URL, {"corp_code": "001"})
        b = http.cache_key(LIST_URL, {"corp_code": "002"})
        self.assertNotEqual(a, b)

    def test_different_endpoint_differs(self):
        http = CachingHttp(MemoryCache())
        a = http.cache_key(LIST_URL, {"corp_code": "001"})
        b = http.cache_key(DOC_URL, {"corp_code": "001"})
        self.assertNotEqual(a, b)


class TestPolicyRouting(unittest.TestCase):
    def test_document_xml_stored_as_blob(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        http.put(DOC_URL, {"rcept_no": "2024030100001"}, 200,
                 {"Content-Type": "application/zip"}, b"PK\x03\x04ZIP")
        key = http.cache_key(DOC_URL, {"rcept_no": "2024030100001"})
        self.assertEqual(backend.get_blob(key), b"PK\x03\x04ZIP")
        self.assertIsNone(backend.get_json(key))

    def test_json_endpoint_stored_as_json_with_ttl(self):
        backend = MemoryCache()
        http = CachingHttp(backend, json_ttl_seconds=100)
        http.put(LIST_URL, {"corp_code": "001"}, 200,
                 {"Content-Type": "application/json"}, b'{"status":"000"}')
        key = http.cache_key(LIST_URL, {"corp_code": "001"})
        stored = backend.get_json(key)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["body_b64"], "eyJzdGF0dXMiOiIwMDAifQ==")

    def test_blob_roundtrip_through_get(self):
        http = CachingHttp(MemoryCache())
        params = {"rcept_no": "2024030100001"}
        http.put(DOC_URL, params, 200, {"Content-Type": "application/zip"}, b"PK\x03\x04ZIP")
        hit = http.get(DOC_URL, params)
        self.assertIsNotNone(hit)
        status, headers, body = hit
        self.assertEqual(status, 200)
        self.assertEqual(body, b"PK\x03\x04ZIP")
        self.assertEqual(headers.get("Content-Type"), "application/zip")

    def test_json_roundtrip_through_get(self):
        http = CachingHttp(MemoryCache())
        params = {"corp_code": "001"}
        http.put(LIST_URL, params, 200, {"Content-Type": "application/json"}, b'{"status":"000"}')
        hit = http.get(LIST_URL, params)
        self.assertIsNotNone(hit)
        status, headers, body = hit
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"status":"000"}')

    def test_miss_returns_none(self):
        http = CachingHttp(MemoryCache())
        self.assertIsNone(http.get(LIST_URL, {"corp_code": "999"}))

    def test_json_expiry_is_a_miss(self):
        clock = {"t": 0.0}
        backend = MemoryCache(now=lambda: clock["t"])
        http = CachingHttp(backend, json_ttl_seconds=10)
        params = {"corp_code": "001"}
        http.put(LIST_URL, params, 200, {"Content-Type": "application/json"}, b'{"status":"000"}')
        clock["t"] = 20.0
        self.assertIsNone(http.get(LIST_URL, params))


class TestNeverCache(unittest.TestCase):
    """corpCode.xml은 신규 상장으로 계속 바뀌므로 캐시 대상이 아니다.

    core의 _load_corp_codes가 24시간 파일 캐시를 이미 두고 있어, 여기서 다시
    캐시하면 그 갱신 주기가 무력화되고 기업 목록이 고정된다.
    """

    CORP_URL = "https://opendart.fss.or.kr/api/corpCode.xml"

    def test_put_stores_nothing(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        http.put(self.CORP_URL, {}, 200, {"Content-Type": "application/zip"}, b"PK\x03\x04")
        key = http.cache_key(self.CORP_URL, {})
        self.assertIsNone(backend.get_blob(key))
        self.assertIsNone(backend.get_json(key))

    def test_get_always_misses(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        # 백엔드에 직접 심어두더라도 조회 경로에서 걸러져야 한다.
        backend.put_blob(http.cache_key(self.CORP_URL, {}), b"STALE")
        self.assertIsNone(http.get(self.CORP_URL, {}))


class TestInstall(unittest.TestCase):
    def tearDown(self):
        from dart_risk_mcp.core import dart_client
        dart_client.set_http_cache(None)

    def test_install_injects_into_core(self):
        from dart_risk_mcp.core import dart_client
        from se_server.http_cache import install

        http = install(MemoryCache())
        self.assertIs(dart_client.get_http_cache(), http)


if __name__ == "__main__":
    unittest.main()
