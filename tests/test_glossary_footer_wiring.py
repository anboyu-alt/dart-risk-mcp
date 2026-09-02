"""MCP 도구 6종 말미의 「이 리포트에 나온 용어」 절 배선을 잠근다.

과제 4 — `core/explain.py`의 `glossary_footer`(과제 1)를 `server.py`의
`_glossary_block` 헬퍼가 감싸 6개 도구(analyze_company_risk·
check_disclosure_risk·find_risk_precedents·build_event_timeline·
track_capital_structure·track_turnover_trend) 말미에 붙인다. MCP 출력에는
마우스 오버가 없어 리포트 말미에 텍스트 절로 붙이지 않으면 MCP 클라이언트가
제 나름의 정의로 설명해 뷰어와 어긋난다(단일 출처 위반) — 이게 이 배선의
존재 이유다.

API 호출 없이 검증한다 — `tests/test_qualification_wiring.py`의
`check_disclosure_risk(report_name=...)` 직접 호출 패턴과
`tests/test_fetch_failure_honesty.py`의 `patch.object(srv, ...)` 패턴을
그대로 따른다.

## 이 파일이 잠그는 것

① 6개 도구 각각 — 해설이 찍힌 출력에 마커가 정확히 1회, 절 줄 수 ≤8,
   각 정의가 60자 이하, 절의 표제어가 전부 해설 본문(마커 이전)에 실제로
   등장한다(=passthrough가 아니라 진짜 렌더된 해설에서 나왔다는 증거).
② 해설이 하나도 안 찍힌 경로(관찰 신호 0건)에는 절이 없다.
③ passthrough 비스캔 — 공시 제목에만 있고 해설에는 없는 용어는 절에
   나타나지 않는다(동적 1건 + 6곳 호출부 전체의 정적 잠금).
④ 정적 — `_glossary_block(` 호출이 정확히 6회이고 각각이 대상 함수
   본문 안에 있다(AST로 함수 경계를 확인 — 문자열 탐색은 CLAUDE.md
   「인자 검증」 절이 경고하는 함정이 있다).
⑤ 배치 — 마커 이후에는 면책·안내 푸터만 오고 신호·패턴 본문이 오지
   않는다.

## 시나리오 선택 근거

여섯 곳 전부에 같은 신호(`REVERSE_SPLIT`, 제목 "주요사항보고서(감자결정)")를
쓴다 — 이 신호의 해설 **첫 문장**에 GLOSSARY 표제어 "감자"가 그대로
들어 있어(`"감자 또는 주식병합 공시입니다."`), 절단 여부와 무관하게
표제어가 실제 렌더된 문장에 등장한다는 것을 안전하게 검증할 수 있다.
DS005 12종 어디에도 걸리지 않아(`resolve_decision_type` 실측 공문자열)
`get_major_decision` 호출도 유발하지 않는다.

`track_capital_structure`만 한 가지 예외를 진 텍스트로 검증한다 —
CLAUDE.md가 명시하는 설계(그 도구의 시계열은 화면에 **첫 문장만** 자르지만
용어 절 입력은 **절단 전 전체**를 본다, 3PCA의 "제3자배정"이 둘째 문장에만
있다는 것이 그 근거다)를 `test_track_capital_structure_전체_텍스트를_본다`
로 별도 고정한다.
"""
from __future__ import annotations

import ast
import pathlib

import dart_risk_mcp.server as srv
from dart_risk_mcp.core import FETCH_OK
from dart_risk_mcp.core.explain import GLOSSARY

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SERVER_PY = _ROOT / "dart_risk_mcp" / "server.py"
_SRC = _SERVER_PY.read_text(encoding="utf-8")

_TOOL_NAMES = (
    "analyze_company_risk",
    "check_disclosure_risk",
    "find_risk_precedents",
    "build_event_timeline",
    "track_capital_structure",
    "track_turnover_trend",
)

_MARKER = "**이 리포트에 나온 용어**"

# 여섯 곳 전부에서 쓰는 공용 신호 — 첫 문장에 이미 "감자"가 들어 있다.
_REVERSE_SPLIT_TITLE = "주요사항보고서(감자결정)"
_REVERSE_SPLIT_FIRST_SENTENCE = "감자 또는 주식병합 공시입니다."


