"""Vercel 함수 번들 경계 — requirements.txt에는 함수가 실제로 쓰는 것만.

실사고(2026-09-07): requirements.txt가 `mcp>=1.0.0`을 담고 있어 Vercel
Python 함수 4개가 배포마다 pydantic·starlette·uvicorn 등 ~24MB를 복제했고,
master 커밋 1,150건 × 프리뷰 배포가 쌓여 Functions Storage 무료 한도 10GB를
채웠다. 함수 코드(api/·tool_server/)는 `mcp`를 한 번도 import하지 않는다.

이 테스트는 두 방향을 잠근다:
① requirements.txt에 `mcp`가 되살아나지 않을 것
② 함수 코드와 그것이 import하는 core 모듈이 `mcp`에 기대지 않을 것
   (기대게 되면 ①을 풀어야 하므로 그 사실이 여기서 먼저 드러난다)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "requirements.txt"
FUNC_DIRS = [ROOT / "api", ROOT / "tool_server"]

_IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+mcp\b", re.M)


def _requirement_names() -> list[str]:
    names = []
    for line in REQ.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        names.append(re.split(r"[<>=!~\[ ]", line, maxsplit=1)[0].lower())
    return names


def test_requirements_txt에_mcp가_없다():
    assert "mcp" not in _requirement_names(), (
        "requirements.txt는 Vercel 함수 전용이다. `mcp`를 넣으면 함수 4개의 "
        "번들이 배포마다 ~24MB씩 복제돼 Functions Storage를 채운다 "
        "(2026-09-07 실사고). 함수가 정말 mcp를 쓰게 됐다면 이 테스트와 "
        "test_함수_코드는_mcp를_import하지_않는다를 함께 고쳐라."
    )


def test_requirements_txt에_requests는_남아_있다():
    # 함수가 실제로 쓰는 유일한 외부 의존성. 빠지면 프로덕션에서
    # ModuleNotFoundError로 함수가 죽는다(.vercelignore 주석의 2026-07-27 실사고).
    assert "requests" in _requirement_names()


def test_함수_코드는_mcp를_import하지_않는다():
    offenders = []
    for d in FUNC_DIRS:
        for p in d.glob("*.py"):
            if _IMPORT_RE.search(p.read_text(encoding="utf-8")):
                offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, f"함수 코드가 mcp를 import한다: {offenders}"


def test_함수가_쓰는_core_모듈은_mcp_없이_import된다():
    """mcp 패키지가 설치되지 않은 환경(Vercel 함수 런타임)을 흉내 낸다.

    별도 프로세스에서 `mcp` import를 막은 채 tool_server 4종을 import한다 —
    현재 프로세스에는 mcp가 이미 로드돼 있어 그 안에서는 검사가 되지 않는다.
    """
    code = r"""
import builtins, sys
_real = builtins.__import__
def _blocked(name, *a, **k):
    if name == "mcp" or name.startswith("mcp."):
        raise ModuleNotFoundError("mcp is not installed in the Vercel function bundle")
    return _real(name, *a, **k)
builtins.__import__ = _blocked
for m in ("tool_server.doc", "tool_server.corp", "tool_server.stats", "tool_server.track"):
    __import__(m)
print("ok")
"""
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True
    )
    assert r.returncode == 0 and "ok" in r.stdout, r.stderr[-2000:]
