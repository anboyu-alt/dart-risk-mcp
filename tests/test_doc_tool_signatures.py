"""CLAUDE.md의 도구 카탈로그가 **실제 시그니처**와 맞는지 기계로 대조한다.

`find_risk_precedents` 출력을 읽어보다 문서 쪽을 훑어 찾았다(2026-08-25).
26개 도구 중 **6개의 인자 목록이 어긋나** 있었고, 하나는 **존재하지 않는
인자를 설명**하고 있었다.

    get_major_decision(rcept_no, corp_cls="K", decision_type="")   ← 문서
    get_major_decision(rcept_no, decision_type="", corp_code="")   ← 실제

문서는 `corp_cls`의 허용값(`Y`/`K`/`N`/`E`)까지 적어 뒀는데 **그런 인자는
없다**. 게다가 같은 문서 다른 곳(라이브 검증 매트릭스)은 "12종 모두 DART
스펙상 **corp_code**가 항상 필수"라고 적고 있었다 — **자기모순**이다.

나머지 5건은 v1.18.x가 더한 `from_date`/`to_date`/`confirm_long`/
`lookback_days`가 제목 줄에 반영되지 않은 것이다(본문에는 설명이 있다).

이 파일은 그 대조를 자동화한다 — 도구에 인자를 더하거나 이름을 바꾸면
문서를 함께 고치라고 요구한다.
"""
import inspect
import pathlib
import re

import pytest

import dart_risk_mcp.server as srv

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_DOC = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")

# "### 3. `find_risk_precedents(signal_types, lookback_days=90)`"
_HEADS = re.findall(r"^### \d+\. `([a-z_]+)\(([^`]*)\)`", _DOC, re.M)


def _documented_args(argtxt):
    return [a.split("=")[0].strip() for a in argtxt.split(",") if a.strip()]


def _real_args(name):
    fn = getattr(srv, name, None)
    fn = getattr(fn, "fn", fn)   # FastMCP 래퍼
    return list(inspect.signature(fn).parameters) if fn else None


def test_문서_도구_목록이_등록_도구와_같다():
    registered = {t.name for t in srv.mcp._tool_manager.list_tools()}
    documented = {n for n, _ in _HEADS}
    assert documented == registered, (
        f"문서에만: {sorted(documented - registered)} / "
        f"코드에만: {sorted(registered - documented)}"
    )


def test_도구_개수가_스물여섯이다():
    """CLAUDE.md 곳곳이 "26개"라 적는다 — 늘리면 그 문장들도 함께 고쳐야 한다."""
    assert len(_HEADS) == 26
    assert "MCP 도구 26개" in _DOC


@pytest.mark.parametrize("name,argtxt", _HEADS)
def test_인자_목록이_실제와_같다(name, argtxt):
    real = _real_args(name)
    assert real is not None, f"{name}이 server.py에 없다"
    assert _documented_args(argtxt) == real, (
        f"{name}\n  문서 {_documented_args(argtxt)}\n  실제 {real}"
    )


def test_없는_인자를_설명하지_않는다():
    """`corp_cls`는 실존한 적 없는 이름이다 — 재발 방지."""
    assert "corp_cls`: `Y`(유가증권)" not in _DOC
    real = _real_args("get_major_decision")
    assert "corp_code" in real and "corp_cls" not in real


def test_제거된_기능을_문서가_광고하지_않는다():
    """「위기 타임라인」은 v0.8.5 원칙으로 출력에서 빠졌다(severity 파생)."""
    i = _DOC.index("### 3. `find_risk_precedents")
    block = _DOC[i:i + 600]
    assert "각 신호의 의미, 위기 타임라인, 복합 패턴을 반환" not in block


def test_find_risk_precedents가_실제로_타임라인을_내지_않는다():
    """문서만 고치고 출력이 그대로면 정정이 거짓이 된다."""
    fn = getattr(srv.find_risk_precedents, "fn", srv.find_risk_precedents)
    out = fn(signal_types=["CB_BW"])
    assert "위기 타임라인" not in out
    assert "개월" not in out.split("━━ 카탈로그 선례")[0], "신호 해설에 기간 표기가 남았다"