def _mk_disclosure(report_nm, rcept_no="20260101000001", rcept_dt="20260101",
                    corp_name="테스트기업"):
    return {
        "report_nm": report_nm,
        "rcept_no": rcept_no,
        "rcept_dt": rcept_dt,
        "corp_code": "00000001",
        "corp_name": corp_name,
        "flr_nm": corp_name,
    }


def _resolve_corp_stub(name, api_key):
    return ("테스트기업", {"corp_code": "00000001", "stock_code": "000000"})


def _split_glossary(out: str):
    """마커 인덱스로 (본문, 용어 절 줄들, 마커 이후 전체)를 가른다."""
    assert out.count(_MARKER) == 1, f"마커가 1회가 아니다: {out.count(_MARKER)}회\n{out}"
    idx = out.index(_MARKER)
    head = out[:idx]
    tail = out[idx + len(_MARKER):]
    lines = [ln for ln in tail.split("\n") if ln.startswith("- ")]
    return head, lines, tail


def _assert_glossary_section(out: str, required_terms: set):
    """① — 마커 1회·줄 수 ≤8·각 정의 ≤60자·표제어가 GLOSSARY 소속·
    표제어가 실제로 본문(마커 이전)에 등장한다."""
    head, lines, _ = _split_glossary(out)
    assert lines, "용어 절이 비어 있다"
    assert len(lines) <= 8, f"줄 수가 8을 넘는다: {len(lines)}"
    found_terms = set()
    for ln in lines:
        body = ln[2:]  # "- " 제거
        assert " — " in body, f"줄 형식이 다르다: {ln!r}"
        term, _, definition = body.partition(" — ")
        assert term in GLOSSARY, f"GLOSSARY에 없는 표제어: {term!r}"
        assert definition == GLOSSARY[term]
        assert len(definition) <= 60, f"{term}의 정의가 60자를 넘는다: {definition!r}"
        found_terms.add(term)
    for t in required_terms:
        assert t in found_terms, f"기대한 표제어 {t!r}가 절에 없다: {found_terms}"
        # passthrough가 아니라 실제 해설 본문에서 나왔다는 증거 — 마커
        # 이전 텍스트(신호·패턴 렌더 본문)에 표제어가 그대로 있어야 한다.
        assert t in head, (
            f"{t!r}가 용어 절에는 있는데 해설 본문(마커 이전)에는 없다 — "
            "passthrough로 새어 들어왔을 수 있다"
        )
    return found_terms


# ── ① + ⑤ 6개 도구 각각 ──────────────────────────────────────────────────


class TestAnalyzeCompanyRisk:
    def _run(self, monkeypatch):
        monkeypatch.setattr(srv, "_DART_API_KEY", "testkey")
        monkeypatch.setattr(srv, "resolve_corp", _resolve_corp_stub)
        monkeypatch.setattr(
            srv, "fetch_company_disclosures_with_status",
            lambda *a, **kw: ([_mk_disclosure(_REVERSE_SPLIT_TITLE)], FETCH_OK),
        )
        monkeypatch.setattr(srv, "fetch_fund_usage", lambda *a, **kw: [])
        monkeypatch.setattr(srv, "fetch_distress_events", lambda *a, **kw: [])
        monkeypatch.setattr(srv, "fetch_financial_statements_all", lambda *a, **kw: [])
        return srv.analyze_company_risk("테스트기업")

    def test_용어_절이_있고_감자를_포함한다(self, monkeypatch):
        out = self._run(monkeypatch)
        _assert_glossary_section(out, {"감자"})

    def test_말미에_있고_뒤에_본문이_오지_않는다(self, monkeypatch):
        """기본 lookback_years=1(deep=True)이면 shallow_notice·size footer가
        붙지 않아 용어 절이 리포트의 진짜 마지막 내용이어야 한다."""
        out = self._run(monkeypatch)
        _, _, tail = _split_glossary(out)
        # 용어 절 줄 다음에 남는 것은 개행뿐이어야 한다.
        after_lines = [ln for ln in tail.split("\n") if ln.strip() and not ln.startswith("- ")]
        assert not after_lines, f"용어 절 뒤에 본문이 남아 있다: {after_lines}"


