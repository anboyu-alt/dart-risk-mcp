"""SE 캐시 백엔드 기본 동작."""
import unittest

from se_server.cache.base import MemoryCache


class TestMemoryCacheBlob(unittest.TestCase):
    def test_miss_returns_none(self):
        cache = MemoryCache()
        self.assertIsNone(cache.get_blob("없는키"))

    def test_put_then_get(self):
        cache = MemoryCache()
        cache.put_blob("20240301000001", b"ZIP-BYTES")
        self.assertEqual(cache.get_blob("20240301000001"), b"ZIP-BYTES")

    def test_blob_never_expires(self):
        """원문 ZIP은 rcept_no가 불변이므로 시간이 흘러도 유효하다."""
        clock = {"t": 100.0}
        cache = MemoryCache(now=lambda: clock["t"])
        cache.put_blob("k", b"data")
        clock["t"] = 100.0 + 86400 * 3650
        self.assertEqual(cache.get_blob("k"), b"data")


class TestMemoryCacheJson(unittest.TestCase):
    def test_miss_returns_none(self):
        self.assertIsNone(MemoryCache().get_json("없는키"))

    def test_roundtrip_without_ttl(self):
        cache = MemoryCache()
        cache.put_json("k", {"status": "000"}, ttl_seconds=None)
        self.assertEqual(cache.get_json("k"), {"status": "000"})

    def test_expires_after_ttl(self):
        clock = {"t": 100.0}
        cache = MemoryCache(now=lambda: clock["t"])
        cache.put_json("k", {"status": "000"}, ttl_seconds=10)
        clock["t"] = 111.0
        self.assertIsNone(cache.get_json("k"))

    def test_valid_just_before_ttl(self):
        clock = {"t": 100.0}
        cache = MemoryCache(now=lambda: clock["t"])
        cache.put_json("k", {"status": "000"}, ttl_seconds=10)
        clock["t"] = 109.0
        self.assertEqual(cache.get_json("k"), {"status": "000"})

    def test_blob_and_json_namespaces_are_separate(self):
        """같은 키라도 blob과 json은 서로 덮어쓰지 않는다."""
        cache = MemoryCache()
        cache.put_blob("k", b"blob")
        cache.put_json("k", {"a": 1}, ttl_seconds=None)
        self.assertEqual(cache.get_blob("k"), b"blob")
        self.assertEqual(cache.get_json("k"), {"a": 1})


if __name__ == "__main__":
    unittest.main()
