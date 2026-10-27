"""`check_board_conflict` 도구 + 재사용 블록 `_board_conflict_block` (이사회 이해상충 점검 Task 4).

네트워크는 전부 막는다 — 서버 모듈이 이름으로 import한 함수를 `srv.<name>`으로 패치하고
Task 1 픽스처(SKAI 357880 실공시 원문)를 먹인다. 거래 공시 원문·사업보고서 마크다운·
임원현황 응답이 전부 가공 없는 실물이다.
"""
import json
import pathlib

import pytest

import dart_risk_mcp.server as srv
from dart_risk_mcp.core.dart_client import FETCH_ERROR, FETCH_OK, FetchList

_FIX = pathlib.Path(__file__).parent / "fixtures" / "board"

CORP = "01381984"
FILING = "20251219000418"
PERIODIC = "20260323001292"
CONTROL = "20261023000221"

_FILING_ROW = {
    "rcept_no": FILING, "corp_code": CORP, "corp_name": "SKAI",
    "report_nm": "주요사항보고서(타법인주식및출자증권양수결정)",
    "rcept_dt": "20251219", "flr_nm": "SKAI",
}
_PERIODIC_ROW = {
    "rcept_no": PERIODIC, "corp_code": CORP, "corp_name": "SKAI",
    "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260323", "flr_nm": "SKAI",
}
_CONTROL_ROW = {
    "rcept_no": CONTROL, "corp_code": "00999999", "corp_name": "데이원컴퍼니",
    "report_nm": "주요사항보고서(타법인주식및출자증권양수결정)",
    "rcept_dt": "20261023", "flr_nm": "데이원컴퍼니",
}


def _txt(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


@pytest.fixture
def roster():
    return json.loads(_txt("exctvSttus_01381984_2025_11011.json"))


class _Calls:
    def __init__(self):
        self.doc_text = []
        self.audit_text = []
        self.roster = []


@pytest.fixture
def wired(monkeypatch, roster):
    """네트워크 전부 차단 + SKAI 픽스처 연결. 테스트가 필요한 것만 덮어쓴다."""
    calls = _Calls()
    monkeypatch.setattr(srv, "_api_key", lambda: "k")
    monkeypatch.setattr(
        srv, "resolve_corp",
        lambda q, k: ("SKAI", {"corp_code": CORP, "stock_code": "357880"}))
    monkeypatch.setattr(
        srv, "resolve_disclosure_row_with_status",
        lambda rcept, k, *a, **kw: (_FILING_ROW, "found"))
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: ([_PERIODIC_ROW, _FILING_ROW], FETCH_OK))

    def _doc(rcept, k, max_chars=3000):
        calls.doc_text.append(rcept)
        return {FILING: _txt("20251219000418_text.txt"),
                CONTROL: _txt("control_20261023000221_text.txt")}.get(rcept, "")

    def _audit(rcept, k, prefer=""):
        calls.audit_text.append(rcept)
        return _txt("20260323001292_board_section.md") if rcept == PERIODIC else ""

    def _roster(code, k, year, reprt="11011"):
        calls.roster.append((code, year, reprt))
        return FetchList(roster) if code == CORP else FetchList()

    monkeypatch.setattr(srv, "fetch_document_text", _doc)
    monkeypatch.setattr(srv, "fetch_audit_report_text", _audit)
    monkeypatch.setattr(srv, "fetch_executive_roster_rows", _roster)
    monkeypatch.setattr(srv, "classify_target_listing", lambda *a, **kw: "unlisted")
    return calls


FORBIDDEN = ["제척 없음", "위험", "심각", "의심", "점수", "등급"]


def _assert_no_judgment(out: str):
    for w in FORBIDDEN:
        # 「등급이 아닙니다」처럼 원칙을 밝히는 꼬리말만 허용한다
        text = out.replace("판정·점수·등급이 아닙니다", "")
        assert w not in text, w


# ── rcept 모드: SKAI 실공시 ────────────────────────────────────────────────

@pytest.mark.usefixtures("no_structured_dart")
class TestSkaiRceptMode:
    def test_첫_줄과_절_순서(self, wired):
        out = srv.check_board_conflict("SKAI", FILING)
        assert out.splitlines()[0] == f"🪑 SKAI — 이사회 이해상충 확인 · {FILING}"
        heads = ["━━ 거래 ━━", "━━ 이사회 의결 ━━", "━━ 겸직 대조 ━━", "━━ 한계 ━━"]
        pos = [out.index(h) for h in heads]
        assert pos == sorted(pos)
        assert out.index("요약:") > pos[-1]
        assert out.rstrip().splitlines()[-1].startswith("📎 사실 표기입니다")

    def test_거래_절_사실(self, wired):
        out = srv.check_board_conflict("SKAI", FILING)
        assert f"(rcept_no={FILING})" in out
        assert "타법인 주식 양수" in out
        assert "이사회결의일 2025.12.19" in out
        assert "사외이사 참석 2" in out
        assert "거래상대방: 주식회사 디렉터스컴퍼니" in out
        assert "대표자 신재혁" in out           # 【거래상대방에 관한 사항】 표에서
        assert "「최대주주」" in out
        assert "대상회사: (주)스카이인텔리전스" in out
        assert "대표자 이재철" in out
        assert "「최대주주의 특수관계인」" in out

    def test_의결표_출처와_표기(self, wired):
        out = srv.check_board_conflict("SKAI", FILING)
        assert PERIODIC in out
        assert "「(2) 이사회의 주요 의결사항 등」" in out
        assert "35회차" in out
        assert "2025.12.19" in out
        assert "타법인 주식취득 계약의 건" in out
        assert "가결" in out
        assert "신재혁 찬성" in out
        assert "MAO, XUCHAO -" in out
        assert "「-」는 표가 불참과 제척을 가르지 않습니다" in out

    def test_겸직_대조_네_명과_요약(self, wired):
        out = srv.check_board_conflict("SKAI", FILING)
        assert "신재혁" in out and "이재철" in out and "제갈완" in out
        assert "MAO, XUCHAO" in out
        assert "디렉터스컴퍼니" in out
        assert "🎯 이사회 결의 참여 이사의 상대방·대상회사 겸직" in out
        want = ("요약: 이사 7인 중 4인이 상대방·대상회사 임원 겸직 · "
                "겸직 이사 결의 표기: 찬성 3 · 「-」 1 · "
                "전체 이사 결의 표기: 찬성 4 · 「-」 3")
        assert want in out

    def test_의결표_이사가_명부에_없으면_밝힌다(self, wired):
        out = srv.check_board_conflict("SKAI", FILING)
        assert "신기동" in out.split("━━ 겸직 대조 ━━")[1].split("━━ 한계 ━━")[0]

    def test_명부는_정기보고서의_사업연도로_받는다(self, wired):
        srv.check_board_conflict("SKAI", FILING)
        assert wired.roster == [(CORP, "2025", "11011")]

    def test_한계_절_고정_문장(self, wired):
        out = srv.check_board_conflict("SKAI", FILING)
        tail = out.split("━━ 한계 ━━")[1]
        assert "비상장 상대방 임원은 공시 기재" in tail
        assert "등기부 대조를 권합니다" in tail
        assert "이사회의사록 첨부는 이 도구가 읽지 않습니다" in tail
        assert "CB·BW·유상증자 발행대상자 유형은 이 도구의 1차 범위 밖" in tail

    def test_판정_어휘가_없다(self, wired):
        _assert_no_judgment(srv.check_board_conflict("SKAI", FILING))

    def test_의결표는_원문_전체에서_읽는다(self, wired):
        srv.check_board_conflict("SKAI", FILING)
        assert wired.audit_text == [PERIODIC]


