"""패키징 경계 회귀 테스트.

핵심 계약: pypdf는 scripts 전용 optional이며 런타임 패키지 의존성을 늘리지 않는다.
"""
import tomllib
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


class TestPackaging(unittest.TestCase):
    def setUp(self):
        self.cfg = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_runtime_dependencies_unchanged(self):
        deps = self.cfg["project"]["dependencies"]
        self.assertEqual(len(deps), 2, f"런타임 의존성이 늘었다: {deps}")
        self.assertTrue(any(d.startswith("mcp") for d in deps))
        self.assertTrue(any(d.startswith("requests") for d in deps))

    def test_pypdf_is_optional_only(self):
        optional = self.cfg["project"].get("optional-dependencies", {})
        self.assertIn("catalog", optional)
        self.assertTrue(any("pypdf" in d for d in optional["catalog"]))
        self.assertFalse(any("pypdf" in d for d in self.cfg["project"]["dependencies"]))

    def test_runtime_package_does_not_import_pypdf(self):
        hits = [p for p in (_ROOT / "dart_risk_mcp").rglob("*.py")
                if "pypdf" in p.read_text(encoding="utf-8")]
        self.assertEqual(hits, [], f"런타임 패키지가 pypdf를 참조한다: {hits}")


class TestWorkflow(unittest.TestCase):
    def test_workflow_exists_with_dispatch_and_cron(self):
        wf = (_ROOT / ".github" / "workflows" / "refresh-catalog.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", wf)
        self.assertIn("cron", wf)
        self.assertIn("ANTHROPIC_API_KEY", wf)

    def test_workflow_does_not_require_collection_api_keys(self):
        # 수집은 게시판 웹 파싱으로 전환됐다(2026-08-17). FSS 오픈API는 일일 30회
        # 한도가 실증돼 폐기했고, 정책브리핑은 이 파이프라인 범위 밖이다.
        # 워크플로우가 이 키들을 요구하면 없는 Secret을 기다리다 실패한다.
        wf = (_ROOT / ".github" / "workflows" / "refresh-catalog.yml").read_text(encoding="utf-8")
        self.assertNotIn("FSS_API_KEY", wf)
        self.assertNotIn("DATA_GO_KR_API_KEY", wf)

    def test_workflow_installs_catalog_extra(self):
        wf = (_ROOT / ".github" / "workflows" / "refresh-catalog.yml").read_text(encoding="utf-8")
        self.assertIn("[catalog]", wf)


if __name__ == "__main__":
    unittest.main()
