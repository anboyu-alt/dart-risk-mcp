"""제목으로 발화하지 않는 신호 정리 (2026-08-22).

1년 코퍼스(고유 공시 201,361건, 정정 제외 163,429건)에서 키워드가 **전부
0건**인 신호 9종을 정리했다. 조회는 되는데 실제로는 한 번도 안 잡히는
신호를 설명만 보여주면 "이 도구가 이걸 탐지한다"는 인상을 준다.

세 부류로 갈린다:
  · structured — 구조화 API·파생 탐지기가 생성(제목 경로가 아님)
  · covered    — 같은 공시를 다른 신호가 이미 잡음
  · absent     — 개념 자체가 DART 제목에 없음(조합·시계열로만 성립)
"""
import pytest

from dart_risk_mcp.core.signals import (
    NON_TITLE_SIGNALS,
    SIGNAL_KEY_TO_TAXONOMY,
    SIGNAL_TYPES,
    match_signals,
)
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS, TAXONOMY

_BY_KEY = {s["key"]: s for s in SIGNAL_TYPES}


class TestKeywordsRemoved:
    @pytest.mark.parametrize("key", sorted(NON_TITLE_SIGNALS))
    def test_키워드가_비어있다(self, key):
        """되살리려면 CLAUDE.md 관례대로 시장 실측 근거부터 붙여야 한다."""
        assert _BY_KEY[key]["keywords"] == [], key

    @pytest.mark.parametrize("title", [
        "주요사항보고서(전환사채권발행결정)",
        "전환사채(해외전환사채포함)발행후만기전사채취득",
        "주요사항보고서(자기주식취득결정)",
        "주주총회소집공고",
        "의결권대리행사권유참고서류",
        "주요사항보고서(회사합병결정)",
        "감자결정",
    ])
    def test_실제_공시가_사장_신호로_잡히지_않는다(self, title):
        """제거 전에도 0건이었으므로 동작 변화가 없어야 한다."""
        keys = {s["key"] for s in match_signals(title)}
        assert not (keys & set(NON_TITLE_SIGNALS)), (title, keys)


class TestRouteClassification:
    def test_세_부류만_쓴다(self):
        assert set(NON_TITLE_SIGNALS.values()) <= {"structured", "covered", "absent"}

    def test_구조화_경로는_CB_ROLLOVER뿐(self):
        """detect_debt_rollover가 문자열 "CB_ROLLOVER"를 만든다 —
        키를 지우면 track_capital_structure가 깨진다."""
        structured = [k for k, v in NON_TITLE_SIGNALS.items() if v == "structured"]
        assert structured == ["CB_ROLLOVER"]

    def test_모든_키가_실존_신호다(self):
        for k in NON_TITLE_SIGNALS:
            assert k in _BY_KEY, k

    def test_taxonomy_매핑은_유지된다(self):
        """패턴·카탈로그가 이 taxonomy를 참조하므로 매핑은 지우지 않는다."""
        for k in NON_TITLE_SIGNALS:
            tids = SIGNAL_KEY_TO_TAXONOMY.get(k)
            assert tids, k
            for t in tids:
                assert t in TAXONOMY, (k, t)


class TestPatternImpact:
    """**두** 패턴이 관찰 불가능한 taxonomy를 요구한다 — 구조적으로 전부 일치 불가.

    1년 실측: 창업주 퇴장 겹침 284곳·전부일치 0곳 · 무자본 M&A 195곳/0곳.
    시장에 사례가 없어서가 아니라 요구 신호 하나가 관찰될 수 없기 때문이다.

    `CB_ROLLOVER`(1.5)·`DISTRESS_MA`(5.4)는 **다른 신호가 같은 taxonomy를 켜므로**
    (1.5←CB_BW, 5.4←MGMT) debt_spiral·fake_new_biz는 막혀 있지 않다 —
    아래 두 테스트가 이 구분을 기계적으로 지킨다.
    """

    EXPECTED = {
        "zombie_ma": ("CB_REPAY", "1.2"),
        "founder_fade": ("MEETING_VIOL", "4.1"),
    }
    # 사장 신호가 담당하지만 다른 신호가 대신 켜 주는 것 — 패턴은 살아 있다
    COVERED_ELSEWHERE = {
        "CB_ROLLOVER": ("1.5", "CB_BW"),
        "DISTRESS_MA": ("5.4", "MGMT"),
    }

    @pytest.mark.parametrize("key,pair", sorted(COVERED_ELSEWHERE.items()))
    def test_다른_신호가_켜주는_taxonomy는_막히지_않는다(self, key, pair):
        tid, other = pair
        assert tid in SIGNAL_KEY_TO_TAXONOMY[key]
        assert tid in SIGNAL_KEY_TO_TAXONOMY[other]
        assert _BY_KEY[other]["keywords"], f"{other} 도 죽으면 서술을 갱신해야 한다"

    @pytest.mark.parametrize("pattern,pair", sorted(EXPECTED.items()))
    def test_패턴이_관찰불가_taxonomy를_요구한다(self, pattern, pair):
        key, tid = pair
        assert key in NON_TITLE_SIGNALS
        assert tid in SIGNAL_KEY_TO_TAXONOMY[key]
        assert tid in CROSS_SIGNAL_PATTERNS[pattern]["signal_sequence"]

    def test_그_taxonomy를_담당하는_다른_신호가_없다(self):
        """다른 신호가 같은 taxonomy를 켜 준다면 패턴이 살아난다 —
        이 테스트가 깨지면 위 '전부 일치 불가' 서술을 갱신해야 한다."""
        for _, (key, tid) in self.EXPECTED.items():
            others = [
                s["key"] for s in SIGNAL_TYPES
                if s["key"] != key
                and tid in SIGNAL_KEY_TO_TAXONOMY.get(s["key"], [])
                and s["keywords"]
            ]
            assert not others, f"{tid}를 {others}가 켠다 — 서술 갱신 필요"


class TestPresetsCleaned:
    def test_프리셋에_사장_신호가_없다(self):
        from dart_risk_mcp.server import _PRESET_TO_SIGNALS

        for preset, keys in _PRESET_TO_SIGNALS.items():
            leftover = [k for k in keys if k in NON_TITLE_SIGNALS]
            assert not leftover, f"{preset} 에 {leftover}"


class TestFindRiskPrecedentsHonesty:
    @pytest.mark.parametrize("key,marker", [
        ("CB_ROLLOVER", "구조화 데이터"),
        ("CB_REPAY", "다른 신호가 잡습니다"),
        ("MEETING_VIOL", "DART 공시 제목에 등장하지 않습니다"),
    ])
    def test_조회하면_발화하지_않는다는_사실을_알린다(self, key, marker):
        from dart_risk_mcp.server import find_risk_precedents

        out = find_risk_precedents([key])
        assert marker in out, out[:400]

    def test_살아있는_신호에는_안내가_붙지_않는다(self):
        from dart_risk_mcp.server import find_risk_precedents

        out = find_risk_precedents(["CB_BW"])
        assert "제목 스캔에서" not in out
