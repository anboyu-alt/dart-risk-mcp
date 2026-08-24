"""중첩 괄호 파싱과 '회사에 유리하게 끝난 판정'(R6)을 잠근다.

둘 다 사용자 제보(*"SK하이닉스에 부채악순환·무자본M&A가 잡히면 안 된다"*)를
추적하다 대형주 카드의 근거를 실명으로 열어 보고 찾았다(2026-08-25).

## ① 중첩 괄호가 본체 추출을 깨뜨렸다

`_PAREN_RE`는 `[^()]*`라 중첩을 못 본다. 한 번만 적용하면 본체에 **괄호가
남는다**:

    기타주요경영사항(주요사항보고서(유상증자) 철회)
      → body='기타주요경영사항(주요사항보고서철회)'   tail=''

`WRAPPER_BODIES`('기타주요경영사항')에도, `PHASE_TAILS`('철회')에도 걸리지
않는다. **증자를 철회한 건이 관찰 신호로 남았다** — v1.12.3이 R2b로 고쳤다고
기록한 바로 그 결함이 중첩 괄호에서는 그대로 새고 있었다.

1년 코퍼스: 중첩 괄호 제목 **112건이 전부** 이렇게 깨졌고, 고치면
**26건이 관찰→강등**된다. **반대 방향은 0건**이다(손실 없는 교정).

## ② 위반이 아니라고 판정된 공시가 위반의 근거였다

POSCO홀딩스의 「무자본 M&A」·「허위 신사업 주가부양」 카드에서 4.3(공시·보고
의무 위반)의 근거가 이랬다:

    4.3  20260624  DISCLOSURE_VIOL  불성실공시법인**미지정**(지정유예)

1년 전수로 세 마커(불성실공시법인미지정 · 실질심사대상제외 · 실질심사미해당)를
확인하니 **8종 60건이 전부 이 성격**이고, 그중 **50건이 관찰**이었다. 나머지
10건은 어미가 '해제'라 R2가 우연히 잡던 것이라 — **같은 사건이 포장지에 따라
판정이 갈리고 있었다.**

⚠ 「기각」은 넣지 않았다. 1년 45건이 전부 「상장폐지결정 효력정지 가처분 신청
**기각**에 따른 정리매매절차 재개」류로 회사가 **진** 건이다. 부정 표현을
일괄로 묶으면 뜻이 뒤집힌다.
"""
import collections
import json
import pathlib

import pytest