# ── 정기보고서 미접수 경로 ─────────────────────────────────────────────────

@pytest.mark.usefixtures("no_structured_dart")
def test_정기보고서가_목록에_전혀_없으면_전년_11011로_명부를_받고_그_사실을_적는다(wired, monkeypatch):
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: ([_FILING_ROW], FETCH_OK))
    out = srv.check_board_conflict("SKAI", FILING)
    assert "결의일 이후 정기보고서 미접수 — 의결표 없음" in out
    assert "명부 기준 보고서: 결의일 전년(2024)" in out
    assert wired.roster == [(CORP, "2024", "11011")]
    assert wired.audit_text == []
    assert "의결표 없음" in out.split("요약:")[1]
    assert "「-」는 표가 불참과 제척을 가르지 않습니다" not in out


@pytest.mark.usefixtures("no_structured_dart")
def test_접수순_앞_정기보고서가_의결표를_안_가지면_다음_보고서를_본다(wired, monkeypatch):
    first = dict(_PERIODIC_ROW, rcept_no="20260101000001",
                 report_nm="분기보고서 (2025.09)", rcept_dt="20260105")
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: ([_PERIODIC_ROW, first, _FILING_ROW], FETCH_OK))
    out = srv.check_board_conflict("SKAI", FILING)
    assert wired.audit_text == ["20260101000001", PERIODIC]
    assert PERIODIC in out and "35회차" in out


@pytest.mark.usefixtures("no_structured_dart")
def test_첨부정정_태그_정기보고서도_후보다(wired, monkeypatch):
    tagged = dict(_PERIODIC_ROW, report_nm="[첨부정정]사업보고서 (2025.12)")
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: ([tagged, _FILING_ROW], FETCH_OK))
    out = srv.check_board_conflict("SKAI", FILING)
    assert "35회차" in out


# ── 창 모드 ────────────────────────────────────────────────────────────────

def _targets(n):
    return [dict(_FILING_ROW, rcept_no=f"2025121{i}000418", rcept_dt=f"2025121{i}",
                 report_nm="주요사항보고서(타법인주식및출자증권양수결정)")
            for i in range(n)]


def _doc_all_related(wired, monkeypatch, related=(), unrelated=()):
    """창 모드 후보 접수번호마다 SKAI 원문(관계 「최대주주」) 또는 대조군 원문(관계 「-」)을 준다."""
    skai, ctrl = _txt("20251219000418_text.txt"), _txt("control_20261023000221_text.txt")

    def _doc(rcept, k, max_chars=3000):
        wired.doc_text.append(rcept)
        if rcept in related or rcept == FILING:
            return skai
        if rcept in unrelated or rcept == CONTROL:
            return ctrl
        return ""

    monkeypatch.setattr(srv, "fetch_document_text", _doc)


@pytest.mark.usefixtures("no_structured_dart")
def test_창_모드_대상_4건_중_최근_3건만_확인한다(wired, monkeypatch):
    targets = _targets(4)
    _doc_all_related(wired, monkeypatch, related={t["rcept_no"] for t in targets})
    rows = targets + [
        dict(_FILING_ROW, rcept_no="20251218000001", rcept_dt="20251218",
             report_nm="[기재정정]주요사항보고서(타법인주식및출자증권양수결정)"),
        dict(_FILING_ROW, rcept_no="20251217000001", rcept_dt="20251217",
             report_nm="주주총회소집공고"),
    ]
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: (rows, FETCH_OK))
    out = srv.check_board_conflict("SKAI")
    assert out.splitlines()[0].startswith("🪑 SKAI — 이사회 이해상충 확인 · ")
    assert ("해당 유형 공시 4건 중 최근 3건 원문 확인 · 1건 미확인 — 상대방 관계 표기가 "
            "최대주주·특수관계인인 건 3건 대조(표시 상한 3건)") in out
    # 관계가 확인된 3건이 차면 멈춘다 (정정·무관 공시는 후보가 아니다). 원문은 관계를 읽을 때
    # 한 번만 받는다 — 블록이 다시 받지 않는다.
    assert wired.doc_text == ["20251213000418", "20251212000418", "20251211000418"]
    assert out.count("━━ 거래 ━━") == 3
    assert "접수번호 모드는" not in out   # 접수번호 모드 한계 줄은 그 모드에서만


