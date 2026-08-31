"""메자닌(CB·BW·EB) 발행 조건과 공시 분류를 고정한다.

## 왜 만들었나

메자닌은 이 도구가 쫓는 수법(무자본 M&A·주가부양)의 중심 도구인데, 정보가
다섯 군데로 흩어져 있고 **가장 중요한 「발행 조건」은 어디에도 없었다**.
v1.21.21 희석 블록의 꼬리말이 *"발행 조건은 개별 공시를 열어 확인하라"*고
적어 둔 자리가 이것이다.

⚠ 배선은 **이미 있었다** — `fetch_cb_issue_decision`이 구조화 응답을 받아오는데
`cb_extractor._parse_structured`가 3필드만 남기고 전환가액·리픽싱·만기를 버렸다.

## 실측 (2026-09-01)

    발행 조건 필드   15개사 42건에서 100% 채워짐
    리픽싱 하한      42건 중 70%(법정 하한) 29건 · **70% 미만 2건**(둘 다 제이스코)
    메자닌 공시      제이스코 3년 297건 중 119건(40%) · 코아스 349건 중 130건
    `actnmn`         CB/BW 56키에 **없다** → 구조화 인수자 경로는 항상 빈 결과
    rcept_no 중복    6개사 40행에서 **0** → `bd_fta`는 권면총액이다

## 함정 셋

**① EB에는 리픽싱 필드가 없다** — 교환 대상이 이미 발행된 주식이라 서식 자체에
항목이 없다. 공란으로 두면 「리픽싱 조항 없음」으로 읽힌다.

**② 하한을 3버킷으로 나누면 70%보다 높은 하한이 「미상」으로 떨어진다** — 첫
구현이 그랬다. 제이스코 5·6회차는 전환가 506원·하한 500원(**98.8%**)인데 이건
미상이 아니라 **리픽싱 여지가 거의 없다**는 뜻이고, 11.1%와 정반대다.

**③ 회차 join은 불가능하다** — 증자·감자 현황의 행사 행에 회차가 없고,
발행가액으로 되짚는 것도 리픽싱 때문에 안 맞는다(일치율 0~78%).
"""
import pathlib

import pytest

from dart_risk_mcp.core.dart_client import (
    _mzn_date,
    classify_mezzanine_filing,
    parse_mezzanine_row,
    summarize_mezzanine,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── 공시 분류 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,category,round_", [
    # 실측 제목(제이스코·코아스·HLB·유티아이 3년)
    ("주요사항보고서(전환사채권발행결정)", "issue", None),
    ("주요사항보고서(신주인수권부사채권발행결정)", "issue", None),
    ("전환가액의조정", "refix", None),
    ("전환가액의조정 (제38회차)", "refix", 38),
    ("신주인수권행사가액의조정(제37회차)", "refix", 37),
    ("전환가액ㆍ신주인수권행사가액ㆍ교환가액의조정(안내공시)", "refix", None),
    ("전환주식의전환가액조정 (전환우선주)", "refix", None),
    ("전환청구권행사", "exercise", None),
    ("전환청구권행사 (제3회차)", "exercise", 3),
    ("전환청구권ㆍ신주인수권ㆍ교환청구권행사", "exercise", None),
    ("전환주식의전환청구권행사", "exercise", None),
    ("전환사채(해외전환사채포함)발행후만기전사채취득", "redeem", None),
    ("주요사항보고서(자기전환사채만기전취득결정)", "redeem", None),
    ("주요사항보고서(자기신주인수권부사채만기전취득결정)", "redeem", None),
    ("주요사항보고서(자기전환사채매도결정)", "resell", None),
    ("유상증자또는주식관련사채등의발행결과(자율공시)", "result", None),
])
def test_공시_분류(title, category, round_):
    c = classify_mezzanine_filing(title)
    assert c is not None, f"분류되지 않았다: {title}"
    assert c["category"] == category
    assert c["round"] == round_


@pytest.mark.parametrize("title", [
    # ⚠ 「사채」 한 글자로 넓히면 이것들이 딸려온다
    "주요사항보고서(단기사채발행결정)",
    "회사채발행결정",
    "주요사항보고서(신종자본증권발행결정)",
    "최대주주변경",
    "주요사항보고서(유상증자결정)",
    "",
])
def test_메자닌이_아닌_제목은_분류하지_않는다(title):
    assert classify_mezzanine_filing(title) is None


def test_정정을_표시하되_분류는_유지한다():
    c = classify_mezzanine_filing("[기재정정]주요사항보고서(자기전환사채매도결정)")
    assert c["category"] == "resell"
    assert c["is_amendment"] is True


