"""채무불이행(부도류) 재현율 회귀 테스트 (2026-08-22).

1년 코퍼스(고유 공시 201,361건)에서 채무불이행 사실 공시 두 종이 **어떤
신호에도 잡히지 않았다** — 제목에 '부도'라는 낱말이 없기 때문이다.

  · 「사채원리금미지급발생」   16건 / 13개사
  · 「대출원리금연체사실발생」 18건 /  7개사

둘 다 `INSOLVENCY`(자본잠식/부도)의 의미에 정확히 들어맞고, 실측에서 다른
맥락의 표기가 0건이라 오탐 여지가 없다.
"""
import pytest

from dart_risk_mcp.core.signals import SIGNAL_TYPES, match_signals

_SIG = next(s for s in SIGNAL_TYPES if s["key"] == "INSOLVENCY")

DEFAULT_TITLES = [
    "사채원리금미지급발생",
    "사채원리금미지급발생(자율공시)",
    "대출원리금연체사실발생",
    "대출원리금연체사실발생(자율공시)",
]


class TestDefaultDisclosures:
    @pytest.mark.parametrize("title", DEFAULT_TITLES)
    def test_채무불이행_공시를_잡는다(self, title):
        assert "INSOLVENCY" in [s["key"] for s in match_signals(title)], title

    def test_기존_부도_자본잠식도_그대로(self):
        for t in ("주요사항보고서(부도발생)",
                  "반기검토의견부적정,의견거절또는완전자본잠식사실발생"):
            assert "INSOLVENCY" in [s["key"] for s in match_signals(t)], t

    def test_두_키워드가_남아있다(self):
        """제거하려면 CLAUDE.md 관례대로 시장 실측 근거부터 붙여야 한다."""
        assert "사채원리금미지급" in _SIG["keywords"]
        assert "대출원리금연체" in _SIG["keywords"]


class TestNotForceMapped:
    """대응 taxonomy가 없는 갭은 **억지로 매핑하지 않는다**.

    의미가 맞지 않는 taxonomy에 신호를 밀어 넣는 것이 2026-08-21 INQUIRY
    실사고의 원인이었다(조회공시를 '공시·보고 의무 위반' 4.3에 매핑). 아래
    두 종은 1년 실측으로 갭이 확인됐지만 맞는 자리가 없어 남겨 두었다 —
    신설 판단이 끝나기 전에 기존 신호에 끼워 넣으면 같은 실수를 반복한다.
    """

    @pytest.mark.parametrize("title", [
        "회계처리기준위반행위로인한증권선물위원회의검찰고발등",
        "회계처리기준위반에따른임원의해임권고조치",
        "파생상품거래손실발생",
    ])
    def test_아직_어떤_신호에도_잡히지_않는다(self, title):
        """이 테스트가 실패하면 = 누군가 매핑을 추가했다는 뜻이다.
        그 자체는 좋은 일이지만, 어느 taxonomy에 왜 넣었는지 근거를
        `docs/superpowers/specs/2026-08-22-signal-keyword-audit.md`에 남기고
        이 테스트를 갱신해야 한다."""
        assert match_signals(title) == [], (
            f"{title} 에 신호가 붙었다 — 매핑 근거를 스펙에 남기고 이 테스트를 갱신할 것"
        )
