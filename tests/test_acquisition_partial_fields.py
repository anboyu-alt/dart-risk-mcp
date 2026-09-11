"""취득 대상 확인이 **못 읽은 것**을 어떻게 다루는가.

두 가지를 잠근다.

① **이름과 관계는 서로 다른 사실이다.** 옛 `_confirm_acquisition_targets`는
   `if det and det.get("issuer"):` 한 줄로 묶어, 발행회사 이름을 못 읽으면
   원문에 「특수관계인」이 적혀 있어도 관계·금액·자기자본 대비까지 통째로
   버렸다. 화면에는 「취득 대상: (미확인) · 관계: 미확인」만 남는다.

② **확인 상한을 숨기지 않는다.** 후보를 최근 3건으로 자르면서 그 사실을
   적지 않으면, 나머지에 계열 취득이 있어도 목록에 흔적이 없다 — 판정의
   근거를 제한하면서 제한을 숨기는 것이다(`_confirm_outflow_counterparties`가
   이미 같은 수정을 거쳤다).

⚠ **게이트 통과 조건은 이 변경의 대상이 아니다.** `affiliated` + `unlisted`
   둘 다 필요하고 `unknown`은 통과하지 않는다는 v1.13.2 판단은 그대로이며,
   아래 테스트가 그것을 함께 고정한다 — 사실을 더 보여 주는 것과 카드를 더
   띄우는 것은 다른 일이다.
"""
import pathlib
import re
from unittest import mock

from dart_risk_mcp import server


_HTML = (pathlib.Path(__file__).resolve().parents[1]
         / "docs" / "tool" / "index.html").read_text(encoding="utf-8")


def _events(n: int) -> list[dict]:
    return [{"key": "ACQ_REVIEW", "rcept_no": f"2026090100{i:04d}",
             "rcept_dt": f"2026090{i % 9 + 1}", "report_nm": "타법인주식및출자증권취득결정",
             "is_amendment": False} for i in range(n)]


def test_이름을_못_읽어도_관계와_금액은_남는다():
    det = {"issuer": "", "nation": "", "relation": "특수관계인",
           "amount": 19999998370, "equity_ratio": 33.91}
    with mock.patch.object(server, "fetch_acquisition_detail", return_value=det):
        rows = server._confirm_acquisition_targets(_events(1), [])
    assert rows[0]["relation"] == "특수관계인", "관계가 이름과 함께 버려졌다"
    assert rows[0]["amount"] == 19999998370
    assert rows[0]["equity_ratio"] == 33.91
    assert rows[0]["classification"] == "affiliated"
    assert rows[0]["listing"] == "unknown", (
        "이름 없이 명부를 물을 수 없다 — 상장 여부는 unknown으로 남아야 한다")


def test_이름이_없으면_게이트는_여전히_막는다():
    """사실을 더 보여 주는 것이 카드를 더 띄우는 것이 되면 안 된다."""
    rows = [{"rcept_no": "20260901000001", "rcept_dt": "20260901",
             "report_nm": "타법인주식및출자증권취득결정", "issuer": "",
             "relation": "특수관계인", "classification": "affiliated",
             "amount": 100, "equity_ratio": 1.0, "nation": "", "listing": "unknown"}]
    gate = server._fund_diversion_gate(rows)
    assert gate["pass"] is False, "상장 여부 미확인은 통과시키지 않는다(v1.13.2)"
    assert any("특수관계인" in l for l in gate["fact_lines"]), (
        "막더라도 확인된 사실은 남긴다")


def test_확인_상한을_사실로_적는다():
    det = {"issuer": "(주)대상", "nation": "", "relation": "-",
           "amount": 100, "equity_ratio": 1.0}
    with mock.patch.object(server, "fetch_acquisition_detail", return_value=det), \
         mock.patch.object(server, "classify_target_listing", return_value="listed"):
        rows = server._confirm_acquisition_targets(_events(5), [])
    assert len(rows) == 3, "상한 자체는 그대로다(원문 ZIP 비용)"
    assert getattr(rows, "unreviewed", 0) == 2
    note = server._acq_cap_note(rows)
    assert "후보 5건" in note and "2건 미확인" in note
    assert note in "".join(server._fund_diversion_gate(rows)["fact_lines"]), (
        "상한을 세어 놓고 화면에 적지 않으면 조용한 절단이다")


