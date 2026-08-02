"""mcp 의존성 상한 가드 — 설치 확장 전면 장애 실사고 회귀 테스트.

실사고(2026-08-06): pyproject의 `mcp>=1.0.0`에 상한이 없어, mcp 2.0.0
릴리스 후 uv가 확장 venv에 2.0.0을 설치했다. mcp 2.0은
`mcp.server.fastmcp`를 제거해 server.py의 import가 즉사 —
"ModuleNotFoundError: No module named 'mcp.server.fastmcp'"로 확장이
Server disconnected 상태가 됐다(로컬 개발 환경은 mcp 1.x가 이미 깔려
있어 테스트가 전부 통과하는 바람에 릴리스 시점에 드러나지 않았다).

FastMCP API로 마이그레이션하기 전까지는 상한을 유지해야 한다.
"""
import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _dependency_lines(pyproject: Path) -> list[str]:
    text = pyproject.read_text(encoding="utf-8")
    block = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL)
    return [ln.strip().strip('",') for ln in block.group(1).splitlines() if ln.strip()] if block else []


class TestMcpDependencyPin(unittest.TestCase):
    def test_mcp_has_upper_bound(self):
        deps = _dependency_lines(_ROOT / "pyproject.toml")
        mcp_dep = next((d for d in deps if d.startswith("mcp")), "")
        self.assertTrue(mcp_dep, "pyproject dependencies에 mcp가 없다")
        self.assertIn("<2", mcp_dep,
                      "mcp 2.x는 mcp.server.fastmcp를 제거해 server.py import가 죽는다 — "
                      "상한을 지우려면 FastMCP 마이그레이션이 선행돼야 한다")

    def test_server_imports_fastmcp_from_v1_path(self):
        """상한의 근거가 되는 import 경로가 실제로 그대로인지 확인."""
        src = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
        self.assertIn("from mcp.server.fastmcp import FastMCP", src)

    def test_extension_pin_matches_package_version(self):
        """확장 의존성 핀이 패키지 버전과 어긋나면 설치본이 구세대로 굳는다."""
        pkg_version = re.search(
            r'^version\s*=\s*"([^"]+)"',
            (_ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE).group(1)
        ext_text = (_ROOT / "extension" / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'"dart-risk-mcp=={pkg_version}"', ext_text)
        manifest = (_ROOT / "extension" / "manifest.json").read_text(encoding="utf-8")
        self.assertIn(f'"version": "{pkg_version}"', manifest)


if __name__ == "__main__":
    unittest.main()
