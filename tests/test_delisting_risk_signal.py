"""DELISTING_RISK(상장폐지 절차) 신호 + R2 국면 상승 예외 회귀 테스트.

배경: 2026-08-21에 INQUIRY의 "거래정지" 키워드를 실측 근거로 제거하면서
(액면병합 등 정례적 매매정지가 조회공시로 오탐) 거래소 퇴출 절차 계열이
어떤 신호에도 잡히지 않는 공백이 생겼다. 이 신호가 그 공백을 메운다.

픽스처 제목은 전부 2026-05-24~08-22 시장 전체 실측(고유 공시 48,646건)에서
그대로 가져온 실제 DART 공시명이다.
"""
import pytest

from dart_risk_mcp.core.explain import SIGNAL_PROSE
from dart_risk_mcp.core.qualifiers import (
    ESCALATION_SUBTITLES,
    TIER_OBSERVED,
    parse_report_name,
    qualify_signals,
)
from dart_risk_mcp.core.signals import (
    SIGNAL_KEY_TO_TAXONOMY,
    SIGNAL_TYPES,
    match_signals,
)
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS, TAXONOMY

_SIG = next(s for s in SIGNAL_TYPES if s["key"] == "DELISTING_RISK")

# 거래소 퇴출 절차의 각 단계 (실측 제목)
DELISTING_TITLES = [
    "기타시장안내(상장적격성 실질심사 대상 결정기한 안내)",
    "기타시장안내(상장적격성 실질심사 사유 추가 안내)",
    "상장적격성 실질심사 관련 주요 개선계획(자율공시)",
    "주권매매거래정지(상장폐지 사유 발생)",
    "주권매매거래정지기간변경(개선기간 부여)",
    "기타시장안내(개선기간 종료에 따른 상장폐지 여부 결정 안내)",
    "기타시장안내(코스닥시장위원회 개최결과 및 상장폐지 결정 안내)",
    "기타시장안내(주권 상장폐지 우려 예고)",
    "기타시장안내(정리매매 보류 관련)",
    "기타시장안내(실질심사 대상 여부 결정을 위한 조사기간 연장 안내)",
]

# 걸리면 안 되는 제목 (실측 — 상장 추진·해소 등)
MUST_NOT_MATCH = [
    "기타주요경영사항(자율공시)(코스닥시장 상장을 위한 상장예비심사 신청)",
    "기타시장안내(관리종목 지정우려 종목)(주가 1,000원 미달)",
    "기타시장안내(기업심사위원회 심의·의결 결과 및 상장유지 결정 안내)",
    "주권매매거래정지(주식의 병합, 분할 등 전자등록 변경, 말소)",
    "주권매매거래정지해제 (액면병합 주권 변경상장)",
]


class TestSignalMatching:
    @pytest.mark.parametrize("title", DELISTING_TITLES)
    def test_퇴출_절차_공시를_잡는다(self, title):
        assert "DELISTING_RISK" in [s["key"] for s in match_signals(title)], title

    @pytest.mark.parametrize("title", MUST_NOT_MATCH)
    def test_상장추진_해소_정례정지는_안_잡는다(self, title):
        assert "DELISTING_RISK" not in [s["key"] for s in match_signals(title)], title

    def test_키워드는_실측으로_고른_4종(self):
        """되살리거나 추가하려면 CLAUDE.md 관례대로 시장 실측 근거가 먼저다."""
        assert set(_SIG["keywords"]) == {"상장폐지", "실질심사", "개선기간", "정리매매"}

    def test_산문이_있다(self):
        """뷰어가 신호 설명으로 그대로 렌더한다."""
        assert "상장폐지" in SIGNAL_PROSE["DELISTING_RISK"]


class TestTaxonomyMapping:
    def test_taxonomy는_하나만_매핑한다(self):
        """신호 1개가 taxonomy 2개를 켜면 공시 한 건이 패턴 부분 겹침
        임계를 단독 충족한다(2026-08-21 INQUIRY 실사고)."""
        assert SIGNAL_KEY_TO_TAXONOMY["DELISTING_RISK"] == ["8.5"]

    def test_점수_가산이_없다(self):
        """v0.8.5 무판정 원칙 — 사실 표기만 한다."""
        assert _SIG["score"] == 0
        assert TAXONOMY["8.5"]["base_score"] == 0
        assert TAXONOMY["8.5"]["severity"] == "OBSERVATION"

    def test_8_5는_어떤_패턴에도_쓰이지_않는다(self):
        """이 매핑이 복합 패턴 발화를 바꾸지 않는다는 근거."""
        used = {t for p in CROSS_SIGNAL_PATTERNS.values() for t in p["signal_sequence"]}
        assert "8.5" not in used