@pytest.mark.usefixtures("no_structured_dart")
def test_창_모드_3건_이하면_미확인_문구가_없다(wired, monkeypatch):
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: ([_FILING_ROW, _PERIODIC_ROW], FETCH_OK))
    out = srv.check_board_conflict("SKAI")
    assert "해당 유형 공시 1건 원문 확인 — 상대방 관계 표기가 최대주주·특수관계인인 건 1건 대조" in out
    assert "미확인" not in out


@pytest.mark.usefixtures("no_structured_dart")
def test_창_모드_해당_유형_0건(wired, monkeypatch):
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: ([_PERIODIC_ROW], FETCH_OK))
    out = srv.check_board_conflict("SKAI")
    assert "이 창에는 해당 유형 공시가 없습니다" in out


@pytest.mark.usefixtures("no_structured_dart")
def test_조회_실패는_없다고_말하지_않는다(wired, monkeypatch):
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: ([], FETCH_ERROR))
    out = srv.check_board_conflict("SKAI")
    assert "자료가 없다는 뜻이 아닙니다" in out
    assert "해당 유형 공시가 없습니다" not in out


@pytest.mark.usefixtures("no_structured_dart")
def test_창_모드는_lookback_days로_조회한다(wired, monkeypatch):
    seen = {}

    def fake(corp, key, days, *a, **kw):
        seen["days"] = days
        return ([_PERIODIC_ROW], FETCH_OK)

    monkeypatch.setattr(srv, "fetch_company_disclosures_with_status", fake)
    srv.check_board_conflict("SKAI", "", 90)
    assert seen["days"] == 90


# ── 입력 검증 ──────────────────────────────────────────────────────────────

def test_키가_없으면_안내한다(monkeypatch):
    monkeypatch.setattr(srv, "_api_key", lambda: "")
    assert srv.check_board_conflict("SKAI").startswith("❌ DART_API_KEY")


@pytest.mark.usefixtures("no_structured_dart")
@pytest.mark.parametrize("lb", ["abc", None, True, 1.9, 100000, 0, -1, "90"])
def test_lookback_days가_예외를_내지_않는다(wired, lb):
    out = srv.check_board_conflict("SKAI", "", lb)
    assert isinstance(out, str) and out.strip()


@pytest.mark.usefixtures("no_structured_dart")
def test_lookback_days_abc는_기본_180이다(wired, monkeypatch):
    seen = {}

    def fake(corp, key, days, *a, **kw):
        seen["days"] = days
        return ([], FETCH_OK)

    monkeypatch.setattr(srv, "fetch_company_disclosures_with_status", fake)
    srv.check_board_conflict("SKAI", "", "abc")
    assert seen["days"] == 180
    srv.check_board_conflict("SKAI", "", None)
    assert seen["days"] == 180


@pytest.mark.usefixtures("no_structured_dart")
def test_회사를_못_찾으면_안내한다(wired, monkeypatch):
    monkeypatch.setattr(srv, "resolve_corp", lambda q, k: None)
    assert "찾을 수 없습니다" in srv.check_board_conflict("없는회사")


@pytest.mark.usefixtures("no_structured_dart")
def test_빈_기업명(wired):
    assert srv.check_board_conflict("  ").startswith("❌")


@pytest.mark.usefixtures("no_structured_dart")
def test_corp_code_8자리를_직접_받는다(wired, monkeypatch):
    monkeypatch.setattr(srv, "corp_name_by_code", lambda c, k: "SKAI")
    monkeypatch.setattr(
        srv, "resolve_corp",
        lambda q, k: pytest.fail("corp_code 8자리는 resolve_corp을 타지 않는다"))
    out = srv.check_board_conflict(CORP, FILING)
    assert out.startswith("🪑 SKAI")


@pytest.mark.usefixtures("no_structured_dart")
def test_corp_code를_명부에서_못_찾으면_안내한다(wired, monkeypatch):
    monkeypatch.setattr(srv, "corp_name_by_code", lambda c, k: "")
    assert "찾을 수 없습니다" in srv.check_board_conflict("99999999", FILING)


# ── rcept 모드 오류 경로 ───────────────────────────────────────────────────

@pytest.mark.usefixtures("no_structured_dart")
@pytest.mark.parametrize("status", ["scan_limit", "error"])
def test_행_조회_실패는_신호_없음이_아니라고_말한다(wired, monkeypatch, status):
    monkeypatch.setattr(
        srv, "resolve_disclosure_row_with_status",
        lambda *a, **kw: (None, status))
    out = srv.check_board_conflict("SKAI", FILING)
    assert "신호가 없다는 뜻이 아닙니다" in out


@pytest.mark.usefixtures("no_structured_dart")
def test_접수번호를_못_찾으면_확인을_안내한다(wired, monkeypatch):
    monkeypatch.setattr(
        srv, "resolve_disclosure_row_with_status",
        lambda *a, **kw: (None, "not_found"))
    assert "접수번호를 찾지 못했습니다" in srv.check_board_conflict("SKAI", FILING)


@pytest.mark.usefixtures("no_structured_dart")
def test_접수번호_형식이_틀리면_거절한다(wired):
    assert srv.check_board_conflict("SKAI", "abc").startswith("❌")


@pytest.mark.usefixtures("no_structured_dart")
def test_다른_회사의_접수번호는_거절한다(wired, monkeypatch):
    monkeypatch.setattr(
        srv, "resolve_disclosure_row_with_status",
        lambda *a, **kw: (dict(_FILING_ROW, corp_code="00000001"), "found"))
    out = srv.check_board_conflict("SKAI", FILING)
    assert "다른 회사" in out
    assert wired.doc_text == []


