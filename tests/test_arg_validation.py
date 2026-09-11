"""도구 인자 검증 — 잘못된 값을 **조용히 받아 축소 결과를 내지 않는다**.

경계 입력 두드리기(2026-08-30)에서 두 부류가 나왔다.

## ① 잘못된 연도가 조용히 통과해 축소 결과를 냈다

    get_shareholder_info(회사, "abcd")       1,192자 → **182자**
    get_affiliate_investments(회사, "2099")  2,681자 → **108자**
    scan_financial_anomaly(회사, "1900")     2,769자 →  **60자**
    track_debt_balance(회사, "20240")          329자 → **112자**
    get_executive_compensation(회사, "-2024") 1,115자 → **367자**

사용자는 「이 회사는 데이터가 없구나」로 읽는다. 실제로는 **연도가 틀렸다**.
전각 「２０２４」·소수점 「2024.0」·다섯 자리 「20240」이 전부 통과했다.

## ② `lookback_years`에 문자열·None이 오면 도구가 죽었다

    analyze_company_risk(회사, "3")   TypeError: '>' not supported
                                      between instances of 'int' and 'str'
    analyze_company_risk(회사, None)  같은 예외

프로젝트 규칙은 **예외를 도구 레벨로 전파하지 않는다**. MCP 클라이언트가
느슨하면 문자열이 올 수 있다. `track_turnover_trend`는 `isinstance` 검사가
있어 안전했다 — 그쪽에 맞췄다.

⚠ `bool`은 `int`의 하위형이라 `True`가 1로 통과한다. 의미가 없으므로
기본값으로 돌린다.
"""
import os
from datetime import datetime

from unittest.mock import patch

import pytest

import dart_risk_mcp.server as S
from dart_risk_mcp.server import _coerce_lookback, _validate_year

_KEY = os.environ.get("DART_API_KEY", "")


# ── 연도 검증 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("y", ["", None, "  ", "2024", "2000",
                               str(datetime.now().year)])
def test_정상_연도는_통과한다(y):
    assert _validate_year(y) == ""


@pytest.mark.parametrize("y", ["abcd", "20240", "-2024", "2024.0", "２０２４",
                               "24", "20a4", "２024"])
def test_형식이_틀리면_거절한다(y):
    err = _validate_year(y)
    assert err.startswith("❌") and "4자리" in err, f"{y!r} → {err!r}"


@pytest.mark.parametrize("y", ["1900", "1999", "2099", "3000"])
def test_범위를_벗어나면_거절한다(y):
    err = _validate_year(y)
    assert err.startswith("❌") and "범위" in err, f"{y!r} → {err!r}"


def test_내년까지는_허용한다():
    """결산 전 사업연도를 조회하려는 의도가 있을 수 있다."""
    assert _validate_year(str(datetime.now().year + 1)) == ""
    assert _validate_year(str(datetime.now().year + 2)) != ""


def test_오류_문구가_고칠_방법을_알려준다():
    err = _validate_year("abcd")
    assert "2024" in err, "예시가 없다"
    assert "직전 연도" in err, "미입력 시 동작을 알려주지 않는다"


# ── lookback 강제 ────────────────────────────────────────────────────────

@pytest.mark.parametrize("v,want", [
    (1, 1), (3, 3), (5, 5),
    (0, 1), (-1, 1), (100, 5),          # 범위 밖은 클램프
    ("3", 3), ("  4 ", 4),              # 문자열 숫자는 해석
    ("abc", 1), ("", 1), ("3.5", 1),    # 숫자가 아니면 기본값
    (None, 1), (True, 1), (False, 1),   # bool은 int 하위형 — 기본값으로
    (2.9, 2),                           # float은 버림
])
def test_lookback_강제(v, want):
    assert _coerce_lookback(v) == want, f"{v!r}"


def test_lookback이_예외를_던지지_않는다():
    for v in ([], {}, object(), "２", "٣", float("nan"), float("inf")):
        _coerce_lookback(v)   # 예외가 나면 이 줄에서 실패한다


