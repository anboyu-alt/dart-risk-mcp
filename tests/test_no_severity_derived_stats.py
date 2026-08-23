"""내부 severity에서 파생된 **수치**가 사용자 출력에 나가지 않는지 잠근다.

2026-08-24까지 세 도구가 이렇게 말하고 있었다.

    analyze_company_risk   • 경영권분쟁 신호 기준: 위기 도달까지 약 12개월, 예상 지분 손실 40%
    check_disclosure_risk  ━━ 과거 유사 신호가 끝까지 간 경우의 참고 궤적 ━━ … 손실은 평균 70% 수준으로 추정됩니다
    find_risk_precedents   과거 같은 유형의 신호가 끝까지 간 사례를 모아 보면, … 평균 70% 수준이었습니다

그 수치의 정체는 `SEVERITY_LEVELS` **4행 조회표**다.

    CRITICAL → 9개월 / 90%      HIGH → 15개월 / 70%
    MEDIUM   → 12개월 / 40%     LOW  → 6개월 / 20%

taxonomy 40종이 단 3가지 답을 공유했고, 골든에는 같은 상수가 한 문장 안에서
`"…15개월…70%; …9개월…90%; …15개월…70%."`로 반복돼 서로 다른 실증인 것처럼
보이기까지 했다.

세 원칙을 동시에 어긴다.
  · **v0.8.5** — 위험도를 정량화하거나 등급으로 노출하지 않는다. 90%를 보면
    CRITICAL임을 그대로 되읽을 수 있으니 severity를 숫자로 내보낸 셈이다.
  · **비범위(가격 예측)** — 이 도구는 주가 데이터를 아예 다루지 않는다.
  · **근거 표기** — "사례를 모아 보면 … 평균 …이었습니다"는 측정이 아니었다.

기존 `test_golden_output_hygiene.py`는 점수·등급 **어휘**를 찾는데, 이건
어휘가 아니라 **숫자**라 통과했다. 그래서 별도로 건다.
"""
import inspect
import pathlib

import pytest

import dart_risk_mcp.server as srv
from dart_risk_mcp.core.taxonomy import SEVERITY_LEVELS, estimate_crisis_timeline

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GOLDEN = _ROOT / "tests" / "fixtures" / "sample_outputs"

# 조회표에서 나오는 값들 — 출력에 이 조합이 보이면 안 된다
_MONTHS = {str(d["max_months"]) for d in SEVERITY_LEVELS.values()}
_LOSSES = {str(d["equity_loss_pct"]) for d in SEVERITY_LEVELS.values()}

BANNED_PHRASES = (
    "예상 지분 손실",
    "주가·지분 손실은 평균",
    "위기 도달까지 평균",
    "위기 도달까지 약",
    "과거 유사 신호가 끝까지 간",
    "신호가 끝까지 간 사례를 모아",
)


@pytest.mark.parametrize("phrase", BANNED_PHRASES)
def test_서버_출력에_그_문구가_없다(phrase):
    src = inspect.getsource(srv)
    # 주석에는 남아 있어도 된다(왜 뺐는지 기록). 문자열 리터럴만 본다.
    import ast

    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert phrase not in node.value, (
                f"server.py 문자열에 '{phrase}' — severity 파생 수치가 복귀했다"
            )


@pytest.mark.parametrize("phrase", BANNED_PHRASES)
def test_골든에도_없다(phrase):
    hits = [p.name for p in _GOLDEN.glob("*.txt")
            if phrase in p.read_text(encoding="utf-8")]
    assert not hits, f"'{phrase}' 가 남은 골든: {hits[:5]}"


def test_estimate_crisis_timeline은_여전히_공개API다():
    """제거가 아니라 **렌더 중단**이다 — 시그니처는 유지한다(하위 호환)."""
    from dart_risk_mcp.core import estimate_crisis_timeline as exported

    got = exported("8.1")
    assert set(got) == {"months_to_impact", "equity_loss_pct"}


def test_그_값이_severity_조회표와_같다():
    """'측정이 아니라 조회표'라는 사실 자체를 고정한다."""
    from dart_risk_mcp.core.taxonomy import TAXONOMY

    distinct = {(v["months_to_impact"], v["equity_loss_pct"])
                for v in (estimate_crisis_timeline(t) for t in TAXONOMY)}
    # 40여 종이 조회표 4행 + 미상 센티널 안에서만 답한다
    assert len(distinct) <= len(SEVERITY_LEVELS) + 1, distinct
    for sev, d in SEVERITY_LEVELS.items():
        assert (d["max_months"], d["equity_loss_pct"]) in distinct or sev == "LOW"


def test_어떤_도구도_숫자로_severity를_되돌려주지_않는다():
    """조회표 값 조합(개월·%)이 함께 찍히는 문장이 없어야 한다."""
    import ast
    import re

    src = inspect.getsource(srv)
    for node in ast.walk(ast.parse(src)):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        text = node.value
        if "개월" in text and "%" in text:
            for m in _MONTHS:
                for loss in _LOSSES:
                    assert not (m in text and loss in text), (
                        f"조회표 값이 함께 나오는 문자열: {text[:80]!r}"
                    )


def test_기존_hygiene가_못_잡던_이유를_기록한다():
    """어휘 검사로는 숫자를 못 잡는다 — 이 파일이 필요한 이유."""
    hygiene = (_ROOT / "tests" / "test_golden_output_hygiene.py").read_text(encoding="utf-8")
    assert "지분 손실" not in hygiene, (
        "hygiene가 이 문구를 직접 다루게 됐다면 이 테스트의 서술을 갱신하세요"
    )