class TestCheckDisclosureRisk:
    def test_용어_절이_있고_감자를_포함한다(self):
        out = srv.check_disclosure_risk(report_name=_REVERSE_SPLIT_TITLE)
        _assert_glossary_section(out, {"감자"})

    def test_말미에_있고_뒤에_아무것도_없다(self):
        out = srv.check_disclosure_risk(report_name=_REVERSE_SPLIT_TITLE)
        assert out.rstrip("\n").endswith(
            "- 감자 — " + GLOSSARY["감자"]
        ), "용어 절이 출력의 마지막이 아니다"

    def test_passthrough_비스캔_동적(self):
        """제목에 심어 둔 GLOSSARY 표제어(매출채권)는 REVERSE_SPLIT 해설에
        없어 절에 나타나면 안 된다 — "매출채권"은 어떤 신호 키워드도 아니라서
        (core/signals.py 실측) 이 제목이 여전히 REVERSE_SPLIT 하나만
        매칭하고, 절 자체는 정당한 "감자"만으로 채워진다(마커가 아예 안
        뜨는 경우와 구분하기 위해 일부러 진짜 신호와 decoy를 함께 심었다)."""
        title = "주요사항보고서(감자결정)(매출채권 관련 참고)"
        out = srv.check_disclosure_risk(report_name=title)
        assert "매출채권" in out, "제목 자체에는 있어야 한다(head 확인용 전제)"
        found_terms = _assert_glossary_section(out, {"감자"})
        assert "매출채권" not in found_terms, (
            "제목에만 있는 용어가 용어 절에 새어 들어왔다 — passthrough"
        )

    def test_해설이_없으면_절이_없다(self):
        """관찰 신호 0건(강등만 있는 공시)에는 🎯 prose가 안 찍히므로 절도 없다."""
        out = srv.check_disclosure_risk(
            report_name="주식등의대량보유상황보고서(일반)"
        )
        assert _MARKER not in out


class TestFindRiskPrecedents:
    def test_용어_절이_있고_감자를_포함한다(self):
        out = srv.find_risk_precedents(["REVERSE_SPLIT"])
        _assert_glossary_section(out, {"감자"})

    def test_말미에_있고_뒤에_아무것도_없다(self):
        out = srv.find_risk_precedents(["REVERSE_SPLIT"])
        assert out.rstrip("\n").endswith(
            "- 감자 — " + GLOSSARY["감자"]
        )

    def test_알수없는_신호만_주면_해설이_없어_절도_없다(self):
        out = srv.find_risk_precedents(["존재하지않는키"])
        assert _MARKER not in out

    def test_패턴_prose도_모은다(self):
        """2개 이상 신호가 전부 일치하는 등록 패턴을 찾으면 그 PATTERN_PROSE도
        용어 절 입력에 들어간다 — "capital_churn_anomaly"(2.7+4.3, CAPITAL_CHURN
        + DISCLOSURE_VIOL로 전부 일치)는 "희석"이라는 GLOSSARY 표제어를
        포함한다(실측 확인). 두 신호의 개별 SIGNAL_PROSE에는 GLOSSARY 표제어가
        없어, 이 절이 순수하게 패턴 prose에서만 나온 것임을 보장한다."""
        out = srv.find_risk_precedents(["CAPITAL_CHURN", "DISCLOSURE_VIOL"])
        # 패턴 서술이 실제로 찍혔는지 먼저 확인(전제 조건).
        assert "이 신호들이 동시에 나타날 때의 의미" in out
        _assert_glossary_section(out, {"희석"})


class TestBuildEventTimeline:
    def _run(self, monkeypatch):
        monkeypatch.setattr(srv, "_DART_API_KEY", "testkey")
        monkeypatch.setattr(srv, "resolve_corp", _resolve_corp_stub)
        monkeypatch.setattr(
            srv, "fetch_company_disclosures_with_status",
            lambda *a, **kw: ([_mk_disclosure(_REVERSE_SPLIT_TITLE)], FETCH_OK),
        )
        monkeypatch.setattr(srv, "fetch_financial_statements_all", lambda *a, **kw: [])
        return srv.build_event_timeline("테스트기업")

    def test_용어_절이_있고_감자를_포함한다(self, monkeypatch):
        out = self._run(monkeypatch)
        _assert_glossary_section(out, {"감자"})

    def test_말미에_있고_뒤에는_고정_면책_문구만_온다(self, monkeypatch):
        out = self._run(monkeypatch)
        _, _, tail = _split_glossary(out)
        after = [ln for ln in tail.split("\n") if ln.strip() and not ln.startswith("- ")]
        # deep=True(기본 1년)면 shallow_notice가 안 붙어 고정 면책 문구
        # 한 줄만 남아야 한다.
        assert after == [
            "⚠️ 이 타임라인은 공시 제목 기반 자동 분류이며, 실제 상황과 다를 수 있습니다."
        ], after
        for bad in ("🎯", "확인해볼 것", "관찰됨:", "[진입기]", "[심화기]", "[탈출기]"):
            assert bad not in "\n".join(after), f"본문 마커 {bad!r}가 용어 절 뒤에 있다"


