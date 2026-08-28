"""`track_fund_usage`의 상세 목록 상한 — **조용히 자르지 않는지**를 잠근다.

금융지주·증권사는 조달 회차가 수백 개다. 실측(2026-08-28): KB금융 499건
**51,343자** · 미래에셋증권 46,682자. 같은 표본에서 다른 도구는 전부 1만 자
미만이었다(analyze 최대 9,247 · affiliates 3,071). 한 번의 도구 호출이 대화
컨텍스트의 상당 부분을 먹는다.

상한을 두되 **이 도구의 목적을 해치지 않는 축**으로 둔다:

    이상 플래그가 붙은 건   상한과 무관하게 전부(안전 상한 60건까지)
    나머지                  최신순 30건까지
    잘린 만큼               몇 건인지 사실로 적는다

집계(총 건수·플래그 건수)는 상한과 무관하게 그대로다 — 요약 문장이
목록 길이에 따라 달라지면 안 된다.
"""
import re

import pytest

from dart_risk_mcp.server import (
    _FUND_USAGE_DETAIL_MAX,
    _FUND_USAGE_FLAGGED_MAX,
)


def test_상한이_관례_값과_같다():
    """`get_affiliate_investments`의 상위 30건 관례를 따른다."""
    assert _FUND_USAGE_DETAIL_MAX == 30
    assert _FUND_USAGE_FLAGGED_MAX >= 55, (
        "실측 오르비텍 55건(전부 플래그)을 온전히 담지 못하면 진짜 사례가 잘린다"
    )


def _render(records):
    """서버 렌더 로직만 떼어 흉내 — 상한·생략 문구 계약을 재현한다."""
    flagged = [r for r in records if r["flags"]]
    rest = [r for r in records if not r["flags"]]
    flag_omitted = max(0, len(flagged) - _FUND_USAGE_FLAGGED_MAX)
    flagged = flagged[:_FUND_USAGE_FLAGGED_MAX]
    budget = max(0, _FUND_USAGE_DETAIL_MAX - len(flagged))
    omitted = max(0, len(rest) - budget)
    return flagged + rest[:budget], omitted, flag_omitted


def _rec(flagged: bool):
    return {"flags": ["FUND_UNREPORTED"] if flagged else []}


def test_플래그가_붙은_건은_상한에_밀려나지_않는다():
    """정상 건이 아무리 많아도 플래그 건이 먼저다 — 목적이 그것이다."""
    records = [_rec(False)] * 400 + [_rec(True)] * 25
    shown, omitted, flag_omitted = _render(records)
    assert sum(1 for r in shown if r["flags"]) == 25
    assert flag_omitted == 0
    # 플래그 25건을 먼저 채우고 남은 예산 5건만 정상 건에 쓴다
    assert len(shown) == _FUND_USAGE_DETAIL_MAX
    assert omitted == 395


def test_정상_건만_있으면_상한까지만_싣는다():
    records = [_rec(False)] * 499
    shown, omitted, flag_omitted = _render(records)
    assert len(shown) == _FUND_USAGE_DETAIL_MAX
    assert omitted == 499 - _FUND_USAGE_DETAIL_MAX
    assert flag_omitted == 0


def test_실측_오르비텍_규모는_전부_실린다():
    """55건이 전부 플래그였다 — 이 사례가 잘리면 도구가 쓸모를 잃는다."""
    records = [_rec(True)] * 55 + [_rec(False)] * 77
    shown, omitted, flag_omitted = _render(records)
    assert sum(1 for r in shown if r["flags"]) == 55
    assert flag_omitted == 0
    assert omitted == 77


def test_플래그가_안전_상한을_넘으면_그것도_밝힌다():
    records = [_rec(True)] * 200
    shown, omitted, flag_omitted = _render(records)
    assert len(shown) == _FUND_USAGE_FLAGGED_MAX
    assert flag_omitted == 200 - _FUND_USAGE_FLAGGED_MAX


def test_상한보다_적으면_아무것도_생략하지_않는다():
    records = [_rec(True)] * 3 + [_rec(False)] * 10
    shown, omitted, flag_omitted = _render(records)
    assert len(shown) == 13
    assert omitted == 0 and flag_omitted == 0


@pytest.mark.parametrize("marker", ["표시했습니다", "생략"])
def test_생략_문구가_소스에_있다(marker):
    """조용히 자르면 사용자는 전부 본 줄 안다 — 프로젝트의 명시적 원칙."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    i = src.index("def track_fund_usage(")
    body = src[i:i + 9000]
    assert marker in body


def test_집계는_상한과_무관하다():
    """총 건수·플래그 건수는 잘린 목록이 아니라 전체에서 세야 한다."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    i = src.index("def track_fund_usage(")
    body = src[i:i + 9000]
    assert re.search(r"총 \{len\(records\)\}건 조회", body), "총 건수가 목록 기준이 되면 안 된다"
    assert "len(anomaly_records)" in body, "플래그 건수가 목록 기준이 되면 안 된다"
    assert "len(_shown)}건 조회" not in body
