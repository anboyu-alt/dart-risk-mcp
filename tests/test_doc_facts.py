"""문서가 적은 **개수**가 코드와 어긋나지 않는지 잠근다.

문서에는 테스트가 없다. 그래서 조용히 늙는다 — 2026-08-24 대조에서 넷이
어긋나 있었다.

| 문서 | 적혀 있던 값 | 실제 |
|---|---|---|
| CLAUDE.md 구조도 | `server.py # MCP 서버 + **13개** 도구 정의` | 26 |
| CLAUDE.md 발화 불가 신호 | **15종** (목록에 `THEME_STOCK` 누락) | 16 |
| CLAUDE.md 골든 재생성 | 6개 회사 × **23개** 도구 | 24 |
| README 검증 방식 | **23개** 도구 · 골드 **133건** · 테스트 **459개** | 24 · 262 · 2,300여 |

`THEME_STOCK` 누락은 **이 세션의 #251이 만든 드리프트**다 — absent로 정리하면서
목록과 개수를 함께 고치지 않았다. 그래서 세는 일을 사람 손에 남기지 않는다.

⚠ 테스트 개수는 여기서 검사하지 않는다(자기 참조라 항상 어긋난다).
README도 정확한 수 대신 "2,300여 개"로 적어 둔다.
"""
import pathlib
import re

import pytest

import dart_risk_mcp.server as srv
from dart_risk_mcp.core.signals import NON_TITLE_SIGNALS, SIGNAL_TYPES
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS, TAXONOMY

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CLAUDE = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
_README = (_ROOT / "README.md").read_text(encoding="utf-8")
_TOOLS = {t.name for t in srv.mcp._tool_manager.list_tools()}


def test_구조도의_도구_수가_실제와_같다():
    m = re.search(r"server\.py\s+# MCP 서버 \+ (\d+)개 도구 정의", _CLAUDE)
    assert m, "구조도 줄을 찾지 못했다"
    assert int(m.group(1)) == len(_TOOLS)


def test_신호_유형_수가_실제와_같다():
    m = re.search(r"signals\.py\s+# (\d+)개 신호 유형", _CLAUDE)
    assert m
    assert int(m.group(1)) == len(SIGNAL_TYPES)


def test_발화_불가_신호_목록이_실제와_같다():
    """개수와 목록을 함께 본다 — 개수만 맞고 이름이 빠지면 더 헷갈린다."""
    m = re.search(r"아래 키 중 (\d+)종\(([^)]+)\)", _CLAUDE)
    assert m, "NON_TITLE_SIGNALS 안내 문장을 찾지 못했다"
    listed = set(re.findall(r"`([A-Z_]+)`", m.group(2)))
    assert int(m.group(1)) == len(NON_TITLE_SIGNALS), "개수가 어긋난다"
    assert listed == set(NON_TITLE_SIGNALS), (
        f"목록 차이 — 문서에만: {listed - set(NON_TITLE_SIGNALS)}, "
        f"코드에만: {set(NON_TITLE_SIGNALS) - listed}"
    )


def _golden_matrix_tools() -> set:
    src = (_ROOT / "scripts" / "regen_goldens.py").read_text(encoding="utf-8")
    return {m for m in re.findall(r"\b([a-z_]{6,})\(", src) if m in _TOOLS}


def test_골든_매트릭스_도구_수가_실제와_같다():
    n = len(_golden_matrix_tools())
    for doc, text in (("CLAUDE.md", _CLAUDE), ("README.md", _README)):
        for m in re.finditer(r"6개(?:사| 회사) × (\d+)개 도구", text):
            assert int(m.group(1)) == n, f"{doc}: {m.group(1)} (실제 {n})"


def test_매트릭스에서_빠진_도구를_문서가_밝힌다():
    missing = _TOOLS - _golden_matrix_tools()
    assert missing, "전부 포함되면 이 문장은 지워야 한다"
    for name in missing:
        assert name in _CLAUDE, f"{name}이 매트릭스에서 빠진 이유가 문서에 없다"


def test_골드_출력_건수가_실제와_같다():
    n = len(list((_ROOT / "tests" / "fixtures" / "sample_outputs").glob("*.txt")))
    m = re.search(r"실측 골드 출력 (\d+)건", _README)
    assert m
    assert int(m.group(1)) == n, f"README {m.group(1)} (실제 {n})"


def test_테스트_수는_어림수로_적는다():
    """정확한 수를 적으면 테스트를 추가할 때마다 문서가 틀린다."""
    assert re.search(r"테스트 [\d,]+여 개", _README), (
        "README의 테스트 개수는 '…여 개' 형태로 적어 둔다"
    )


@pytest.mark.parametrize("n,label", [
    (len(TAXONOMY), "taxonomy"),
    (len(CROSS_SIGNAL_PATTERNS), "패턴"),
])
def test_참고_실제값(n, label):
    """드리프트 대상은 아니지만 값이 크게 바뀌면 문서를 훑어볼 신호."""
    assert n > 0, label