@pytest.mark.usefixtures("no_structured_dart")
def test_1차_대상_유형이_아니면_그_사실을_적고_끝낸다(wired, monkeypatch):
    monkeypatch.setattr(
        srv, "resolve_disclosure_row_with_status",
        lambda *a, **kw: (dict(_FILING_ROW, report_nm="주주총회소집공고"), "found"))
    out = srv.check_board_conflict("SKAI", FILING)
    assert "1차 대상 유형이 아닙니다" in out
    assert wired.doc_text == []


@pytest.mark.usefixtures("no_structured_dart")
def test_정정공시는_원공시를_안내한다(wired, monkeypatch):
    monkeypatch.setattr(
        srv, "resolve_disclosure_row_with_status",
        lambda *a, **kw: (dict(
            _FILING_ROW, report_nm="[기재정정]주요사항보고서(타법인주식및출자증권양수결정)"),
            "found"))
    out = srv.check_board_conflict("SKAI", FILING)
    assert "정정" in out and wired.doc_text == []


@pytest.mark.usefixtures("no_structured_dart")
def test_원문을_못_받으면_없다고_말하지_않는다(wired, monkeypatch):
    monkeypatch.setattr(srv, "fetch_document_text", lambda *a, **kw: "")
    out = srv.check_board_conflict("SKAI", FILING)
    assert "원문을 받지 못했습니다" in out
    assert "신호가 없다는 뜻이 아닙니다" in out


@pytest.mark.usefixtures("no_structured_dart")
def test_임원현황_조회_실패는_겸직_없음이_아니다(wired, monkeypatch):
    monkeypatch.setattr(
        srv, "fetch_executive_roster_rows",
        lambda *a, **kw: FetchList(fetch_failed=True))
    out = srv.check_board_conflict("SKAI", FILING)
    assert "자료가 없다는 뜻이 아닙니다" in out
    assert "해당 없음" not in out


# ── 대조군 ────────────────────────────────────────────────────────────────

@pytest.mark.usefixtures("no_structured_dart")
def test_대조군은_해당_없음_사실_문장과_0인(wired, monkeypatch, roster):
    monkeypatch.setattr(
        srv, "fetch_executive_roster_rows",
        lambda *a, **kw: FetchList(roster))
    monkeypatch.setattr(
        srv, "resolve_disclosure_row_with_status",
        lambda *a, **kw: (_CONTROL_ROW, "found"))
    monkeypatch.setattr(
        srv, "resolve_corp",
        lambda q, k: ("데이원컴퍼니", {"corp_code": "00999999", "stock_code": "1"}))
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: ([_CONTROL_ROW], FETCH_OK))
    out = srv.check_board_conflict("데이원컴퍼니", CONTROL)
    assert "해당 없음" in out.split("━━ 겸직 대조 ━━")[1].split("━━ 한계 ━━")[0]
    # 의결표가 없으면 명부의 등기이사(사내 4 · 사외 2 — 감사·미등기 제외)가 분모다
    assert "등기이사 6인(명부 기준) 중 0인이 상대방·대상회사 임원 겸직" in out
    assert "🎯" not in out
    assert "결의일 이후 정기보고서 미접수" in out
    _assert_no_judgment(out)


# ── 빈 명부는 「겸직 없음」이 아니다 (fix round 1) ───────────────────────────

@pytest.mark.usefixtures("no_structured_dart")
class TestEmptyRoster:
    @pytest.fixture(autouse=True)
    def _empty(self, no_structured_dart, wired, monkeypatch):
        monkeypatch.setattr(
            srv, "fetch_executive_roster_rows", lambda *a, **kw: FetchList())

    def test_0행_명부는_대조하지_못했다고_적는다(self, wired):
        out = srv.check_board_conflict("SKAI", FILING)
        sec = out.split("━━ 겸직 대조 ━━")[1].split("━━ 한계 ━━")[0]
        assert "대조를 하지 못했습니다" in sec
        # DART가 0행을 줬다(013) — 실패가 아니므로 「자료 없음과 다릅니다」라 쓰지 않는다
        assert "DART 응답에 해당 사업연도 임원현황 자료가 없습니다" in sec
        assert "자료 없음과 다릅니다" not in sec
        assert "해당 없음" not in out
        assert "0인" not in out
        assert "겸직 대조 불가" in out.split("요약:")[1]
        assert "🎯" not in out

    def test_블록은_겹침_False와_대조_불가_요약(self, wired):
        block, found, summary = srv._board_conflict_block(
            CORP, "SKAI", [_PERIODIC_ROW, _FILING_ROW], _FILING_ROW, "k")
        assert found is False
        assert "겸직 대조 불가" in summary and "0인" not in summary

    def test_명부_조회_실패도_0인으로_말하지_않는다(self, wired, monkeypatch):
        monkeypatch.setattr(
            srv, "fetch_executive_roster_rows",
            lambda *a, **kw: FetchList(fetch_failed=True))
        out = srv.check_board_conflict("SKAI", FILING)
        assert "자료가 없다는 뜻이 아닙니다" in out
        assert "대조를 하지 못했습니다" in out
        assert "0인" not in out and "해당 없음" not in out


@pytest.mark.usefixtures("no_structured_dart")
class TestRosterBasis:
    def test_결의일_이후_정기보고서가_없으면_결의일_이전_최근_정기보고서를_쓴다(
            self, wired, monkeypatch):
        old = dict(_PERIODIC_ROW, rcept_no="20250320000001",
                   report_nm="사업보고서 (2024.12)", rcept_dt="20250320")
        half = dict(_PERIODIC_ROW, rcept_no="20250814000002",
                    report_nm="반기보고서 (2025.06)", rcept_dt="20250814")
        monkeypatch.setattr(
            srv, "fetch_company_disclosures_with_status",
            lambda *a, **kw: ([_FILING_ROW, half, old], FETCH_OK))
        out = srv.check_board_conflict("SKAI", FILING)
        assert wired.roster == [(CORP, "2025", "11012")]
        assert ("명부 기준: 반기보고서 (2025.06) 20250814000002 — 결의일 이전 최근 "
                "정기보고서라 결의 시점 명부와 다를 수 있습니다") in out
        assert "결의일 이후 정기보고서 미접수" in out
        assert "임원 명부를 확인하지 못해" not in out   # 명부가 실제로 대조됐다
        assert "4인" in out


