"""공시 피드의 행 표시가 한정층을 따르는지 잠근다.

뷰어를 띄워 SK하이닉스 피드를 열어 찾았다(2026-08-25). 표시된 17건 중
**11건이 강등 대상**인데 붉은 「● 신호」로 찍혀 있었다.

    26.08.21  자기주식처분결과보고서               ● 신호   ← R2  결과 보고
    26.08.05  주식등의대량보유상황보고서(일반)      ● 신호   ← R1b 제출인 SK스퀘어
    26.08.05  풍문또는보도에대한해명(미확정)        ● 신호   ← R4  미확정 해명
    26.07.15  유상증자또는주식관련사채등의발행결과   ● 신호   ← R2c 결과 보고
    26.xx.xx  유상증자결정(종속회사의주요경영사항)   ● 신호   ← R3  자회사 사안

**국민연금·SK스퀘어가 낸 보고서가 이 회사의 신호로 찍혀 있었다.**

앞선 세 라운드가 이 함수를 이미 손봤다 — 필터 predicate, MAX 배지,
우선순위 배지를 전부 observed 기준으로 옮겼다. 그런데 **세 곳이 남았다**:

    const s0 = r.signals[0];               // 카테고리 점
    ... : r.signals.length ? "● 신호"      // 붉은 점
    ${s0 && s0.note ? ...}                 // 주석

배지만 고치고 그 아래 폴백은 원시 배열을 그대로 봤다.

1년 코퍼스: 신호가 붙는 32,427건 중 **15,706건(48.4%)**이 관찰 0이다 —
피드에서 붉은 점의 절반이 잘못 찍히고 있었다.

강등된 행은 '신호 없음'(—)과 구별해 「절차·사후」와 **사유**를 낸다.
대시보드의 「절차·사후 보고」 절과 같은 태도다.
"""
import json
import pathlib
import re

from dart_risk_mcp.core.qualifiers import (
    TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import match_signals

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
_ROW = _HTML[_HTML.index('<div class="rowhead g-feed">'):]
_ROW = _ROW[:_ROW.index('$("feedTable")')]
# 첫 번째 `detailBody`는 빈 화면 문구라 실제 렌더 블록(마지막)을 잡는다.
_DETAIL = _HTML[_HTML.rindex('$("detailBody").innerHTML'):]
_DETAIL = _DETAIL[:_DETAIL.index("▍SIGNAL CHAIN — 이 공시의 위치")]


def test_붉은_점이_관찰_기준이다():
    assert "r.signals.length ? `<span class=\"sigdot\">" not in _ROW, "옛 폴백이 남아 있다"
    assert 'obsSigs.length ? `<span class="sigdot">' in _ROW


def test_카테고리도_관찰_기준이다():
    assert "const s0 = r.signals[0];" not in _ROW, "원시 첫 신호를 쓴다"
    assert "const s0 = obsSigs0[0];" in _ROW


def test_강등된_행은_사유를_낸다():
    """'신호 없음'과 구별하지 않으면 왜 빠졌는지 알 수 없다."""
    assert 'class="procmark">절차·사후' in _ROW
    assert "procSig.reason" in _ROW
    assert ".procmark {" in _HTML, "CSS가 없으면 스타일이 상속돼 붉게 보일 수 있다"


def test_강등_표시는_붉지_않다():
    m = re.search(r"\.procmark \{[^}]*\}", _HTML)
    assert m and "--red" not in m.group(0), m and m.group(0)


def test_피드_머리글_건수와_같은_기준이다():
    """머리글은 observed를 세는데 행은 원시 배열을 봐서 둘이 어긋났다."""
    i = _HTML.index('$("feedMeta").textContent')
    assert "observedEvents.length" in _HTML[i:i + 200]


def test_실물에서_잘못_찍히던_제목들():
    """SK하이닉스 피드에서 실제로 붉게 찍혀 있던 제목 — 전부 강등이 맞다."""
    cases = [
        ("자기주식처분결과보고서", {"report_nm": "자기주식처분결과보고서"}),
        ("주식등의대량보유상황보고서(일반)",
         {"report_nm": "주식등의대량보유상황보고서(일반)",
          "corp_name": "SK하이닉스", "flr_nm": "SK스퀘어"}),
        ("풍문또는보도에대한해명(미확정)",
         {"report_nm": "풍문또는보도에대한해명(미확정)"}),
        ("유상증자또는주식관련사채등의발행결과(자율공시)",
         {"report_nm": "유상증자또는주식관련사채등의발행결과(자율공시)"}),
        ("유상증자결정(종속회사의주요경영사항)",
         {"report_nm": "유상증자결정(종속회사의주요경영사항)"}),
    ]
    for nm, filing in cases:
        sigs = match_signals(nm)
        assert sigs, f"신호가 아예 안 붙는다: {nm}"
        quals = qualify_signals(sigs, parse_report_name(nm), filing)
        assert all(q.tier != TIER_OBSERVED for q in quals), (
            f"{nm}이 관찰로 남았다 — 피드 붉은 점의 근거가 사라진다"
        )
        assert all(q.reason for q in quals), f"{nm}에 사유가 없다"


def test_사유_없는_강등은_없다():
    """피드가 사유를 렌더하므로 빈 사유는 빈 줄이 된다."""
    corpus = json.loads((_ROOT / "tests" / "fixtures" / "corpus"
                         / "signal_titles_365d.json").read_text(encoding="utf-8"))
    bad = []
    for t in corpus["titles"]:
        nm = t["nm"]
        sigs = match_signals(nm)
        if not sigs:
            continue
        quals = qualify_signals(sigs, parse_report_name(nm), {"report_nm": nm})
        if any(q.tier == TIER_OBSERVED for q in quals):
            continue
        if not quals[0].reason:
            bad.append(nm.strip())
    assert not bad, f"사유 없는 강등 {len(bad)}종: {bad[:5]}"


# ── 공시 상세 화면 — 같은 누락이 있었다 ──────────────────────────
# 「자기주식처분결과보고서」(R2 강등)의 상세가 「SIGNAL DETECTED」와
# "주가 조작이나 경영권 방어 도구로 악용되기도 합니다"를 띄웠다.
# 이 화면도 앞선 라운드에서 TOP WEIGHT·체인 위치·우선순위 행을 이미
# observed 기준으로 옮겼는데 **s0만 남아 있었다**.


def test_상세도_관찰_기준으로_고른다():
    assert "const s0 = r.signals[0] || null;" not in _HTML, "원시 첫 신호를 쓴다"
    assert "const s0 = detObs[0] || null;" in _HTML


def test_상세가_강등_공시에_위험_해설을_붙이지_않는다():
    assert "r.signals.map((s) => renderWhyRow(" not in _DETAIL, "원시 배열로 해설을 낸다"
    assert "detObs.map((s) => renderWhyRow(" in _DETAIL
    assert "이 유형의 위험 해설은 붙이지 않습니다" in _DETAIL


def test_상세_머리말이_강등을_구별한다():
    assert "PROCEDURAL FILING" in _DETAIL
    assert 'r.signals.length ? "감지됨"' not in _DETAIL
    assert 'detObs.length ? "감지됨"' in _DETAIL


def test_상세가_강등_사유를_보여준다():
    assert "esc(procSig.reason)" in _DETAIL
