"""CLAUDE.md **내부 함수 표**의 시그니처를 실제 코드와 대조한다.

도구 시그니처는 `tests/test_doc_tool_signatures.py`가 지킨다. 그런데 **내부
함수 표(「핵심 내부 함수」 절)는 아무도 안 지켜서** 낡았다.

실측(2026-08-30, 표의 63개 함수 전수):

    fetch_fund_usage       문서 (corp_code, api_key, **corp_cls**, lookback_years)
                           실제 (corp_code, api_key, lookback_years)
    fetch_major_decision   문서 (rcept_no, **corp_cls**, decision_type)
                           실제 (rcept_no, api_key, decision_type, corp_code, corp_cls)
    resolve_decision_type  문서 (report_nm)   실제 (report_name)
    detect_debt_rollover   문서 (balance_history, capital_events)
                           실제 (balances, events)

⚠ 이 세션에서 내가 직접 걸렸다 — 문서의 4인자 형태로 `fetch_fund_usage`를
불렀다가 `TypeError: takes from 2 to 3 positional arguments but 4 were given`.
문서를 믿고 코드를 쓰면 깨진다.

⚠ 문서가 **일부 인자만** 적는 것은 허용한다(`...`·`**kwargs` 표기). 잡는 것은
**실제에 없는 인자를 적거나 순서가 뒤바뀐 것** 두 가지뿐이다.
"""
import inspect
import pathlib
import re

import pytest

from dart_risk_mcp.core import catalog as ct
from dart_risk_mcp.core import dart_client as dc
from dart_risk_mcp.core import qualifiers as q
from dart_risk_mcp.core import signals as sg
from dart_risk_mcp.core import taxonomy as tx

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MD = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
_MODS = (dc, q, sg, tx, ct)

# 생략 표기 — 「나머지는 코드를 보라」는 뜻이라 오기가 아니다
# `*`는 키워드 전용 구분자다(`f(a, *, b)`) — 인자가 아니다.
_ELLIPSIS = {"...", "…", "**kwargs", "*args", "*"}

_ROW = re.compile(r"^\|\s*`(\w+)\(([^`]*)\)`", re.M)


def _rows():
    for m in _ROW.finditer(_MD):
        name, params_s = m.group(1), m.group(2)
        fn = None
        for mod in _MODS:
            cand = getattr(mod, name, None)
            if callable(cand):
                fn = cand
                break
        if fn is None:
            continue
        doc = [p.strip().split("=")[0].split(":")[0].strip()
               for p in params_s.split(",") if p.strip()]
        doc = [p for p in doc if p and p not in _ELLIPSIS]
        try:
            real = list(inspect.signature(fn).parameters)
        except (TypeError, ValueError):
            continue
        yield name, doc, real


def test_표가_실제로_함수를_담고_있다():
    n = sum(1 for _ in _rows())
    assert n >= 50, f"표에서 {n}개만 찾았다 — 파싱이 헛돈다"


def test_실제에_없는_인자를_적지_않는다():
    bad = []
    for name, doc, real in _rows():
        unknown = [p for p in doc if p not in real]
        if unknown:
            bad.append(f"{name}: 문서에 {unknown}, 실제 ({', '.join(real)})")
    assert not bad, "CLAUDE.md 내부 함수 표가 낡았다:\n  " + "\n  ".join(bad)


def test_인자_순서가_뒤바뀌지_않는다():
    bad = []
    for name, doc, real in _rows():
        idxs = [real.index(p) for p in doc if p in real]
        if idxs != sorted(idxs):
            bad.append(f"{name}: 문서 ({', '.join(doc)}) · 실제 ({', '.join(real)})")
    assert not bad, "인자 순서가 실제와 다르다:\n  " + "\n  ".join(bad)


@pytest.mark.parametrize("name,want", [
    ("fetch_fund_usage", ["corp_code", "api_key", "lookback_years"]),
    ("resolve_decision_type", ["report_name"]),
    ("detect_debt_rollover", ["balances", "events"]),
])
def test_이번에_고친_것들이_되돌아가지_않는다(name, want):
    """네 건은 2026-08-30에 실측으로 고쳤다 — 그 값을 못 박는다."""
    found = [(d, r) for n, d, r in _rows() if n == name]
    assert found, f"{name}이 표에서 사라졌다"
    doc, real = found[0]
    assert real == want, f"{name}의 실제 시그니처가 바뀌었다: {real}"
    assert all(p in real for p in doc)
