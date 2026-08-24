"""한 신호가 **서로 반대 방향**의 제목을 함께 잡으면 안내가 있어야 한다.

이번 세션에서 같은 뿌리의 결함을 다섯 번 고쳤다.

| 신호 | 대립 | 어떻게 틀렸나 |
|---|---|---|
| `CB_BW`·`EB`·`RCPS` | 발행↔소각·만기전취득 | 해설이 "발행입니다"라 단정 |
| `REVERSE_SPLIT` | 감자↔병합 | 해설이 병합만 설명(45%가 감자) |
| `RELATED_PARTY` | 받음↔줌 | 해설이 "받아온 공시"라 단정(221건이 나감) |
| `TREASURY` | 취득↔신탁계약해지 | 해설이 "취득·처분"(526건이 신탁) |
| `DEBT_RESTR` | 받음↔줌 | 해설이 워크아웃을 설명(전부 채무면제) |

매번 리포트를 읽다 하나씩 찾았다. 이 파일은 그 찾기를 **자동화**한다 —
방향 대립쌍을 정의하고, 관찰 제목이 양쪽에 걸치는 신호에 `DIRECTION_NOTES`가
있는지 코퍼스로 검사한다. 새 키워드가 반대 방향을 삼키면 여기서 걸린다.

⚠ **마커는 부분 문자열이라 오탐이 난다** — 「신주**인수**권」이 '인수'에,
「가**처분**」이 '처분'에 걸린다. 그래서 그 축은 예외로 적어 둔다. 예외를
늘릴 때는 왜 오탐인지 함께 적을 것.
"""
import json
import pathlib
from collections import defaultdict

import pytest

from dart_risk_mcp.core.qualifiers import (
    DIRECTION_NOTES, TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import NON_TITLE_SIGNALS, match_signals

# (A쪽 마커, B쪽 마커, 축 이름)
AXES = [
    (("체결", "설정"), ("해지", "해제", "취소", "철회", "중단"), "체결↔해지"),
    (("취득", "매입", "인수"), ("처분", "매도", "매각", "양도"), "취득↔처분"),
    (("양수",), ("양도",), "양수↔양도"),
    (("으로부터", "받은"), ("에대한", "에게"), "받음↔줌"),
    (("발행",), ("소각", "만기전취득", "상환"), "발행↔소멸"),
    (("개시", "신청"), ("종결", "폐지", "취하"), "개시↔종료"),
]

# 마커 부분 문자열 오탐 — (신호, 축): 사유
KNOWN_FALSE_POSITIVES = {
    ("DELISTING_RISK", "취득↔처분"):
        "「신주인수권행사기간만료」의 '인수'와 「가처분」의 '처분'이 걸린다",
    ("INQUIRY", "취득↔처분"):
        "「타법인인수설」의 '인수'와 「가처분결정설」의 '처분'이 걸린다",
    ("MGMT_DISPUTE", "개시↔종료"):
        "소 취하 1건뿐 — 분쟁이 끝난 사실도 관찰 대상이라 안내가 필요 없다",
}

_CORPUS = (pathlib.Path(__file__).parent / "fixtures" / "corpus"
           / "signal_titles_365d.json")


def _observed():
    rows = json.loads(_CORPUS.read_text(encoding="utf-8"))["titles"]
    out = defaultdict(dict)
    for t in rows:
        nm, n = t["nm"], t["n"]
        sigs = match_signals(nm)
        for s, q in zip(sigs, qualify_signals(sigs, parse_report_name(nm), {})):
            if q.tier == TIER_OBSERVED:
                out[s["key"]][nm.replace(" ", "")] = n
    return out


_OBSERVED = _observed()


def _split(titles, a_marks, b_marks):
    a = {t: n for t, n in titles.items() if any(m in t for m in a_marks)}
    b = {t: n for t, n in titles.items() if any(m in t for m in b_marks)}
    both = set(a) & set(b)          # 한 제목에 양쪽이 다 있으면 대립이 아니다
    return ({t: n for t, n in a.items() if t not in both},
            {t: n for t, n in b.items() if t not in both})


CASES = [(k, ax) for k in _OBSERVED if k not in NON_TITLE_SIGNALS
         for *_, ax in AXES]


@pytest.mark.parametrize("key,axis", CASES, ids=lambda v: str(v))
def test_방향이_갈리면_안내가_있다(key, axis):
    a_marks, b_marks, _ = next(x for x in AXES if x[2] == axis)
    a, b = _split(_OBSERVED[key], a_marks, b_marks)
    if not a or not b:
        pytest.skip("이 축에서 갈리지 않는다")
    if (key, axis) in KNOWN_FALSE_POSITIVES:
        pytest.skip(KNOWN_FALSE_POSITIVES[(key, axis)])
    assert key in DIRECTION_NOTES, (
        f"{key}가 {axis} 양쪽을 잡는데(A {sum(a.values()):,}건 / "
        f"B {sum(b.values()):,}건) 방향 안내가 없다. "
        f"예: A={list(a)[:1]} B={list(b)[:1]}"
    )


@pytest.mark.parametrize("key", sorted(DIRECTION_NOTES))
def test_안내가_실제로_어딘가에_붙는다(key):
    """쓰이지 않는 안내는 규칙이 낡았다는 뜻이다."""
    if key not in _OBSERVED:
        pytest.skip("이 코퍼스에서 관찰되지 않는 신호")
    rule = DIRECTION_NOTES[key]
    hit = [t for t in _OBSERVED[key] if any(m in t for m in rule["markers"])]
    assert hit, f"{key}: 마커 {rule['markers']}가 1년 코퍼스에서 0건"


def test_안내가_다수쪽에_붙지_않는다():
    """모든 줄에 붙으면 안내가 아니라 기본값이다(#259와 같은 계산)."""
    for key, rule in DIRECTION_NOTES.items():
        titles = _OBSERVED.get(key)
        if not titles:
            continue
        total = sum(titles.values())
        noted = sum(n for t, n in titles.items()
                    if any(m in t for m in rule["markers"]))
        assert noted < total, f"{key}: 관찰 전부에 안내가 붙는다"


def test_이번_감사에서_고친_다섯이_모두_덮인다():
    """기록을 코드로 고정 — 하나라도 빠지면 서술을 갱신해야 한다."""
    for key in ("CB_BW", "EB", "RCPS", "TREASURY", "RELATED_PARTY", "DEBT_RESTR"):
        assert key in DIRECTION_NOTES, key
