"""회생절차 국면 구분 + 라벨 정합 (2026-08-23).

1년 전수에서 GOING_CONCERN을 켜는 제목은 **전부 회생·파산 절차**다(107건).
그런데 국면에 따라 뜻이 정반대인데 라벨은 셋 다 같았다.

| 국면 | 건수 | 뜻 |
|---|---:|---|
| 개시 | 83 | 회사 존속이 법정 절차로 넘어갔다 |
| 폐지 | 12 | 회생이 **실패**해 파산으로 간다 — 더 나쁘다 |
| 종결 | 5 | 회생이 **성공**해 정상화됐다 — 위험 신호가 아니다 |

그리고 라벨 "계속기업불확실"은 감사의견 기재사항을 가리키는데, 그 표기는
DART 공시 제목에 아예 없다(1년 전수 0건). 이용자가 읽는 말과 실제 잡는
것이 달랐다.
"""
import json
import pathlib

import pytest

from dart_risk_mcp.core.signals import SIGNAL_TYPES, match_signals
from dart_risk_mcp.core.qualifiers import parse_report_name, qualify_signals

_LABEL = {s["key"]: s["label"] for s in SIGNAL_TYPES}
_CORPUS = (pathlib.Path(__file__).parent / "fixtures" / "corpus"
           / "signal_titles_365d.json")
_TITLES = json.loads(_CORPUS.read_text(encoding="utf-8"))["titles"]


def _q(title):
    return [x for x in qualify_signals(match_signals(title), parse_report_name(title))
            if x.key == "GOING_CONCERN"]


class TestPhaseDirection:
    @pytest.mark.parametrize("title", ["회생절차종결결정", "회생절차종결신청"])
    def test_종결에는_방향_안내가_붙는다(self, title):
        q = _q(title)
        assert q and "종결" in q[0].note

    @pytest.mark.parametrize("title", [
        "주요사항보고서(회생절차개시신청)", "회생절차개시결정",
        "회생절차폐지결정", "회생절차폐지신청",
    ])
    def test_개시_폐지에는_붙지_않는다(self, title):
        """폐지는 회생 실패라 개시보다 더 나쁘다 — 방향이 다르지 않다."""
        q = _q(title)
        assert q and q[0].note == ""

    def test_종결도_신호는_유지된다(self):
        """회생을 거친 이력 자체는 관찰 대상이라 목록에서 빼지 않는다."""
        q = _q("회생절차종결결정")
        assert q and q[0].tier == "observed"


class TestLabelHonesty:
    def test_라벨이_실제_발화를_가리킨다(self):
        assert _LABEL["GOING_CONCERN"] == "회생·파산 절차"

    def test_계속기업은_제목에_없다(self):
        """옛 라벨이 가리키던 표기는 1년 전수에서 0건이다."""
        assert not any("계속기업" in t["nm"] for t in _TITLES)

    def test_발화_제목이_전부_회생_파산이다(self):
        hits = [t["nm"] for t in _TITLES
                if any(s["key"] == "GOING_CONCERN" for s in match_signals(t["nm"]))]
        assert hits, "코퍼스에 발화 사례가 있어야 한다"
        for nm in hits:
            assert "회생" in nm or "파산" in nm, nm


class TestCorpusScale:
    def test_국면_분포가_기록과_맞는다(self):
        g = {"개시": 0, "종결": 0, "폐지": 0}
        for t in _TITLES:
            if not any(s["key"] == "GOING_CONCERN" for s in match_signals(t["nm"])):
                continue
            for k in g:
                if k in t["nm"]:
                    g[k] += t["n"]
                    break
        assert g["개시"] > g["폐지"] > g["종결"], g
        assert g["종결"] <= 20, "종결이 늘면 방향 안내의 비중을 재검토"
