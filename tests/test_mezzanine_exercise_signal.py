"""메자닌 **행사**(실제 희석) 신호와 taxonomy 1.8을 고정한다.

## 왜 신설했나 — 이 라운드에서 taxonomy를 새로 만든 유일한 건

이 도구는 메자닌 **발행**(제목)과 **전환 실적**(증자·감자 현황 원장)을 각각
보는데, **그 사이의 공시 기록**이 신호에서 빠져 있었다. 「전환청구권행사」는
**기존 주주가 실제로 희석된 시점**이다.

1년 전수(271,141건 · 절단일 0, 정정 제외 228,492건)에서 **735건 / 304개사가
무신호**였다.

    전환청구권행사                      522
    전환청구권ㆍ신주인수권ㆍ교환청구권행사      95
    신주인수권행사                        47
    교환청구권행사                        43
    전환주식의전환청구권행사                 23
    기타경영사항(…신주인수권행사)              5

기존 `1.1`~`1.7` 어디에도 맞지 않는다 — `1.1`은 가액 **조정**이고 `1.4` RCPS는
발행 **조건**이지 행사가 아니다(카테고리 1·2 전수 확인). **그래서 `1.8`을
신설했다.** 위험 목록 10번 B가 「새 taxonomy가 필요하다」로 남겨 둔 자리다.

## 무판정 설계 (v0.8.5)

`base_score 0 · OBSERVATION`(`8.5` 선례)이고 **어느 패턴에도 넣지 않았다** —
패턴 발화 조건을 바꾸지 않는 것이 이 신설의 전제였다(전 패턴 영향 **+0** 실측).
`AMBIGUOUS_SIGNAL_KEYS`·`_PRIORITY_CONTEXT`에 넣어 헤드라인 승격도 막았다.
**행사 자체는 정상적인 계약 이행이기도 하다** — 전환은 갚아야 할 사채가 자본으로
바뀌는 것이라 방향이 하나로 정해지지 않는다.

## 함정 — 「신주인수권행사」를 그대로 쓰면 안 된다

그러면 「신주인수권**행사**가액의조정」 160건(리픽싱, v1.21.24에서 `CB_BW`가
잡게 한 것)이 함께 걸려 **조정을 행사라고 잘못 적는다**. 화면이 회사에 대해
거짓을 말하는 것이라 오탐 중에서도 나쁜 쪽이다.

뒤 3글자를 실측하니 경계가 깨끗했다.

    가액ㆍ  127      가액의  33      (공백)  47      )  5

공백형·괄호형 둘로 좁히니 **넓은 키워드와 동일하게 735건**을 잡으면서 리픽싱
159건을 배제한다(실측 차이 **0건**).

⚠ **알려진 한계**: 공백형은 DART가 제목 뒤에 붙이는 여백에 기댄다. 1년 전수
47건은 전부 여백이 있었지만, 여백 없는 제목이 오면 놓친다 — **잘못 붙이는
것보다 놓치는 편이 낫다**고 판단했다.
"""
import pathlib

import pytest

from dart_risk_mcp.core.catalog import taxonomy_label_ko
from dart_risk_mcp.core.explain import SIGNAL_PROSE
from dart_risk_mcp.core.qualifiers import parse_report_name, qualify_signals
from dart_risk_mcp.core.signals import (
    AMBIGUOUS_SIGNAL_KEYS, SIGNAL_KEY_TO_TAXONOMY, SIGNAL_TYPES,
    match_signals, observation_priority,
)
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS, TAXONOMY

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_KEY = "MEZZ_EXERCISE"


@pytest.mark.parametrize("title", [
    # 실측 제목(여백은 DART 원문 그대로)
    "전환청구권행사              ",
    "전환청구권행사              (제1회차)",
    "전환청구권ㆍ신주인수권ㆍ교환청구권행사              ",
    "전환주식의전환청구권행사              ",
    "교환청구권행사              ",
    "교환청구권행사              (제1회차)",
    "신주인수권행사              (제13회차)",
    "기타경영사항(자율공시)              (상장주관사의 신주인수권행사)",
    "기타경영사항(자율공시)              (신주인수권행사)",
])
def test_행사가_잡힌다(title):
    assert _KEY in [m["key"] for m in match_signals(title)], f"무신호: {title!r}"


