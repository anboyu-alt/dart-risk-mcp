"""감사의견 계열 키워드 정리 (2026-08-22).

1년 전수 코퍼스(270,882건, 절단일 0)로 잰 결과를 고정한다. 90일 창에서는
"감사 시즌이 창 밖이라 0건인가"를 배제할 수 없어 판단을 미뤄 뒀던 것들이다.

핵심은 **어순**이었다. `AUDIT`은 "부적정의견"을 갖고 있었는데 DART 실제
표기는 「반기검토(감사)**의견부적정**등사실확인…」이다. 그 47건은 제목에
'자본잠식'이 들어간 덕에 `INSOLVENCY`로만 잡히고 감사의견 신호는 붙지
않았다 — 감사의견을 못 받은 회사가 감사의견 신호 없이 표시되고 있었다.
"""
import json
import pathlib

import pytest

from dart_risk_mcp.core.signals import SIGNAL_TYPES, match_signals

_KW = {s["key"]: s["keywords"] for s in SIGNAL_TYPES}
_CORPUS = (pathlib.Path(__file__).parent / "fixtures" / "corpus"
           / "signal_titles_365d.json")
_TITLES = json.loads(_CORPUS.read_text(encoding="utf-8"))["titles"]


def _keys(title):
    return {s["key"] for s in match_signals(title)}


class TestAuditRecall:
    def test_실제_표기_의견부적정이_감사의견을_켠다(self):
        """1년 전수 47건(정정 제외 41건) — 옛 키워드로는 전부 놓쳤다."""
        real = ("반기검토(감사)의견부적정등사실확인"
                "(자본잠식률100분의50이상또는자기자본10억원미만포함)")
        assert "AUDIT" in _keys(real)

    def test_자본잠식과_함께_와도_둘_다_켜진다(self):
        """이 제목은 감사의견 문제이면서 동시에 자본잠식 사실 확인이다."""
        real = ("반기검토(감사)의견부적정등사실확인"
                "(자본잠식률100분의50이상또는자기자본10억원미만포함)")
        assert {"AUDIT", "INSOLVENCY"} <= _keys(real)

    def test_의견거절_경로는_그대로다(self):
        assert "AUDIT" in _keys("반기검토의견부적정,의견거절또는완전자본잠식사실발생")
        assert "AUDIT" in _keys("반기검토의견부적정또는의견거절")


class TestDeadKeywordsRemoved:
    """1년 전수에서 0건이라 제거한 것들 — 되살리려면 실측 근거부터."""

    @pytest.mark.parametrize("key,dead", [
        ("AUDIT", "한정의견"), ("AUDIT", "부적정의견"),
        ("AUDIT", "계속기업불확실성"), ("AUDIT", "감사범위제한"),
        ("AUDIT", "감사인교체"),
        ("GOING_CONCERN", "계속기업가정불확실"),
        ("GOING_CONCERN", "계속기업불확실"),
        ("INSOLVENCY", "어음부도"), ("INSOLVENCY", "의도적부도"),
    ])
    def test_제거됐다(self, key, dead):
        assert dead not in _KW[key]

    def test_계속기업은_제목에_아예_없다(self):
        """`계속기업`으로 넓혀도 1년 전수 0건 — 감사보고서 본문에만 있다.

        그래서 GOING_CONCERN은 라벨과 달리 회생·파산절차로만 발화한다.
        taxonomy 8.4가 계속기업 의문의 **후속 단계**를 담당하므로 의미는 맞다.
        """
        assert not any("계속기업" in t["nm"] for t in _TITLES)
        assert _KW["GOING_CONCERN"] == ["회생절차", "파산절차"]


class TestNoLoss:
    """제거가 실제 포착을 줄이지 않았는지 — 코퍼스 전수로 확인."""

    def test_제거한_키워드가_잡던_제목이_없다(self):
        dead = ("한정의견", "부적정의견", "계속기업불확실성", "감사범위제한",
                "감사인교체", "계속기업가정불확실", "계속기업불확실",
                "어음부도", "의도적부도", "공시의무위반", "공시누락",
                "중요정보누락", "발행철회", "공시철회", "보고서미제출")
        hit = [t["nm"] for t in _TITLES if any(d in t["nm"] for d in dead)]
        assert hit == [], f"제거로 잃는 제목이 있다: {hit[:5]}"


class TestDisclosureDelayRecall:
    def test_띄어쓰기_세_변형이_모두_잡힌다(self):
        """taxonomy 4.3이 명시한 대상인데 붙여쓴 형태만 잡고 있었다."""
        for real in ("기타경영사항(자율공시)              (감사보고서 제출 지연)",
                     "기타경영사항(자율공시)              (감사보고서 제출지연)",
                     "기타경영사항(자율공시)              (감사보고서 지연 제출)"):
            assert "DISCLOSURE_VIOL" in _keys(real), real

    def test_보고서_미제출_공백형이_잡힌다(self):
        """정기보고서 미제출로 인한 매매거래정지 — 지금까지 무신호였다."""
        assert "DISCLOSURE_VIOL" in _keys(
            "주권매매거래정지              (사업보고서 미제출)")

    def test_지연_단독은_쓰지_않는다(self):
        """펀드명 「글로벌클린에너**지연**금증권」이 걸린다(1년 5건 실측).

        WATCH_ISSUE가 "미달"을 못 쓰는 것과 같은 종류의 함정이다.
        """
        assert "지연" not in _KW["DISCLOSURE_VIOL"]
        fund = ("[기재정정]투자설명서(집합투자증권)"
                "(삼성클래식글로벌클린에너지연금증권자투자신탁H[주식-재간접형])")
        assert "DISCLOSURE_VIOL" not in _keys(fund)


class TestCorpusEffect:
    def test_감사의견_포착이_늘었다(self):
        """15건 → 62건(정정 포함 기준). 코퍼스 빈도로 확인한다."""
        n = sum(t["n"] for t in _TITLES if "AUDIT" in _keys(t["nm"]))
        assert n >= 50, f"AUDIT 포착 {n}건 — 어순 교정이 반영되지 않았다"