class TestTrackCapitalStructure:
    def _base_patches(self, monkeypatch):
        monkeypatch.setenv("DART_API_KEY", "testkey")
        monkeypatch.setattr(srv, "resolve_corp", _resolve_corp_stub)
        monkeypatch.setattr(srv, "fetch_treasury_decisions", lambda *a, **kw: [])
        monkeypatch.setattr(srv, "_mezzanine_block", lambda *a, **kw: [])
        monkeypatch.setattr(srv, "_dilution_block", lambda *a, **kw: [])
        monkeypatch.setattr(
            srv, "fetch_debt_balance",
            lambda *a, **kw: {"total": 0, "year": None, "maturity_1y_share": 0.0},
        )

    def test_용어_절이_있고_감자를_포함한다(self, monkeypatch):
        self._base_patches(monkeypatch)
        monkeypatch.setattr(
            srv, "fetch_company_disclosures_with_status",
            lambda *a, **kw: ([_mk_disclosure(_REVERSE_SPLIT_TITLE)], FETCH_OK),
        )
        out = srv.track_capital_structure("테스트기업")
        _assert_glossary_section(out, {"감자"})

    def test_말미에_있고_뒤에는_고정_참고_문구만_온다(self, monkeypatch):
        self._base_patches(monkeypatch)
        monkeypatch.setattr(
            srv, "fetch_company_disclosures_with_status",
            lambda *a, **kw: ([_mk_disclosure(_REVERSE_SPLIT_TITLE)], FETCH_OK),
        )
        out = srv.track_capital_structure("테스트기업")
        _, _, tail = _split_glossary(out)
        after = [ln for ln in tail.split("\n") if ln.strip() and not ln.startswith("- ")]
        assert len(after) == 1
        assert after[0].startswith("📎 참고:")
        for bad in ("🎯", "시계열", "확인해볼 것", "▸"):
            assert bad not in after[0]

    def test_패턴_prose도_모은다(self, monkeypatch):
        """희석성 자본 이벤트 3건(12개월 이내)이면 CAPITAL_CHURN이 뜨고
        capital_churn_anomaly 패턴 서술("희석" 포함)도 용어 절에 실린다."""
        self._base_patches(monkeypatch)
        rows = [
            _mk_disclosure(_REVERSE_SPLIT_TITLE, rcept_no="1"*14, rcept_dt="20260101"),
            _mk_disclosure(_REVERSE_SPLIT_TITLE, rcept_no="2"*14, rcept_dt="20260201"),
            _mk_disclosure(_REVERSE_SPLIT_TITLE, rcept_no="3"*14, rcept_dt="20260301"),
        ]
        monkeypatch.setattr(
            srv, "fetch_company_disclosures_with_status",
            lambda *a, **kw: (rows, FETCH_OK),
        )
        out = srv.track_capital_structure("테스트기업")
        assert "유사 패턴 서술" in out  # 전제 조건 — 패턴이 실제로 렌더됐는지
        _assert_glossary_section(out, {"감자", "희석"})

    def test_track_capital_structure_전체_텍스트를_본다(self, monkeypatch):
        """CLAUDE.md의 명시적 설계 — 화면의 시계열 한 줄은 **첫 문장만**
        잘라 보여주지만(`meaning.split("다.")[0] + "다."`), 용어 절 입력은
        절단 전 전체 해설을 본다. 3PCA의 "제3자배정"은 둘째 문장에만 있어
        (`"유상증자 공시입니다."`가 첫 문장), 이 사실을 직접 증명한다.
        """
        self._base_patches(monkeypatch)
        title = "주요사항보고서(제3자배정유상증자결정)"
        monkeypatch.setattr(
            srv, "fetch_company_disclosures_with_status",
            lambda *a, **kw: ([_mk_disclosure(title)], FETCH_OK),
        )
        out = srv.track_capital_structure("테스트기업")
        head, lines, _ = _split_glossary(out)
        found_terms = {ln[2:].split(" — ", 1)[0] for ln in lines}
        assert "제3자배정" in found_terms, "절단 전 전체 해설에서 나와야 하는 용어가 없다"
        # 화면에 실제로 찍힌 한 줄(첫 문장만)에는 이 표제어가 없다 — 그래서
        # "표제어가 해설 본문에 등장" 일반 규칙과 달리 이 도구는 예외라는
        # 사실 자체가 이 테스트의 요점이다.
        assert "유상증자 공시입니다." in head
        # one_liner로 실제 렌더된 줄만 뽑아 검사 — meaning 전체(제3자배정
        # 포함)가 아니라 절단된 한 줄만 남아 있어야 한다.
        rendered_line = next(
            ln for ln in head.split("\n") if ln.strip().startswith("→ ")
        )
        assert "제3자배정" not in rendered_line, (
            "화면에 찍힌 한 줄에 아직 절단되지 않은 문장이 남아 있다 — "
            "이 테스트의 전제(첫 문장 절단)가 깨졌다"
        )