# ── 발행 조건 파싱 ───────────────────────────────────────────────────────

def _cb_row(**kw):
    row = {
        "rcept_no": "20250115000001", "bd_tm": "4", "bd_fta": "40,000,000,000",
        "bd_intr_ex": "7.5", "bd_intr_sf": "11.2", "bd_mtd": "2028년 01월 15일",
        "bdis_mthn": "사모", "pymd": "2025년 01월 15일",
        "cv_prc": "1,670", "cvisstk_cnt": "23,952,095", "cvisstk_tisstk_vs": "36.55",
        "cvrqpd_bgd": "2026년 01월 15일", "cvrqpd_edd": "2027년 12월 15일",
        "act_mktprcfl_cvprc_lwtrsprc": "1,169", "rmislmt_lt70p": "-",
        "fdpp_op": "30,000,000,000", "fdpp_dtrp": "10,000,000,000",
    }
    row.update(kw)
    return row


def test_CB_발행조건_파싱():
    p = parse_mezzanine_row(_cb_row(), "CB")
    assert p["round"] == 4 and p["face_amount"] == 40_000_000_000
    assert p["strike"] == 1670 and p["strike_label"] == "전환가액"
    assert p["maturity"] == "20280115" and p["pay_date"] == "20250115"
    assert p["refix_floor"] == 1169
    assert p["refix_floor_pct"] == pytest.approx(70.0, abs=0.05)
    assert p["refix_field_absent"] is False
    assert p["use_of_funds"] == ["운영자금", "채무상환자금"]


def test_EB는_리픽싱_필드가_없다():
    """⚠ 공란으로 두면 「리픽싱 조항 없음」으로 읽힌다 — 다른 값으로 가른다."""
    p = parse_mezzanine_row(
        {"rcept_no": "x", "bd_tm": "1", "ex_prc": "10,000",
         "exrqpd_bgd": "2025년 01월 01일", "exrqpd_edd": "2027년 01월 01일",
         "extg": "자기주식", "extg_tisstk_vs": "3.2"}, "EB")
    assert p["refix_field_absent"] is True
    assert p["refix_floor"] is None and p["refix_floor_pct"] is None
    assert p["refix_sub70_limit"] is None
    assert p["strike_label"] == "교환가액"
    # EB는 신주가 나오지 않는다 — 이미 발행된 주식을 넘긴다
    assert p["potential_shares"] is None


def test_결측은_None이지_0이_아니다():
    p = parse_mezzanine_row({"rcept_no": "x", "bd_fta": "-", "cv_prc": "-",
                             "bd_intr_ex": "-"}, "CB")
    assert p["face_amount"] is None and p["strike"] is None
    assert p["coupon"] is None
    assert p["refix_floor_pct"] is None


@pytest.mark.parametrize("raw,want", [
    ("2023년 04월 27일", "20230427"),
    ("2023.04.27", "20230427"),
    ("2023-4-7", "20230407"),
    ("-", ""),
    ("", ""),
])
def test_날짜_파싱(raw, want):
    assert _mzn_date(raw) == want


# ── 집계 ─────────────────────────────────────────────────────────────────

def _tot(qty="10,000,000"):
    return [{"se": "보통주", "istc_totqy": qty}, {"se": "합계", "istc_totqy": "99,999"}]


def test_잠재_희석은_주식수를_더해_하나의_분모로_나눈다():
    """⚠ `cvisstk_tisstk_vs`(총수 대비 %)를 **더하지 않는다** — 회차마다 발행
    시점의 분모가 달라 합이 뜻을 잃는다."""
    rows = [
        {**_cb_row(rcept_no="a", cvisstk_cnt="1,000,000", cvisstk_tisstk_vs="50"),
         "_kind": "CB"},
        {**_cb_row(rcept_no="b", cvisstk_cnt="500,000", cvisstk_tisstk_vs="40"),
         "_kind": "CB"},
    ]
    d = summarize_mezzanine(rows, [], _tot("10,000,000"))
    assert d["potential_shares"] == 1_500_000
    assert d["potential_pct"] == pytest.approx(15.0)   # 50+40=90이 아니다


def test_분모를_못_고르면_비율을_내지_않는다():
    d = summarize_mezzanine([{**_cb_row(), "_kind": "CB"}], [],
                            [{"se": "합계", "istc_totqy": "10,000"}])
    assert d["potential_shares"] > 0
    assert d["potential_pct"] is None


