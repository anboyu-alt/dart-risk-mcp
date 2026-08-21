"""WATCH_ISSUE(관리종목 지정요건) 신호 회귀 테스트.

거래소 퇴출 트랙의 앞 단계 — 관리종목 지정 요건에 걸리거나 걸릴 우려가
있다는 사실. DELISTING_RISK(실질심사·상장폐지 절차)와는 상태가 달라 분리했다.

픽스처 제목은 전부 2026-05-24~08-22 시장 전체 실측(고유 공시 48,646건)에서
그대로 가져온 실제 DART 공시명이다.
"""
import pytest

from dart_risk_mcp.core.explain import SIGNAL_PROSE
from dart_risk_mcp.core.qualifiers import (
    TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import (
    SIGNAL_KEY_TO_TAXONOMY, SIGNAL_TYPES, match_signals,
)
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS, TAXONOMY

_SIG = next(s for s in SIGNAL_TYPES if s["key"] == "WATCH_ISSUE")

WATCH_TITLES = [
    "기타시장안내(관리종목지정우려종목)(시가총액 200억원 미달)",
    "기타시장안내(관리종목지정우려종목)(주가 1,000원 미달)",
    "기타시장안내(관리종목지정우려종목)(시가총액 150억원 미달)",
    "기타시장안내(관리종목지정우려종목)",
    "기타시장안내(관리종목지정사유추가우려)(주가 1,000원 미달)",
    "기타시장안내(관리종목지정우려종목)(소프트센1우선주(거래량 미달))",
    "반기또는분기매출액미달사실발생",
]

# 걸리면 안 되는 것 — 펀드명의 '미달러'(미(美) 달러)가 대표적 함정
MUST_NOT_MATCH = [
    "[기재정정]일괄신고서(집합투자증권-신탁형)"
    "(카디안미국뱅크론특별자산자투자신탁(미달러)[대출채권-재간접형])",
    "증권발행실적보고서(집합투자증권)"
    "(카디안글로벌온콜로지증권자투자신탁(미달러)[주식-재간접형])",
    "기타시장안내(상장적격성 실질심사 대상 결정)",
    "기타시장안내(단기과열종목지정해제)",
    "주권매매거래정지(주식의 병합, 분할 등 전자등록 변경, 말소)",
]


class TestMatching:
    @pytest.mark.parametrize("title", WATCH_TITLES)
    def test_관리종목_요건_공시를_잡는다(self, title):
        assert "WATCH_ISSUE" in [s["key"] for s in match_signals(title)], title

    @pytest.mark.parametrize("title", MUST_NOT_MATCH)
    def test_무관한_공시는_안_잡는다(self, title):
        assert "WATCH_ISSUE" not in [s["key"] for s in match_signals(title)], title

    def test_미달_단독_키워드는_쓰지_않는다(self):
        """'미달'만 쓰면 집합투자증권 공시의 펀드명 '미달러'가 걸린다(실측 6건).
        되살리려면 시장 실측 근거부터 붙여야 한다."""
        assert "미달" not in _SIG["keywords"]
        assert set(_SIG["keywords"]) == {"관리종목", "매출액미달"}

    def test_산문이_있다(self):
        assert "관리종목" in SIGNAL_PROSE["WATCH_ISSUE"]


class TestTaxonomyAndScoring:
    def test_taxonomy는_하나만_매핑한다(self):
        assert SIGNAL_KEY_TO_TAXONOMY["WATCH_ISSUE"] == ["8.5"]

    def test_DELISTING_RISK와_8_5를_공유한다(self):
        """의도된 공유 — 둘 다 퇴출 트랙이고 8.5는 패턴에 안 쓰인다."""
        assert SIGNAL_KEY_TO_TAXONOMY["DELISTING_RISK"] == ["8.5"]

    def test_점수_가산이_없다(self):
        assert _SIG["score"] == 0
        assert TAXONOMY["8.5"]["base_score"] == 0

    def test_패턴_발화를_바꾸지_않는다(self):
        used = {t for p in CROSS_SIGNAL_PATTERNS.values() for t in p["signal_sequence"]}
        assert "8.5" not in used


class TestStageSeparation:
    """두 신호가 서로의 영역을 침범하지 않는지 — 라벨이 단계를 구분한다."""

    @pytest.mark.parametrize("title,expected", [
        ("기타시장안내(관리종목지정우려종목)(주가 1,000원 미달)", "WATCH_ISSUE"),
        ("기타시장안내(상장적격성 실질심사 대상 결정)", "DELISTING_RISK"),
        ("주권매매거래정지(상장폐지 사유 발생)", "DELISTING_RISK"),
        ("반기또는분기매출액미달사실발생", "WATCH_ISSUE"),
    ])
    def test_단계별로_다른_신호가_붙는다(self, title, expected):
        keys = [s["key"] for s in match_signals(title)]
        assert expected in keys
        other = "DELISTING_RISK" if expected == "WATCH_ISSUE" else "WATCH_ISSUE"
        assert other not in keys, f"{title} 이 두 신호에 동시에 걸린다"

    def test_한정층이_강등하지_않는다(self):
        """실측 115건 전부 observed였다(제출인 코스닥시장본부 = 거래소 예외)."""
        title = "기타시장안내(관리종목지정우려종목)(시가총액 200억원 미달)"
        row = {"flr_nm": "코스닥시장본부", "corp_name": "아무회사"}
        sigs = match_signals(title)
        q = qualify_signals(sigs, parse_report_name(title), row)[0]
        assert q.tier == TIER_OBSERVED, q.reason
