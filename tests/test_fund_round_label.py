r"""자금조달 회차 라벨이 「제N회차회차」로 나오던 것을 잠근다 (2026-08-27).

골드에서 날짜 표기를 훑다 이게 보였다 —

    • 2026.04.10 · [자금조달(사모) 제12회차회차] 타법인 증권 취득 자금
                              ~~~~~~~~~~

DART의 `tm`(회차)이 **세 가지 모양**으로 온다(30개사 2,877건 실측):

    숫자만  1,302 · 빈값 1,198 · "N회차" 197 · "N회" 174 · 각주 붙은 것 6

옛 코드는 `f"제{tm}회차"`라, 접미가 붙어 오는 **371건(12.9%)**이 전부
「제12회차회차」·「제9회회차」가 됐다.

각주 기호와 줄바꿈이 낀 것도 있다 — `"37회차(*)"` · `"32회차\n주1)"`.
"""
import pytest

from dart_risk_mcp.server import _format_fund_year_prefix, _fund_round_korean


@pytest.mark.parametrize("raw,want", [
    ("12", "제12회차"),          # 숫자만 (최다)
    ("3회차", "제3회차"),         # 접미 — 옛 코드는 「제3회차회차」
    ("9회", "제9회차"),           # 접미 변형 — 옛 코드는 「제9회회차」
    ("제5회차", "제5회차"),       # 접두까지 붙은 경우
    ("제7회", "제7회차"),
    ("37회차(*)", "제37회차"),    # 각주 기호
    ("32회차\n주1)", "제32회차"),  # 줄바꿈 + 각주
    (" 4 ", "제4회차"),
])
def test_한_가지_모양으로_모은다(raw, want):
    assert _fund_round_korean(raw) == want


@pytest.mark.parametrize("raw", ["-", "", "   ", None])
def test_빈_값은_생략한다(raw):
    assert _fund_round_korean(raw) == ""


def test_숫자가_없으면_감싸지_않는다():
    """「제미상회차」처럼 말이 안 되는 라벨을 만들지 않는다."""
    assert _fund_round_korean("미상") == "미상"


def test_회차가_두_번_나오지_않는다():
    for raw in ["12", "3회차", "9회", "제5회차", "37회차(*)"]:
        assert _fund_round_korean(raw).count("회차") == 1, raw


def test_프리픽스에_반영된다():
    out = _format_fund_year_prefix({"year": 2026, "kind": "private", "tm": "12회차"})
    assert "회차회차" not in out
    assert "제12회차" in out
