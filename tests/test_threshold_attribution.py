"""**우리가 정한 문턱**을 외부 통념으로 적지 않는지 잠근다.

세 문장이 이렇게 적혀 있었다.

    AR_SURGE            "**일반적으로** 매출 대비 매출채권 비율의 전년 대비
                         변화가 10%포인트 이상 커지면 **이상 신호로 봅니다**."
    INVENTORY_SURGE     "…10%포인트 이상 벌어지면 **주의 구간입니다**."
    CAPITAL_IMPAIRMENT  "자본총계가 자본금의 200% 이하로 떨어지면
                         **위험 구간에 진입한 것으로 봅니다**."

10%포인트·200%는 **이 도구가 정한 값**이다 — 금감원 카탈로그(보도자료 317건)에
'10%포인트'가 0건이고, taxonomy 6.1의 red_flags도 "Accounts receivable /
revenue ratio spike"로 임계가 없다. 그런데 문장은 회계·규제 통념인 것처럼
읽혔다. #262(정정공시 "정상 기업은 5% 이내")와 같은 부류다.

**값은 그대로 두고 출처만 갈랐다** — 골든 11개에서 AR_SURGE·INVENTORY_SURGE는
0건, CAPITAL_IMPAIRMENT는 2건(STX·제이스코홀딩스, 둘 다 부실 기업)이라 문턱
자체는 변별력이 있다.

⚠ **규정과 우리 문턱을 섞지 않는다** — 「자본잠식률 50% 초과 → 관리종목,
완전 잠식 → 상장폐지」는 실제 거래소 규정이고 공시 제목에도
「자본잠식률100분의50이상…」으로 나온다. 그건 유지하고 200%만 갈랐다.
"""
import re

import pytest

from dart_risk_mcp.core.dart_client import detect_financial_anomaly  # noqa: F401
from dart_risk_mcp.core.explain import FLAG_PROSE

OURS = ("AR_SURGE", "INVENTORY_SURGE", "CAPITAL_IMPAIRMENT")


@pytest.mark.parametrize("key", OURS)
def test_우리_문턱임을_밝힌다(key):
    body = FLAG_PROSE[key]["body"]
    assert "이 도구가 정한 관찰 문턱" in body, f"{key}: 출처 표기가 없다"


@pytest.mark.parametrize("key", OURS)
def test_통념처럼_적지_않는다(key):
    body = FLAG_PROSE[key]["body"]
    for phrase in ("일반적으로", "이상 신호로 봅니다", "주의 구간입니다",
                   "위험 구간에 진입한 것으로 봅니다"):
        assert phrase not in body, f"{key}: '{phrase}'"


def test_거래소_규정은_규정으로_남긴다():
    """우리 문턱과 섞지 않되, 진짜 규정을 지우지도 않는다."""
    body = FLAG_PROSE["CAPITAL_IMPAIRMENT"]["body"]
    assert "자본잠식률이 50%" in body and "상장폐지 사유" in body
    assert "거래소 규정" in body


@pytest.mark.parametrize("key,threshold", [
    ("AR_SURGE", "10%포인트"),
    ("INVENTORY_SURGE", "10%포인트"),
    ("CAPITAL_IMPAIRMENT", "200%"),
])
def test_문장의_수치가_판정식과_같다(key, threshold):
    """문구만 고치고 코드를 안 고치면(또는 반대면) 둘이 갈린다."""
    import inspect

    assert threshold in FLAG_PROSE[key]["body"]
    src = inspect.getsource(detect_financial_anomaly)
    if threshold == "10%포인트":
        assert "delta >= 10" in src, "판정식이 10이 아니다"
    else:
        assert "ratio < 200" in src, "판정식이 200이 아니다"


def test_다른_플래그도_통념_어휘를_쓰지_않는다():
    """새 플래그가 같은 습관으로 들어오면 여기서 걸린다."""
    banned = re.compile(r"일반적으로|통용|정상 기업은")
    for key, d in FLAG_PROSE.items():
        text = f"{d.get('title', '')} {d.get('body', '')}"
        m = banned.search(text)
        assert not m, f"{key}: '{m.group(0)}' — 출처를 밝히거나 문구를 바꾸세요"