class TestTrackTurnoverTrend:
    def _period(self):
        return {
            "매출액": 1000,
            "매출원가": 600,
            "매출채권": 100,
            "재고자산": 150,
            "매입채무": 120,
            "유동자산": 500,
            "유동부채": 200,
            "자산총계": 2000,
        }

    def _run(self, monkeypatch):
        monkeypatch.setenv("DART_API_KEY", "testkey")
        monkeypatch.setattr(srv, "resolve_corp", _resolve_corp_stub)
        monkeypatch.setattr(
            srv, "fetch_turnover_history",
            lambda *a, **kw: {
                "years_requested": ["2023"],
                "years_retrieved": ["2023"],
                "years_failed": [],
                "fs_div": {"2023": "CFS"},
                "periods": {"2023": self._period()},
            },
        )
        monkeypatch.setattr(srv, "fetch_financial_statements_all", lambda *a, **kw: [])
        return srv.track_turnover_trend("테스트기업")

    def test_용어_절이_있고_매출채권을_포함한다(self, monkeypatch):
        out = self._run(monkeypatch)
        _assert_glossary_section(out, {"매출채권"})

    def test_말미에_있고_뒤에는_고정_면책_문구만_온다(self, monkeypatch):
        out = self._run(monkeypatch)
        _, _, tail = _split_glossary(out)
        after = [ln for ln in tail.split("\n") if ln.strip() and not ln.startswith("- ")]
        assert after, "면책 문구가 있어야 한다"
        assert after[0].startswith("기말잔액 기준으로 계산했습니다")
        assert any(ln.startswith("⚠️") for ln in after)
        for bad in ("- 매출채권회전율", "**지표 읽는 법**"):
            assert bad not in "\n".join(after)

    def test_값이_없으면_해설도_절도_없다(self, monkeypatch):
        """계산되지 않은 지표만 있으면 _prose_keys가 비어 절도 안 붙는다."""
        monkeypatch.setenv("DART_API_KEY", "testkey")
        monkeypatch.setattr(srv, "resolve_corp", _resolve_corp_stub)
        monkeypatch.setattr(
            srv, "fetch_turnover_history",
            lambda *a, **kw: {
                "years_requested": ["2023"],
                "years_retrieved": ["2023"],
                "years_failed": [],
                "fs_div": {"2023": "CFS"},
                # 회전율 계산에 필요한 계정이 전혀 없는 회사 — 값이 전부 None.
                "periods": {"2023": {}},
            },
        )
        monkeypatch.setattr(srv, "fetch_financial_statements_all", lambda *a, **kw: [])
        out = srv.track_turnover_trend("테스트기업")
        assert _MARKER not in out


# ── ② 해설이 없으면 절이 없다(공용 케이스) ──────────────────────────────


