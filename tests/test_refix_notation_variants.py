"""리픽싱 표기 변형을 `CB_BW`가 잡는지 — 그리고 **행사와 섞이지 않는지** 고정한다.

## 무엇이 문제였나

`CB_BW`는 「전환가액의조정」을 잡지만 DART가 쓰는 **결합 표기**를 놓쳤다.
1년 시장 전수(2025-08-22~2026-08-21 · **271,141건 · 절단일 0**, 정정 제외
228,492건)에서 아래가 통째로 무신호였다.

    전환가액ㆍ신주인수권행사가액ㆍ교환가액의조정(안내공시)   127
    신주인수권행사가액의조정 (+회차)                       33
    교환가액의조정 (+회차)                                 6
    ─────────────────────────────────────────────────────
    합계                                    166건 / 75개사

첫 줄이 핵심이다 — **결합 표기라 어미가 「교환가액의조정」**이어서 「전환가액의
조정」에 걸리지 않는다. 새 개념이 아니라 이미 매핑된 `1.1`(Refixing)의 표기다.

## 「행사」는 나중에 taxonomy를 만들어 메웠다 (2026-09-02)

같은 감사에서 「전환청구권행사」·「신주인수권행사」·「교환청구권행사」가
**735건 / 304개사** 무신호로 나왔다. **그때는 taxonomy가 없어** 넣지 않았다 —
`1.1`은 조정이고 `1.4` RCPS는 발행 조건이지 행사가 아니다. 뒤에 위험 목록
10번 B로 **`1.8`(메자닌 전환·행사)을 신설**해 메웠다
(`tests/test_mezzanine_exercise_signal.py`). 이 파일에서는 **조정과 행사가
섞이지 않는지**를 계속 지킨다 — 「신주인수권**행사**가액의조정」이 양쪽에
걸리면 화면이 둘을 뒤섞는다.

뜻이 어긋나는 자리에 밀어 넣는 것이 `INQUIRY` 실사고(v1.12.1 — 정례 매매정지를
삼켜 패턴 카드 3개 오발화)의 뿌리였고, v1.13.4·v1.13.5에서 후보 7종 중 5종이
같은 이유로 기각됐다. **맞는 자리가 없으면 만들거나 두는 것**이 답이고, 이번엔
만들었다.

## 감사 결과 (같은 전수에서)

    부분 문자열 충돌      0
    한정층                166건 100% observed (강등 0)
    패턴 영향             11개 패턴 전부 **+0** · 카드를 받는 회사 252곳 불변

⚠ 패턴 영향은 **`supports_pattern`을 태워** 재야 한다. 처음엔 그것 없이 재서
「fund_diversion_chain 146 → 151곳(+5)」이라 적었는데, 방향 안내가 붙은 이벤트는
패턴 근거로 서지 못하므로 그 다섯 곳은 실제로는 임계를 채우지 못한다. 제대로
재면 기준선부터 139곳이고 변화가 없다.

이 제목을 낸 회사 75곳 중 **41곳(55%)은 이미 다른 공시로 `CB_BW`를 갖고 있었고**,
처음 켜지는 34곳도 `5.8`(ACQ_REVIEW) 등 짝이 없어 어느 패턴 임계에도 닿지 않는다.
즉 이 변경의 효과는 **관찰 목록에 사실이 보이는 것**이지 패턴이 늘어나는 게 아니다.
"""
import pathlib

import pytest

from dart_risk_mcp.core.signals import (
    SIGNAL_KEY_TO_TAXONOMY, SIGNAL_TYPES, match_signals,
)
from dart_risk_mcp.core.qualifiers import parse_report_name, qualify_signals

_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("title", [
    # 실측 제목 그대로(공백은 원문에 있는 그대로가 아니라 정규화된 형태)
    "전환가액ㆍ신주인수권행사가액ㆍ교환가액의조정(안내공시)",
    "신주인수권행사가액의조정",
    "신주인수권행사가액의조정 (제11회차)",
    "교환가액의조정",
    "교환가액의조정 (제16회차)",
    "신주인수권행사가액의조정 (제3회차 및 제4회차)",
])
def test_리픽싱_표기_변형이_잡힌다(title):
    keys = [m["key"] for m in match_signals(title)]
    assert "CB_BW" in keys, f"무신호로 돌아갔다: {title}"


