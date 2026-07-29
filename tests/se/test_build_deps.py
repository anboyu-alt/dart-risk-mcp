"""build_deps()의 레지스트리 캐시 배선 — SE-5c Task 2 요구사항 5.

SE는 job store·인증에 Supabase를 이미 필수로 요구한다(SEConfig.from_env가
미설정 시 ValueError). 그 전제(유효한 SEConfig) 위에서, 레지스트리 캐시
설치 자체가 어떤 이유로든 실패해도 build_deps() 전체가 죽으면 안 된다 —
레지스트리는 opt-in 기능이고 이 캐시는 순수 성능 최적화라, 여기서 죽으면
작업 생성·조회 등 캐시와 무관한 기능까지 함께 막힌다.
"""
import unittest
from unittest import mock

_ENV = {"SUPABASE_URL": "https://proj.supabase.co", "SUPABASE_SERVICE_KEY": "K"}


class TestBuildDepsRegistryCacheWiring(unittest.TestCase):
    def setUp(self):
        from dart_risk_mcp.core import known_actors as ka
        ka.set_registry_cache(None)

    def tearDown(self):
        from dart_risk_mcp.core import known_actors as ka
        ka.set_registry_cache(None)

    def test_registry_cache_installed_alongside_http_cache(self):
        from dart_risk_mcp.core import known_actors as ka
        from se_server.api import handlers

        with mock.patch.dict("os.environ", _ENV, clear=False):
            deps = handlers.build_deps()

        self.assertIsNotNone(deps)
        self.assertIsNotNone(ka.get_registry_cache())

    def test_build_deps_survives_registry_cache_install_failure(self):
        """Supabase(레지스트리 캐시 특정 단계)가 실패해도 SE 전체가 죽지
        않는다."""
        from dart_risk_mcp.core import known_actors as ka
        from se_server.api import handlers

        with mock.patch.dict("os.environ", _ENV, clear=False), \
             mock.patch("se_server.registry_cache.install",
                         side_effect=RuntimeError("supabase down")):
            deps = handlers.build_deps()

        self.assertIsNotNone(deps)
        self.assertIsNotNone(deps.store)
        self.assertIsNotNone(deps.auth)
        # 설치가 실패했으니 시임에는 아무것도 꽂히지 않는다(부분 상태 없음).
        self.assertIsNone(ka.get_registry_cache())


if __name__ == "__main__":
    unittest.main()