# ── 🎯 게이트 (fix round 1) ────────────────────────────────────────────────

def _only(roster, *names):
    return [r for r in roster if r["nm"].replace("\n", " ").strip() in names]


@pytest.mark.usefixtures("no_structured_dart")
class TestGate:
    def test_의결표가_없으면_사실_줄만_쓰고_게이트는_False다(self, wired, monkeypatch):
        monkeypatch.setattr(
            srv, "fetch_company_disclosures_with_status",
            lambda *a, **kw: ([_FILING_ROW], FETCH_OK))
        out = srv.check_board_conflict("SKAI", FILING)
        assert "🎯" not in out
        assert "겸직 4인 확인 — 결의 참여 표기는 의결표에서 확인되지 않았습니다" in out
        _, found, _ = srv._board_conflict_block(
            CORP, "SKAI", [_FILING_ROW], _FILING_ROW, "k")
        assert found is False

    def test_겸직_이사_표기가_전부_대시면_사실_줄만_쓴다(self, wired, monkeypatch, roster):
        # MAO, XUCHAO 한 명만 대상회사 쪽으로 겹치고 그의 표기는 「-」다
        mao = _only(roster, "MAO, XUCHAO")
        assert len(mao) == 1
        monkeypatch.setattr(
            srv, "fetch_executive_roster_rows", lambda *a, **kw: FetchList(mao))
        out = srv.check_board_conflict("SKAI", FILING)
        assert "🎯" not in out
        assert "겸직 1인 확인 — 그 이사들의 결의 표기는 전부 「-」입니다" in out
        block, found, summary = srv._board_conflict_block(
            CORP, "SKAI", [_PERIODIC_ROW, _FILING_ROW], _FILING_ROW, "k")
        assert found is False
        assert "이사 7인 중 1인이" in summary

    def test_대상회사_쪽만_겹쳐도_근거와_표기를_그대로_적는다(self, wired, monkeypatch, roster):
        mao = _only(roster, "MAO, XUCHAO")
        monkeypatch.setattr(
            srv, "fetch_executive_roster_rows", lambda *a, **kw: FetchList(mao))
        out = srv.check_board_conflict("SKAI", FILING)
        sec = out.split("━━ 겸직 대조 ━━")[1].split("━━ 한계 ━━")[0]
        line = next(ln for ln in sec.splitlines() if ln.startswith("- MAO"))
        assert "대상회사 (주)스카이인텔리전스" in line
        assert "상대방 주식회사" not in line
        assert "스카이인텔리전스 글로벌 CEO" in line
        assert "결의 표기 -" in line

    def test_표기가_하나라도_대시가_아니면_게이트_통과(self, wired, monkeypatch, roster):
        two = _only(roster, "MAO, XUCHAO", "신재혁")
        monkeypatch.setattr(
            srv, "fetch_executive_roster_rows", lambda *a, **kw: FetchList(two))
        out = srv.check_board_conflict("SKAI", FILING)
        assert "🎯 이사회 결의 참여 이사의 상대방·대상회사 겸직" in out
        _, found, _ = srv._board_conflict_block(
            CORP, "SKAI", [_PERIODIC_ROW, _FILING_ROW], _FILING_ROW, "k")
        assert found is True


# ── rcept 모드 정기보고서 창 (fix round 1) ──────────────────────────────────

@pytest.mark.usefixtures("no_structured_dart")
class TestRceptPeriodicWindow:
    def test_결의일과_접수일_사이의_반기보고서를_쓴다(self, wired, monkeypatch):
        # 결의 2025-08-14(의결표 25회차 날짜) → 접수 2025-12-19: 사이에 반기보고서가 있다
        text = _txt("20251219000418_text.txt").replace("2025년 12월 19일", "2025년 8월 14일")
        monkeypatch.setattr(srv, "fetch_document_text", lambda *a, **kw: text)
        half = dict(_PERIODIC_ROW, rcept_no="20250815000111",
                    report_nm="반기보고서 (2025.06)", rcept_dt="20250815")
        seen = {}

        def fake_list(corp, key, *a, **kw):
            seen.update(kw)
            return ([_FILING_ROW, half, _PERIODIC_ROW], FETCH_OK)

        monkeypatch.setattr(srv, "fetch_company_disclosures_with_status", fake_list)
        md = _txt("20260323001292_board_section.md")
        monkeypatch.setattr(srv, "fetch_audit_report_text", lambda r, k, prefer="": md)
        out = srv.check_board_conflict("SKAI", FILING)
        assert "출처: 반기보고서 (2025.06) 20250815000111" in out
        assert "25회차 2025.08.14" in out
        assert seen["bgn_de"] <= "20250814"          # 접수일(20251219)보다 앞서 훑는다
        assert seen["pblntf_ty"] == "A"
        assert wired.roster == [(CORP, "2025", "11012")]

    def test_정기보고서_목록_조회_실패는_미접수가_아니다(self, wired, monkeypatch):
        monkeypatch.setattr(
            srv, "fetch_company_disclosures_with_status",
            lambda *a, **kw: ([], FETCH_ERROR))
        out = srv.check_board_conflict("SKAI", FILING)
        assert "정기보고서 목록" in out
        assert "자료가 없다는 뜻이 아닙니다" in out
        assert "의결표가 없다는 뜻이 아닙니다" in out
        assert "정기보고서 미접수" not in out


# ── 자금유출 서식 폴백 ────────────────────────────────────────────────────

