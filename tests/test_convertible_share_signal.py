"""「전환주식의전환가액조정」은 사채가 아니라 우선주다.

1년 코퍼스에서 CB_BW 키워드 「전환가액조정」(의 없음)이 잡는 22건은
**전부** 「전환주식의전환가액조정」이었다. 전환주식 = 전환우선주·상환전환
우선주라 사채가 아니다.

고치는 이유는 오탐 자체보다 **구조**다. CB_BW는 taxonomy를 3개(1.1·1.5·1.6)
켜므로, 이 제목 하나가 RCPS(1.4)와 함께 `debt_spiral`의 부분 겹침 임계
(min_overlap=2)를 혼자 충족했다 — 한탑 실사고(INQUIRY가 4.3+7.1을 켜서
카드 3개를 띄운 건)와 같은 구조다.

⚠ 「전환가액의조정」(의 있음, 588건)은 CB 리픽싱이라 CB_BW에 남는다.
두 문자열은 서로 부분 문자열이 아니다.
"""
import json
import pathlib

import pytest

from dart_risk_mcp.core.qualifiers import parse_report_name, qualify_signals
from dart_risk_mcp.core.signals import SIGNAL_KEY_TO_TAXONOMY, match_signals
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS

_CORPUS = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "corpus"
     / "signal_titles_365d.json").read_text(encoding="utf-8"))


def _keys(nm):
    return sorted({s["key"] for s in match_signals(nm)})


class TestConvertibleShareIsNotBond:
    SHARE_TITLES = [
        "전환주식의전환가액조정              (전환우선주)",
        "전환주식의전환가액조정              (상환전환우선주)",
        "전환주식의전환가액조정              ((제2회 상환전환우선주))",
        "전환주식의전환가액조정",           # 부제 없는 변형 — 이게 빠지면 무신호였다
    ]
    BOND_TITLES = [
        "전환가액의조정",
        "전환가액의조정              (제3회차)",
        "주요사항보고서(전환사채권발행결정)",
        "주요사항보고서(신주인수권부사채권발행결정)",
    ]

    @pytest.mark.parametrize("nm", SHARE_TITLES)
    def test_전환주식은_RCPS만_켠다(self, nm):
        assert _keys(nm) == ["RCPS"], nm

    @pytest.mark.parametrize("nm", BOND_TITLES)
    def test_사채_제목은_그대로_CB_BW다(self, nm):
        assert "CB_BW" in _keys(nm), nm
        assert "RCPS" not in _keys(nm), nm


class TestNoSingleTitleFillsDebtSpiral:
    """제목 하나가 혼자 `debt_spiral` 임계를 채우지 못한다."""

    def _taxonomies(self, nm):
        q = qualify_signals(match_signals(nm), parse_report_name(nm),
                            {"flr_nm": "", "corp_name": ""})
        tax = set()
        for x in q:
            if x.tier != "observed":
                continue
            v = SIGNAL_KEY_TO_TAXONOMY.get(x.key)
            tax |= set(v if isinstance(v, (list, tuple)) else [v] if v else [])
        return tax

    @pytest.mark.parametrize("nm", TestConvertibleShareIsNotBond.SHARE_TITLES)
    def test_전환주식_제목은_혼자_패턴을_못_채운다(self, nm):
        seq = set(CROSS_SIGNAL_PATTERNS["debt_spiral"]["signal_sequence"])
        assert len(self._taxonomies(nm) & seq) < 2, nm

    def test_코퍼스에_debt_spiral_단독_충족_제목이_없다(self):
        seq = set(CROSS_SIGNAL_PATTERNS["debt_spiral"]["signal_sequence"])
        offenders = [t["nm"] for t in _CORPUS["titles"]
                     if match_signals(t["nm"])
                     and len(self._taxonomies(t["nm"]) & seq) >= 2]
        assert not offenders, f"혼자 채우는 제목: {offenders[:5]}"