from dart_risk_mcp.core.qualifiers import (
    NEGATIVE_FINDING_MARKS, TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import match_signals

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CORPUS = json.loads((_ROOT / "tests" / "fixtures" / "corpus"
                      / "signal_titles_365d.json").read_text(encoding="utf-8"))


def _tiers(nm):
    sigs = match_signals(nm)
    return [q.tier for q in qualify_signals(sigs, parse_report_name(nm),
                                            {"report_nm": nm})]


# ── ① 중첩 괄호 ────────────────────────────────────────────────

@pytest.mark.parametrize("nm,body,tail", [
    ("기타주요경영사항(주요사항보고서(유상증자) 철회)", "기타주요경영사항", ""),
    ("기타주요경영사항(유상증자결정(제3자배정) 철회)", "기타주요경영사항", ""),
    ("주권매매거래정지해제(상장적격성 실질심사 미해당 (사유발생 해소))",
     "주권매매거래정지해제", "해제"),
])
def test_중첩_괄호를_끝까지_벗긴다(nm, body, tail):
    p = parse_report_name(nm)
    assert "(" not in p.body and ")" not in p.body, p.body
    assert p.body == body
    assert p.tail == tail


def test_철회가_관찰로_남지_않는다():
    for nm in ("기타주요경영사항(주요사항보고서(유상증자) 철회)",
               "기타주요경영사항(유상증자결정(제3자배정) 철회)",
               "기타주요경영사항(자기 전환사채(제3,4,5회차) 매도결정 철회)"):
        tiers = _tiers(nm)
        assert tiers, f"신호가 안 붙는다: {nm}"
        assert TIER_OBSERVED not in tiers, nm


def test_단일_괄호는_동작이_같다():
    """중첩만 고친다 — 흔한 제목의 파싱이 바뀌면 안 된다."""
    p = parse_report_name("주요사항보고서(자기주식취득결정)")
    assert (p.body, p.subtitles, p.tail) == (
        "주요사항보고서", ("자기주식취득결정",), "결정")


def test_국면_상승_예외가_살아_있다():
    """정리매매 개시는 어미가 '해제'여도 관찰이다(v1.12.2). 회귀 방지."""
    nm = "주권매매거래정지해제(상장폐지에 따른 정리매매 개시)"
    assert TIER_OBSERVED in _tiers(nm)


def test_코퍼스에_본체_괄호가_남지_않는다():
    left = [t["nm"].strip() for t in _CORPUS["titles"]
            if "(" in parse_report_name(t["nm"]).body]
    assert not left, f"본체에 괄호가 남은 제목 {len(left)}종: {left[:4]}"


# ── ② R6 부정 판정 ──────────────────────────────────────────────

@pytest.mark.parametrize("mark,_why", NEGATIVE_FINDING_MARKS)
def test_마커가_코퍼스에_실존한다(mark, _why):
    """실측 없이 넣은 마커가 아님을 고정 — 0건이면 근거가 없다."""
    hit = [t for t in _CORPUS["titles"]
           if mark in parse_report_name(t["nm"]).compact]
    assert hit, f"'{mark}'가 1년 코퍼스에 없다"


def test_미지정은_위반의_근거가_아니다():
    """POSCO홀딩스 실물 제목."""
    nm = "불성실공시법인미지정              (지정유예)"
    tiers = _tiers(nm)
    assert tiers, "신호가 안 붙는다"
    assert TIER_OBSERVED not in tiers


def test_지정은_그대로_관찰이다():
    """반대로 넓게 막으면 진짜 위반을 잃는다."""
    assert TIER_OBSERVED in _tiers("불성실공시법인지정              (공시불이행)")


def test_기각은_강등하지_않는다():
    """회사가 **진** 건이다 — 퇴출 절차가 계속된다."""
    nm = "기타시장안내              (상장폐지결정 효력정지 가처분 신청 기각에 따른 정리매매절차 재개)"
    assert TIER_OBSERVED in _tiers(nm), "기각을 부정 판정으로 묶으면 뜻이 뒤집힌다"


def test_같은_사건이_포장지로_갈리지_않는다():
    """전에는 「주권매매거래정지해제(…대상 제외)」만 강등되고
    「기타시장안내(…대상 제외)」는 관찰이었다."""
    a = _tiers("주권매매거래정지해제              (상장적격성 실질심사 대상 제외 결정)")
    b = _tiers("기타시장안내              (상장적격성 실질심사 대상 제외 결정)")
    assert TIER_OBSERVED not in a and TIER_OBSERVED not in b


def test_마커가_잡는_제목이_전부_강등이다():
    left = collections.Counter()
    for t in _CORPUS["titles"]:
        p = parse_report_name(t["nm"])
        if not any(mk in p.compact for mk, _ in NEGATIVE_FINDING_MARKS):
            continue
        if TIER_OBSERVED in _tiers(t["nm"]):
            left[t["nm"].strip()] += t.get("n", 1)
    assert not left, f"관찰로 남은 부정 판정: {dict(left)}"


def test_뷰어와_export가_따라온다():
    html = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
    assert "r.negative_finding_marks" in html
    assert "let body = compact;" in html, "뷰어 파서가 중첩을 안 벗긴다"
    data = json.loads((_ROOT / "docs" / "tool" / "signals-data.json")
                      .read_text(encoding="utf-8"))
    assert data["qualifier_rules"]["negative_finding_marks"] == [
        list(x) for x in NEGATIVE_FINDING_MARKS]