def test_상한_안이면_군더더기를_붙이지_않는다():
    det = {"issuer": "(주)대상", "nation": "", "relation": "-",
           "amount": 100, "equity_ratio": 1.0}
    with mock.patch.object(server, "fetch_acquisition_detail", return_value=det), \
         mock.patch.object(server, "classify_target_listing", return_value="listed"):
        rows = server._confirm_acquisition_targets(_events(2), [])
    assert server._acq_cap_note(rows) == ""


def test_뷰어도_관계를_이름과_분리한다():
    """core만 고치면 사용자가 보는 화면은 그대로다(이 저장소의 반복 사고)."""
    m = re.search(r"cls:\s*d\.(\w+)\s*\?\s*classifyOutflowRelation", _HTML)
    assert m, "뷰어의 취득 분류 줄을 찾지 못했다"
    assert m.group(1) == "relation", (
        "뷰어가 아직 issuer를 조건으로 쓴다 — 이름을 못 읽으면 관계가 사라진다")


def test_취득_공시의_상대방이_유출_확인_블록에도_나온다():
    """같은 리포트의 두 블록이 같은 공시에 다른 답을 내면 안 된다.

    실측(2026-09-11, 세종메디칼): 「자금유출·자산이전 상대방 확인」이 취득
    3건을 전부 「거래상대방: (미확인)」으로 냈다. 같은 리포트의 취득 대상
    확인 블록은 같은 원문에서 「(주)카나리아바이오 · 특수관계인 · 200억」을
    읽고 있었다 — 「타법인주식및출자증권취득결정」은 `resolve_decision_type`이
    빈 값이고 자산처분 제목도 아니라 **금전대여·담보 서식 파서**로 떨어졌다.
    """
    ev = [{"key": "ACQ_REVIEW", "rcept_no": "20221004900595", "rcept_dt": "20221004",
           "report_nm": "타법인주식및출자증권취득결정", "is_amendment": False}]
    det = {"issuer": "(주)카나리아바이오", "nation": "", "relation": "특수관계인",
           "amount": 19999998370, "equity_ratio": 33.91}
    with mock.patch.object(server, "fetch_acquisition_detail", return_value=det), \
         mock.patch.object(server, "fetch_outflow_detail", return_value={}), \
         mock.patch.object(server, "fetch_asset_disposal_detail", return_value={}):
        rows = server._confirm_outflow_counterparties(ev, [], "00959229", {})
    assert rows and rows[0]["counterparty"] == "(주)카나리아바이오"
    assert rows[0]["classification"] == "affiliated"
    assert rows[0]["amount"] == 19999998370


def test_취득_제목_게이트가_처분과_갈린다():
    assert server._is_acquisition_title("타법인주식및출자증권취득결정")
    assert server._is_acquisition_title("주요사항보고서(타법인주식및출자증권양수결정)")
    assert server._is_acquisition_title("타법인주식및출자증권\n취득결정"), "공백 변형"
    assert not server._is_acquisition_title("유형자산처분결정")
    assert not server._is_acquisition_title("타법인주식및출자증권처분결정")


def test_뷰어도_취득_서식을_가른다():
    """core만 고치면 사용자가 보는 화면은 그대로다."""
    assert "function isAcquisitionTitle(" in _HTML
    assert re.search(r"isAcquisitionTitle\(h\.nm\)\s*\n?\s*\?\s*acquisitionAsOutflow",
                     _HTML), "뷰어 OUTFLOW 블록이 취득 서식을 가르지 않는다"
    assert 'detailBlockHits("ACQ_REVIEW"' in _HTML, (
        "core `_outflow_review_candidates`는 ACQ_REVIEW를 후보로 삼는다")
