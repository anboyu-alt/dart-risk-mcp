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

## 컨트롤러 정정 (리뷰 라운드 1)

승인된 계획의 규칙 「실제로 찍힌 해설에서만 용어를 모은다」가 **여섯 곳
전부에 예외 없이** 적용된다 — `track_capital_structure`에 "절단 전 전체
해설을 본다"는 예외를 뒀던 첫 구현은 브리프 해석 오류였다(컨트롤러가
정정). 그래서:

- `analyze_company_risk`·`build_event_timeline`은 `_render_pattern_watch_block`
  이 렌더하지 않는 `pattern_to_prose(...)`를 절대 절 입력에 넣지 않는다
  (그 함수는 패턴명·taxonomy 라벨·확인해볼 것만 찍지 PATTERN_PROSE 문장을
  찍지 않는다 — 재현: 자기주식취득+채무조정+상환전환우선주 조합에서
  화면에 없는 "메자닌"이 절에 실렸었다).
- `track_capital_structure`는 화면에 실제로 찍힌 문장(`one_liner`, 첫
  문장만)만 절 입력에 넣는다 — 절단된 뒤쪽 문장의 용어(3PCA의
  "제3자배정" 등)는 절에 나타나면 안 된다.

## 이 파일이 잠그는 것

① 6개 도구 각각 — 해설이 찍힌 출력에 마커가 정확히 1회, 마커 앞에
   빈 줄이 정확히 하나, **절 마지막 `- ` 항목 다음 줄은 빈 줄이거나
   출력 끝**(없으면 뒤따르는 고지가 마크다운 lazy continuation으로 그
   항목에 흡수된다), 용어 줄 ≤8 + 생략 줄 0~1, 각 정의가 GLOSSARY 원문과 일치,
   절에 실린 표제어는 **예외 없이 전부** 해설 본문(마커 이전)에 실제로
   등장한다(=passthrough나 미렌더 텍스트가 아니라 진짜 렌더된 해설에서
   나왔다는 증거 — required_terms뿐 아니라 found_terms 전체에 적용).
② 해설이 하나도 안 찍힌 경로(관찰 신호 0건)에는 절이 없다.
③ passthrough 비스캔 — 공시 제목에만 있고 해설에는 없는 용어는 절에
   나타나지 않는다(동적 1건 + 6곳 호출부 전체의 정적 잠금 — append뿐
   아니라 대입·`+=`·컴프리헨션까지 AST로 전부 훑는다).
④ 정적 — `_glossary_block(` 호출이 정확히 6회이고 각각이 대상 함수
   본문 안에 있다(AST로 함수 경계를 확인 — 문자열 탐색은 CLAUDE.md
   「인자 검증」 절이 경고하는 함정이 있다).
⑤ 배치 — 마커 이후에는 면책·안내 푸터만 오고 신호·패턴 본문이 오지
   않는다.

## 시나리오 선택 근거

여섯 곳 전부에 같은 신호(`REVERSE_SPLIT`, 제목 "주요사항보고서(감자결정)")를
쓴다 — 이 신호의 해설 **첫 문장**에 GLOSSARY 표제어 "감자"가 그대로
들어 있어(`"감자 또는 주식병합 공시입니다."`), `track_capital_structure`의
절단(첫 문장만 렌더)과도 무관하게 안전하게 검증된다. DS005 12종 어디에도
걸리지 않아(`resolve_decision_type` 실측 공문자열) `get_major_decision`
호출도 유발하지 않는다.

