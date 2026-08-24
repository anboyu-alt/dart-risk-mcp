"""뷰어가 core의 판정·보정 라벨을 따라가는지 잠근다.

**뷰어를 실제로 띄워 SK하이닉스를 스캔해 찾았다**(2026-08-24). 네 가지가
한 화면에 있었고, 넷 다 뿌리가 같다 — 뷰어가 **신호 유형의 기본 라벨·
카테고리 문구**를 쓰고 한정층이 만든 보정을 반영하지 않았다.

| 화면 | 무엇이 나왔나 | 무엇이 맞나 |
|---|---|---|
| CAPITAL RHYTHM | "12개월 내 **3건 이상**은 관찰 조건에 해당" | core는 v1.20.10부터 **희석성** 기준 — 같은 회사에 core 미발화 / 뷰어 "해당" |
| HEAVIEST | 「교환사채(EB)**발행** ×1」 | 그 1건은 **되사기**(방향 안내가 core엔 붙는다) |
| SIGNAL COMMENTARY | 「**제3자배정**유상증자 ×2」 | SIGNAL CHAIN은 「유상증자(배정방식 미상)」 — **같은 화면에서 라벨이 갈렸다** |
| WATCH 배너 | "거래정지·상장폐지 관련·**횡령** 등 가장 무거운 유형" | 실제 관찰은 **조회공시 9건**뿐 |

⚠ 작성 중 두 번 실물에서 깨졌다 — `CUR.observed`(실제는 `observedEvents`)와
`obs`(buildResult 지역 함수). 브라우저로 확인하지 않았으면 못 봤다.
"""
import json
import pathlib
import re

import pytest

from dart_risk_mcp.core.dart_client import (
    CHURN_NON_DILUTIVE_MARKS, CHURN_RESULT_MARKS, DILUTIVE_CAPITAL_EVENTS,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
_DATA = json.loads((_ROOT / "docs" / "tool" / "signals-data.json")
                   .read_text(encoding="utf-8"))


def test_희석_분류가_뷰어에_내려간다():
    assert _DATA.get("dilutive_capital_events") == sorted(DILUTIVE_CAPITAL_EVENTS)
    assert _DATA.get("churn_result_marks") == list(CHURN_RESULT_MARKS)
    assert _DATA.get("churn_non_dilutive_marks") == list(CHURN_NON_DILUTIVE_MARKS)


def test_뷰어가_전체_카운트로_판정하지_않는다():
    """옛 문구 「12개월 내 3건 이상」은 core와 다른 답을 낸다."""
    assert "12개월 내 3건 이상은 등록 패턴" not in _HTML
    assert "cap12max >= 3" not in _HTML
    assert "function churnCounts(" in _HTML


def test_뷰어_리듬_문구가_희석성을_말한다():
    assert "희석성(증자·메자닌)" in _HTML
    assert "자사주만 자주 사고파는 것으로는" in _HTML


@pytest.mark.parametrize("fn", ["displayLabel", "commonNote", "crisisLabels",
                                "churnCounts", "isHeavySignal"])
def test_헬퍼가_존재한다(fn):
    assert re.search(r"^function " + fn + r"\(", _HTML, re.M), fn


def test_헤드라인과_커멘터리가_보정_라벨을_쓴다():
    """기본 라벨을 쓰면 SIGNAL CHAIN과 같은 화면에서 표기가 갈린다."""
    assert "esc(displayLabel(heaviest.key) || heaviest.label)" in _HTML
    assert "esc(displayLabel(s.key) || s.label)" in _HTML


def test_방향_안내를_헤드라인과_커멘터리에_붙인다():
    """「EB발행」인데 되사기 1건뿐인 경우 라벨만으로는 방향이 반대로 읽힌다."""
    assert _HTML.count("commonNote(") >= 4   # 정의 + 헤드라인 + 커멘터리(조건·본문)


def test_배너가_실제_관찰된_신호를_말한다():
    """카테고리의 최악 사례를 나열하면 조회공시뿐인 회사에도 횡령이 적힌다."""
    assert "거래정지·상장폐지 관련·횡령 등 가장 무거운 유형입니다" not in _HTML
    assert "crisisLabels(crisisEvents)" in _HTML


def test_지역_함수를_전역_헬퍼에서_쓰지_않는다():
    """`obs`는 buildResult 지역 함수다 — 밖에서 부르면 화면이 죽는다.

    실제로 그렇게 죽였다가 브라우저에서 잡았다.
    """
    for fn in ("crisisLabels", "displayLabel", "commonNote", "churnCounts"):
        m = re.search(r"^function " + fn + r"\(.*?\n\}", _HTML, re.M | re.S)
        assert m, fn
        assert not re.search(r"\bobs\(", m.group(0)), f"{fn}이 지역 함수 obs를 쓴다"


def test_export가_경로_조작_뒤에_있다():
    """앞에 두면 설치본(site-packages)의 옛 모듈을 잡는다 — 실제로 겪었다."""
    src = (_ROOT / "scripts" / "export_tool_data.py").read_text(encoding="utf-8")
    i_path = src.index("sys.path.insert")
    i_imp = src.index("CHURN_NON_DILUTIVE_MARKS")
    assert i_path < i_imp, "import가 sys.path 조작보다 앞에 있다"