def test_하한이_70퍼센트보다_높아도_미상이_아니다():
    """첫 구현의 오류 — 제이스코 5·6회차(506원 → 500원 = 98.8%)가 「미상」에
    떨어졌다. 리픽싱 여지가 **거의 없다**는 뜻이고 11.1%와 정반대다."""
    rows = [{**_cb_row(rcept_no="hi", cv_prc="506",
                       act_mktprcfl_cvprc_lwtrsprc="500"), "_kind": "CB"}]
    d = summarize_mezzanine(rows, [], _tot())
    assert len(d["refix"]["floors"]) == 1
    assert d["refix"]["floors"][0]["refix_floor_pct"] == pytest.approx(98.8, abs=0.1)
    assert not d["refix"]["lt70"]
    assert not d["refix"]["no_value"]


def test_70퍼센트_미만만_따로_센다():
    """법정 하한을 밑도는 예외(주총 특별결의) — 42건 중 2건뿐이었다."""
    rows = [
        {**_cb_row(rcept_no="a", cv_prc="4,501",
                   act_mktprcfl_cvprc_lwtrsprc="500"), "_kind": "CB"},   # 11.1%
        {**_cb_row(rcept_no="b", cv_prc="4,293",
                   act_mktprcfl_cvprc_lwtrsprc="3,006"), "_kind": "CB"},  # 70.0%
    ]
    d = summarize_mezzanine(rows, [], _tot())
    assert len(d["refix"]["lt70"]) == 1
    assert d["refix"]["lt70"][0]["rcept_no"] == "a"


def test_만기_경계():
    rows = [
        {**_cb_row(rcept_no="a", bd_mtd="2026년 09월 01일"), "_kind": "CB"},
        {**_cb_row(rcept_no="b", bd_mtd="2026년 08월 31일"), "_kind": "CB"},
        {**_cb_row(rcept_no="c", bd_mtd="-"), "_kind": "CB"},
    ]
    d = summarize_mezzanine(rows, [], _tot(), today="20260901")
    assert d["maturity"] == {"not_yet": 1, "passed": 1, "unknown": 1}


def test_정정은_집계에서만_빠지고_리스트에는_남는다():
    filings = [
        {"rcept_dt": "20260714", "rcept_no": "1",
         "report_nm": "주요사항보고서(전환사채권발행결정)"},
        {"rcept_dt": "20260713", "rcept_no": "2",
         "report_nm": "[기재정정]주요사항보고서(전환사채권발행결정)"},
        {"rcept_dt": "20260712", "rcept_no": "3", "report_nm": "최대주주변경"},
    ]
    d = summarize_mezzanine([], filings, _tot())
    assert d["filings_total"] == 2          # 메자닌 아닌 건 제외
    assert d["filings_amended"] == 1
    assert d["filing_counts"] == {"issue": 1}   # 정정은 집계에서 제외
    assert [f["rcept_no"] for f in d["filings"]] == ["1", "2"]   # 리스트엔 남는다


# ── 렌더 ─────────────────────────────────────────────────────────────────

def test_블록에_판정_어휘가_없다():
    """⚠ 독스트링·주석을 벗기고 본다 — 근거 문장이 「위험」을 인용한다."""
    import ast

    src = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    i = src.index("def _mezzanine_block(")
    body = src[i:src.index("\n_DILUTION_KIND_LABEL", i)]
    fn = ast.parse(body).body[0]
    stmts = fn.body[1:] if ast.get_docstring(fn) else fn.body
    code = "\n".join(
        l for l in "\n".join(ast.unparse(s) for s in stmts).splitlines()
        if not l.strip().startswith("#"))
    for bad in ("위험", "의심", "고위험", "점수", "등급", "score"):
        assert bad not in code, f"판정 어휘가 들어왔다: {bad}"


def _rendered(monkeypatch=None):
    """가짜 데이터로 블록을 렌더해 **사용자가 보는 문자열**을 얻는다.

    ⚠ 소스 텍스트를 검사하면 안 된다 — 이 파일을 처음 쓸 때 그렇게 했다가
    「**서로 다른 " + "원장**」처럼 **줄바꿈으로 쪼개진 문구**를 못 찾아 세 개가
    헛되이 실패했다. 독스트링의 문구를 본문으로 오인하기도 했다(이번 라운드
    세 번째 함정).
    """
    import dart_risk_mcp.server as sv

    rows = [{**_cb_row(rcept_no=f"r{i}", bd_tm=str(i)), "_kind": "CB"}
            for i in range(1, 12)]          # 상한(8)을 넘겨 생략 문구를 만든다
    filings = [{"rcept_dt": f"2026081{i%10}", "rcept_no": f"f{i}",
                "report_nm": "전환가액의조정"} for i in range(20)]
    orig = (sv.fetch_mezzanine_decisions, sv.fetch_stock_totals)
    sv.fetch_mezzanine_decisions = lambda *a, **k: {
        "rows": rows, "failed_kinds": [], "fetch_failed": False,
        "window": ("20230901", "20260901")}
    sv.fetch_stock_totals = lambda *a, **k: _tot()
    try:
        return chr(10).join(sv._mezzanine_block("00000000", "k", 3, filings))
    finally:
        sv.fetch_mezzanine_decisions, sv.fetch_stock_totals = orig