`track_capital_structure`는 별도로 "절단된 문장의 용어는 절에 없다"를
직접 증명하는 테스트를 하나 더 둔다(3PCA의 "제3자배정"으로).
"""
from __future__ import annotations

import ast
import pathlib
import re

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


_OMISSION_PREFIX = "- 외 "


def _is_term_line(ln: str) -> bool:
    """절의 `- ` 줄 중 **표제어 줄**만 고른다.

    상한(8)에 걸려 뺀 용어가 있으면 `glossary_footer`가 마지막에
    「- 외 N개 용어는 생략」을 붙인다(조용한 절단 금지). 그 줄도 `- `로
    시작하지만 표제어가 아니다 — `- 외 `로 시작하고 ` — ` 구분자가 없다.
    """
    return ln.startswith("- ") and not (
        ln.startswith(_OMISSION_PREFIX) and " — " not in ln
    )


def _split_glossary(out: str):
    """마커 인덱스로 (본문, 용어 절 표제어 줄들, 마커 이후 전체)를 가른다.

    생략 줄은 표제어 줄에 섞지 않는다 — 섞으면 `found_terms`가 「외」를
    표제어로 오인한다.
    """
    assert out.count(_MARKER) == 1, f"마커가 1회가 아니다: {out.count(_MARKER)}회\n{out}"
    idx = out.index(_MARKER)
    head = out[:idx]
    tail = out[idx + len(_MARKER):]
    lines = [ln for ln in tail.split("\n") if _is_term_line(ln)]
    return head, lines, tail


def _omission_lines(out: str) -> "list[str]":
    """절의 생략 줄(0개 또는 1개)."""
    _, _, tail = _split_glossary(out)
    return [
        ln for ln in tail.split("\n")
        if ln.startswith(_OMISSION_PREFIX) and " — " not in ln
    ]


def _assert_blank_line_after_section(out: str) -> None:
    """절의 마지막 `- ` 줄 **다음 줄**이 빈 줄이거나 출력 끝이어야 한다.

    없으면 뒤따르는 고지(timeline의 「⚠️ … 실제 상황과 다를 수 있습니다」,
    track_capital_structure의 「📎 참고: …」 등)가 마크다운 lazy
    continuation으로 마지막 용어 항목에 흡수돼 풀이의 일부처럼 읽힌다
    (골든 28개에서 재현했다 — 예 `STX_timeline.txt`).
    """
    _, _, tail = _split_glossary(out)
    rows = tail.split("\n")
    last = max(i for i, ln in enumerate(rows) if ln.startswith("- "))
    if last + 1 >= len(rows):
        return  # 출력 끝
    nxt = rows[last + 1]
    assert nxt.strip() == "", (
        f"용어 절 마지막 항목 다음 줄이 빈 줄이 아니다: {nxt!r} — "
        "마크다운 lazy continuation으로 항목에 흡수된다"
    )


def _assert_single_blank_line_before_marker(out: str) -> None:
    """마커 앞 개행이 정확히 2개(=빈 줄 하나)인지 — 3개 이상(빈 줄 두 개
    이상)이면 안 된다. 리뷰에서 find_risk_precedents 등 여러 도구가
    "\\n\\n\\n"(빈 줄 두 개)이 되고 있던 것을 잡았다."""
    idx = out.index(_MARKER)
    head = out[:idx]
    stripped = head.rstrip("\n")
    trailing = len(head) - len(stripped)
    assert trailing == 2, (
        f"마커 앞 개행이 {trailing}개다(2개=빈 줄 하나여야 한다): {head[-6:]!r}"
    )


def _assert_glossary_section(out: str, required_terms: set):
    """① — 마커 1회·마커 앞뒤 빈 줄 정확히 하나·**용어 줄 ≤8 + 생략 줄
    0~1**·각 정의가 GLOSSARY 원문과 일치·절에 실린 표제어는
    **전부(required_terms뿐 아니라 found_terms 전체)** 해설 본문(마커
    이전)에 실제로 등장한다."""
    head, lines, _ = _split_glossary(out)
    _assert_single_blank_line_before_marker(out)
    _assert_blank_line_after_section(out)
    assert lines, "용어 절이 비어 있다"
    assert len(lines) <= 8, f"용어 줄이 8을 넘는다: {len(lines)}"
    omitted = _omission_lines(out)
    assert len(omitted) <= 1, f"생략 줄이 둘 이상이다: {omitted}"
    if omitted:
        assert len(lines) == 8, (
            f"생략 줄이 있는데 용어 줄이 8개가 아니다: {len(lines)}"
        )
        assert re.fullmatch(r"- 외 \d+개 용어는 생략", omitted[0]), (
            f"생략 줄 형식이 다르다: {omitted[0]!r}"
        )
    found_terms = set()
    for ln in lines:
        body = ln[2:]  # "- " 제거
        assert " — " in body, f"줄 형식이 다르다: {ln!r}"
        term, _, definition = body.partition(" — ")
        assert term in GLOSSARY, f"GLOSSARY에 없는 표제어: {term!r}"
        assert definition == GLOSSARY[term]
        assert len(definition) <= 60, f"{term}의 정의가 60자를 넘는다: {definition!r}"
        found_terms.add(term)
    # 브리프의 핵심 규칙 — "실제로 찍힌 해설에서만 용어를 모은다": 절에
    # 실린 표제어는 **예외 없이 전부** 해설 본문에 등장해야 한다(요구한
    # required_terms만이 아니라 찾아낸 found_terms 전체).
    for t in found_terms:
        assert t in head, (
            f"{t!r}가 용어 절에는 있는데 해설 본문(마커 이전)에는 없다 — "
            "passthrough로 새어 들어왔거나 화면에 렌더되지 않은 문장에서 "
            "왔을 수 있다"
        )
    for t in required_terms:
        assert t in found_terms, f"기대한 표제어 {t!r}가 절에 없다: {found_terms}"
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

    def test_패턴이_렌더돼도_패턴_prose는_넣지_않는다(self, monkeypatch):
        """`_render_pattern_watch_block`은 PATTERN_PROSE를 렌더하지 않는다
        (패턴명·taxonomy 라벨·확인해볼 것만 찍는다) — 그래서 「관찰된 신호가
        겹치는 등록 패턴」 블록이 실제로 뜬 상황에서도 용어 절에는 그
        신호들 자체의 SIGNAL_PROSE 표제어만 실려야 한다.

        REVERSE_SPLIT 3건(12개월 이내, 희석성 ≥3건 조건 충족)으로
        CAPITAL_CHURN(2.7)을 합성 발화시키고 DISCLOSURE_VIOL(4.3, 제목
        "불성실공시법인지정")을 더하면 게이트 없는 2신호 패턴
        capital_churn_anomaly가 2/2 전부 일치로 렌더된다(라이브 확인:
        "구성 신호 2개 중 2개가 이 기간 공시에서 관찰됐습니다"). 그
        PATTERN_PROSE("희석" 포함)가 절에 없어야 하고, REVERSE_SPLIT의
        SIGNAL_PROSE에서 나온 "감자"만 있어야 한다."""
        monkeypatch.setattr(srv, "_DART_API_KEY", "testkey")
        monkeypatch.setattr(srv, "resolve_corp", _resolve_corp_stub)
        rows = [
            _mk_disclosure(_REVERSE_SPLIT_TITLE, rcept_no="1" * 14, rcept_dt="20260101"),
            _mk_disclosure(_REVERSE_SPLIT_TITLE, rcept_no="2" * 14, rcept_dt="20260201"),
            _mk_disclosure(_REVERSE_SPLIT_TITLE, rcept_no="3" * 14, rcept_dt="20260301"),
            _mk_disclosure("불성실공시법인지정", rcept_no="4" * 14, rcept_dt="20260401"),
        ]
        monkeypatch.setattr(
            srv, "fetch_company_disclosures_with_status",
            lambda *a, **kw: (rows, FETCH_OK),
        )
        monkeypatch.setattr(srv, "fetch_fund_usage", lambda *a, **kw: [])
        monkeypatch.setattr(srv, "fetch_distress_events", lambda *a, **kw: [])
        monkeypatch.setattr(srv, "fetch_financial_statements_all", lambda *a, **kw: [])
        out = srv.analyze_company_risk("테스트기업")
        # 패턴 겹침 블록이 실제로 뜨고 전부 일치했는지가 전제 조건이다
        # (게이트가 있는 capital_backflow/fund_diversion_chain과 달리
        # capital_churn_anomaly는 확인 게이트가 없어 이 조합만으로 뜬다).
        assert "관찰된 신호가 겹치는 등록 패턴" in out
        assert "구성 신호 2개 중 2개가 이 기간 공시에서 관찰됐습니다" in out
        found_terms = _assert_glossary_section(out, {"감자"})
        assert "희석" not in found_terms, (
            "capital_churn_anomaly의 PATTERN_PROSE(\"희석\" 포함)가 화면에 "
            "없는데도 용어 절에 새어 들어왔다"
        )


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
        """이 도구는 실제로 `prose_body = pattern_to_prose(...)`를
        `lines.append(prose_body or ...)`로 화면에 낸다(server.py 렌더
        코드 확인) — analyze_company_risk/build_event_timeline과 달리
        패턴 prose를 절 입력에 넣어도 된다. "capital_churn_anomaly"
        (2.7+4.3, CAPITAL_CHURN + DISCLOSURE_VIOL로 전부 일치)는 "희석"
        이라는 GLOSSARY 표제어를 포함한다(실측 확인). 두 신호의 개별
        SIGNAL_PROSE에는 GLOSSARY 표제어가 없어, 이 절이 순수하게 패턴
        prose에서만 나온 것임을 보장한다."""
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
        """희석성 자본 이벤트 3건(12개월 이내)이면 CAPITAL_CHURN이 뜨고,
        이 도구는 실제로 `lines.append(pattern)`으로 capital_churn_anomaly
        PATTERN_PROSE("희석" 포함)를 화면에 낸다 — 그래서 절 입력에 넣어도
        된다(analyze_company_risk/build_event_timeline과 다른 점)."""
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

    def test_절단된_문장의_용어는_절에_없다(self, monkeypatch):
        """컨트롤러 정정 — "실제로 찍힌 해설에서만 용어를 모은다"는
        규칙이 이 도구에도 예외 없이 적용된다. 화면의 시계열 한 줄은
        **첫 문장만** 보여준다(`meaning.split("다.")[0] + "다."`) — 3PCA의
        "제3자배정"은 둘째 문장에만 있어(`"유상증자 공시입니다."`가 첫
        문장) 화면에도, 그래서 용어 절에도 나타나면 안 된다.

        REVERSE_SPLIT을 함께 넣어 절 자체는 뜨게 하되("감자"), 3PCA 쪽의
        절단된 용어("제3자배정")가 새지 않는 것을 직접 확인한다.
        """
        self._base_patches(monkeypatch)
        rows = [
            _mk_disclosure(_REVERSE_SPLIT_TITLE, rcept_no="1" * 14, rcept_dt="20260101"),
            _mk_disclosure(
                "주요사항보고서(제3자배정유상증자결정)",
                rcept_no="2" * 14, rcept_dt="20260201",
            ),
        ]
        monkeypatch.setattr(
            srv, "fetch_company_disclosures_with_status",
            lambda *a, **kw: (rows, FETCH_OK),
        )
        out = srv.track_capital_structure("테스트기업")
        head, _, _ = _split_glossary(out)
        # 3PCA 쪽 렌더 줄(→ ...)이 실제로 첫 문장만인지 먼저 확인한다(전제).
        rendered_3pca = next(
            ln for ln in head.split("\n")
            if ln.strip().startswith("→") and "유상증자" in ln
        )
        assert "제3자배정" not in rendered_3pca, (
            "전제가 깨졌다 — 화면에 이미 절단되지 않은 문장이 찍히고 있다"
        )
        assert rendered_3pca.strip() == "→ " + "유상증자 공시입니다."
        found_terms = _assert_glossary_section(out, {"감자"})
        assert "제3자배정" not in found_terms, (
            "화면(one_liner)에 없는 용어가 용어 절에 실렸다 — 절단된 뒤쪽 "
            "문장이 새어 들어왔다"
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
# signal_to_prose/pattern_to_prose/turnover_prose의 반환값을 담는 이름
# (meaning/prose/prose_body/pattern/one_liner)과 TURNOVER_PROSE 필드
# (_p[...])만 허용한다. report_nm·title·corp_name·label처럼 DART 원문이나
# 표시용 라벨을 가리키는 이름은 전부 금지.
_ALLOWED_GLOSSARY_SOURCES = {"meaning", "prose", "prose_body", "pattern", "one_liner"}
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
    """정적 잠금(문자열 대조) — 여섯 함수 전부에서 `_glossary_texts`를
    채우는 표현이 DART 원문·제목·라벨을 가리키는 변수명을 쓰지 않는다.
    AST 기반의 더 정밀한 검사는
    `test_glossary_texts_모든_유입_경로가_허용된_이름만_쓴다`가 한다."""
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


def _flatten_list_like(node: ast.AST) -> list:
    """List/Tuple 리터럴이면 그 원소들을(재귀), ListComp/GeneratorExp면
    반복 표현식(elt)을, 그 외엔 노드 자체를 하나짜리 리스트로 돌려준다.

    패턴 prose 누수(리뷰 finding 1)는 정확히 이 경로 — 컴프리헨션의 elt
    — 로 들어왔다. `.append(X)`만 보던 옛 검사는 이 경로를 놓쳤다.
    """
    if isinstance(node, (ast.List, ast.Tuple)):
        out: list = []
        for el in node.elts:
            out.extend(_flatten_list_like(el))
        return out
    if isinstance(node, (ast.ListComp, ast.GeneratorExp)):
        return _flatten_list_like(node.elt)
    return [node]


def _is_glossary_texts_name(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id == "_glossary_texts"


def _glossary_texts_source_exprs(fn: ast.FunctionDef) -> list:
    """`_glossary_texts`로 흘러드는 모든 값 표현식을 찾는다 — 초기 대입
    (`_glossary_texts: list[str] = [...]`/`= [...]`), `+=`, `.append(X)`/
    `.extend(X)`, 그리고 그 안의 리스트·컴프리헨션까지 전부 편다."""
    exprs: list = []
    for sub in ast.walk(fn):
        if isinstance(sub, ast.AnnAssign) and _is_glossary_texts_name(sub.target):
            if sub.value is not None:
                exprs.extend(_flatten_list_like(sub.value))
        elif isinstance(sub, ast.Assign) and any(
            _is_glossary_texts_name(t) for t in sub.targets
        ):
            exprs.extend(_flatten_list_like(sub.value))
        elif isinstance(sub, ast.AugAssign) and _is_glossary_texts_name(sub.target):
            exprs.extend(_flatten_list_like(sub.value))
        elif (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr in ("append", "extend")
            and _is_glossary_texts_name(sub.func.value)
        ):
            for a in sub.args:
                exprs.extend(_flatten_list_like(a))
    return exprs


def _describe_expr(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Subscript):
        return f"{_describe_expr(node.value)}[...]"
    if isinstance(node, ast.Call):
        fname = getattr(node.func, "id", None) or getattr(node.func, "attr", "")
        return f"{fname}(...)"
    return ast.dump(node)


def test_glossary_texts_모든_유입_경로가_허용된_이름만_쓴다():
    """AST로 여섯 함수 전부를 훑어 `_glossary_texts`로 흘러드는 **모든**
    표현식(대입·`+=`·`.append`·`.extend`·리스트/컴프리헨션 내부까지)이
    허용 목록 안의 이름이거나 `_p[...]` 형태인지 확인한다.

    함수 호출 결과(예: `pattern_to_prose(...)`)를 변수에 담지 않고 곧바로
    흘려 넣는 것은 **허용하지 않는다** — 리뷰에서 잡힌 패턴 prose 누수가
    정확히 이 형태(컴프리헨션 elt에 직접 함수 호출)였다. 먼저 이름 있는
    변수에 담아야(그리고 그 변수가 실제로 화면에도 렌더되는지 사람이
    확인해야) 이 허용 목록에 들어올 수 있다.
    """
    tree = ast.parse(_SRC)
    module_funcs = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    for name in _TOOL_NAMES:
        fn = module_funcs[name]
        for expr in _glossary_texts_source_exprs(fn):
            if isinstance(expr, ast.Name):
                assert expr.id in _ALLOWED_GLOSSARY_SOURCES, (
                    f"{name}: 허용 목록 밖 이름이 용어 절에 유입된다: "
                    f"{expr.id!r}"
                )
            elif isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Name):
                assert expr.value.id == "_p", (
                    f"{name}: 허용되지 않은 subscript 유입: "
                    f"{_describe_expr(expr)!r}"
                )
            else:
                raise AssertionError(
                    f"{name}: 허용되지 않은 표현식이 용어 절에 직접 유입된다"
                    f"(먼저 이름 있는 변수에 담아야 한다): {_describe_expr(expr)!r}"
                )


def test_glossary_texts_append_인자가_허용_목록_안에_있다():
    """`.append(X)` 형태만 보는 얕은 문자열 검사 — 위 AST 검사와 별개로
    남겨 이중 잠금한다(문자열 검사는 더 읽기 쉬운 실패 메시지를 준다)."""
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


def test_analyze와_build_event_timeline은_패턴_prose를_호출하지_않는다():
    """리뷰 finding 1의 회귀 방지 — `_render_pattern_watch_block`은
    PATTERN_PROSE를 렌더하지 않으므로 이 두 함수 안에 `pattern_to_prose(...)`
    **호출**이 아예 없어야 한다(AST 기준 — 설명용 주석에 그 이름이
    나오는 것은 정상이라 문자열 검사가 아니라 `ast.Call`만 본다)."""
    tree = ast.parse(_SRC)
    module_funcs = {
        node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    for name in ("analyze_company_risk", "build_event_timeline"):
        fn = module_funcs[name]
        calls = [
            n for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "pattern_to_prose"
        ]
        assert not calls, (
            f"{name}이 렌더하지 않는 PATTERN_PROSE를 여전히 호출한다 "
            f"({len(calls)}회)"
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
    """`_glossary_block(` 자체의 전체 출현 횟수도 6이어야 한다."""
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
