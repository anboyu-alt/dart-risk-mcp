"""Vercel 번들 포함 여부 — .vercelignore가 필요한 것을 빼지 않는지 검사한다.

실제 배포에서 겪은 실패다: `.vercelignore`가 `/*`로 루트를 통째로 제외하고
`api`·`docs`·`vercel.json`만 허용했다. 그래서 `api/index.py`가 import하는
`se_server`·`dart_risk_mcp`가 함수 번들에 들어가지 않아 프로덕션이
`ModuleNotFoundError: No module named 'se_server'`로 죽었다.

로컬에서는 전부 존재하므로 어떤 런타임 테스트로도 잡히지 않는다. 배포
설정과 코드의 import를 **정적으로 대조**해야만 잡힌다.
"""
import ast
import pathlib
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_ADAPTER = _ROOT / "api" / "index.py"
_IGNORE = _ROOT / ".vercelignore"


def _allowlist() -> set[str]:
    """.vercelignore의 부정 패턴(`!이름`)에서 허용 항목을 모은다."""
    allowed = set()
    for raw in _IGNORE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("!"):
            allowed.add(line[1:].strip().strip("/").split("/")[0])
    return allowed


def _top_level_imports(path: pathlib.Path) -> set[str]:
    """파일이 import하는 최상위 모듈 이름을 모은다."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _local_packages() -> set[str]:
    """저장소 루트의 파이썬 패키지 디렉토리 이름."""
    return {
        p.name for p in _ROOT.iterdir()
        if p.is_dir() and (p / "__init__.py").exists()
    }


class TestVercelIgnoreCoversAdapterImports(unittest.TestCase):
    def test_adapter_local_imports_are_bundled(self):
        """어댑터가 import하는 로컬 패키지가 전부 허용목록에 있어야 한다."""
        allowed = _allowlist()
        needed = _top_level_imports(_ADAPTER) & _local_packages()
        missing = sorted(needed - allowed)
        self.assertEqual(
            missing, [],
            "api/index.py가 import하는데 .vercelignore가 제외하는 패키지가 "
            "있습니다. 배포하면 ModuleNotFoundError로 함수가 죽습니다:\n  "
            + "\n  ".join(missing),
        )

    def test_transitive_local_packages_are_bundled(self):
        """어댑터가 끌어오는 패키지가 다시 import하는 로컬 패키지까지 확인한다.

        se_server가 dart_risk_mcp를 import하므로, 어댑터의 직접 import만
        보면 dart_risk_mcp 누락을 놓친다.
        """
        allowed = _allowlist()
        local = _local_packages()
        seen, frontier = set(), _top_level_imports(_ADAPTER) & local
        while frontier:
            pkg = frontier.pop()
            if pkg in seen:
                continue
            seen.add(pkg)
            for py in (_ROOT / pkg).rglob("*.py"):
                frontier |= (_top_level_imports(py) & local) - seen
        missing = sorted(seen - allowed)
        self.assertEqual(
            missing, [],
            "함수 번들에 필요한 로컬 패키지가 .vercelignore에서 빠졌습니다:\n  "
            + "\n  ".join(missing),
        )

    def test_requirements_is_bundled(self):
        """requirements.txt가 없으면 requests가 설치되지 않아 import가 깨진다."""
        self.assertIn("requirements.txt", _allowlist())

    def test_pyproject_stays_excluded(self):
        """pyproject.toml이 보이면 Vercel이 Python 앱으로 오인해 빌드가 깨진다.

        원래 .vercelignore가 존재하는 이유이므로 되살아나면 안 된다.
        """
        self.assertNotIn("pyproject.toml", _allowlist())


if __name__ == "__main__":
    unittest.main()
