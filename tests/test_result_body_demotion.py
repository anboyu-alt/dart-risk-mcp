"""결과 보고 제목이 결정과 따로 관찰 신호로 잡히지 않는지 잠근다.

사용자 질문에서 시작했다 — *"SK하이닉스는 역대급 시총을 기록하는 건실한
회사인데 왜 신호가 여러 개 잡히나"*. 표시 계층을 세 번 고친 뒤에도 남은 것이
이것이다.

    20260624  주요사항보고서(유상증자결정)                   관찰
    20260715  유상증자또는주식관련사채등의발행결과(자율공시)   관찰  ← 같은 증자

헤드라인이 「유상증자(배정방식 미상) ×2」였다. **증자는 한 번이다.**

core는 이 표기를 이미 사후 보고로 알고 있었다 — `CHURN_RESULT_MARKS`
(v1.20.10)가 자본 이벤트 집계에서 같은 이유로 뺀다. 한정층만 몰랐다.
**두 층이 같은 제목에 서로 다른 답을 내고 있었다.**

원인은 **어미**다. 「…결과보고서」는 tail이 '결과보고서'라 R2가 잡는데,
「…발행결과(자율공시)」는 tail이 '자율공시'라 안 걸린다. 같은 뜻인데 표기가
달라서 갈렸다.

실측 (1년 코퍼스):

    발행결과  391건 (3PCA 371 · RCPS 17 · CB_BW 3)  전부 관찰
    청약결과  123건 (3PCA 123)                       전부 관찰
    ─────────────────────────────────────────────
    합계      514건 전부 관찰 (강등 0)
    비교      '결과보고서' 어미 946건은 이미 강등

회사 단위 영향 (90일 시장 전수 56,646건 · 증자·메자닌 관찰 505개사):

    결과보고를 가진 73개사
      ├ 63개사(86%)  결정도 같은 창에 있음 → 순수한 중복 제거
      └ 10개사(14%)  결정이 창 밖 → 관찰 0

⚠ 강등은 **삭제가 아니라 이동**이다 — 「절차·사후 보고」 절에 사유와 함께
남으므로 10개사에서도 사실 자체는 계속 보인다.
"""
import json
import pathlib

import pytest

from dart_risk_mcp.core.dart_client import CHURN_RESULT_MARKS
from dart_risk_mcp.core.qualifiers import (
    RESULT_BODY_MARKS, TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import match_signals

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CORPUS = json.loads((_ROOT / "tests" / "fixtures" / "corpus"
                      / "signal_titles_365d.json").read_text(encoding="utf-8"))


def _tiers(nm):
    sigs = match_signals(nm)
    return [(m["key"], q.tier, q.reason or q.note)
            for m, q in zip(sigs, qualify_signals(
                sigs, parse_report_name(nm), {"report_nm": nm}))]


@pytest.mark.parametrize("nm", [
    "유상증자또는주식관련사채등의발행결과(자율공시)",
    "증권발행결과(자율공시)              (제3자배정 유상증자)",
    "유상증자또는주식관련사채등의청약결과(자율공시)",
])
def test_결과_보고는_강등된다(nm):
    rows = _tiers(nm)
    assert rows, f"신호가 아예 안 붙는다: {nm}"
    for key, tier, reason in rows:
        assert tier != TIER_OBSERVED, f"{key}가 관찰로 남았다"
        assert "결과 보고" in (reason or ""), reason


def test_결정_자체는_그대로_관찰이다():
    """반대 방향으로 넓게 강등하면 진짜 사건을 잃는다."""
    rows = _tiers("주요사항보고서(유상증자결정)")
    assert any(t == TIER_OBSERVED for _, t, _ in rows)


def test_한정층과_자본집계가_같은_말을_한다():
    """`CHURN_RESULT_MARKS`만 알고 한정층이 몰라서 두 층이 갈렸다."""
    assert set(CHURN_RESULT_MARKS) - {"결과보고서"} <= set(RESULT_BODY_MARKS), (
        "자본 집계가 사후 보고로 빼는 표기를 한정층이 모른다"
    )


def test_코퍼스에_관찰로_남은_결과보고가_없다():
    left = []
    for t in _CORPUS["titles"]:
        nm, n = t["nm"], t.get("n", 1)
        if not any(mk in parse_report_name(nm).body for mk in RESULT_BODY_MARKS):
            continue
        for key, tier, _ in _tiers(nm):
            if tier == TIER_OBSERVED:
                left.append((nm.strip(), key, n))
    assert not left, f"관찰로 남은 결과 보고 {len(left)}종: {left[:5]}"


def test_결과로_끝나는_표기는_이_셋뿐이다():
    """넓히거나 좁힐 때 근거가 되는 전수 — 새 표기가 생기면 여기서 걸린다."""
    bodies = set()
    for t in _CORPUS["titles"]:
        body = parse_report_name(t["nm"]).body
        if body.endswith("결과"):
            bodies.add(body)
    assert bodies == {
        "증권발행결과",
        "유상증자또는주식관련사채등의발행결과",
        "유상증자또는주식관련사채등의청약결과",
    }, bodies


def test_뷰어도_같은_규칙을_쓴다():
    html = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
    assert "r.result_body_marks" in html
    data = json.loads((_ROOT / "docs" / "tool" / "signals-data.json")
                      .read_text(encoding="utf-8"))
    assert data["qualifier_rules"]["result_body_marks"] == list(RESULT_BODY_MARKS)
