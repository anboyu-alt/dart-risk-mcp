"""`track_capital_structure`가 **이 회사가 자본을 건드린 횟수**만 세는지 잠근다.

위험 목록 9번을 제작자 승인으로 처리한 결과(2026-08-30).

## 무엇이 문제였나

같은 `detect_capital_churn`을 부르는 두 곳이 **다른 것을 셌다.**

    analyze_company_risk       observed_events만 넘긴다  (한정층 적용)
    track_capital_structure    원자료를 그대로 넘긴다     ← 여기

`detect_capital_churn`이 자체로 빼는 것은 정정(`is_amendment`)과
「발행결과」·「결과보고서」(`CHURN_RESULT_MARKS`)뿐이라 아래가 남아 있었다
(25개사 3년 실측, 새로 빠지는 **69건**):

    R3  자회사     34건  「유상증자결정(종속회사의주요경영사항)」
    R5  첨부정정    20건  `is_amendment_disclosure`가 이 태그를 안 본다
    R2  해제·철회    9건  「최대주주변경을수반하는주식담보제공계약해제ㆍ취소등」
    R2c 청약결과     6건  `CHURN_RESULT_MARKS`에 「발행결과」만 있다

## 되사기는 빠지지 않는다 — 이게 핵심 제약

`detect_capital_churn` 독스트링이 경고한다: 되사기·소각을 빼면 한탑(라이브
검증된 진짜 사례)이 떨어진다. 이 필터는 그것을 **건드리지 않는다** — 되사기는
강등이 아니라 **방향 안내**(`DIRECTION_NOTES`)라 tier가 observed다.

## 라이브 효과

    진짜 사례 유지   한탑 · 코아스 · 제이스코홀딩스 · 진원생명과학 · 유티아이
    대형주 해소      SK하이닉스 · 이마트 · 고려아연

SK하이닉스는 사용자 제보로 「이런 게 잡히면 안 된다」고 지목된 회사다.

## 왜 규칙 id를 안 만들었나

처음엔 `Qualified`에 규칙 id를 신설해 「중복·타사만」 빼려 했다. 그런데
25개사에서 **「중복·타사만」과 「observed만」이 결과가 완전히 같았다** —
자본 이벤트 키가 R1·R1b·R1c·R4·R6로 강등되는 일이 실제로는 없기 때문이다.
개념을 새로 만들 이유가 없어 형제 호출부와 같은 방식을 쓴다.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")


def _fn() -> str:
    i = _SRC.index("def track_capital_structure(")
    j = _SRC.index("\n@mcp.tool()", i)
    return _SRC[i:j]


def _code() -> str:
    keep = [l for l in _fn().splitlines() if not l.strip().startswith("#")]
    return "\n".join(keep)


def test_한정층을_건다():
    body = _code()
    assert "qualify_signals(matches, parse_report_name(report_nm), d)" in body
    assert "if _q.tier != TIER_OBSERVED:" in body


def test_형제_호출부와_같은_기준이다():
    """`analyze_company_risk`는 이미 observed만 넘긴다 — 갈리면 안 된다."""
    i = _SRC.index("def analyze_company_risk(")
    j = _SRC.index("\n@mcp.tool()", i)
    sibling = _SRC[i:j]
    assert "detect_capital_churn(observed_events" in sibling
    assert 'e.get("tier", TIER_OBSERVED) == TIER_OBSERVED' in sibling


def test_구조화_자사주_이벤트는_거르지_않는다():
    """제목이 없는 구조화 데이터는 한정 대상이 아니다(analyze와 같은 태도)."""
    body = _code()
    i = body.index("fetch_treasury_decisions(")
    tail = body[i:]
    assert "qualify_signals" not in tail, "구조화 이벤트까지 한정하고 있다"
    assert "signal_events.append({" in tail


def test_뺀_건수를_밝힌다():
    body = _fn()
    assert "_churn_demoted" in body
    assert "건은 집계에서 뺐습니다**" in body
    assert "if _churn_demoted:" in _code(), "0건일 때도 말하면 소음이다"


def test_되사기는_빼지_않는다고_적어_둔다():
    """이 제약이 사라지면 한탑이 떨어진다 — 근거를 코드에 남긴다."""
    body = _fn()
    assert "되사기·소각은 빼지 않습니다" in body


def test_자본_이벤트만_센다():
    """제외 건수는 자본 이벤트 기준이어야 한다 — 전체 강등을 세면 부풀려진다."""
    body = _code()
    assert 'if m["key"] in CAPITAL_EVENT_KEYS:' in body
    assert "_churn_demoted += 1" in body


def test_되사기가_강등되지_않는다():
    """방향 안내는 tier를 바꾸지 않는다 — 이 필터가 안전한 이유."""
    from dart_risk_mcp.core.qualifiers import (
        TIER_OBSERVED, parse_report_name, qualify_signals,
    )
    for title in ("주요사항보고서(자기전환사채만기전취득결정)",
                  "주요사항보고서(자기신주인수권부사채만기전취득결정)",
                  "주요사항보고서(자기주식취득신탁계약해지결정)"):
        q = qualify_signals([{"key": "CB_BW", "label": "CB/BW발행"}],
                            parse_report_name(title), {})
        assert q[0].tier == TIER_OBSERVED, f"되사기가 강등된다: {title}"


def test_빠져야_할_것은_강등된다():
    """실측에서 새로 빠진 네 부류가 실제로 procedural인지."""
    from dart_risk_mcp.core.qualifiers import (
        TIER_OBSERVED, parse_report_name, qualify_signals,
    )
    cases = [
        "유상증자결정(종속회사의주요경영사항)",
        "[첨부정정]주요사항보고서(회사합병결정)",
        "최대주주변경을수반하는주식담보제공계약해제ㆍ취소등",
        "유상증자또는주식관련사채등의청약결과(자율공시)",
    ]
    for title in cases:
        q = qualify_signals([{"key": "3PCA", "label": "유상증자"}],
                            parse_report_name(title), {})
        assert q[0].tier != TIER_OBSERVED, f"강등되지 않는다: {title}"


def test_기존_자체_필터를_지우지_않았다():
    """`detect_capital_churn`의 정정·결과보고 제외는 그대로 남는다(이중 안전)."""
    dc = (_ROOT / "dart_risk_mcp" / "core" / "dart_client.py").read_text(encoding="utf-8")
    assert 'if e.get("is_amendment"):' in dc
    assert "CHURN_RESULT_MARKS" in dc


def test_규칙_id를_만들지_않았다():
    """25개사에서 「중복·타사만」과 「observed만」이 같았다 — 개념을 늘리지 않는다."""
    q = (_ROOT / "dart_risk_mcp" / "core" / "qualifiers.py").read_text(encoding="utf-8")
    assert "DUPLICATE_OR_OTHER_RULES" not in q
    assert not re.search(r"^\s*rule: str", q, re.M), "안 쓰는 공개 필드가 생겼다"
