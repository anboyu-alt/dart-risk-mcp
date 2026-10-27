"""BOARD_CONFLICT 신호 + taxonomy 4.5 등록 (구조화 파생 신호 — 제목 키워드 없음).

`check_board_conflict`가 의결표·임원현황을 대조해 겸직이 확인될 때만 붙는 신호다.
어느 패턴에도 넣지 않는다(패턴 발화 조건 +0) — 1.8 선례와 같은 전제.
"""
import json
import pathlib
import re

from dart_risk_mcp.core.explain import FLAG_PROSE
from dart_risk_mcp.core.signals import (
    AMBIGUOUS_SIGNAL_KEYS, NON_TITLE_SIGNALS, SIGNAL_KEY_TO_TAXONOMY,
    SIGNAL_TYPES, match_signals, observation_priority,
)
from dart_risk_mcp.core.taxonomy import (
    CROSS_SIGNAL_PATTERNS, TAXONOMY, find_pattern_overlaps,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LABEL = "이사회 결의 참여 이사의 상대방·대상회사 겸직"


def test_신호가_신호표에_있다():
    row = next(s for s in SIGNAL_TYPES if s["key"] == "BOARD_CONFLICT")
    assert row["label"] == _LABEL
    assert row["score"] == 0
    assert row["keywords"] == []


def test_제목으로는_발화하지_않는다():
    assert not [m for m in match_signals("이사회결의 겸직 거래") if m["key"] == "BOARD_CONFLICT"]


def test_매핑이_4_5_하나다():
    assert SIGNAL_KEY_TO_TAXONOMY["BOARD_CONFLICT"] == ["4.5"]


def test_taxonomy_4_5():
    t = TAXONOMY["4.5"]
    assert t["id"] == "4.5"
    assert t["name"] == "특수관계자 거래 결의의 이사 겸직"
    assert t["base_score"] == 0
    assert t["severity"] == "OBSERVATION"
    assert t["keywords"] == ["이사회 결의", "겸직"]
    assert any("상법 제398조" in x for x in t["legal_basis"])
    assert any("제368조" in x for x in t["legal_basis"])
    assert t["field_evidence"] == []


def test_한글_라벨이_있다():
    labels = json.loads((_ROOT / "data" / "catalog" / "labels_ko.json").read_text(encoding="utf-8"))
    assert labels["4.5"]["title"]
    assert labels["4.5"]["definition"]


def test_FLAG_PROSE가_있고_판정어가_없다():
    p = FLAG_PROSE["BOARD_CONFLICT"]
    text = p["title"] + p["body"]
    for bad in ("위험", "심각", "의심", "제척 없음", "위반"):
        assert bad not in text
    # test_prose_readability._sentences 와 같은 분할 규칙
    sents = [s.strip() for s in re.split(r"(?<=[다요])\.", p["body"]) if s.strip()]
    assert len(sents) == 3
    # track_capital_structure 가 split("다.")[0] 로 첫 문장을 자르므로 첫 문장 안에 「다.」는 하나
    assert sents[0].count("다") >= 1
    assert (sents[0] + ".").count("다.") == 1

def test_4_5는_1_8의_필드를_모두_갖는다():
    assert set(TAXONOMY["4.5"]) >= set(TAXONOMY["1.8"])


def test_export에_severity가_없다():
    text = (_ROOT / "docs" / "tool" / "signals-data.json").read_text(encoding="utf-8")
    assert '"severity"' not in text


def test_단계는_심화기다():
    from dart_risk_mcp.server import _PHASE_MAP
    assert _PHASE_MAP["BOARD_CONFLICT"] == "심화기"


def test_도구는_라벨을_신호표에서_읽는다():
    src = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    assert "🎯 " + _LABEL not in src      # 리터럴로 박아 두지 않는다
    assert '"🎯 이사회' not in src


def test_기본_watch_이고_예외_집합에_없다():
    assert "BOARD_CONFLICT" not in NON_TITLE_SIGNALS
    assert "BOARD_CONFLICT" not in AMBIGUOUS_SIGNAL_KEYS
    assert observation_priority("BOARD_CONFLICT") == "watch"


def test_어느_패턴에도_4_5가_없다():
    for name, p in CROSS_SIGNAL_PATTERNS.items():
        assert "4.5" not in p["signal_sequence"], name


def test_4_5만으로는_패턴_겹침이_없다():
    assert find_pattern_overlaps({"4.5"}) == []