@pytest.mark.usefixtures("no_structured_dart")
def test_금전대여_서식은_outflow_파서로_상대방을_채운다(wired, monkeypatch):
    loan = dict(_FILING_ROW, report_nm="주요사항보고서(타법인에대한채무보증결정)")
    monkeypatch.setattr(
        srv, "resolve_disclosure_row_with_status",
        lambda *a, **kw: (loan, "found"))
    monkeypatch.setattr(
        srv, "fetch_document_text",
        lambda *a, **kw: "이사회결의일 2025년 12월 19일 채무보증 상대 회사명 주식회사 디렉터스컴퍼니")
    monkeypatch.setattr(
        srv, "parse_outflow_detail",
        lambda t: {"counterparty": "주식회사 디렉터스컴퍼니", "relation": "최대주주",
                   "amount": 1, "equity_ratio": 0.0, "kind": "guarantee"})
    out = srv.check_board_conflict("SKAI", FILING)
    assert "거래상대방: 주식회사 디렉터스컴퍼니" in out
    assert "「최대주주」" in out


# ── 상장 상대방 명부 대조 ─────────────────────────────────────────────────

@pytest.mark.usefixtures("no_structured_dart")
def test_상대방이_상장사면_상대방_임원현황도_대조한다(wired, monkeypatch, roster):
    monkeypatch.setattr(srv, "classify_target_listing", lambda *a, **kw: "listed")
    resolved = {}

    def fake_resolve(q, k):
        resolved["q"] = q
        if q == "SKAI":
            return ("SKAI", {"corp_code": CORP, "stock_code": "357880"})
        return ("디렉터스컴퍼니", {"corp_code": "00777777", "stock_code": "999999"})

    monkeypatch.setattr(srv, "resolve_corp", fake_resolve)
    other = [{"nm": "신재혁", "birth_ym": "1981년 06월", "ofcps": "대표이사",
              "rgist_exctv_at": "사내이사", "main_career": "",
              "mxmm_shrholdr_relate": ""}]

    def _roster(code, k, year, reprt="11011"):
        wired.roster.append((code, year, reprt))
        return FetchList(roster if code == CORP else other)

    monkeypatch.setattr(srv, "fetch_executive_roster_rows", _roster)
    out = srv.check_board_conflict("SKAI", FILING)
    assert ("00777777", "2025", "11011") in wired.roster
    assert resolved["q"] == "주식회사 디렉터스컴퍼니"
    assert "생년월 일치" in out


# ── 재사용 블록 ───────────────────────────────────────────────────────────

@pytest.mark.usefixtures("no_structured_dart")
class TestBlockFunction:
    def test_시그니처와_반환_모양(self, wired):
        import inspect
        sig = inspect.signature(srv._board_conflict_block)
        assert list(sig.parameters) == [
            "corp_code", "corp_name", "disclosures", "row", "api_key", "want_header", "info",
            "text", "rcept_mode"]
        assert sig.parameters["want_header"].kind is inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["want_header"].default is True

        block, found, summary = srv._board_conflict_block(
            CORP, "SKAI", [_PERIODIC_ROW, _FILING_ROW], _FILING_ROW, "k")
        assert isinstance(block, str) and found is True
        assert summary.startswith("이사 7인 중 4인이 상대방·대상회사 임원 겸직")
        assert block.splitlines()[0] == f"🪑 SKAI — 이사회 이해상충 확인 · {FILING}"
        assert f"요약: {summary}" in block

    def test_want_header_False면_머리글_없이_거래_절부터(self, wired):
        block, _, _ = srv._board_conflict_block(
            CORP, "SKAI", [_PERIODIC_ROW, _FILING_ROW], _FILING_ROW, "k",
            want_header=False)
        assert block.splitlines()[0] == "━━ 거래 ━━"
        assert "🪑" not in block

    def test_블록은_꼬리말_고지를_싣지_않는다(self, wired):
        """꼬리말 한 줄은 도구가 한 번만 붙인다 — 재사용처에서 되풀이되지 않게."""
        block, _, _ = srv._board_conflict_block(
            CORP, "SKAI", [_PERIODIC_ROW, _FILING_ROW], _FILING_ROW, "k")
        assert "📎 사실 표기입니다" not in block

    def test_겹침_없으면_False(self, wired, monkeypatch):
        monkeypatch.setattr(
            srv, "fetch_executive_roster_rows",
            lambda *a, **kw: FetchList([{"nm": "아무개", "main_career": ""}]))
        _, found, summary = srv._board_conflict_block(
            CORP, "SKAI", [_PERIODIC_ROW, _FILING_ROW], _FILING_ROW, "k")
        assert found is False
        assert "0인" in summary

    def test_공시_목록이_None이어도_죽지_않는다(self, wired):
        block, found, _ = srv._board_conflict_block(
            CORP, "SKAI", None, _FILING_ROW, "k")
        assert "정기보고서 미접수" in block and isinstance(found, bool)


class TestMissingFromTable:
    def test_겸직_이사가_의결표에_없으면_그렇게_적는다(self, wired, monkeypatch, roster):
        mao = [dict(r, nm="가나다") for r in _only(roster, "MAO, XUCHAO")]
        monkeypatch.setattr(
            srv, "fetch_executive_roster_rows", lambda *a, **kw: FetchList(mao))
        out = srv.check_board_conflict("SKAI", FILING)
        assert "🎯" not in out
        # 최종 리뷰 I3: 의결표에 없는 임원은 따로 적고 「이사 N인 중 K인」의 K에 넣지 않는다
        assert "의결표 밖 임원 겸직: 가나다 — 요약의 겸직 이사 수에 넣지 않았습니다" in out
        assert "의결표 이사 중 해당 없음" in out
        summary = out.split("요약: ")[1].splitlines()[0]
        assert summary.startswith("이사 7인 중 0인이 상대방·대상회사 임원 겸직 · 의결표 밖 임원 겸직 1인")
        assert "그 이사들은 의결표에 이름이 없습니다" not in out


