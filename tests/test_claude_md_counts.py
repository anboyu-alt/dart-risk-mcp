"""CLAUDE.md의 개수 서술이 실코드와 어긋나지 않게 고정한다.

이 레포는 CLAUDE.md를 설계 기록으로 쓴다. 그래서 서술이 코드와 어긋나면
다음 사람이 **틀린 전제로 작업한다**. 실제로 그런 사례가 기록돼 있다
(`WINDOW_MONTHS` "12개월"이 실코드와 불일치해 2026-08-04 감사에서 정정).

2026-08-23 기계 대조에서 네 곳이 어긋나 있었다:

| 서술 | 문서 | 코드 |
|---|---|---|
| signals.py 신호 유형 | 54개 | **57개** |
| signals.py "v1.6.1 기준 N종" | 54종 | 57 (날짜 고정 서술이라 제거) |
| taxonomy.py 신호 분류 | 44개 | **45개** |
| taxonomy.py 패턴 | 10종 | **11종** |
| find_risk_precedents 신호 키 | 30개 | 표에 실제로 적힌 것 **33개** |

전부 신호·패턴을 추가하면서 서술을 안 고친 것이다. 사람이 매번 기억하는
대신 여기서 막는다 — `test_export_tool_data`가 버전 4곳을 묶어 두는 것과
같은 취지다.

⚠ 이 테스트는 **개수처럼 기계적으로 셀 수 있는 주장만** 본다. 설계 근거·
실측 기록 같은 서술은 대상이 아니다(그건 사람이 판단할 몫이다).
"""
import pathlib
import re

import pytest

import dart_risk_mcp.server as srv
from dart_risk_mcp.core.signals import SIGNAL_KEY_TO_TAXONOMY, SIGNAL_TYPES
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS, TAXONOMY

_MD = (pathlib.Path(__file__).parent.parent / "CLAUDE.md").read_text(encoding="utf-8")


def _claim(pattern: str) -> int:
    m = re.search(pattern, _MD, re.S)
    assert m, f"CLAUDE.md에서 서술을 찾지 못했다: {pattern!r}"
    return int(m.group(1))


CASES = [
    (r"# MCP 도구 (\d+)개", "MCP 도구 개수",
     lambda: len(srv.mcp._tool_manager.list_tools())),
    (r"signals\.py\s+# (\d+)개 신호 유형", "signals.py 신호 유형",
     lambda: len(SIGNAL_TYPES)),
    (r"taxonomy\.py\s+# (\d+)개 신호 분류", "taxonomy.py 신호 분류",
     lambda: len(TAXONOMY)),
    (r"taxonomy\.py.*?복합 패턴 (\d+)종", "taxonomy.py 패턴",
     lambda: len(CROSS_SIGNAL_PATTERNS)),
    (r"등록 패턴 (\d+)개", "등록 패턴", lambda: len(CROSS_SIGNAL_PATTERNS)),
]


@pytest.mark.parametrize("pattern,label,actual", CASES,
                         ids=[c[1] for c in CASES])
def test_문서_개수가_코드와_같다(pattern, label, actual):
    assert _claim(pattern) == actual(), (
        f"{label}: CLAUDE.md {_claim(pattern)} · 코드 {actual()} — "
        f"둘 중 하나를 고쳐야 한다"
    )


def test_신호_키_표가_실제_매핑과_맞는다():
    """`find_risk_precedents` 절의 표에 적힌 키가 전부 실존하고,
    바로 위 문장의 개수와도 맞는지 본다."""
    tbl = re.search(r"\| 카테고리 \| 키 목록 \|(.+?)\n\n", _MD, re.S)
    assert tbl, "신호 키 표를 찾지 못했다"
    listed = set(re.findall(r"`([A-Z_0-9]+)`", tbl.group(1)))
    missing = listed - set(SIGNAL_KEY_TO_TAXONOMY)
    assert not missing, f"표에 있는데 매핑에 없는 키: {sorted(missing)}"
    assert _claim(r"사용 가능한 신호 키 \(아래 표 (\d+)개") == len(listed), (
        f"문장의 개수와 표의 행 수가 다르다 (표 {len(listed)}개)"
    )
