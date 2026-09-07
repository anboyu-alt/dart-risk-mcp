"""API 키 조회는 `_api_key()` 한 곳 — 두 관례가 섞여 있던 것을 잠근다.

실사고(2026-09-07): `server.py`가 키를 두 방식으로 읽고 있었다 — 모듈 상수
`_DART_API_KEY`(import 시점에 env를 한 번 읽음, 22개 도구)와
`os.environ.get("DART_API_KEY")`(호출 시점, 4개 도구). 테스트는 둘 중 하나만
패치하므로 어긋난 쪽에서 도구가 「환경변수가 설정되지 않았습니다」로 조기
반환했고, **키가 없는 환경**에서 7건이 실패했다. 제작자 PC는 env에 키가
있어 두 경로 모두 채워졌고 CI는 전체 스위트를 돌리지 않아 한 번도 드러나지
않았다(2026-04-22 · 07-07 · 08-28에 세 번 따로 들어온 관례 분기).

이 테스트는 키가 없는 환경을 흉내 내어(env 제거 + 모듈 상수 비움) 두 가지를
잠근다:
① `_api_key()`가 모듈 상수와 env **어느 쪽이든** 읽는다(상수 우선 — 이유는
   아래 테스트 docstring)
② 도구 본문이 `_DART_API_KEY`를 직접 읽지 않는다(AST) — 직접 읽는 곳이
   하나라도 다시 생기면 ①의 보장이 그 도구에서 깨진다
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import dart_risk_mcp.server as srv

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "dart_risk_mcp" / "server.py"


def test_모듈_상수가_있으면_그것을_읽는다(monkeypatch):
    """env보다 모듈 상수가 먼저다 — 테스트 다수가 상수를 패치하고 그 값이
    fetcher에 넘어갔는지를 `assert_called_with`로 본다(예:
    test_qualification_wiring). env 우선이면 env에 실제 키가 있는 제작자 PC에서
    그 검사가 깨진다."""
    monkeypatch.setenv("DART_API_KEY", "ENV")
    monkeypatch.setattr(srv, "_DART_API_KEY", "CONST")
    assert srv._api_key() == "CONST"


def test_모듈_상수가_비면_env를_읽는다(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "ENV")
    monkeypatch.setattr(srv, "_DART_API_KEY", "")
    assert srv._api_key() == "ENV"


def test_둘_다_없으면_빈_문자열(monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.setattr(srv, "_DART_API_KEY", "")
    assert srv._api_key() == ""


def _functions_reading_name(name: str) -> list[str]:
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name == "_api_key":
            continue  # 유일하게 허용되는 자리
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name) and sub.id == name:
                found.append(node.name)
                break
    return sorted(set(found))


def test_도구_본문은_모듈_상수를_직접_읽지_않는다():
    assert _functions_reading_name("_DART_API_KEY") == [], (
        "키는 `_api_key()`로만 읽는다. 직접 읽으면 env만 패치한 테스트·환경에서 "
        "그 도구만 「환경변수가 설정되지 않았습니다」로 조기 반환한다."
    )


def _functions_reading_env_key() -> list[str]:
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name == "_api_key":
            continue
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and sub.args
                and isinstance(sub.args[0], ast.Constant)
                and sub.args[0].value == "DART_API_KEY"
            ):
                found.append(node.name)
                break
    return sorted(set(found))


def test_도구_본문은_os_environ에서_키를_직접_읽지_않는다():
    assert _functions_reading_env_key() == [], (
        "키는 `_api_key()`로만 읽는다. env를 직접 읽으면 모듈 상수만 패치한 "
        "테스트·환경에서 그 도구만 조기 반환한다."
    )


def test_키_없는_환경에서_모듈_상수_패치만으로_도구가_열린다(monkeypatch):
    """env를 지우고 모듈 상수만 채웠을 때, env를 직접 읽던 네 도구가 조기
    반환하지 않는다(실사고 재현 — 수정 전에는 track_capital_structure 등이
    「환경변수가 설정되지 않았습니다」를 돌려줬다). resolve_corp를 막아
    네트워크 없이 그 문장의 부재만 본다."""
    monkeypatch.delenv("DART_API_KEY", raising=False)
    monkeypatch.setattr(srv, "_DART_API_KEY", "CONST")
    monkeypatch.setattr(srv, "resolve_corp", lambda *a, **k: None)
    for tool in (
        srv.get_affiliate_investments,
        srv.scan_financial_anomaly,
        srv.track_capital_structure,
        srv.track_turnover_trend,
    ):
        out = tool("테스트회사")
        assert "환경변수가 설정되지 않았습니다" not in out, tool.__name__


def test_헬퍼가_인자_없는_함수다():
    assert inspect.signature(srv._api_key).parameters == {}