class TestParticipationMark:
    """결의 참여는 양성 근거(찬성·반대·기권)로만 센다 — 불참·미참석·결석·「-」·참석(감사 칸)은 아니다.
    안건이 여럿이라 한 칸에 붙은 `찬성불참`은 찬성이 들어 있어 True다(문서화된 안건 단위 모호성)."""

    @pytest.mark.parametrize("v,expected", [
        ("찬성", True), ("반대", True), ("기권", True), ("-", False), ("", False),
        (None, False), ("불참", False), ("불참불참불참", False), ("불참 )", False),
        ("불참(출장)", False), ("미참석", False), ("결석", False), ("참석", False),
        ("의결권제한", False), ("찬성불참", True),
    ])
    def test_참여_표기(self, v, expected):
        assert srv._board_participated(v) is expected


# ── 최종 리뷰 수정 (2026-10-28) ──────────────────────────────────────────────

def _summary(out: str) -> str:
    return out.split("요약: ")[1].splitlines()[0]


def _overlap_sec(out: str) -> str:
    return out.split("━━ 겸직 대조 ━━")[1].split("━━ 한계 ━━")[0]


@pytest.mark.usefixtures("no_structured_dart")
class TestPartiesUnread:
    """I1 — 거래 당사자를 원문에서 못 읽으면 「해당 없음 … 0인」이 아니라 대조 불가다."""

    def test_당사자를_못_읽으면_대조_불가(self, wired, monkeypatch):
        monkeypatch.setattr(srv, "fetch_document_text",
                            lambda *a, **kw: "주요사항보고서 본문 — 서식을 읽을 수 있는 표가 없음")
        out = srv.check_board_conflict("SKAI", FILING)
        sec = _overlap_sec(out)
        assert ("거래 당사자를 원문에서 읽지 못해 겸직 대조를 하지 못했습니다(자료 없음과 다릅니다)"
                in sec)
        assert "해당 없음" not in out and "0인" not in out
        assert "겸직 대조 불가(거래 당사자를 원문에서 읽지 못함)" in _summary(out)
        assert wired.roster == []   # 대조할 상대가 없으면 명부를 받지 않는다
        assert "🎯" not in out


@pytest.mark.usefixtures("no_structured_dart")
class TestDoosanRepeatedTable:
    """I2 — 반복 의결표(두산): 행 없음은 「의결표 없음」이 아니고, 둘째 표의 행도 읽는다."""

    @pytest.fixture(autouse=True)
    def _doosan(self, no_structured_dart, wired, monkeypatch):
        monkeypatch.setattr(
            srv, "fetch_audit_report_text",
            lambda rcept, k, prefer="": _txt("두산_board_section.md") if rcept == PERIODIC else "")

    def test_결의일_행이_없으면_읽은_행_수를_적는다(self, wired):
        out = srv.check_board_conflict("SKAI", FILING)   # 결의일 2025.12.19 — 두산 표에 없음
        assert ("의결표(표 2개·7행 읽음)에 결의일 2025.12.19 행이 없습니다(출처 사업보고서 "
                f"(2025.12) {PERIODIC}) — 의결표가 없다는 뜻이 아닙니다.") in out
        s = _summary(out)
        assert s.endswith("결의일 행 없음") and "의결표 없음" not in s
        # 행이 없으니 분모는 명부의 등기이사다
        assert s.startswith("등기이사 6인(명부 기준) 중 4인이")

    def test_둘째_표의_행이면_그_표의_이사로_센다(self, wired, monkeypatch):
        text = _txt("20251219000418_text.txt").replace("2025년 12월 19일", "2025년 9월 10일")
        monkeypatch.setattr(srv, "fetch_document_text", lambda *a, **kw: text)
        out = srv.check_board_conflict("SKAI", FILING)
        assert "5회차 2025.09.10" in out
        assert "반복 의결표 서식 — 이사 구성이 바뀔 때마다 이어진 표 2개를 모두 읽었고" in out
        assert "유승우 찬성찬성찬성" in out and "문홍성" not in out.split("이사별 표기:")[1].splitlines()[0]
        # SKAI 명부의 겸직자는 두산 의결표에 없다 — K는 0, 의결표 밖으로 따로 센다
        assert _summary(out).startswith(
            "이사 7인 중 0인이 상대방·대상회사 임원 겸직 · 의결표 밖 임원 겸직 4인")


@pytest.mark.usefixtures("no_structured_dart")
def test_정기보고서_원문을_못_받으면_의결표_확인_불가(wired, monkeypatch):
    monkeypatch.setattr(srv, "fetch_audit_report_text", lambda *a, **kw: "")
    out = srv.check_board_conflict("SKAI", FILING)
    assert "정기보고서 원문을 받지 못해 의결표를 확인하지 못했습니다 — 의결표가 없다는 뜻이 아닙니다." in out
    assert _summary(out).endswith("의결표 확인 불가")


@pytest.mark.usefixtures("no_structured_dart")
def test_과거_경력은_사실_줄만_남고_겸직이_아니다(wired, monkeypatch):
    rows = [{"nm": "홍길동", "ofcps": "사외이사", "rgist_exctv_at": "사외이사",
             "main_career": "18.07~21.04 디렉터스컴퍼니 전무\n21.05~ 現 서울대학교 교수",
             "mxmm_shrholdr_relate": "-"}]
    monkeypatch.setattr(srv, "fetch_executive_roster_rows", lambda *a, **kw: FetchList(rows))
    out = srv.check_board_conflict("SKAI", FILING)
    sec = _overlap_sec(out)
    assert ("- 과거 경력에 상대방명 등장: 홍길동 — 「18.07~21.04 디렉터스컴퍼니 전무」 "
            "(현재 경력 표기가 없어 겸직으로 세지 않았습니다)") in sec
    assert "해당 없음" in sec and "🎯" not in out
    assert "중 0인이" in _summary(out)


