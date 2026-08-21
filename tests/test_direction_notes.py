"""방향 안내(DIRECTION_NOTES) 회귀 테스트.

신호 라벨이 '발행'인데 제목이 되사기·소각을 가리키면 방향이 정반대로 읽힌다.
2026-08-22 실측(90일·고유 공시 48,646건)에서 되사기·소각 제목 208건 중
기존 마커 2종이 잡은 것은 122건(59%)뿐이었다 — 나머지는 「주요사항보고서
(자기전환사채만기전취득결정)」 61건처럼 '사채취득'이 붙지 않는 표기였다.

픽스처 제목은 전부 그 코퍼스에서 그대로 가져온 실제 DART 공시명이다.
"""
import pytest

from dart_risk_mcp.core.qualifiers import (
    DIRECTION_NOTES, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import match_signals


def _notes(title):
    """제목 → {신호키: 방향안내 문자열}"""
    sigs = match_signals(title)
    out = {}
    for s, q in zip(sigs, qualify_signals(sigs, parse_report_name(title), {})):
        out[s["key"]] = q.note or ""
    return out


# 되사기·소각 — 방향 안내가 반드시 붙어야 하는 제목
RETIREMENT = [
    ("주요사항보고서(자기전환사채만기전취득결정)", "CB_BW"),
    ("주요사항보고서(자기신주인수권부사채만기전취득결정)", "CB_BW"),
    ("전환사채(해외전환사채포함)발행후만기전사채취득", "CB_BW"),
    ("신주인수권부사채(해외신주인수권부사채포함)발행후만기전사채취득", "CB_BW"),
    ("기타경영사항(자율공시)(자기사채(제13회전환사채)소각결정의건)", "CB_BW"),
    ("기타경영사항(자율공시)(제14회차신주인수권부사채만기전취득후재매각)", "CB_BW"),
    ("주요사항보고서(자기전환사채매도결정)", "CB_BW"),
    ("교환사채(해외교환사채포함)발행후만기전사채취득", "EB"),
    ("자기교환사채만기전취득결정", "EB"),
    ("주식소각결정(상환전환우선주)", "RCPS"),
]

# 진짜 발행 — 안내가 붙으면 안 되는 제목
ISSUANCE = [
    ("주요사항보고서(전환사채권발행결정)", "CB_BW"),
    ("주요사항보고서(신주인수권부사채권발행결정)", "CB_BW"),
    ("주요사항보고서(교환사채권발행결정)", "EB"),
    ("전환주식의전환가액조정(상환전환우선주)", "RCPS"),
    ("전환주식의전환청구권행사(상환전환우선주)", "RCPS"),
]


class TestRetirementGetsNote:
    @pytest.mark.parametrize("title,key", RETIREMENT)
    def test_되사기_소각에는_방향_안내가_붙는다(self, title, key):
        note = _notes(title).get(key, "")
        assert note, f"{key} 에 안내가 없다: {title}"
        assert "발행이 아니라" in note


class TestIssuanceHasNoNote:
    @pytest.mark.parametrize("title,key", ISSUANCE)
    def test_발행에는_안내가_붙지_않는다(self, title, key):
        assert _notes(title).get(key, "") == "", title


class TestMarkerDesign:
    def test_RCPS는_상환을_마커로_쓰지_않는다(self):
        """상품명이 '상환전환우선주'라 '상환'을 마커로 쓰면 전 건에 안내가 붙는다."""
        assert "상환" not in DIRECTION_NOTES["RCPS"]["markers"]

    def test_되사기_계열_세_신호에_모두_항목이_있다(self):
        """EB·RCPS는 2026-08-22 전까지 항목이 없어 되사기가 전부
        '발행'으로 표시됐다."""
        assert {"CB_BW", "EB", "RCPS"} <= set(DIRECTION_NOTES)

    def test_CB_BW와_EB는_같은_마커를_쓴다(self):
        """둘 다 사채라 표기 변형이 같다 — 한쪽만 고치면 드리프트가 생긴다."""
        assert (set(DIRECTION_NOTES["CB_BW"]["markers"])
                == set(DIRECTION_NOTES["EB"]["markers"]))

    def test_라벨과_tier는_바뀌지_않는다(self):
        """방향 안내는 강등이 아니다 — 되사기·소각도 관찰 대상이다."""
        title = "주요사항보고서(자기전환사채만기전취득결정)"
        sigs = match_signals(title)
        q = next(q for s, q in zip(sigs, qualify_signals(sigs, parse_report_name(title), {}))
                 if s["key"] == "CB_BW")
        assert q.label == "CB/BW발행"
        assert q.tier == "observed"