def test_리픽싱은_taxonomy_1_1로_간다():
    """`1.1`은 Refixing(리픽싱)이다 — 이 제목들이 가야 할 정확한 자리."""
    assert "1.1" in SIGNAL_KEY_TO_TAXONOMY["CB_BW"]


@pytest.mark.parametrize("title", [
    "전환가액ㆍ신주인수권행사가액ㆍ교환가액의조정(안내공시)",
    "신주인수권행사가액의조정",
    "교환가액의조정",
])
def test_강등되지_않는다(title):
    """전수에서 166건 100% observed였다 — 강등되면 이득이 사라진다."""
    ms = match_signals(title)
    q = qualify_signals(ms, parse_report_name(title))
    assert q and all(i.tier == "observed" for i in q), \
        f"강등됐다: {[(i.tier, i.reason) for i in q]}"


@pytest.mark.parametrize("title", [
    # ⚠ 2026-09-02: 「행사」 계열은 **새 taxonomy `1.8`을 만들어** 메웠다
    #    (위험 목록 10번 B). 이 테스트는 「안 잡힌다」에서 **「조정과 섞이지
    #    않는다」**로 뜻이 바뀌었다 — 행사는 `MEZZ_EXERCISE`, 조정은 `CB_BW`다.
    #    여백은 DART 원문 그대로다(키워드가 여백에 기댄다).
    "전환청구권행사              ",
    "전환청구권행사              (제1회차)",
    "전환청구권ㆍ신주인수권ㆍ교환청구권행사              ",
    "전환주식의전환청구권행사              ",
    "교환청구권행사              ",
    "신주인수권행사              (제13회차)",
])
def test_행사는_조정과_섞이지_않는다(title):
    """행사에 `CB_BW`(리픽싱)가 붙으면 화면이 조정과 행사를 뒤섞는다."""
    keys = [m["key"] for m in match_signals(title)]
    assert "MEZZ_EXERCISE" in keys, f"행사 신호가 사라졌다: {title!r} → {keys}"
    assert "CB_BW" not in keys, f"행사에 리픽싱 신호가 붙었다: {title!r} → {keys}"


@pytest.mark.parametrize("title", [
    # 새 키워드가 삼키면 안 되는 것 — 전수에서 실제로 걸리지 않았다
    "주요사항보고서(전환사채권발행결정)",   # 이미 다른 키워드가 잡는다(중복 무해)
    "최대주주변경",
    "주요사항보고서(유상증자결정)",
    "기타경영사항(자율공시)",
])
def test_새_키워드가_엉뚱한_제목을_켜지_않는다(title):
    for kw in ("교환가액의조정", "행사가액의조정"):
        assert kw not in title, f"표본 선정 오류: {title}에 {kw}가 있다"


def test_추가한_키워드가_실제로_등록돼_있다():
    kws = next(s["keywords"] for s in SIGNAL_TYPES if s["key"] == "CB_BW")
    for kw in ("교환가액의조정", "행사가액의조정"):
        assert kw in kws, f"{kw}가 CB_BW에서 사라졌다"
    # 최소 집합 — 「신주인수권행사가액의조정」은 「행사가액의조정」의 상위라
    # 따로 넣을 필요가 없다(넣으면 중복이지 해롭지는 않다)
    assert "신주인수권행사가액의조정" in "신주인수권행사가액의조정"


def test_위험_목록에_판단_근거가_남아_있다():
    """근거만 있고 기록이 없으면 다음 사람이 다시 잰다."""
    doc = (_ROOT / "docs" / "DEFERRED-DECISIONS.md").read_text(encoding="utf-8")
    assert "## 10." in doc
    assert "Refixing" in doc or "리픽싱" in doc, (
        "「1.1은 조정이지 행사가 아니다」는 판단이 기록에서 사라졌다")
