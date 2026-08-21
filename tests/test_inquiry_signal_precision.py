"""INQUIRY(조회공시) 신호 정밀화 회귀 테스트.

배경(한탑 002680 실사고): 「주권매매거래정지(주식의 병합, 분할 등 전자등록
변경, 말소)」는 액면병합에 따른 정례적·기술적 매매정지 안내인데, INQUIRY
키워드의 "거래정지"에 걸려 조회공시로 잡혔다. 여기에 INQUIRY가 taxonomy
4.3+7.1 두 개에 매핑돼 있어, 이 공시 **한 건**이 복합 패턴 부분 겹침
임계(min_overlap=2)를 단독 충족시켜 무자본 M&A·허위 신사업 주가부양·상폐
회피 카드 3개를 한꺼번에 띄웠다.

픽스처 제목은 전부 2026-05-23~2026-08-21 시장 전체 실측(고유 공시 49,816건)
에서 그대로 가져온 실제 DART 공시명이다.
"""
import pytest

from dart_risk_mcp.core.signals import (
    SIGNAL_KEY_TO_TAXONOMY,
    SIGNAL_TYPES,
    match_signals,
)
from dart_risk_mcp.core.taxonomy import find_pattern_overlaps

_INQUIRY = next(s for s in SIGNAL_TYPES if s["key"] == "INQUIRY")

# 기업행위에 따른 정례적·기술적 매매정지 — 조회공시가 아니다(실측 상위 제목).
ROUTINE_HALTS = [
    "주권매매거래정지(주식의 병합, 분할 등 전자등록 변경, 말소)",
    "주권매매거래정지해제 (액면병합 주권 변경상장)",
    "주권매매거래정지해제(감자주권변경상장)",
    "주권매매거래정지(무상증자)",
    "주권매매거래정지(단일판매공급계약)",
    "주권매매거래정지해제(액면분할주권변경상장)",
    "주권매매거래정지(SPAC합병(예비심사청구대상))",
    "매매거래정지및정지해제(중요내용공시)",
]

# 거래소가 해명을 요구했거나 회사가 해명한 진짜 조회공시 계열(실측 상위 제목).
REAL_INQUIRIES = [
    "조회공시요구(현저한시황변동)",
    "조회공시요구(현저한시황변동)에대한답변(미확정)",
    "조회공시요구(풍문또는보도)에대한답변(미확정)",
    "조회공시요구(풍문또는보도)",
    "풍문또는보도에대한해명(미확정)",
    "풍문또는보도에대한해명",
    "조회공시요구(풍문또는보도)(코스닥시장이전상장추진설)",
]


class TestRoutineHaltIsNotInquiry:
    @pytest.mark.parametrize("title", ROUTINE_HALTS)
    def test_정례적_매매정지는_조회공시로_잡히지_않는다(self, title):
        assert "INQUIRY" not in [s["key"] for s in match_signals(title)], title

    def test_한탑_실사고_공시_2건은_아예_무신호(self):
        """이 두 건이 세 패턴 카드를 띄운 장본인이다."""
        for title in (
            "주권매매거래정지 (주식의 병합, 분할 등 전자등록 변경, 말소)",
            "주권매매거래정지해제 (액면병합 주권 변경상장)",
        ):
            assert match_signals(title) == [], title


class TestRealInquiryStillMatches:
    @pytest.mark.parametrize("title", REAL_INQUIRIES)
    def test_진짜_조회공시는_그대로_잡힌다(self, title):
        assert "INQUIRY" in [s["key"] for s in match_signals(title)], title


class TestInquiryTaxonomyMapping:
    def test_공시의무위반_4_3에_매핑되지_않는다(self):
        """4.3으로 실제 잡히는 공시는 불성실공시법인지정 계열이고
        그건 DISCLOSURE_VIOL이 맡는다."""
        assert SIGNAL_KEY_TO_TAXONOMY["INQUIRY"] == ["7.1"]
        assert "4.3" in SIGNAL_KEY_TO_TAXONOMY["DISCLOSURE_VIOL"]

    def test_조회공시_한건은_패턴_임계를_단독_충족하지_못한다(self):
        """이중 매핑 시절에는 이 한 줄이 zombie_ma·fake_new_biz를 띄웠다."""
        tax = list(SIGNAL_KEY_TO_TAXONOMY["INQUIRY"])
        assert find_pattern_overlaps(tax, min_overlap=2) == []


class TestRemovedKeywordsStayRemoved:
    @pytest.mark.parametrize("kw", ["거래정지", "매매정지", "주가이상", "이상거래", "거래량급증"])
    def test_실측_근거로_제거한_키워드는_되돌아오지_않는다(self, kw):
        """되살리려면 CLAUDE.md 관례대로 시장 실측 근거부터 붙여야 한다."""
        assert kw not in _INQUIRY["keywords"], kw

    def test_남긴_키워드는_실측에서_발화가_확인된_3종뿐(self):
        assert set(_INQUIRY["keywords"]) == {"조회공시", "풍문또는보도", "조회공시요구"}
