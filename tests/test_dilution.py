"""희석 추적 — 형태 분류와 집계를 고정한다.

## 왜 만들었나

이 도구는 CB/BW **발행**을 공시 제목으로 잡았지만 **전환이 실제로 얼마나
일어났는지**는 한 번도 보지 않았다. 기존 주주가 희석되는 건 전환 시점이고,
그것이 무자본 M&A 수법의 핵심 고리다(저가 CB 발행 → 주가 부양 → 전환 → 매도).

`irdsSttus`(증자·감자 현황)는 공시 제목이 아니라 **원장**이다. 실측
(2026-08-31, 15개사 사업보고서) 신주 발생원 분포:

    전환권행사 147 · 신주인수권행사 89 · 주식매수선택권행사 71 ·
    유상증자 39 · 무상증자 6 · 무상감자 4 · 주식배당 3 · 주식분할 2

## 함정 셋 — 전부 실측으로 찾았다

**① 비례 배분을 희석으로 세면 안 된다.** 무상증자·주식분할·주식배당은 모든
주주에게 같은 비율로 배분돼 지분율이 변하지 않는다. 희석으로 세면 도구가
**주주에게 공짜로 준 것**을 위험처럼 표시한다 — 파생상품 평가손실을 위험으로
표시하려다 되돌린 것(2026-08-31)과 같은 부류의 함정이다.

**② 「합계」·「비고」 행이 20/20 회사에 섞여 온다.** 발행총수 분모로 잡으면
우선주까지 더해져 커진다. 보통주 표기는 3종이고(「보통주」18 ·
「의결권 있는 주식」1(셀트리온) · 「보통주식」1(두산)) 그 셋으로 20/20을 덮는다
— `_FS_ALIASES` 사고(별칭 하나가 빠지면 그 회사에서 조용히 사라진다)의 재현을
막으려고 실측으로 만들었다.

**③ DART가 「모든 칸이 `-`인 자리 행」을 보낸다.** 신주 발행이 없는 회사에도
온다(실측: 삼성전자 2행·두산 1행). 「일자 미기재 2건」으로 세면 사용자는
「뭔가 있는데 날짜를 모른다」로 읽지만 **실제로는 아무것도 없다**.
"""
import pathlib

import pytest

from dart_risk_mcp.core.dart_client import (
    _issuance_date8,
    classify_issuance_type,
    pick_common_stock_total,
    summarize_dilution,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── 형태 분류 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("stle,kind", [
    # 실측 상위 형태 (15개사 · 371행)
    ("전환권행사", "dilutive"),
    ("신주인수권행사", "dilutive"),
    ("주식매수선택권행사", "dilutive"),
    ("유상증자(제3자배정)", "dilutive"),
    ("유상증자(주주배정)", "dilutive"),
    ("유상증자(주주우선공모)", "dilutive"),
    ("유상증자(일반공모)", "dilutive"),
    # 비례 배분 — 지분율이 변하지 않는다
    ("무상증자", "proportional"),
    ("주식배당", "proportional"),
    ("주식분할", "proportional"),
    # 감소
    ("무상감자", "decrease"),
    ("이익소각", "decrease"),
    # 미기재
    ("-", "unknown"),
    ("", "unknown"),
])
def test_형태_분류(stle, kind):
    assert classify_issuance_type(stle) == kind


def test_무상증자를_희석으로_세지_않는다():
    """이 테스트가 이 기능의 **핵심 안전장치**다.

    무상증자를 희석에 넣으면 도구가 「주주에게 공짜로 준 것」을 위험처럼
    표시한다. 파생손실에서 「주가가 올라서 생긴 손실」을 위험으로 표시하려다
    되돌린 것과 같은 부류다.
    """
    for good in ("무상증자", "주식분할", "주식배당"):
        assert classify_issuance_type(good) == "proportional", good
        assert classify_issuance_type(good) != "dilutive"


def test_유상과_무상을_가른다():
    """「무상증자」가 「유상증자」 키워드에 걸려 희석으로 떨어지면 안 된다."""
    assert classify_issuance_type("유상증자") == "dilutive"
    assert classify_issuance_type("무상증자") == "proportional"


# ── 발행총수 고르기 ──────────────────────────────────────────────────────

def _tot(se, qty):
    return {"se": se, "istc_totqy": qty}


def test_합계_행을_보통주로_잡지_않는다():
    """20/20 회사에 「합계」·「비고」가 섞여 온다 — 잡으면 분모가 커진다."""
    rows = [_tot("보통주", "88,616,044"), _tot("우선주", "-"),
            _tot("합계", "99,999,999"), _tot("비고", "-")]
    assert pick_common_stock_total(rows) == 88_616_044


@pytest.mark.parametrize("se", ["보통주", "보통주식", "의결권 있는 주식"])
def test_보통주_표기_3종을_모두_읽는다(se):
    """실측: 「보통주」18 · 「보통주식」1(두산) · 「의결권 있는 주식」1(셀트리온).

    셋이면 20/20을 덮는다. 하나가 빠지면 그 회사에서 분모가 조용히 사라진다.
    """
    assert pick_common_stock_total([_tot(se, "1,234,567"),
                                    _tot("합계", "9,999,999")]) == 1_234_567


def test_못_고르면_None이지_0이_아니다():
    """없는 사실을 만들지 않는다 — 0이면 비율이 0%로 찍힌다."""
    assert pick_common_stock_total([_tot("합계", "100")]) is None
    assert pick_common_stock_total([]) is None


# ── 날짜 ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,want", [
    ("2023.08.11", "20230811"),   # 실측 318/321이 점 표기
    ("2023-08-11", "20230811"),   # 3/321
    ("2023.8.1", "20230801"),
    ("20230811", "20230811"),
    ("-", ""),
    ("", ""),
])
def test_날짜_파싱(raw, want):
    assert _issuance_date8(raw) == want


