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

    def test_delimiters_in_values_do_not_collide(self):
        """값에 `&`나 `=`가 섞여도 다른 파라미터 조합은 다른 키를 낳는다.

        단순 문자열 결합이면 아래 둘이 모두 "...?a=b&c=d"로 축약돼 충돌한다.
        """
        http = CachingHttp(MemoryCache())
        a = http.cache_key(LIST_URL, {"a": "b&c=d"})
        b = http.cache_key(LIST_URL, {"a": "b", "c": "d"})
        self.assertNotEqual(a, b)


class TestBlobPoisoningGuard(unittest.TestCase):
    """DART는 오류 시에도 HTTP 200 + JSON/텍스트 바디로 응답할 수 있다.

    blob은 TTL 없이 영구 보관되고 캐시 키가 crtfc_key를 제외해 전 사용자가
    공유하므로, 오류 바디가 한 번 저장되면 해당 rcept_no가 모두에게 영구히
    조회 불가가 된다. 실제 ZIP만 저장해야 한다.
    """

    def test_json_error_body_is_not_stored_as_blob(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"rcept_no": "2024030100001"}
        http.put(DOC_URL, params, 200,
                 {"Content-Type": "application/json"},
                 b'{"status":"013","message":"\xec\xa1\xb0\xed\x9a\x8c\xeb\x90\x9c \xeb\x8d\xb0\xec\x9d\xb4\xed\x84\xb0 \xec\x97\x86\xec\x9d\x8c"}')
        self.assertIsNone(backend.get_blob(http.cache_key(DOC_URL, params)))
        self.assertIsNone(http.get(DOC_URL, params))

    def test_text_error_body_is_not_stored_as_blob(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"rcept_no": "2024030100002"}
        http.put(DOC_URL, params, 200, {"Content-Type": "text/html"}, b"<html>error</html>")
        self.assertIsNone(backend.get_blob(http.cache_key(DOC_URL, params)))

    def test_real_zip_is_still_stored(self):
        """가드가 정상 ZIP까지 막아서는 안 된다."""
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"rcept_no": "2024030100003"}
        http.put(DOC_URL, params, 200, {"Content-Type": "application/zip"}, b"PK\x03\x04REAL")
        self.assertEqual(backend.get_blob(http.cache_key(DOC_URL, params)), b"PK\x03\x04REAL")

    def test_xbrl_endpoint_gets_same_guard(self):
        xbrl_url = "https://opendart.fss.or.kr/api/fnlttXbrl.xml"
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"rcept_no": "2024030100004"}
        http.put(xbrl_url, params, 200, {"Content-Type": "application/json"}, b'{"status":"013"}')
        self.assertIsNone(backend.get_blob(http.cache_key(xbrl_url, params)))


class TestJsonErrorBodyGuard(unittest.TestCase):
    """DART는 JSON 엔드포인트도 쿼터 초과(020)·점검(800)·키 오류(900) 등을

    HTTP 200 + 바디의 status 필드로만 알린다. 캐시 키가 crtfc_key를
    제외해 전 사용자가 공유하므로, 한 사용자의 오류 응답이 저장되면
    다른 모든 사용자가 TTL(7일) 동안 그 오류를 받는다. status가 "000"
    (정상) 또는 "013"(데이터 없음 — 일시적 장애가 아닌 안정적인 정상
    답변)인 응답만 저장해야 한다.
    """

    def test_status_020_quota_exceeded_is_not_stored(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"corp_code": "001"}
        http.put(LIST_URL, params, 200, {"Content-Type": "application/json"},
                 b'{"status":"020","message":"\xec\x9a\x94\xec\xb2\xad \xed\x95\x9c\xeb\x8f\x84 \xec\xb4\x88\xea\xb3\xbc"}')
        self.assertIsNone(backend.get_json(http.cache_key(LIST_URL, params)))
        self.assertIsNone(http.get(LIST_URL, params))

    def test_status_800_system_check_is_not_stored(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"corp_code": "002"}
        http.put(LIST_URL, params, 200, {"Content-Type": "application/json"},
                 b'{"status":"800","message":"check"}')
        self.assertIsNone(backend.get_json(http.cache_key(LIST_URL, params)))

    def test_status_013_no_data_is_stored(self):
        """013(데이터 없음)은 일시적 장애가 아니라 안정적인 정상 답변이므로

        000과 동일하게 캐시 대상이다. 이를 배제하면 fetch_insider_timeline·
        fetch_fund_usage 같은 고팬아웃 루프가 013 지배적인 응답을 매 요청마다
        DART에 다시 물어보게 되어, 이 가드가 막으려던 쿼터 소진(020)을 스스로
        유발한다.
        """
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"corp_code": "003"}
        http.put(LIST_URL, params, 200, {"Content-Type": "application/json"},
                 b'{"status":"013","message":"no data"}')
        self.assertIsNotNone(backend.get_json(http.cache_key(LIST_URL, params)))

    def test_status_013_roundtrips_through_get(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"corp_code": "003b"}
        body = b'{"status":"013","message":"no data"}'
        http.put(LIST_URL, params, 200, {"Content-Type": "application/json"}, body)
        hit = http.get(LIST_URL, params)
        self.assertIsNotNone(hit)
        status, headers, stored_body = hit
        self.assertEqual(status, 200)
        self.assertEqual(stored_body, body)

    def test_status_000_success_is_stored(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"corp_code": "004"}
        http.put(LIST_URL, params, 200, {"Content-Type": "application/json"},
                 b'{"status":"000","message":"ok"}')
        self.assertIsNotNone(backend.get_json(http.cache_key(LIST_URL, params)))
        self.assertIsNotNone(http.get(LIST_URL, params))

    def test_unparseable_body_is_not_stored(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"corp_code": "005"}
        http.put(LIST_URL, params, 200, {"Content-Type": "application/json"}, b"not json at all")
        self.assertIsNone(backend.get_json(http.cache_key(LIST_URL, params)))

    def test_body_without_status_field_is_not_stored(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"corp_code": "006"}
        http.put(LIST_URL, params, 200, {"Content-Type": "application/json"}, b'{"list":[]}')
        self.assertIsNone(backend.get_json(http.cache_key(LIST_URL, params)))


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
