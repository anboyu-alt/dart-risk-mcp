"""이사회 이해상충 블록을 analyze·timeline·check_disclosure_risk에 배선 (Task 6).

네트워크는 전부 막는다 — 서버 모듈이 이름으로 import한 함수를 `srv.<name>`으로 패치하고
Task 1 픽스처(SKAI 357880 실공시 원문)를 먹인다. 상대방 확인(`_confirm_*`)은 행을 직접
돌려줘 「계열·최대주주로 확인된 거래가 있는가」만 바꾼다.
"""
import json
import pathlib

import pytest

import dart_risk_mcp.server as srv
from dart_risk_mcp.core.dart_client import FETCH_OK, FetchList

_FIX = pathlib.Path(__file__).parent / "fixtures" / "board"

CORP = "01381984"
FILING = "20251219000418"
PERIODIC = "20260323001292"
CONTROL = "20261023000221"
TITLE = "주요사항보고서(타법인주식및출자증권양수결정)"
LABEL = "이사회 결의 참여 이사의 상대방·대상회사 겸직"

_FILING_ROW = {
    "rcept_no": FILING, "corp_code": CORP, "corp_name": "SKAI",
    "report_nm": TITLE, "rcept_dt": "20251219", "flr_nm": "SKAI",
}
_PERIODIC_ROW = {
    "rcept_no": PERIODIC, "corp_code": CORP, "corp_name": "SKAI",
    "report_nm": "사업보고서 (2025.12)", "rcept_dt": "20260323", "flr_nm": "SKAI",
}
_CONTROL_ROW = {
    "rcept_no": CONTROL, "corp_code": "00999999", "corp_name": "데이원컴퍼니",
    "report_nm": TITLE, "rcept_dt": "20261023", "flr_nm": "데이원컴퍼니",
}


def _txt(name: str) -> str:
    return (_FIX / name).read_text(encoding="utf-8")


def _affiliated_row(classification="affiliated", relation="최대주주"):
    return srv._outflow_row(
        "20251219", TITLE, FILING, "주식회사 디렉터스컴퍼니", relation,
        classification, 0)


class _Calls:
    def __init__(self):
        self.doc_text = []
        self.audit_text = []
        self.roster = []


@pytest.fixture
def wired(monkeypatch):
    """네트워크 전부 차단 + SKAI 픽스처 연결."""
    calls = _Calls()
    roster = json.loads(_txt("exctvSttus_01381984_2025_11011.json"))
    monkeypatch.setattr(srv, "_api_key", lambda: "k")
    monkeypatch.setattr(srv, "_DART_API_KEY", "k")
    monkeypatch.setattr(
        srv, "resolve_corp",
        lambda q, k: ("SKAI", {"corp_code": CORP, "stock_code": "357880"}))
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: (FetchList([_PERIODIC_ROW, _FILING_ROW]), FETCH_OK))
    monkeypatch.setattr(srv, "fetch_major_decision", lambda *a, **kw: {"error": "x"})

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
    # 상대방 확인: 기본은 계열 최대주주로 확인된 1건
    monkeypatch.setattr(
        srv, "_confirm_outflow_counterparties",
        lambda *a, **kw: [_affiliated_row()])
    monkeypatch.setattr(srv, "_confirm_acquisition_targets", lambda *a, **kw: [])
    return calls


def _no_calls(c: _Calls):
    return not c.doc_text and not c.audit_text and not c.roster


def _observed_section(out: str) -> str:
    head = out.split("━━ 관찰된 신호", 1)[1]
    return head.split("\n━━ ", 1)[0]


# ── analyze_company_risk ───────────────────────────────────────────────────