# ── 집계 ─────────────────────────────────────────────────────────────────

def _row(de, stle, qty):
    return {"isu_dcrs_de": de, "isu_dcrs_stle": stle,
            "isu_dcrs_stock_knd": "보통주", "isu_dcrs_qy": qty}


_BLANK = {"isu_dcrs_de": "-", "isu_dcrs_stle": "-",
          "isu_dcrs_stock_knd": "-", "isu_dcrs_qy": "-"}


def test_빈_껍데기_행을_미기재로_세지_않는다():
    """실측: 삼성전자 2행·두산 1행이 전부 이것 — 「없다」이지 「모른다」가 아니다."""
    d = summarize_dilution([_BLANK, _BLANK], [], since="20230101")
    assert d["blank"] == 2
    assert d["undated"] == 0
    assert d["in_window"] == 0


def test_날짜만_없는_행은_따로_센다():
    d = summarize_dilution(
        [{"isu_dcrs_de": "-", "isu_dcrs_stle": "전환권행사",
          "isu_dcrs_stock_knd": "보통주", "isu_dcrs_qy": "1,000"}],
        [], since="20230101")
    assert d["blank"] == 0 and d["undated"] == 1


def test_창_밖은_집계에서_빠지되_덮인_구간은_남는다():
    """원장은 다년(실측 3~12년)이라 요청 창보다 넓게 온다.

    빠뜨린 게 아니라 창 밖이라는 것을, `earliest`로 알 수 있어야 한다.
    """
    rows = [_row("2019.01.01", "전환권행사", "1,000"),
            _row("2025.06.01", "전환권행사", "2,000")]
    d = summarize_dilution(rows, [], since="20230101")
    assert d["in_window"] == 1
    assert d["buckets"]["dilutive"] == 2000
    assert d["earliest"] == "20190101"   # 창 밖이지만 덮인 구간은 사실이다


def test_비례_배분은_희석_집계에_들어가지_않는다():
    rows = [_row("2025.01.01", "무상증자", "1,000,000"),
            _row("2025.02.01", "전환권행사", "500,000")]
    d = summarize_dilution(rows, [_tot("보통주", "10,000,000")], since="20240101")
    assert d["buckets"]["dilutive"] == 500_000
    assert d["buckets"]["proportional"] == 1_000_000
    assert d["dilutive_pct"] == pytest.approx(5.0)


def test_분모를_못_고르면_비율을_내지_않는다():
    d = summarize_dilution([_row("2025.01.01", "전환권행사", "1,000")],
                           [_tot("합계", "10,000")], since="20240101")
    assert d["buckets"]["dilutive"] == 1000
    assert d["dilutive_pct"] is None


def test_미분류를_버리지_않는다():
    """실측: 셀트리온에 형태가 「-」인 73,887,750주 1건이 있다.

    DART가 형태를 비워 보낸 건이라 우리가 「합병 신주」라고 단정할 근거가
    없다. 그렇다고 버리면 7,388만 주가 **조용히 사라진다**.
    """
    d = summarize_dilution([_row("2023.12.28", "-", "73,887,750")],
                           [], since="20230101")
    assert d["buckets"]["unknown"] == 73_887_750
    assert "-" in d["by_type"]


