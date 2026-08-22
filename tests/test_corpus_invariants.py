"""실측 코퍼스 불변식 테스트 — 픽스처 몇 개보다 넓은 회귀 방어.

`tests/fixtures/corpus/signal_titles_90d.json`은 2026-05-24~08-22 시장 전체
공시 48,646건에서 **신호가 붙는 고유 제목 404종**을 빈도와 함께 고정한 것이다.
개별 제목을 손으로 나열하는 대신 코퍼스 전체에 성립해야 할 성질을 건다 —
키워드를 건드렸을 때 어디가 깨지는지 이 파일이 알려준다.

코퍼스를 갱신하려면 `tmp/delisting_signal/measure.py`로 다시 수집한다.
"""
import json
import pathlib
import collections

import pytest

from dart_risk_mcp.core.qualifiers import (
    TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import (
    SIGNAL_KEY_TO_TAXONOMY, SIGNAL_TYPES, match_signals,
)
from dart_risk_mcp.core.taxonomy import TAXONOMY

_CORPUS = pathlib.Path(__file__).parent / "fixtures" / "corpus" / "signal_titles_90d.json"
_DATA = json.loads(_CORPUS.read_text(encoding="utf-8"))
_TITLES = [t["nm"] for t in _DATA["titles"]]
_WEIGHT = {t["nm"]: t["n"] for t in _DATA["titles"]}


def _observed(title):
    sigs = match_signals(title)
    return [
        (s, q) for s, q in zip(sigs, qualify_signals(sigs, parse_report_name(title), {}))
        if q.tier == TIER_OBSERVED
    ]


class TestCorpusShape:
    def test_코퍼스가_비어있지_않다(self):
        assert len(_TITLES) >= 300
        assert _DATA["n_disclosures_scanned"] > 40_000

    def test_모든_제목이_여전히_신호를_낸다(self):
        """이 파일에 담긴 제목은 수집 시점에 전부 신호가 붙던 것이다.
        키워드를 좁히면 여기서 먼저 드러난다."""
        dead = [t for t in _TITLES if not match_signals(t)]
        assert not dead, (
            f"{len(dead)}종이 더 이상 신호를 내지 않는다 (총 "
            f"{sum(_WEIGHT[t] for t in dead)}건). 예: {dead[:5]}"
        )


class TestSignalIntegrity:
    def test_모든_신호_키가_taxonomy에_매핑된다(self):
        for s in SIGNAL_TYPES:
            tids = SIGNAL_KEY_TO_TAXONOMY.get(s["key"])
            assert tids, f"{s['key']} 에 taxonomy 매핑이 없다"
            for t in tids:
                assert t in TAXONOMY, f"{s['key']} → {t} 가 TAXONOMY에 없다"

    def test_키워드가_다른_신호를_통째로_삼키지_않는다(self):
        """한 신호의 키워드가 다른 신호의 키워드를 부분 문자열로 포함하면
        후자는 영원히 단독으로 관찰되지 않는다(설계 사고의 전형)."""
        collisions = []
        for a in SIGNAL_TYPES:
            for b in SIGNAL_TYPES:
                if a["key"] >= b["key"]:
                    continue
                for ka in a["keywords"]:
                    for kb in b["keywords"]:
                        if ka != kb and (ka in kb or kb in ka):
                            collisions.append((a["key"], ka, b["key"], kb))
        # 알려진 포함 관계 — 각 항목에 "왜 지금은 문제가 아닌가"를 적는다.
        # 새 충돌이 생기면 이 테스트가 실패하고, 여기에 근거를 적거나
        # 키워드를 고쳐야 한다. 2026-08-22 90일 실측 기준.
        allowed = {
            # 의도된 계층 — 넓은 키워드가 좁은 것을 포함(같은 신호 안)
            ("3PCA", "유상증자", "3PCA", "유상증자결정"),
            ("3PCA", "유상증자", "RIGHTS_UNDER", "유상증자미달"),
            # 2026-08-22: CB_REPAY·BUYBACK_NEG의 키워드는 1년 실측 0건 확인 후
            # 제거했다(NON_TITLE_SIGNALS). 그 두 충돌은 이제 존재하지 않는다.
            # 아래 3건은 한쪽이 1년 발화 0건이라 실제 충돌이 없다 — 2차 정리 대상.
            ("EB", "EB배임", "EMBEZZLE", "배임"),                  # EB배임 0건
            ("3PCA", "제3자배정", "EB", "제3자배정교환채"),          # 둘 다 0건
            ("AUDIT", "계속기업불확실성", "GOING_CONCERN", "계속기업불확실"),  # 둘 다 0건
        }
        unexpected = [c for c in collisions if c not in allowed]
        assert not unexpected, f"예상 밖 키워드 포함 관계: {unexpected[:8]}"

    def test_한_제목이_같은_신호를_두_번_내지_않는다(self):
        for t in _TITLES:
            keys = [s["key"] for s in match_signals(t)]
            assert len(keys) == len(set(keys)), t


class TestQualificationSanity:
    def test_강등된_신호에는_반드시_사유가_있다(self):
        for t in _TITLES:
            sigs = match_signals(t)
            for s, q in zip(sigs, qualify_signals(sigs, parse_report_name(t), {})):
                if q.tier != TIER_OBSERVED:
                    assert q.reason, f"{t} / {s['key']} 강등인데 사유가 없다"

    def test_observed_신호에는_강등_사유가_없다(self):
        for t in _TITLES:
            for s, q in _observed(t):
                assert not q.reason, f"{t} / {s['key']} observed인데 사유가 있다"

    def test_라벨이_비어있지_않다(self):
        for t in _TITLES:
            sigs = match_signals(t)
            for s, q in zip(sigs, qualify_signals(sigs, parse_report_name(t), {})):
                assert q.label.strip(), f"{t} / {s['key']} 라벨이 비었다"


class TestDirectionNoteCoverage:
    """되사기·소각 제목에 방향 안내가 빠짐없이 붙는지 — 코퍼스 전수."""

    RETIRE_MARKS = ("만기전사채취득", "만기전취득", "소각", "사채매도")
    BOND_KEYS = {"CB_BW", "EB", "RCPS"}

    def test_되사기_제목에_방향_안내가_붙는다(self):
        missing = []
        for t in _TITLES:
            flat = t.replace(" ", "")
            if not any(m in flat for m in self.RETIRE_MARKS):
                continue
            for s, q in _observed(t):
                if s["key"] in self.BOND_KEYS and not q.note:
                    missing.append((s["key"], t, _WEIGHT[t]))
        assert not missing, (
            f"{len(missing)}종에 방향 안내가 없다 "
            f"(총 {sum(m[2] for m in missing)}건): {missing[:5]}"
        )

    def test_발행_제목에는_방향_안내가_붙지_않는다(self):
        wrong = []
        for t in _TITLES:
            flat = t.replace(" ", "")
            if any(m in flat for m in self.RETIRE_MARKS) or "재매각" in flat:
                continue
            for s, q in _observed(t):
                if s["key"] in self.BOND_KEYS and q.note:
                    wrong.append((s["key"], t))
        assert not wrong, f"발행 제목에 방향 안내가 붙었다: {wrong[:5]}"


class TestKnownFalsePositiveGuards:
    """과거에 실제로 터진 오탐이 되살아나지 않는지 — 코퍼스에서 확인."""

    def test_정례적_매매정지가_조회공시로_잡히지_않는다(self):
        """2026-08-21 실사고 — 한탑 002680."""
        bad = [t for t in _TITLES
               if "매매거래정지" in t.replace(" ", "")
               and "INQUIRY" in [s["key"] for s in match_signals(t)]
               and "조회공시" not in t.replace(" ", "")]
        assert not bad, bad[:5]

    def test_펀드명_미달러가_관리종목으로_잡히지_않는다(self):
        """'미달' 단독 키워드를 쓰면 집합투자증권 펀드명이 걸린다."""
        bad = [t for t in _TITLES
               if "미달러" in t.replace(" ", "")
               and "WATCH_ISSUE" in [s["key"] for s in match_signals(t)]]
        assert not bad, bad[:5]

    def test_상장예비심사는_상장폐지_신호가_아니다(self):
        bad = [t for t in _TITLES
               if "상장예비심사" in t.replace(" ", "")
               and "DELISTING_RISK" in [s["key"] for s in match_signals(t)]]
        assert not bad, bad[:5]