# ── 종단 ─────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _KEY, reason="DART_API_KEY 없음")
@pytest.mark.parametrize("fn", [
    lambda: S.get_shareholder_info("삼성전자", "abcd"),
    lambda: S.get_affiliate_investments("삼성전자", "2099"),
    lambda: S.track_debt_balance("삼성전자", "20240"),
    lambda: S.get_executive_compensation("삼성전자", "-2024", "annual"),
    lambda: S.scan_financial_anomaly("삼성전자", "1900", "annual"),
    lambda: S.get_financial_summary("삼성전자", "2024.0", "annual"),
    lambda: S.compare_financials(["삼성전자", "셀트리온"], "２０２４"),
])
def test_도구가_잘못된_연도를_거절한다(fn):
    out = fn()
    assert out.startswith("❌"), out[:80]


@pytest.mark.skipif(not _KEY, reason="DART_API_KEY 없음")
@pytest.mark.parametrize("lb", ["3", None, True, 1.9, 100, 0, -1])
def test_analyze가_lookback_예외를_내지_않는다(lb):
    out = S.analyze_company_risk("삼성전자", lb)
    assert isinstance(out, str) and out.strip()


# ── lookback_years를 받는 **모든** 도구 (2026-09-12) ──────────────────────
#
# 기존 검사는 `analyze_company_risk` 하나뿐이었다. 정적으로 훑으니 이 인자를
# 받는 도구가 11개인데 `_coerce_lookback`을 거치는 것은 2개뿐이다 — 나머지가
# 안전한지 아무도 확인한 적이 없었다. 프로젝트 규칙은 「예외를 도구 레벨로
# 전파하지 않는다」이므로 느슨한 MCP 클라이언트가 문자열을 보내도 도구가 죽으면
# 안 된다.

_LOOKBACK_TOOLS = [
    ("analyze_company_risk", lambda v: S.analyze_company_risk("삼성전자", v)),
    ("build_event_timeline", lambda v: S.build_event_timeline("삼성전자", v)),
    ("find_risk_precedents", lambda v: S.find_risk_precedents(["CB_BW"], v)),
    ("find_actor_overlap",
     lambda v: S.find_actor_overlap(["삼성전자", "셀트리온"], v)),
    ("list_disclosures_by_stock",
     lambda v: S.list_disclosures_by_stock("005930", v)),
    ("track_insider_trading", lambda v: S.track_insider_trading("삼성전자", v)),
    ("get_audit_opinion_history",
     lambda v: S.get_audit_opinion_history("삼성전자", v)),
    ("check_disclosure_anomaly",
     lambda v: S.check_disclosure_anomaly("삼성전자", v)),
    ("track_fund_usage", lambda v: S.track_fund_usage("삼성전자", v)),
    ("track_capital_structure",
     lambda v: S.track_capital_structure("삼성전자", v)),
    ("track_turnover_trend", lambda v: S.track_turnover_trend("삼성전자", v)),
]


@pytest.mark.parametrize("name,call", _LOOKBACK_TOOLS,
                         ids=[n for n, _ in _LOOKBACK_TOOLS])
@pytest.mark.parametrize("lb", ["3", None, True, 1.9, 100, 0, -1])
def test_키가_없어도_lookback으로_죽지_않는다(name, call, lb):
    """키 확인보다 **앞에서** 인자를 만지는 도구를 잡는다.

    실측: `find_actor_overlap("갑","을", "3")`이 키 없는 환경에서도
    `TypeError: '>' not supported between instances of 'int' and 'str'`로
    죽었다 — 사용자에게는 도구가 통째로 사라진 것으로 보인다.
    """
    with patch.object(S, "_api_key", return_value=""):
        out = call(lb)
    assert isinstance(out, str) and out.strip()


@pytest.mark.skipif(not _KEY, reason="DART_API_KEY 없음")
@pytest.mark.parametrize("name,call", _LOOKBACK_TOOLS,
                         ids=[n for n, _ in _LOOKBACK_TOOLS])
@pytest.mark.usefixtures("no_structured_dart")
def test_실행_경로에서도_lookback으로_죽지_않는다(name, call):
    out = call("3")
    assert isinstance(out, str) and out.strip()