class TestEscalationException:
    """R2(사후·해제 국면)가 국면 상승을 해소로 오독하지 않는지."""

    def _tier(self, title):
        sigs = match_signals(title) or [{"key": "X", "label": "L", "score": 0}]
        return qualify_signals(sigs, parse_report_name(title), {})[0]

    @pytest.mark.parametrize("title", [
        "주권매매거래정지해제 (상장폐지에 따른 정리매매 개시)",
        "주권매매거래정지해제 (상장폐지에 따른 정리매매 재개)",
    ])
    def test_정리매매_개시는_강등되지_않는다(self, title):
        """어미는 '해제'지만 상장폐지가 확정돼 정리매매가 시작된다는 뜻 —
        퇴출 절차에서 가장 무거운 국면이다. 실측 90일 21건."""
        assert self._tier(title).tier == TIER_OBSERVED, title

    @pytest.mark.parametrize("title", [
        "주권매매거래정지해제 (상장폐지사유 미해당)",
        "주권매매거래정지해제 (상장적격성 실질심사 대상 제외 결정)",
    ])
    def test_실제로_해소된_건은_그대로_강등된다(self, title):
        """예외가 너무 넓으면 이 둘까지 관찰 신호로 올라온다. 실측 90일 2건."""
        q = self._tier(title)
        assert q.tier != TIER_OBSERVED, title
        assert "해제" in (q.reason or "")

    def test_예외_목록은_정리매매_2종뿐(self):
        assert set(ESCALATION_SUBTITLES) == {"정리매매개시", "정리매매재개"}

    def test_무관한_해제_공시는_계속_강등된다(self):
        """예외가 R2 전체를 무력화하지 않았는지."""
        q = self._tier("주식담보제공계약 해제ㆍ취소등")
        assert q.tier != TIER_OBSERVED


class TestWrapperPhaseTail:
    """R2b — 포장 제목(기타주요경영사항 등)의 부제가 사후·해제 국면인 경우.

    「기타주요경영사항(제3자배정유상증자결정철회)」의 tail은 본체
    '기타주요경영사항'에서 뽑혀 PHASE_TAILS에 걸리지 않았다. 그래서 증자를
    **철회**한 건이 관찰 신호 '제3자배정유상증자'로 표시됐다 — 같은 사건이
    단독 제목이면 강등되는데 포장지가 씌워지면 강등되지 않는 비일관이었다.
    """

    def _q(self, title):
        from dart_risk_mcp.core.signals import match_signals as _ms
        sigs = _ms(title)
        return list(zip(sigs, qualify_signals(sigs, parse_report_name(title), {})))

    @pytest.mark.parametrize("title,key", [
        ("기타주요경영사항(제3자배정유상증자결정철회)", "3PCA"),
        ("기타주요경영사항(소액공모제3자배정유상증자결정철회)", "3PCA"),
        ("기타주요경영사항(제10회차전환사채권발행결정철회)", "CB_BW"),
        ("기타주요경영사항(회사분할결정철회)", "DEMERGER"),
    ])
    def test_포장_제목의_철회는_강등된다(self, title, key):
        got = {s["key"]: q for s, q in self._q(title)}
        assert key in got, f"{key} 가 매칭되지 않았다: {title}"
        assert got[key].tier != TIER_OBSERVED, title
        assert "철회" in got[key].reason

    def test_본체가_행위인_제목은_강등되지_않는다(self):
        """「소송등의제기ㆍ신청(경영권분쟁소송)(주주총회결의취소)」의
        '주주총회결의취소'는 소송의 청구 취지이지 소송 철회가 아니다."""
        title = "소송등의제기ㆍ신청(경영권분쟁소송)(주주총회결의취소)"
        got = {s["key"]: q for s, q in self._q(title)}
        assert "MGMT_DISPUTE" in got
        assert got["MGMT_DISPUTE"].tier == TIER_OBSERVED, got["MGMT_DISPUTE"].reason

    def test_포장_제목이어도_사건이면_강등되지_않는다(self):
        """부제가 phase tail로 끝나지 않으면 그대로 관찰 신호다."""
        title = "기타경영사항(자율공시)(자기사채(제13회전환사채)소각결정의건)"
        got = {s["key"]: q for s, q in self._q(title)}
        assert got["CB_BW"].tier == TIER_OBSERVED

    def test_포장_목록은_실측으로_고른_3종(self):
        from dart_risk_mcp.core.qualifiers import WRAPPER_BODIES
        assert set(WRAPPER_BODIES) == {
            "기타주요경영사항", "기타경영사항", "투자판단관련주요경영사항",
        }
