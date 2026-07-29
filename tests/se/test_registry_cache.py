"""se_server/registry_cache.py — core 레지스트리 캐시 시임 배선(SE-5c Task 2).

se_server/http_cache.py의 TestInstall과 같은 패턴 — 백엔드가 core 전역
시임(dart_risk_mcp.core.known_actors.set_registry_cache)에 실제로 꽂히는지,
적중 시 /api/se/actors 핸들러가 Notion을 부르지 않는지를 검증한다.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dart_risk_mcp.core import known_actors as ka
from se_server import registry_cache
from se_server.api.auth import AuthError
from se_server.api.handlers import Deps, handle
from se_server.api.types import Request
from se_server.cache.base import MemoryCache
from se_server.jobs.store import MemoryJobStore


class TestInstall(unittest.TestCase):
    def tearDown(self):
        ka.set_registry_cache(None)

    def test_install_injects_into_core(self):
        backend = MemoryCache()
        registry_cache.install(backend)
        self.assertIs(ka.get_registry_cache(), backend)

    def test_default_ttl_matches_known_actors_cache_ttl(self):
        """두 캐시(주입·기존 파일)가 다른 주기로 만료되면 어느 쪽이 최신인지
        추론할 수 없다 — TTL을 반드시 맞춘다."""
        import inspect
        default = inspect.signature(registry_cache.install).parameters["ttl_seconds"].default
        self.assertEqual(default, ka._CACHE_TTL)


class _Auth:
    def verify(self, bearer):
        if not bearer:
            raise AuthError(401, "인증 토큰이 없습니다")
        return "user-1"


def _req(path, token="T"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return Request("GET", path, headers, {})


def _deps():
    return Deps(store=MemoryJobStore(), auth=_Auth())


class TestCacheHitAvoidsNotionCall(unittest.TestCase):
    """캐시 적중 시 /api/se/actors 핸들러가 Notion을 한 번도 부르지 않는다."""

    def tearDown(self):
        ka.set_registry_cache(None)

    def test_cache_hit_skips_notion(self):
        preload = {"version": 1, "actors": {
            "홍길동": [{"source": "s", "evidence": "e", "status": "verified",
                       "companies": ["테스트회사"]}]}}
        backend = MemoryCache()
        backend.put_json(ka._REGISTRY_CACHE_KEY, preload, ttl_seconds=ka._CACHE_TTL)

        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "notion.json"  # 미존재 → 신선 파일캐시 없음
            with mock.patch.object(ka, "_CACHE_FILE", cache_file), \
                 mock.patch.object(ka.requests, "post") as post, \
                 mock.patch.dict(os.environ, {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}):
                os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                registry_cache.install(backend)
                resp = handle(_req("/api/se/actors?company=테스트회사"), _deps())
        post.assert_not_called()
        self.assertEqual(resp.status, 200)
        self.assertEqual(len(resp.body["actors"]), 1)
        self.assertEqual(resp.body["actors"][0]["name"], "홍길동")


if __name__ == "__main__":
    unittest.main()
