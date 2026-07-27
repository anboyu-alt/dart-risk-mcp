"""Vercel 런타임 호환성 — import 시점에 죽는 부류를 정적으로 막는다.

실제 배포에서 겪은 실패다: `api/index.py`가 끌어오는 core 모듈 3개가
`X | None`(PEP 604)을 `from __future__ import annotations` 없이 써서,
Python 3.10 미만 런타임에서 **import 시점에** TypeError로 죽었다.

증상이 고약했다 — Vercel은 `FUNCTION_INVOCATION_FAILED`라는 text/plain
오류 페이지만 돌려주고 원인을 말해주지 않는다. 로컬에서는 최신 파이썬이라
잘 돌아가므로 테스트로도 안 잡혔다.

이 테스트는 런타임 버전에 의존하지 않고 **소스를 정적으로 검사**해 같은
부류를 막는다.
"""
import ast
import pathlib
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_FUTURE = "from __future__ import annotations"


def _annotations_of(node):
    """노드에 달린 애노테이션 표현식을 모은다."""
    found = []
    if isinstance(node, ast.AnnAssign) and node.annotation:
        found.append(node.annotation)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.returns:
            found.append(node.returns)
        args = node.args
        for arg in list(args.args) + list(args.posonlyargs) + list(args.kwonlyargs):
            if arg.annotation:
                found.append(arg.annotation)
    return found


def uses_pep604(tree: ast.AST) -> bool:
    """애노테이션에 `X | Y` 표기가 쓰였는지 검사한다."""
    for node in ast.walk(tree):
        for ann in _annotations_of(node):
            for sub in ast.walk(ann):
                if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr):
                    return True
    return False


def _python_sources():
    for pkg in ("dart_risk_mcp", "se_server"):
        yield from (_ROOT / pkg).rglob("*.py")
    yield _ROOT / "api" / "index.py"


class TestPep604NeedsFutureImport(unittest.TestCase):
    def test_no_module_uses_pep604_without_future_import(self):
        offenders = []
        for path in _python_sources():
            src = path.read_text(encoding="utf-8")
            if uses_pep604(ast.parse(src)) and _FUTURE not in src:
                offenders.append(str(path.relative_to(_ROOT)))
        self.assertEqual(
            offenders, [],
            "PEP 604(`X | None`)을 쓰면서 `from __future__ import annotations`가 "
            "없는 모듈이 있습니다. Python 3.10 미만 런타임에서 import 시점에 "
            "TypeError로 죽습니다:\n  " + "\n  ".join(offenders),
        )


class TestAdapterReportsImportFailure(unittest.TestCase):
    """어댑터는 import가 깨져도 이유를 말해야 한다.

    말하지 못하면 Vercel의 불투명한 오류 페이지만 남아, 로그 접근 권한이
    없는 사람은 진단할 수 없다.
    """

    def _adapter_source(self) -> str:
        return (_ROOT / "api" / "index.py").read_text(encoding="utf-8")

    def test_imports_are_guarded(self):
        src = self._adapter_source()
        self.assertIn("_IMPORT_ERROR", src)
        tree = ast.parse(src)
        guarded = any(
            isinstance(node, ast.Try)
            and any(isinstance(n, (ast.Import, ast.ImportFrom)) for n in ast.walk(node))
            for node in tree.body
        )
        self.assertTrue(guarded, "모듈 레벨 import가 try로 감싸여 있지 않습니다")

    def test_failure_body_has_diagnostics_without_secrets(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "vercel_adapter_probe", _ROOT / "api" / "index.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        mod._IMPORT_ERROR = "TypeError: unsupported operand type(s) for |"
        body = mod._import_failure_body()

        self.assertIn("detail", body)
        self.assertIn("python", body)          # 버전이 있어야 3.9 가설을 즉시 확인한다
        self.assertIn("packages_present", body)
        # 자격증명이 새면 안 된다.
        import json
        dumped = json.dumps(body, ensure_ascii=False).lower()
        for leaked in ("supabase_service_key", "crtfc_key", "eyj"):
            self.assertNotIn(leaked, dumped)


if __name__ == "__main__":
    unittest.main()