def test_analyze_company_risk_공시가_없으면_절이_없다(monkeypatch):
    monkeypatch.setattr(srv, "_DART_API_KEY", "testkey")
    monkeypatch.setattr(srv, "resolve_corp", _resolve_corp_stub)
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: ([], FETCH_OK),
    )
    monkeypatch.setattr(srv, "fetch_fund_usage", lambda *a, **kw: [])
    monkeypatch.setattr(srv, "fetch_distress_events", lambda *a, **kw: [])
    monkeypatch.setattr(srv, "fetch_financial_statements_all", lambda *a, **kw: [])
    out = srv.analyze_company_risk("테스트기업")
    assert _MARKER not in out


def test_build_event_timeline_공시가_없으면_절이_없다(monkeypatch):
    monkeypatch.setattr(srv, "_DART_API_KEY", "testkey")
    monkeypatch.setattr(srv, "resolve_corp", _resolve_corp_stub)
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: ([], FETCH_OK),
    )
    out = srv.build_event_timeline("테스트기업")
    assert _MARKER not in out


def test_track_capital_structure_자본_이벤트가_없으면_절이_없다(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "testkey")
    monkeypatch.setattr(srv, "resolve_corp", _resolve_corp_stub)
    monkeypatch.setattr(srv, "fetch_treasury_decisions", lambda *a, **kw: [])
    monkeypatch.setattr(srv, "_mezzanine_block", lambda *a, **kw: [])
    monkeypatch.setattr(srv, "_dilution_block", lambda *a, **kw: [])
    monkeypatch.setattr(
        srv, "fetch_debt_balance",
        lambda *a, **kw: {"total": 0, "year": None, "maturity_1y_share": 0.0},
    )
    monkeypatch.setattr(
        srv, "fetch_company_disclosures_with_status",
        lambda *a, **kw: ([], FETCH_OK),
    )
    out = srv.track_capital_structure("테스트기업")
    assert _MARKER not in out


# ── ③ passthrough 비스캔 — 6곳 호출부 전체의 정적 잠금 ──────────────────


def _function_source(name: str) -> str:
    """`name` 함수 정의부터 다음 최상위 정의(데코레이터 포함) 직전까지."""
    start = _SRC.index(f"def {name}(")
    tail = _SRC[start:]
    candidates = []
    for marker in ("\n@mcp.tool()", "\ndef main("):
        idx = tail.find(marker, 1)
        if idx != -1:
            candidates.append(idx)
    end = min(candidates) if candidates else len(tail)
    return tail[:end]


# `_glossary_texts`에 실려도 되는 것은 우리가 만든 해설 문자열뿐이다 —
# signal_to_prose/pattern_to_prose의 반환값(meaning/prose/prose_body/
# pattern)과 TURNOVER_PROSE 필드(_p[...])만 허용한다. report_nm·title·
# corp_name·label처럼 DART 원문이나 표시용 라벨을 가리키는 이름은 전부 금지.
_ALLOWED_GLOSSARY_SOURCES = {"meaning", "prose", "prose_body", "pattern"}
_FORBIDDEN_SUBSTRINGS = (
    "report_nm", "corp_name", "corp_info", "title", "label",
    "d[", "e[\"report_nm\"", "e['report_nm'", "evt[", "sig[\"label\"",
    "sig['label'", "q.label", "_d[", "_r[",
)


def test_glossary_texts_수집이_여섯_곳_모두에_있다():
    for name in _TOOL_NAMES:
        body = _function_source(name)
        assert "_glossary_texts" in body, f"{name}에 용어 절 수집이 없다"


def test_glossary_texts에_report_nm이나_title을_넘기지_않는다():
    """정적 잠금 — 여섯 함수 전부에서 `_glossary_texts`를 채우는 표현이
    DART 원문·제목·라벨을 가리키는 변수명을 쓰지 않는다."""
    for name in _TOOL_NAMES:
        body = _function_source(name)
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped.startswith("_glossary_texts"):
                continue
            for bad in _FORBIDDEN_SUBSTRINGS:
                assert bad not in stripped, (
                    f"{name}의 `_glossary_texts` 수집 줄이 passthrough로 "
                    f"보이는 표현({bad!r})을 담고 있다: {stripped!r}"
                )


