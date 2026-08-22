"""관찰 우선순위 — "무엇부터 보면 되는가"의 순서 (2026-08-22).

v1.14.0은 뷰어 배지를 taxonomy severity에서 파생하면서 예외 목록
(`_CAUTION_FORCE_KEYS`)으로 뒤집힘을 우회했다. 이 모듈이 검증하는 것은 그
우회를 걷어내고 축 자체를 분리한 뒤의 계약이다.

severity는 이 레포에서 "얼마나 심각한가"가 아니라 사실상 "점수를 매기느냐"로
쓰여 왔다(OBSERVATION = base_score 0). 그 겸직이 두 방향으로 깨졌다:
  ① 무점수 신호가 낮은 우선순위로 내려앉음 — 「상장폐지 결정」이 '참고'
  ② severity가 HIGH라는 이유만으로 양면적 신호에 배지가 붙음 —
     `RELATED_PARTY`·`ASSET_TRANSFER`는 헤드라인 승격이 막혀 있는데 '주의'

**점수는 여전히 매기지 않는다**(v0.8.5). 이 축은 표시 순서일 뿐이다.
"""
import importlib.util
import json
import pathlib

import pytest

from dart_risk_mcp.core.signals import (
    AMBIGUOUS_SIGNAL_KEYS,
    NON_TITLE_SIGNALS,
    SIGNAL_TYPES,
    _PRIORITY_CONTEXT,
    _PRIORITY_FIRST,
    match_signals,
    observation_priority,
)
from dart_risk_mcp.core.qualifiers import parse_report_name, qualify_signals

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_JSON = _ROOT / "docs" / "tool" / "signals-data.json"
_CORPUS = _ROOT / "tests" / "fixtures" / "corpus" / "signal_titles_365d.json"

_spec = importlib.util.spec_from_file_location(
    "export_tool_data", _ROOT / "scripts" / "export_tool_data.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


@pytest.fixture(scope="module")
def exported():
    return {s["key"]: s for s in json.loads(_JSON.read_text(encoding="utf-8"))["signals"]}


class TestAxis:
    def test_세_값만_쓴다(self):
        vals = {observation_priority(s["key"]) for s in SIGNAL_TYPES}
        assert vals <= {"first", "watch", "context"}

    def test_기본값은_watch다(self):
        """새 신호가 들어올 때 조용히 first로 승격되지 않아야 한다."""
        assert observation_priority("존재하지_않는_신호") == "watch"

    def test_두_목록은_겹치지_않는다(self):
        assert not (_PRIORITY_FIRST & _PRIORITY_CONTEXT)


class TestFirst:
    def test_퇴출_절차가_first다(self, exported):
        """v1.14.0에서 예외 목록으로 우회했던 것이 이제 축 자체로 표현된다."""
        for key in ("DELISTING_RISK", "WATCH_ISSUE", "DISTRESS_EVENT"):
            assert observation_priority(key) == "first", key
            assert exported[key]["priority"] == "first", key

    def test_회계_신뢰성이_깨진_사실이_first다(self, exported):
        for key in ("AUDIT", "GOING_CONCERN"):
            assert exported[key]["priority"] == "first", key

    def test_부실_단계가_first다(self, exported):
        for key in ("INSOLVENCY", "DEBT_RESTR", "CAPITAL_IMPAIRMENT"):
            assert exported[key]["priority"] == "first", key


class TestContext:
    def test_원문_확인이_필요한_신호는_context다(self, exported):
        """제목만으로 정상·이상이 갈리지 않는 것들 — 감사표에 확인 계층이 있다."""
        for key in ("FUND_OUTFLOW", "ACQ_REVIEW", "ASSET_TRANSFER",
                    "RELATED_PARTY", "EARNINGS_SHOCK", "TREASURY"):
            assert exported[key]["priority"] == "context", key

    def test_severity가_HIGH여도_context일_수_있다(self, exported):
        """옛 규칙이 '주의'로 올리던 자기모순을 고정한다.

        RELATED_PARTY(4.2 HIGH)·ASSET_TRANSFER(5.3 HIGH)는 헤드라인 승격이
        막혀 있는데(AMBIGUOUS) 배지는 '주의'로 나갔다.
        """
        for key in ("RELATED_PARTY", "ASSET_TRANSFER"):
            assert key in AMBIGUOUS_SIGNAL_KEYS, key
            assert exported[key]["priority"] == "context", key


class TestRelationToHeadline:
    def test_헤드라인_차단_신호는_모두_context다(self):
        """포함 관계만 강제하고 두 개념을 합치지는 않는다.

        헤드라인이 못 되는 신호가 관찰 순서에서 first로 올라가면 모순이지만,
        반대 방향(context인데 헤드라인 가능)은 각자 판단한다 — 예컨대
        DIVIDEND_DRAIN은 이미 판정을 거친 파생 플래그라 헤드라인이 될 수 있다.
        """
        assert AMBIGUOUS_SIGNAL_KEYS <= _PRIORITY_CONTEXT

    def test_두_집합을_합치지_않았다(self):
        """합치면 헤드라인 정책이 조용히 바뀐다(실측 7종 → 17종)."""
        assert len(AMBIGUOUS_SIGNAL_KEYS) < len(_PRIORITY_CONTEXT)


class TestDiscrimination:
    def test_first가_관찰_공시의_소수다(self):
        """옛 배지는 56.3%에 붙어 변별력이 없었다. 절반을 넘으면 기본값이다."""
        corpus = json.loads(_CORPUS.read_text(encoding="utf-8"))
        total = first = 0
        for row in corpus["titles"]:
            obs = [q for q in qualify_signals(match_signals(row["nm"]),
                                              parse_report_name(row["nm"]))
                   if q.tier == "observed"]
            if not obs:
                continue
            total += row["n"]
            if any(observation_priority(q.key) == "first" for q in obs):
                first += row["n"]
        assert total > 2000, "코퍼스가 너무 작다"
        share = first / total
        assert 0.05 <= share <= 0.25, f"first 비중 {share:.1%} — 재분류 검토"


class TestNoScoreLeak:
    def test_severity_원값은_여전히_미노출이다(self):
        raw = _JSON.read_text(encoding="utf-8")
        for banned in ("CRITICAL", "OBSERVATION", "base_score", "severity"):
            assert banned not in raw, banned

    def test_caution_필드는_사라졌다(self, exported):
        """severity 파생 배지는 이 축으로 대체됐다 — 두 개념을 함께 두지 않는다."""
        for s in exported.values():
            assert "caution" not in s

    def test_우선순위는_점수가_아니다(self):
        """정렬·집계·가산에 쓰지 않는다는 계약 — 값이 문자열이라 산술이 불가능하다."""
        for s in SIGNAL_TYPES:
            assert isinstance(observation_priority(s["key"]), str)


class TestCoverage:
    def test_모든_신호가_분류된다(self, exported):
        assert len(exported) == len(SIGNAL_TYPES)
        for s in SIGNAL_TYPES:
            assert exported[s["key"]]["priority"] == observation_priority(s["key"])

    def test_제목_미발화_신호는_배지에_영향이_없다(self):
        """NON_TITLE_SIGNALS는 관찰되지 않으므로 분류는 기록일 뿐이다."""
        for key in _PRIORITY_FIRST:
            if key in NON_TITLE_SIGNALS:
                assert key in ("ASSET_SPIRAL", "BUYBACK_NEG"), (
                    f"{key}를 first로 둔 근거를 주석에 남겨라"
                )