# ── 렌더 규칙 ────────────────────────────────────────────────────────────

def test_블록에_점수_등급_어휘가_없다():
    """⚠ **독스트링과 주석을 벗기고** 본다.

    이 검사를 처음 돌렸을 때 `_dilution_block`의 독스트링이 걸렸다 —
    「희석으로 세면 **위험**처럼 표시하게 된다」는 **하지 않는 이유**를 적은
    문장이었다. 근거를 지우면 다음 사람이 같은 실수를 한다. 이 함정에
    이번 라운드에서만 세 번 걸렸다(`ctrcvs_rs`·키워드 제거 근거·여기).
    """
    import ast

    src = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    i = src.index("def _dilution_block(")
    body = src[i:src.index("\ndef ", i + 10)]
    tree = ast.parse(body)
    fn = tree.body[0]
    stmts = fn.body[1:] if ast.get_docstring(fn) else fn.body
    code = "\n".join(
        l for l in "\n".join(ast.unparse(s) for s in stmts).splitlines()
        if not l.strip().startswith("#"))
    for bad in ("위험", "매우위험", "고위험", "점수", "등급", "score"):
        assert bad not in code, f"판정 어휘가 들어왔다: {bad}"


def test_꼬리말이_제_데이터와_모순되지_않는다():
    """옛 꼬리말은 「정확한 희석률…은 개별 공시로 확인하라」였다.

    이제 이 도구가 희석 주식 수와 비중을 낸다 — 그대로 두면 화면이 제
    데이터와 반대를 말한다(이 레포에서 반복해 고친 부류).
    """
    src = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    i = src.index("def track_capital_structure(")
    body = src[i:i + 20000]
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))
    assert "정확한 희석률이나" not in code, (
        "꼬리말이 「희석률은 여기서 안 준다」고 말하는데 블록이 준다")


def test_창_밖에만_기재가_있으면_그_사실을_말한다():
    """「자료가 없다」와 「창 밖이다」를 같은 화면으로 만들지 않는다.

    실측 아틀라스링크: 원장에 5건이 있는데 전부 2018~2021이라 3년 창에서는
    0건이다. 침묵하면 「이 회사는 신주 발행이 없었다」로 읽힌다 — 빈 값이
    「없다」로 읽히면 안 된다는 이 레포의 원칙.
    """
    import dart_risk_mcp.server as sv

    calls = {}

    def _hist(cc, key, *a, **k):
        calls["hist"] = True
        return [_row("2018.04.26", "유상증자(주주배정)", "260,000")]

    old_h, old_t = sv.fetch_issuance_history, sv.fetch_stock_totals
    sv.fetch_issuance_history = _hist
    sv.fetch_stock_totals = lambda *a, **k: []
    try:
        out = "\n".join(sv._dilution_block("00000000", "k", 3))
    finally:
        sv.fetch_issuance_history, sv.fetch_stock_totals = old_h, old_t

    assert "주식 수 변동" in out
    assert "창(최근 3년) 안에는" in out
    assert "2018.04.26" in out, "덮인 구간을 밝혀야 창을 넓힐 수 있다"


def test_자리_행만_오면_침묵한다():
    """모든 칸이 `-`인 행은 「없다」는 뜻이다 — 「미기재 N건」이라 적지 않는다."""
    import dart_risk_mcp.server as sv

    old_h, old_t = sv.fetch_issuance_history, sv.fetch_stock_totals
    sv.fetch_issuance_history = lambda *a, **k: [dict(_BLANK), dict(_BLANK)]
    sv.fetch_stock_totals = lambda *a, **k: []
    try:
        assert sv._dilution_block("00000000", "k", 3) == []
    finally:
        sv.fetch_issuance_history, sv.fetch_stock_totals = old_h, old_t


def test_조회_실패는_없음과_구분한다():
    """DART는 오류를 HTTP 200 본문으로 준다 — 빈 리스트로 접으면 거짓말이 된다."""
    import dart_risk_mcp.server as sv
    from dart_risk_mcp.core.dart_client import FetchList

    old_h, old_t = sv.fetch_issuance_history, sv.fetch_stock_totals
    sv.fetch_issuance_history = lambda *a, **k: FetchList(fetch_failed=True)
    sv.fetch_stock_totals = lambda *a, **k: []
    try:
        out = "\n".join(sv._dilution_block("00000000", "k", 3))
    finally:
        sv.fetch_issuance_history, sv.fetch_stock_totals = old_h, old_t
    assert "받지 못했습니다" in out and "없다는 뜻이 아닙니다" in out
