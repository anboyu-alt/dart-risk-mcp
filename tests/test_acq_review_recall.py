"""ACQ_REVIEW 재현율 회귀 테스트 (2026-08-22).

DART는 같은 행위(타 법인 주식 취득)에 두 가지 제목 표기를 쓴다:
  · 「주요사항보고서(타법인주식및출자증권**양수**결정)」 — DS005 법정
  · 「타법인주식및출자증권**취득**결정」 — 자율공시·기타 (4배 흔하다)

'양수'만 키워드로 두는 바람에 90일 실측(고유 공시 48,646건)에서
'타법인주식/출자증권' 포함 제목 220건 중 **189건(86%)이 무신호**였다.
이 신호의 목적이 "상대방을 원문에서 확인하라"는 사실 안내인데, 안내가
필요한 건의 대부분에 안 붙고 있었다.
"""
import pytest

from dart_risk_mcp.core.signals import (
    SIGNAL_KEY_TO_TAXONOMY, SIGNAL_TYPES, match_signals,
)
from dart_risk_mcp.core.qualifiers import (
    TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.taxonomy import TAXONOMY

_SIG = next(s for s in SIGNAL_TYPES if s["key"] == "ACQ_REVIEW")

ACQUISITION = [
    "타법인주식및출자증권취득결정",
    "타법인주식및출자증권취득결정(자율공시)",
    "주요사항보고서(타법인주식및출자증권양수결정)",
    "주요사항보고서(영업양수결정)",
]

# 방향이 반대라 넣지 않은 것 — 자금이 들어오는 쪽
DISPOSAL = [
    "타법인주식및출자증권처분결정",
    "타법인주식및출자증권처분결정(자율공시)",
    "주요사항보고서(타법인주식및출자증권양도결정)",
]


class TestRecall:
    @pytest.mark.parametrize("title", ACQUISITION)
    def test_두_표기_모두_잡는다(self, title):
        assert "ACQ_REVIEW" in [s["key"] for s in match_signals(title)], title

    def test_취득_표기가_키워드에_있다(self):
        """이걸 빼면 실측 기준 재현율이 다시 14%로 떨어진다."""
        assert "타법인주식및출자증권취득" in _SIG["keywords"]

    @pytest.mark.parametrize("title", DISPOSAL)
    def test_처분_양도는_잡지_않는다(self, title):
        """자금이 들어오는 반대 방향이라 '양수거래 상대방 확인'과 성격이 다르다.
        별도 신호 후보로 남겼다(90일 실측 38건)."""
        assert "ACQ_REVIEW" not in [s["key"] for s in match_signals(title)], title


class TestQualification:
    def test_자회사_사안은_강등된다(self):
        """「…취득결정(종속회사의주요경영사항)」은 이 회사가 아니라 자회사 건."""
        title = "타법인주식및출자증권취득결정(종속회사의주요경영사항)"
        sigs = match_signals(title)
        q = next(q for s, q in zip(sigs, qualify_signals(sigs, parse_report_name(title), {}))
                 if s["key"] == "ACQ_REVIEW")
        assert q.tier != TIER_OBSERVED
        assert "자회사" in q.reason

    def test_철회는_강등된다(self):
        title = "기타주요경영사항(타법인주식및출자증권취득결정철회)"
        sigs = match_signals(title)
        q = next(q for s, q in zip(sigs, qualify_signals(sigs, parse_report_name(title), {}))
                 if s["key"] == "ACQ_REVIEW")
        assert q.tier != TIER_OBSERVED
        assert "철회" in q.reason


class TestTaxonomyStaysFactual:
    def test_무점수_관찰_신호다(self):
        """정상적인 사업 확장 M&A가 대다수라 판단 근거가 아니다 — 재현율을
        올려도 이 성격은 바뀌지 않는다."""
        assert SIGNAL_KEY_TO_TAXONOMY["ACQ_REVIEW"] == ["5.8"]
        assert TAXONOMY["5.8"]["base_score"] == 0
        assert TAXONOMY["5.8"]["severity"] == "OBSERVATION"

    def test_signals와_taxonomy_키워드가_일치한다(self):
        """두 곳에 같은 목록이 있어 한쪽만 고치면 카탈로그·표시가 어긋난다."""
        assert set(TAXONOMY["5.8"]["keywords"]) == set(_SIG["keywords"])
