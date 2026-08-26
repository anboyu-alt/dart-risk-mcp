"""채무증권 미상환 잔액 파싱이 **실제 응답 필드**를 읽는지 잠근다.

재무 도구의 선택 블록 출현율을 8개사로 재다 찾았다(2026-08-25).
세 블록이 **전부 0/8**이었다:

    track_debt_balance         회사채 0/8 · 1년 이내 만기 0/8 · 차환 0/8
    track_capital_structure    채무증권 잔액 추이 0/8 · CB_ROLLOVER 0/8

원인은 **필드명**이었다. 코드가 `remndr_amount`·`remndr_within1y_amount`를
읽는데 **다섯 엔드포인트 어디에도 그런 필드가 없다**. 그래서
`fetch_debt_balance`가 **모든 회사에서 항상 빈 결과**였고, 그 위에 선 것들이
통째로 죽어 있었다 —

    · `track_debt_balance` 도구가 늘 "잔액이 없거나 찾지 못했습니다"
    · `track_capital_structure`의 「최근 3년 채무증권 잔액 추이」 블록
    · `detect_debt_rollover`(CB_ROLLOVER 플래그)가 **발화 불가**

⚠ 엔드포인트 **URL은 처음부터 옳았다**(`…NrdmpBlce.json`). 틀린 것은
읽는 필드였고, CLAUDE.md의 엔드포인트 표는 반대로 `…IsDecsn.json`(발행결정,
DART가 status 101로 거부)이라 적고 있었다 — 코드와 문서가 서로 다른 방식으로
틀려 있어 어느 쪽을 봐도 진실이 안 보였다.

## 실제 응답 (실측)

한 엔드포인트가 **3행**을 돌려준다 — `remndr_exprtn2`가 공모/사모/**합계**.
금액은 `sm`, 만기 구간은 `yy1_below`(회사채·신종·조건부) 또는 `de*` 계열
(단기사채·기업어음, 전부 1년 이하 구간).

    두산에너빌리티 2025 회사채  sm 808,470,000,000 · yy1_below 536,470,000,000

**합계 행만** 쓴다 — 공모+사모까지 더하면 두 배로 센다.

수정 후 20개사 중 **16곳**에서 잔액이 잡힌다(이전 0곳). 두산에너빌리티는
총 8,084억 · 1년 이내 **66.4%**로 차환 압박 경고가 발화한다.
"""
import pathlib

import pytest

from dart_risk_mcp.core.dart_client import (
    _DEBT_BALANCE_URLS, _DEBT_UNDER_1Y_FIELDS, fetch_debt_balance,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "dart_risk_mcp" / "core" / "dart_client.py").read_text(encoding="utf-8")


def _code_lines():
    """주석을 걷어낸 실행 줄만 — **소스 문자열 검색의 자기참조 함정**을 피한다.

    이 파일도, `dart_client.py`의 수정 주석도 옛 필드명을 *인용*한다. 그대로
    검색하면 "아직 읽고 있다"고 오판한다(v1.20.20에서 이미 한 번 겪었다).
    """
    out = []
    for line in _SRC.splitlines():
        code = line.split("#", 1)[0]
        if code.strip():
            out.append(code)
    return chr(10).join(out)


def test_존재하지_않는_필드를_읽지_않는다():
    code = _code_lines()
    assert "remndr_amount" not in code
    assert "remndr_within1y_amount" not in code


def test_실제_금액_필드를_읽는다():
    code = _code_lines()
    assert 'item.get("sm")' in code


def test_합계_행만_쓴다():
    """공모+사모+합계를 다 더하면 두 배가 된다."""
    code = _code_lines()
    assert "remndr_exprtn2" in code and '"합계"' in code


def test_모든_엔드포인트에_만기_필드가_정의돼_있다():
    assert set(_DEBT_UNDER_1Y_FIELDS) == set(_DEBT_BALANCE_URLS)


def test_URL이_미상환잔액_엔드포인트다():
    """`…IsDecsn`(발행결정)은 DART가 status 101로 거부한다."""
    for url in _DEBT_BALANCE_URLS.values():
        assert "NrdmpBlce" in url, url
        assert "IsDecsn" not in url, url


@pytest.mark.parametrize("kind,fields", sorted(_DEBT_UNDER_1Y_FIELDS.items()))
def test_만기_필드가_1년_이하_구간이다(kind, fields):
    for f in fields:
        assert f.startswith("de") or f == "yy1_below", (kind, f)


def test_문서가_같은_엔드포인트를_적는다():
    doc = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    for url in _DEBT_BALANCE_URLS.values():
        ep = url.rsplit("/", 1)[-1]
        assert ep in doc, f"CLAUDE.md에 {ep}가 없다"
    assert "cprndIsDecsn" not in doc, "문서에 옛(잘못된) 엔드포인트가 남아 있다"


def test_빈_입력에_안전하다():
    r = fetch_debt_balance("", "", "2025")
    assert r["total"] == 0 and r["by_kind"] == {}