@pytest.mark.usefixtures("no_structured_dart")
class TestWindowRelatedFilter:
    """I6 — 창 모드는 관계 표기가 최대주주·특수관계인인 건만 대조하고, 태그 붙은 제목은 뺀다."""

    def _rows(self, monkeypatch, rows):
        monkeypatch.setattr(srv, "fetch_company_disclosures_with_status",
                            lambda *a, **kw: (rows + [_PERIODIC_ROW], FETCH_OK))

    def test_첨부정정_제목은_후보가_아니다(self, wired, monkeypatch):
        tagged = dict(_FILING_ROW, rcept_no="20251220000001", rcept_dt="20251220",
                      report_nm="[첨부정정]주요사항보고서(타법인주식및출자증권양수결정)")
        self._rows(monkeypatch, [tagged, _FILING_ROW])
        out = srv.check_board_conflict("SKAI")
        assert "20251220000001" not in wired.doc_text and "20251220000001" not in out
        assert "해당 유형 공시 1건 원문 확인" in out

    def test_관계가_아닌_건만_있으면_블록_없이_그렇게_적는다(self, wired, monkeypatch):
        ts = _targets(2)
        _doc_all_related(wired, monkeypatch, unrelated={t["rcept_no"] for t in ts})
        self._rows(monkeypatch, ts)
        out = srv.check_board_conflict("SKAI")
        assert ("해당 유형 공시 2건 원문 확인 — 상대방 관계 표기가 최대주주·특수관계인인 건 없음"
                in out)
        assert "━━ 거래 ━━" not in out and wired.audit_text == [] and wired.roster == []
        assert "관계 표기가 최대주주·특수관계인으로 읽히지 않아 대조하지 않은 건:" in out
        assert "거래상대방 관계 「-」" in out

    def test_관계가_아닌_건을_건너뛰고_관계인_건을_대조한다(self, wired, monkeypatch):
        ts = _targets(3)   # 최신순: ...12, ...11, ...10
        _doc_all_related(wired, monkeypatch,
                         unrelated={ts[2]["rcept_no"], ts[1]["rcept_no"]},
                         related={ts[0]["rcept_no"]})
        self._rows(monkeypatch, ts)
        out = srv.check_board_conflict("SKAI")
        assert "건 1건 대조" in out
        assert out.count("━━ 거래 ━━") == 1
        assert f"(rcept_no={ts[0]['rcept_no']})" in out.split("━━ 거래 ━━")[1]

    def test_원문은_최대_6건까지만_연다(self, wired, monkeypatch):
        ts = [dict(_FILING_ROW, rcept_no=f"202512{27 - i:02d}000418", rcept_dt=f"202512{27 - i:02d}")
              for i in range(7)]
        _doc_all_related(wired, monkeypatch, unrelated={t["rcept_no"] for t in ts})
        self._rows(monkeypatch, ts)
        out = srv.check_board_conflict("SKAI")
        assert len(wired.doc_text) == 6
        assert ("해당 유형 공시 7건 중 최근 6건 원문 확인 · 1건 미확인 — 상대방 관계 표기가 "
                "최대주주·특수관계인인 건 없음") in out

    def test_원문을_못_받은_건은_관계가_없다고_말하지_않는다(self, wired, monkeypatch):
        ts = _targets(1)
        _doc_all_related(wired, monkeypatch)   # 후보 접수번호에 원문 없음
        self._rows(monkeypatch, ts)
        out = srv.check_board_conflict("SKAI")
        assert "원문 미수신 1건" in out
        assert "원문을 받지 못해 관계를 확인하지 못한 건(관계가 없다는 뜻이 아닙니다):" in out


@pytest.mark.usefixtures("no_structured_dart")
def test_접수번호_모드에만_접수번호_한계_줄이_있다(wired):
    out = srv.check_board_conflict("SKAI", FILING)
    assert "- 접수번호 모드는 접수번호 앞 8자리가" in out
    block, _, _ = srv._board_conflict_block(
        CORP, "SKAI", [_PERIODIC_ROW, _FILING_ROW], _FILING_ROW, "k")
    assert "접수번호 모드는" not in block
    assert "분기보고서는 3월·9월 분기 제목만 정기보고서로 읽습니다" in block


@pytest.mark.usefixtures("no_structured_dart")
def test_창_모드_관계_칸을_못_읽으면_대시가_아니라_못_읽음이다(wired, monkeypatch):
    ts = _targets(1)
    monkeypatch.setattr(srv, "fetch_document_text", lambda *a, **kw: "관계 표가 없는 원문")
    monkeypatch.setattr(srv, "fetch_company_disclosures_with_status",
                        lambda *a, **kw: (ts + [_PERIODIC_ROW], FETCH_OK))
    out = srv.check_board_conflict("SKAI")
    assert "거래상대방 관계 (원문에서 읽지 못함)" in out
    assert "거래상대방 관계 「-」" not in out


def test_제목이_특수관계인_거래면_관계_칸과_무관하게_대상이다(monkeypatch):
    """「특수관계인에대한출자」는 제목이 상대방을 특수관계인으로 밝힌다 — 관계 칸이 「출자조합」이어도
    대조 대상이다(라이브 삼성전자 2026-07-30 2건). 관계 칸만 보면 창 모드에서 빠진다."""
    monkeypatch.setattr(srv, "parse_related_party_detail",
                        lambda text: {"counterparty": "삼성 투자조합", "relation": "출자조합"})
    p = srv._board_parties("특수관계인 출자 원문", "특수관계인에대한출자")
    assert p["counterparty"]["name"] == "삼성 투자조합" and p["related_party"] is True
    monkeypatch.setattr(srv, "parse_outflow_detail",
                        lambda text: {"counterparty": "갑", "relation": "출자조합"})
    assert srv._board_parties("원문", "타인에대한채무보증결정")["related_party"] is False