def test_glossary_texts_append_인자가_허용_목록_안에_있다():
    """`.append(X)` 형태의 X가 허용된 이름(meaning/prose/prose_body/
    pattern) 또는 TURNOVER_PROSE 필드(`_p[...]`)여야 한다."""
    for name in _TOOL_NAMES:
        body = _function_source(name)
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped.startswith("_glossary_texts.append("):
                continue
            arg = stripped[len("_glossary_texts.append("):].rstrip(")")
            assert arg in _ALLOWED_GLOSSARY_SOURCES or arg.startswith("_p["), (
                f"{name}의 append 인자가 허용 목록 밖이다: {arg!r}"
            )


# ── ④ 정적: `_glossary_block(` 호출이 정확히 6회, 각각 대상 함수 안 ──────


def test_glossary_block_호출이_정확히_6회다():
    assert _SRC.count("_glossary_block(_glossary_texts)") == 6, (
        f"호출 횟수가 6이 아니다: {_SRC.count('_glossary_block(_glossary_texts)')}"
    )


def test_glossary_block_각_호출이_대상_함수_안에_있다():
    """AST로 함수 경계를 확인한다 — 문자열 인덱싱은 데코레이터·docstring·
    중첩 함수 경계를 잘못 잡을 수 있다(CLAUDE.md 「인자 검증」 절의 경고)."""
    tree = ast.parse(_SRC)
    module_funcs = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    for name in _TOOL_NAMES:
        assert name in module_funcs, f"{name}이 최상위 함수로 없다"

    call_count_per_fn = {name: 0 for name in _TOOL_NAMES}
    total_calls = 0
    for name, node in module_funcs.items():
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id == "_glossary_block"
            ):
                total_calls += 1
                if name in call_count_per_fn:
                    call_count_per_fn[name] += 1
                else:
                    raise AssertionError(
                        f"_glossary_block 호출이 대상 밖 함수 {name!r}에 있다"
                    )

    assert total_calls == 6, f"모듈 최상위 함수 전체에서 호출이 6회가 아니다: {total_calls}"
    for name, count in call_count_per_fn.items():
        assert count == 1, f"{name}의 _glossary_block 호출 횟수가 1이 아니다: {count}"


def test_glossary_block_이_모듈_밖에서_호출되지_않는다():
    """`_glossary_block(` 자체의 전체 출현 횟수도 6이어야 한다 — 정의
    자체(`def _glossary_block(`)는 포함하지 않도록 정확히 인자 형태로 센다."""
    calls = [
        m for m in _SRC.split("_glossary_block(") if not m.startswith("texts")
    ]
    # split 특성상 마지막 조각은 호출이 아닌 나머지 본문이라 -1을 뺀다.
    assert _SRC.count("_glossary_block(_glossary_texts)") == 6


# ── `_glossary_block` 헬퍼 자체 ─────────────────────────────────────────


def test_glossary_block_빈_입력은_빈_문자열이다():
    assert srv._glossary_block([]) == ""
    assert srv._glossary_block(["아무 전문어도 없는 문장입니다."]) == ""


def test_glossary_block_앞에_빈_줄_하나를_둔다():
    out = srv._glossary_block(["전환사채 이야기입니다."])
    assert out.startswith("\n" + _MARKER)
    assert not out.startswith("\n\n")


def test_glossary_block_glossary_footer를_그대로_감싼다():
    from dart_risk_mcp.core.explain import glossary_footer

    texts = ["감자 이야기와 리픽싱 이야기입니다."]
    assert srv._glossary_block(texts) == "\n" + glossary_footer(texts)


# ── Task 1이 남긴 것: KNOWN_UNUSED에서 glossary_footer 제거 확인 ────────


def test_glossary_footer가_더_이상_KNOWN_UNUSED가_아니다():
    from tests.test_unused_exports import KNOWN_UNUSED

    assert "glossary_footer" not in KNOWN_UNUSED


def test_glossary_footer가_실제로_호출된다():
    """`ast.Call`만 세는 `_called_names()`와 같은 판정 — 이름이 서버
    소스에서 실제 호출 형태로 등장하는지 직접 확인한다."""
    tree = ast.parse(_SRC)
    called = {
        (getattr(n.func, "id", None) or getattr(n.func, "attr", None))
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert "glossary_footer" in called