@pytest.mark.usefixtures("no_structured_dart")
class TestAnalyzeWiring:
    def test_계열_행이_없으면_원문도_명부도_열지_않는다(self, wired, monkeypatch):
        monkeypatch.setattr(
            srv, "_confirm_outflow_counterparties",
            lambda *a, **kw: [_affiliated_row("external", "타인")])
        out = srv.analyze_company_risk("SKAI")
        assert _no_calls(wired)
        assert "이사회 이해상충" not in out

    def test_확인_행이_전혀_없어도_호출_0회(self, wired, monkeypatch):
        monkeypatch.setattr(srv, "_confirm_outflow_counterparties", lambda *a, **kw: [])
        out = srv.analyze_company_risk("SKAI")
        assert _no_calls(wired)
        assert "이사회 이해상충" not in out

    def test_계열_행이_있으면_한_번만_확인한다(self, wired):
        out = srv.analyze_company_risk("SKAI")
        assert wired.doc_text == [FILING]
        assert wired.audit_text == [PERIODIC]
        assert wired.roster == [(CORP, "2025", "11011")]
        assert "🪑 **이사회 이해상충 확인**" in out
        assert "━━ 겸직 대조 ━━" in out
        assert out.count("📎 사실 표기입니다") == 1

    def test_최대주주_표기만_있어도_후보다(self, wired, monkeypatch):
        monkeypatch.setattr(
            srv, "_confirm_outflow_counterparties",
            lambda *a, **kw: [_affiliated_row("unknown", "최대주주")])
        srv.analyze_company_risk("SKAI")
        assert wired.doc_text == [FILING]

    def test_후보가_여럿이면_최근_1건만_보고_미확인_건수를_적는다(self, wired, monkeypatch):
        older = srv._outflow_row("20240101", TITLE, "20240101000001",
                                 "다른회사", "계열회사", "affiliated", 0)
        monkeypatch.setattr(
            srv, "_confirm_outflow_counterparties",
            lambda *a, **kw: [older, _affiliated_row()])
        out = srv.analyze_company_risk("SKAI")
        assert wired.doc_text == [FILING]
        assert "해당 2건 중 최근 1건 확인 · 1건 미확인" in out

    def test_지도_모드는_생략한다(self, wired):
        out = srv.analyze_company_risk("SKAI", lookback_years=3)
        assert _no_calls(wired)
        assert "이사회 이해상충" not in out

    def test_겹침이_서면_관찰된_신호_절에_BOARD_CONFLICT가_나온다(self, wired):
        out = srv.analyze_company_risk("SKAI")
        assert "🎯 " + LABEL in out          # 블록 안의 게이트 줄
        assert LABEL in _observed_section(out)
        # 신호는 결의 공시의 접수일·제목으로 서고 정정공시가 아니다
        assert "이사회 결의 참여 이사 겸직 확인 — 주요사항보고서" in _observed_section(out)

    def test_겹침이_안_서면_신호가_없다(self, wired, monkeypatch):
        monkeypatch.setattr(
            srv, "fetch_executive_roster_rows", lambda *a, **kw: FetchList())
        out = srv.analyze_company_risk("SKAI")
        assert "🪑 **이사회 이해상충 확인**" in out
        assert LABEL not in _observed_section(out)

    def test_블록_예외는_블록만_빼고_한_줄을_남긴다(self, wired, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("net")

        monkeypatch.setattr(srv, "_board_conflict_block", boom)
        out = srv.analyze_company_risk("SKAI")
        assert "이사회 이해상충 확인: 조회 실패로 확인하지 못했습니다" in out
        assert "━━ 겸직 대조 ━━" not in out
        assert LABEL not in out
        assert "기업 공시 관찰 요약: SKAI" in out        # 리포트는 정상 반환

    def test_BOARD_CONFLICT는_의도적으로_헤드라인_후보다(self, wired):
        """의도된 동작 — 이 신호는 제목이 아니라 원문(의결표+임원현황) 대조의 산물이라
        `AMBIGUOUS_SIGNAL_KEYS`(제목만으론 양면적인 신호)가 아니다. 다른 관찰 신호가
        전부 양면적(ACQ_REVIEW 등)이면 이 신호가 요약의 대표 유형이 된다."""
        out = srv.analyze_company_risk("SKAI")
        summary = out.split("조회 기간:", 1)[0]
        assert LABEL in summary

    def test_블록_예외는_트레이스백을_로그에_남긴다(self, wired, monkeypatch, caplog):
        def boom(*a, **kw):
            raise KeyError("code fault")

        monkeypatch.setattr(srv, "_board_conflict_block", boom)
        with caplog.at_level("ERROR"):
            srv.analyze_company_risk("SKAI")
        assert any("이사회 이해상충 블록 생성 실패" in r.getMessage() and r.exc_info
                   for r in caplog.records)

    def test_판정_어휘가_없다(self, wired):
        out = srv.analyze_company_risk("SKAI")
        block = out.split("🪑 **이사회 이해상충 확인**", 1)[1].split("📎 사실 표기입니다", 1)[0]
        for w in ("제척 없음", "위험", "심각", "의심", "점수", "등급"):
            assert w not in block, w


# ── build_event_timeline ───────────────────────────────────────────────────

@pytest.mark.usefixtures("no_structured_dart")
class TestTimelineWiring:
    def test_결의_공시_이벤트_줄_끝에_요약이_붙는다(self, wired):
        out = srv.build_event_timeline("SKAI")
        line = next(ln for ln in out.splitlines()
                    if TITLE in ln and " · 🪑 " in ln and f"[{LABEL}]" not in ln)
        assert " · 🪑 이사 7인 중 4인이 상대방·대상회사 임원 겸직" in line

    def test_겹침이_서면_타임라인에_BOARD_CONFLICT_이벤트가_더해진다(self, wired):
        out = srv.build_event_timeline("SKAI")
        assert any(f"[{LABEL}]" in ln for ln in out.splitlines())
        assert "🪑 **이사회 이해상충 확인**" in out

    def test_같은_접수번호가_신호_둘이면_요약은_첫_줄에만_붙는다(self, wired, monkeypatch):
        orig = srv.match_signals
        extra = next(t for t in srv.SIGNAL_TYPES if t["key"] == "RELATED_PARTY")

        def two(title):
            got = list(orig(title))
            if title == TITLE:
                got.append(dict(extra))
            return got

        monkeypatch.setattr(srv, "match_signals", two)
        # RELATED_PARTY가 켜지면 원문 사실 블록이 따로 DART를 부른다 — 이 테스트의 관심 밖
        monkeypatch.setattr(srv, "_related_party_detail_block", lambda *a, **kw: [])
        out = srv.build_event_timeline("SKAI")
        same = [ln for ln in out.splitlines()
                if TITLE in ln and f"[{LABEL}]" not in ln and ln.lstrip().startswith("•")]
        assert len(same) >= 2                      # 전제: 한 공시가 이벤트 줄 둘
        assert sum(" · 🪑 " in ln for ln in same) == 1

    def test_후보가_없으면_호출_0회(self, wired, monkeypatch):
        monkeypatch.setattr(
            srv, "_confirm_outflow_counterparties",
            lambda *a, **kw: [_affiliated_row("external", "타인")])
        out = srv.build_event_timeline("SKAI")
        assert _no_calls(wired)
        assert "🪑" not in out

    def test_지도_모드는_생략한다(self, wired):
        out = srv.build_event_timeline("SKAI", lookback_years=3)
        assert _no_calls(wired)
        assert "🪑" not in out

    def test_블록_예외는_타임라인을_막지_않는다(self, wired, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("net")

        monkeypatch.setattr(srv, "_board_conflict_block", boom)
        out = srv.build_event_timeline("SKAI")
        assert "조회 실패로 확인하지 못했습니다" in out
        assert "이벤트 타임라인: SKAI" in out
        assert LABEL not in out



# ── check_disclosure_risk ──────────────────────────────────────────────────

@pytest.mark.usefixtures("no_structured_dart")
class TestRiskCheckWiring:
    @pytest.fixture(autouse=True)
    def _row(self, no_structured_dart, wired, monkeypatch):
        self.rows = {FILING: _FILING_ROW, CONTROL: _CONTROL_ROW}
        monkeypatch.setattr(
            srv, "resolve_disclosure_row_with_status",
            lambda rcept, k, *a, **kw: (self.rows[rcept], "found"))
        monkeypatch.setattr(
            srv, "resolve_corp_code_from_rcept_no", lambda *a, **kw: "")

    def test_특수관계_거래_공시면_블록이_붙는다(self, wired):
        out = srv.check_disclosure_risk(rcept_no=FILING)
        assert f"🪑 SKAI — 이사회 이해상충 확인 · {FILING}" in out
        assert "━━ 겸직 대조 ━━" in out
        assert out.count("📎 사실 표기입니다") == 1
        assert wired.audit_text == [PERIODIC]

    def test_대조군은_블록이_없다(self, wired, monkeypatch):
        monkeypatch.setattr(
            srv, "fetch_company_disclosures_with_status",
            lambda *a, **kw: (FetchList([_CONTROL_ROW]), FETCH_OK))
        out = srv.check_disclosure_risk(rcept_no=CONTROL)
        assert "이사회 이해상충" not in out
        assert wired.audit_text == [] and wired.roster == []

    def test_1차_대상이_아닌_제목이면_원문도_열지_않는다(self, wired):
        self.rows[FILING] = dict(_FILING_ROW, report_nm="주주총회소집공고")
        out = srv.check_disclosure_risk(rcept_no=FILING)
        assert "이사회 이해상충" not in out
        assert wired.audit_text == []

    def test_정정공시면_블록이_없다(self, wired):
        self.rows[FILING] = dict(_FILING_ROW, report_nm="[기재정정]" + TITLE)
        out = srv.check_disclosure_risk(rcept_no=FILING)
        assert "이사회 이해상충" not in out

    def test_행_복원_실패면_블록이_없다(self, wired, monkeypatch):
        monkeypatch.setattr(
            srv, "resolve_disclosure_row_with_status",
            lambda *a, **kw: (None, "error"))
        out = srv.check_disclosure_risk(rcept_no=FILING, report_name=TITLE)
        assert "이사회 이해상충" not in out
        assert wired.audit_text == []

    def test_블록_예외는_분석을_막지_않는다(self, wired, monkeypatch):
        def boom(*a, **kw):
            raise RuntimeError("net")

        monkeypatch.setattr(srv, "_board_conflict_block", boom)
        out = srv.check_disclosure_risk(rcept_no=FILING)
        assert "조회 실패로 확인하지 못했습니다" in out
        assert "공시 리스크 분석" in out


# ── 시장 반응 블록 입력 ────────────────────────────────────────────────────

def test_시장_반응_후보에_BOARD_CONFLICT는_들어가지_않는다(monkeypatch):
    seen = {}

    def fake_series(stock, cls, start, end, key, **kw):
        seen["start"], seen["end"] = start, end
        return {"rows": []}

    monkeypatch.setattr(srv, "_market_series", fake_series)
    monkeypatch.setattr(srv, "fetch_market_alerts",
                        lambda *a, **kw: {"alerts": []})
    events = [
        {"key": "BOARD_CONFLICT", "label": "BC라벨", "rcept_dt": "20260301",
         "rcept_no": "1", "is_amendment": False},
        {"key": "ACQ_REVIEW", "label": "AR라벨", "rcept_dt": "20250101",
         "rcept_no": "2", "is_amendment": False},
    ]
    lines = srv._market_reaction_block(events, "357880", "K", "krxkey", lookback_days=365)
    text = "\n".join(lines)
    assert "AR라벨" in text
    assert "BC라벨" not in text
    assert seen["end"] < "20260301"      # 시세 창도 BOARD_CONFLICT 날짜로 늘지 않는다


# ── 후보 선택 (순수 함수) ──────────────────────────────────────────────────

class TestCandidates:
    def test_계열이거나_최대주주_표기에_1차_대상_제목만_후보다(self):
        rows = [
            _affiliated_row("affiliated", "계열회사"),
            srv._outflow_row("20251101", TITLE, "20251101000001", "x", "타인", "external", 0),
            srv._outflow_row("20251102", "주주총회소집공고", "20251102000001",
                             "x", "최대주주", "affiliated", 0),
            srv._outflow_row("20251103", TITLE, "20251103000001", "x", "최대주주", "unknown", 0),
        ]
        got = srv._board_candidates(rows)
        assert [r["rcept_no"] for r in got] == [FILING, "20251103000001"]

    def test_접수번호가_겹치면_한_번만(self):
        a = _affiliated_row()
        assert len(srv._board_candidates([a], [dict(a)])) == 1

    def test_빈_입력(self):
        assert srv._board_candidates(None, []) == []
