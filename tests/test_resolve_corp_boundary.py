"""`resolve_corp`의 **경계 입력** — 엉뚱한 회사를 돌려주지 않는지 잠근다.

도구를 오타·공백·짧은 문자열로 두드리다 찾았다(2026-08-30).

## 빈 문자열이 아무 회사나 잡았다

빈 문자열은 **모든 이름의 부분 문자열**이라, 부분 일치의 「가장 짧은 이름」
규칙이 아무 회사나 골랐다.

    resolve_corp("")  →  「경」(00623698)

사용자는 빈 입력을 했는데 **엉뚱한 회사의 완전한 리포트**를 받고, 자기가
요청한 회사인 줄 안다. `analyze`·`timeline`·`company_info`·`turnover` 네 도구가
전부 그렇게 응답했다.

공백만 있는 입력(`"   "`·`"\\t"`)은 이미 `None`이 나왔다 — **빈 문자열만
새고 있었다.**

## 한 글자 부분 일치도 엉뚱했다

    resolve_corp("주")  →  「가주」
    resolve_corp("a")   →  「Nexans」

정확 일치·종목코드·별칭은 길이와 무관하게 그대로라, 「경」처럼 실제로 한
글자인 법인은 계속 찾힌다. 뷰어의 `/api/corp`도 이미 2자 이상만 받는다.
"""
import os

import pytest

from dart_risk_mcp.core.dart_client import _MIN_PARTIAL_QUERY, resolve_corp

_KEY = os.environ.get("DART_API_KEY", "")
pytestmark = pytest.mark.skipif(not _KEY, reason="DART_API_KEY 없음")


@pytest.mark.parametrize("q", ["", "   ", "\t", "\n", "​", None])
def test_빈_질의는_아무것도_돌려주지_않는다(q):
    assert resolve_corp(q, _KEY) is None


@pytest.mark.parametrize("q", ["주", "a", "1", "㈜"])
def test_한_글자는_부분_일치하지_않는다(q):
    """정확 일치하는 한 글자 법인이 아니라면 None이어야 한다."""
    got = resolve_corp(q, _KEY)
    assert got is None or got[0] == q, f"{q!r} → {got[0] if got else None!r}"


def test_한_글자여도_정확_일치는_찾는다():
    """「경」은 실제 법인명이다 — 부분 일치 차단이 이것까지 막으면 안 된다."""
    got = resolve_corp("경", _KEY)
    assert got is not None and got[0] == "경"


@pytest.mark.parametrize("q,want", [
    ("삼성전자", "삼성전자"),
    ("005930", "삼성전자"),
    ("삼성바이오", "삼성바이오로직스"),   # 두 글자 이상 부분 일치는 유지
])
def test_정상_해석은_그대로다(q, want):
    got = resolve_corp(q, _KEY)
    assert got is not None and got[0] == want, f"{q!r} → {got[0] if got else None!r}"


def test_앞뒤_공백은_다듬는다():
    a = resolve_corp("삼성전자", _KEY)
    for q in (" 삼성전자", "삼성전자 ", "  삼성전자  "):
        b = resolve_corp(q, _KEY)
        assert b is not None and b[0] == a[0], q


def test_최소_길이가_뷰어와_같다():
    """뷰어 `/api/corp`는 2자 이상만 받는다 — 같은 판단을 유지한다."""
    assert _MIN_PARTIAL_QUERY == 2


def test_긴_입력에도_예외가_나지_않는다():
    assert resolve_corp("가" * 500, _KEY) is None


@pytest.mark.parametrize("q", [
    "삼성전자'; DROP TABLE--", "../../etc/passwd",
    "<script>alert(1)</script>", "%00",
])
def test_이상한_입력에도_예외가_나지_않는다(q):
    resolve_corp(q, _KEY)   # 예외가 나면 이 줄에서 실패한다
