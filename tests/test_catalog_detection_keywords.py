"""카탈로그가 「탐지 키워드」로 **검색하지 않는 말**을 싣지 않는지 잠근다.

#293의 매핑 감사에서 `ASSET_TRANSFER→5.3`의 0%가 "taxonomy 쪽 키워드만 옛
개념어로 남은 것"임을 확인했고, 그 실을 당겨 보니 훨씬 넓었다(2026-08-25).

## 실측 (1년 코퍼스)

`TAXONOMY[*]["keywords"]` **217개 중 166개(76%)**가 신호 제목에 0건이고,
**17개 taxonomy는 전멸**이다:

    1.2 1.5 1.6 1.7 2.3 2.5 3.2 3.3 4.2 5.3 5.6 6.1 6.2 6.3 7.1 7.3 8.3

예) 1.5 = 「돌려막기, CB돌려막기, EB돌려막기, 리파이낸싱, 차환, 연속CB발행,
연속차입」 — DART 제목에 **하나도 없다**. 실제로는 `CB_BW`
(전환사채권발행결정 등)와 구조화 탐지 `CB_ROLLOVER`가 켠다.

## 왜 문제인가

`match_signals`는 이 목록을 **쓰지 않는다** — `SIGNAL_TYPES`의 키워드로
매칭한다. 그런데 `render.py`가 이 목록을 「### **탐지** 키워드」라는 제목으로
싣고, 그 MD는 `load_catalog_excerpt`를 거쳐 **사용자 출력에 그대로 실린다**.
검색하지도 않는 말을 "탐지 키워드"라 부르고 있었다.

## 고친 방식

개념어를 지우지 않았다(유형을 설명하는 값이 있다) — **제목만** 사실에 맞추고,
실제로 켜는 신호와 그 신호가 찾는 **DART 실제 표기**를 위에 뒀다.

    ### 이 유형을 켜는 신호
    - **CB/BW발행** — 전환사채권발행결정, 신주인수권부사채권발행결정, …
    - **CB돌려막기** — 제목으로 발화하지 않습니다

    ### 개념어 (참고 — 도구가 검색하는 말이 아닙니다)
    돌려막기, CB돌려막기, …
"""
import json
import pathlib

import pytest

from dart_risk_mcp.core.catalog import load_catalog_excerpt
from dart_risk_mcp.core.signals import (
    NON_TITLE_SIGNALS, SIGNAL_KEY_TO_TAXONOMY, SIGNAL_LABELS,
)
from dart_risk_mcp.core.taxonomy import TAXONOMY

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MD_DIR = _ROOT / "dart_risk_mcp" / "knowledge" / "manipulation_catalog"
_CORPUS = json.loads((_ROOT / "tests" / "fixtures" / "corpus"
                      / "signal_titles_365d.json").read_text(encoding="utf-8"))


def _md_texts():
    return {p.name: p.read_text(encoding="utf-8")
            for p in _MD_DIR.glob("*.md") if p.name != "README.md"}


def test_탐지_키워드라는_제목이_없다():
    for name, txt in _md_texts().items():
        assert "### 탐지 키워드" not in txt, name


def test_개념어_제목이_검색어가_아님을_말한다():
    for name, txt in _md_texts().items():
        if "### 개념어" in txt:
            assert "도구가 검색하는 말이 아닙니다" in txt, name


def test_켜는_신호_절이_모든_파일에_있다():
    for name, txt in _md_texts().items():
        assert "### 이 유형을 켜는 신호" in txt, name


def test_발췌에도_반영된다():
    """MD만 고치고 발췌 경로가 옛 파일을 읽으면 소용이 없다."""
    ex = load_catalog_excerpt(["1.5"])
    assert "### 탐지 키워드" not in ex
    assert "이 유형을 켜는 신호" in ex
    assert SIGNAL_LABELS["CB_BW"] in ex


def test_제목으로_발화하지_않는_신호는_그렇게_적힌다():
    ex = load_catalog_excerpt(["1.5"])
    assert "제목으로 발화하지 않습니다" in ex
    assert "CB_ROLLOVER" in NON_TITLE_SIGNALS


def test_켜는_신호가_실제_매핑과_일치한다():
    """MD가 손으로 고쳐졌거나 매핑이 바뀌면 어긋난다."""
    txt = (_MD_DIR / "01_cb_debt.md").read_text(encoding="utf-8")
    owners = {SIGNAL_LABELS[k] for k, v in SIGNAL_KEY_TO_TAXONOMY.items()
              if "1.1" in v}
    body = txt[txt.index("## 1.1:"):txt.index("## 1.2:")]
    for lab in owners:
        assert lab in body, lab


@pytest.mark.parametrize("tid", ["1.5", "3.2", "5.3", "7.1"])
def test_전멸한_개념어는_여전히_실린다(tid):
    """지우지 않았다 — 유형을 설명하는 값이 있다."""
    kws = TAXONOMY[tid]["keywords"]
    ex = load_catalog_excerpt([tid])
    assert kws[0] in ex, tid


def test_노후_비율은_바뀔_수_있다():
    """비율 자체는 고정하지 않는다(코퍼스가 갱신되면 흔들린다).
    다만 **여전히 상당수가 죽어 있다**는 전제는 확인한다 — 이 전제가
    무너지면 위 문구("검색하는 말이 아닙니다")를 다시 볼 이유가 생긴다."""
    titles = [(t["nm"].replace(" ", ""), t.get("n", 1)) for t in _CORPUS["titles"]]
    dead = alive = 0
    for e in TAXONOMY.values():
        for kw in (e.get("keywords") or []):
            k = kw.replace(" ", "")
            if any(k in nm for nm, _ in titles):
                alive += 1
            else:
                dead += 1
    assert dead + alive > 100
    assert dead / (dead + alive) > 0.5, f"죽은 비율 {dead}/{dead+alive}"