def test_잔액이라고_말하지_않는다():
    """「미상환 잔액」은 그 단어만으로 거짓이 된다 — 발행결정은 발행 시점의
    조건이고 조기상환·만기전취득·전환은 각각 다른 공시다."""
    out = _rendered()
    assert "미상환 잔액" not in out
    assert "잔액이 아닙니다" in out, "한계 고지가 사라졌다"
    assert "만기일 미도래" in out


def test_이을_수_없다는_고지가_있다():
    out = _rendered()
    assert "서로 다른 원장" in out
    assert "회차가 기재되지 않아" in out


def test_상한에_걸리면_생략_건수를_밝힌다():
    """리스트(12)·발행조건(8) 두 상한 모두 — 조용히 자르지 않는다."""
    out = _rendered()
    assert out.count("건 생략") >= 2, out[-400:]
    assert "전체 20건 중 최근 12건" in out      # 공시 리스트
    assert "전체 11건 중 최근 8건" in out       # 발행 조건


def test_전체_공시_대비_비율을_적지_않는다():
    """공시 목록은 상한에 걸려 잘린다(삼성전자 3,933건 중 1,000건) — 분모가
    거짓이 된다. **렌더 결과**로 확인한다(독스트링에는 이 낱말이 있다)."""
    out = _rendered()
    assert "전체 공시" not in out


def test_조회_실패는_없음과_구분한다():
    """CB만 죽었는데 BW·EB가 「전부」로 표기되면 안 된다."""
    import dart_risk_mcp.server as sv

    orig = (sv.fetch_mezzanine_decisions, sv.fetch_stock_totals)
    sv.fetch_mezzanine_decisions = lambda *a, **k: {
        "rows": [], "failed_kinds": ["CB"], "fetch_failed": True,
        "window": ("20230901", "20260901")}
    sv.fetch_stock_totals = lambda *a, **k: []
    try:
        out = chr(10).join(sv._mezzanine_block("00000000", "k", 3, []))
    finally:
        sv.fetch_mezzanine_decisions, sv.fetch_stock_totals = orig
    assert "CB" in out and "받지 못했습니다" in out
    assert "발행이 없다는 뜻이 아닙니다" in out


# ── 죽은 필드 기록 ───────────────────────────────────────────────────────

def test_구조화_인수자_경로가_비어_있다는_사실이_적혀_있다():
    """`actnmn`·`actsen`은 응답에 없다(3개사 56키). 근거를 지우면 다음 사람이
    같은 착각을 한다."""
    src = (_ROOT / "dart_risk_mcp" / "core" / "cb_extractor.py").read_text(
        encoding="utf-8")
    i = src.index("def _parse_structured(")
    doc = src[i:src.index("\ndef ", i + 10)]
    assert "actnmn" in doc and "없다" in doc
    # ⚠ 문구가 줄바꿈으로 쪼개질 수 있어 공백을 접고 본다
    assert "HTML 폴백" in " ".join(doc.split())


def test_발행결정_3종이_실측_키_픽스처에_있다():
    """이 셋이 픽스처에 **없어서** `test_no_dead_fields`가 검사한 적이 없었다."""
    import json

    d = json.loads((_ROOT / "tests" / "fixtures" / "api" / "response_keys.json")
                   .read_text(encoding="utf-8"))
    for ep in ("cvbdIsDecsn", "bdwtIsDecsn", "exbdIsDecsn"):
        ks = d["endpoints"].get(ep)
        assert ks, f"{ep}의 실측 키가 없다"
        assert "actnmn" not in ks, f"{ep}에 actnmn이 생겼다면 구조화 경로를 되살려라"
    assert "cv_prc" in d["endpoints"]["cvbdIsDecsn"]
    assert "act_mktprcfl_cvprc_lwtrsprc" in d["endpoints"]["cvbdIsDecsn"]