@pytest.mark.parametrize("title", [
    # ⚠ 리픽싱 — **행사가 아니다.** 붙으면 화면이 거짓을 말한다.
    "전환가액ㆍ신주인수권행사가액ㆍ교환가액의조정(안내공시)",
    "신주인수권행사가액의조정",
    "신주인수권행사가액의조정              (제11회차)",
])
def test_리픽싱에는_붙지_않는다(title):
    keys = [m["key"] for m in match_signals(title)]
    assert _KEY not in keys, (
        f"조정을 행사로 잘못 적는다: {title!r} → {keys}\n"
        "키워드에 「신주인수권행사」(공백 없는 형태)를 넣지 않았는지 확인하라.")
    assert "CB_BW" in keys, "리픽싱 신호까지 사라졌다"


def test_taxonomy_1_8이_있고_무점수다():
    t = TAXONOMY["1.8"]
    assert t["severity"] == "OBSERVATION"
    assert t["base_score"] == 0, "점수를 매기면 v0.8.5 원칙을 어긴다"
    assert t["category"] == TAXONOMY["1.1"]["category"], "카테고리 1에 있어야 한다"
    assert SIGNAL_KEY_TO_TAXONOMY[_KEY] == ["1.8"]


def test_어느_패턴에도_쓰이지_않는다():
    """패턴 발화 조건을 바꾸지 않는 것이 이 신설의 전제였다(실측 +0)."""
    used = {t for spec in CROSS_SIGNAL_PATTERNS.values()
            for t in spec["signal_sequence"]}
    assert "1.8" not in used, (
        "1.8이 패턴에 들어갔다 — 그러면 발화 조건이 바뀐다. "
        "전 패턴 영향을 다시 재고 위험 목록 10번을 갱신하라.")


def test_헤드라인으로_승격되지_않는다():
    assert observation_priority(_KEY) == "context"
    assert _KEY in AMBIGUOUS_SIGNAL_KEYS


def test_한글_라벨과_해설이_있다():
    label = taxonomy_label_ko("1.8")
    assert label and label != "1.8", "labels_ko.json에 1.8이 없다"
    assert "행사" in label
    prose = SIGNAL_PROSE.get(_KEY, "")
    assert prose, "해설이 없다"
    # 무판정 — 단정 어휘를 쓰지 않는다
    for word in ("위험합니다", "의심됩니다", "고위험", "매우 위험"):
        assert word not in prose, f"판정 어휘: {word}"
    assert "정상적인 계약 이행" in prose, "양면성 고지가 사라졌다"


@pytest.mark.parametrize("title", [
    "전환청구권행사              ",
    "교환청구권행사              ",
    "신주인수권행사              (제13회차)",
])
def test_강등되지_않는다(title):
    """전수 735건이 100% observed였다 — 강등되면 이득이 없다."""
    q = qualify_signals(match_signals(title), parse_report_name(title))
    assert q and all(i.tier == "observed" for i in q), \
        f"강등됐다: {[(i.tier, i.reason) for i in q]}"


def test_키워드가_실측_경계를_유지한다():
    kws = next(s["keywords"] for s in SIGNAL_TYPES if s["key"] == _KEY)
    assert "신주인수권행사" not in kws, (
        "공백 없는 형태가 들어왔다 — 리픽싱 160건을 삼킨다")
    assert "신주인수권행사 " in kws and "신주인수권행사)" in kws
    assert "전환청구권행사" in kws and "교환청구권행사" in kws


def test_위험_목록에_판단_근거가_남아_있다():
    doc = (_ROOT / "docs" / "DEFERRED-DECISIONS.md").read_text(encoding="utf-8")
    assert "## 10." in doc
    assert "1.8" in doc, "신설한 taxonomy id가 기록에서 사라졌다"
