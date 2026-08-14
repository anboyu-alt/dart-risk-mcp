# 신호 한정층(qualification layer) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공시 제목 키워드 부분일치로 잡힌 신호에 표시 계층(`observed` / `procedural`)과 강등 사유를 붙여, 정상 공시가 위험 신호로 표시되는 것을 막는다.

**Architecture:** `match_signals`·`SIGNAL_TYPES`·`taxonomy.py`는 수정하지 않는다. 매칭 **이후**에 동작하는 순수 함수 2개(`parse_report_name`, `qualify_signals`)를 `core/qualifiers.py`에 추가하고, 결과를 `signals-data.json`으로 내보내 MCP(`server.py`)와 뷰어(`docs/tool/index.html`)가 같은 규칙을 쓴다. 신호는 삭제하지 않고 `tier`만 붙는다.

**Tech Stack:** Python 3.11+ (표준 라이브러리 `re`·`dataclasses`만), pytest, 순수 JS(빌드 없음)

**Spec:** [docs/superpowers/specs/2026-08-14-signal-qualification-design.md](../specs/2026-08-14-signal-qualification-design.md)

## Global Constraints

- **외부 라이브러리 추가 금지.** `requests`와 `mcp` 외 의존성을 추가하지 않는다. HTML 파싱도 regex + 문자열 처리로 구현한다.
- **점수·등급 없음 (v0.8.5).** 기업 위험도를 정량화하거나 등급("매우위험", "고위험" 등)으로 부여하는 어떤 표기도 사용자 출력에 노출되면 안 된다. `tests/test_golden_output_hygiene.py`가 기계적으로 막는다.
- **`match_signals`·`SIGNAL_TYPES`·`taxonomy.py`·`_AMENDMENT_RE`는 수정하지 않는다.** 리콜을 그대로 두고 표시 계층만 나눈다.
- **`qualify_signals`는 예외를 던지지 않는다.** 판단 불가하면 `observed`(기존 동작)로 남긴다.
- **`core/qualifiers.py`는 네트워크 호출을 하지 않는다.** 순수 함수만 둔다.
- 오류 처리: API 호출 실패 시 빈 값 반환 (예외를 도구 레벨로 전파하지 않음).
- 규칙 **데이터**(문자열 목록)는 `signals-data.json`으로 내보내고 **로직만** JS로 이식한다. 문자열 이중 관리 금지.
- 커밋 메시지는 한국어, 말미에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## File Structure

| 파일 | 책임 | 상태 |
|---|---|---|
| `dart_risk_mcp/core/qualifiers.py` | 제목 파싱 + 신호 한정. 순수 함수만 | **생성** |
| `tests/test_qualifiers.py` | 위 모듈 단위 테스트 | **생성** |
| `dart_risk_mcp/core/signals.py` | `AMBIGUOUS_SIGNAL_KEYS` 상수 추가 (기존 내용 불변) | 수정 |
| `dart_risk_mcp/core/__init__.py` | 신규 심볼 export | 수정 |
| `scripts/export_tool_data.py` | 규칙 데이터·ambiguous 키 내보내기 | 수정 |
| `tests/test_export_tool_data.py` | 신규 필드 검증 | 수정 |
| `dart_risk_mcp/server.py` | `analyze_company_risk`·`build_event_timeline` 배선 | 수정 |
| `docs/tool/index.html` | 파서·한정자 JS 이식 + 두 층 렌더 | 수정 |
| `docs/tool/signals-data.json` | codegen 산출물 (직접 편집 금지) | 재생성 |
| `tests/fixtures/sample_outputs/*.txt` | 골든 재생성 | 재생성 |

---

## Task 1: `flr_nm` 라이브 검증 (스파이크)

R1 적용 가능 여부를 결정한다. 이 결과에 따라 Task 3의 R1 분기가 살아있는 코드인지 죽은 코드인지 갈린다.

**Files:**
- Create: `tmp/_spike/check_flr_nm.py` (임시, Task 7에서 삭제)

**Interfaces:**
- Consumes: 없음
- Produces: 없음 (판단 근거만). 결과를 Task 3 착수 전에 이 계획 문서 하단 "검증 로그"에 기록한다.

- [ ] **Step 1: 스파이크 스크립트 작성**

```python
# tmp/_spike/check_flr_nm.py
"""list.json 응답에 flr_nm·rm 필드가 실제로 오는지 확인한다."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from dart_risk_mcp.core.dart_client import _retry, BASE_URL  # noqa: E402

api_key = os.environ.get("DART_API_KEY", "")
if not api_key:
    key_path = os.path.join("tmp", "_apikey.txt")
    if os.path.exists(key_path):
        api_key = open(key_path, encoding="utf-8").read().strip()
if not api_key:
    print("SKIP: DART_API_KEY 없음 — R1b(제목 기반)만 구현한다")
    raise SystemExit(2)

resp = _retry(
    "get",
    f"{BASE_URL}/list.json",
    params={
        "crtfc_key": api_key,
        "corp_code": "00126380",   # 삼성전자
        "bgn_de": "20260101",
        "end_de": "20260430",
        "page_count": "10",
    },
    timeout=20,
)
data = resp.json()
rows = data.get("list") or []
print("status:", data.get("status"), "rows:", len(rows))
if not rows:
    print("SKIP: 응답 0건 — 기간을 넓혀 재시도")
    raise SystemExit(2)
print("응답 키:", sorted(rows[0].keys()))
print("flr_nm 존재:", "flr_nm" in rows[0])
print("rm 존재:", "rm" in rows[0])
for r in rows[:8]:
    print("  corp_name=%-10s flr_nm=%-20s rm=%-6s | %s"
          % (r.get("corp_name", ""), r.get("flr_nm", ""), r.get("rm", ""),
             r.get("report_nm", "")))
```

- [ ] **Step 2: 실행**

Run: `python tmp/_spike/check_flr_nm.py`

세 가지 결과 중 하나:

| 출력 | 의미 | Task 3에서 할 일 |
|---|---|---|
| `flr_nm 존재: True` + 대량보유보고의 `flr_nm`이 회사명과 다름 | R1 적용 가능 | R1 + R1b 둘 다 구현 |
| `flr_nm 존재: False` | 필드 없음 | R1 구현하되 **테스트는 합성 dict로만** 검증하고, 실사용은 R1b가 담당 |
| `SKIP` (API 키 없음) | 검증 불가 | 위와 동일 — R1은 합성 dict 테스트만 |

**어느 경우에도 R1 코드는 작성한다.** `filing`에 `flr_nm`이 있으면 쓰고 없으면 R1b로 흐르는 구조라, 필드가 나중에 확인돼도 코드 변경이 필요 없다.

- [ ] **Step 3: 결과를 계획 문서에 기록**

이 파일 맨 아래 "검증 로그" 절에 실행 날짜와 출력 요약 3줄을 적는다. **재지 않은 값을 실측이라 적지 않는다** — SKIP이면 SKIP이라고 적는다.

- [ ] **Step 4: 커밋**

```bash
git add docs/superpowers/plans/2026-08-14-signal-qualification.md
git commit -m "docs: flr_nm 필드 라이브 검증 결과 기록

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: `parse_report_name` — 제목 구조 파서

**Files:**
- Create: `dart_risk_mcp/core/qualifiers.py`
- Create: `tests/test_qualifiers.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `ParsedName` — frozen dataclass, 필드 `tags: tuple[str, ...]`, `body: str`, `subtitles: tuple[str, ...]`, `tail: str`, `compact: str`
  - `parse_report_name(report_nm: str) -> ParsedName`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_qualifiers.py`:

```python
# -*- coding: utf-8 -*-
"""신호 한정층 단위 테스트 — 전부 실측 공시 제목을 케이스로 쓴다."""
from dart_risk_mcp.core.qualifiers import ParsedName, parse_report_name


def test_parse_splits_tag_body_subtitle():
    p = parse_report_name("[첨부정정]유상증자결정(종속회사의주요경영사항)")
    assert p.tags == ("첨부정정",)
    assert p.body == "유상증자결정"
    assert p.subtitles == ("종속회사의주요경영사항",)
    assert p.tail == "결정"


def test_parse_strips_whitespace_inside_subtitle():
    # 실측: '자회사의 주요경영사항'(공백 있음)과 '종속회사의주요경영사항'이 공존
    p = parse_report_name("유상증자결정 (자회사의 주요경영사항)")
    assert p.subtitles == ("자회사의주요경영사항",)


def test_parse_tail_prefers_longest_suffix():
    # '결과보고서'가 '보고서'보다 길어 우선한다
    assert parse_report_name("자기주식취득결과보고서").tail == "결과보고서"


def test_parse_tail_of_wrapper_uses_last_subtitle():
    # '주요사항보고서(...)'는 껍데기 — 실제 행위는 괄호 안에 있다
    assert parse_report_name("주요사항보고서(자기주식취득결정)").tail == "결정"


def test_parse_tail_keeps_body_tail_when_subtitle_has_none():
    p = parse_report_name("주식등의대량보유상황보고서(일반)")
    assert p.body == "주식등의대량보유상황보고서"
    assert p.tail == "보고서"


def test_parse_handles_middle_dot_variant():
    # 'ㆍ'(U+318D)는 DART 실제 표기 — 제거하지 않고 그대로 매칭한다
    p = parse_report_name("최대주주변경을수반하는주식담보제공계약해제ㆍ취소등")
    assert p.tail == "해제ㆍ취소등"


def test_parse_multiple_tags():
    p = parse_report_name("[기재정정][첨부추가]주요사항보고서(전환사채권발행결정)")
    assert p.tags == ("기재정정", "첨부추가")


def test_parse_empty_is_safe():
    p = parse_report_name("")
    assert p == ParsedName(tags=(), body="", subtitles=(), tail="", compact="")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_qualifiers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dart_risk_mcp.core.qualifiers'`

- [ ] **Step 3: 최소 구현**

`dart_risk_mcp/core/qualifiers.py`:

```python
# -*- coding: utf-8 -*-
"""신호 한정층 — 공시 제목 구조 파싱 + 신호 표시 계층 판정.

match_signals(signals.py)는 제목에 키워드가 들어있는지만 본다. 그래서
부정("해제"·"철회")·방향(발행/취득)·주체(회사/제3자)·수식어(제3자배정/일반공모)를
구분할 수단이 없고, 정상 공시가 위험 신호로 잡힌다.

이 모듈은 match_signals '이후'에 동작한다. 신호를 지우지 않고 tier만 붙인다:
- observed:   회사가 낸, 해당 사건 자체의 공시
- procedural: 제3자 제출 / 사후 보고 / 철회·해제 / 해명 / 정정

순수 함수만 둔다 — 네트워크 호출 없음.
"""
import re
from dataclasses import dataclass

# 본체 어미 후보. 긴 것이 먼저 매칭돼야 하므로 _tail_of가 길이순으로 검사한다.
# 'ㆍ'(U+318D)는 DART 실제 표기라 그대로 둔다.
TAILS: tuple[str, ...] = (
    "해제ㆍ취소등", "결과보고서", "계약체결", "보고서", "결정", "해제",
    "취소", "철회", "해지", "중단", "해명", "신청", "확정", "변경",
    "발생", "요구", "취득", "매도",
)

_TAG_RE = re.compile(r"^\[([^\]]*)\]\s*")
_PAREN_RE = re.compile(r"\(([^()]*)\)")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ParsedName:
    """공시 제목을 구조 조각으로 나눈 결과.

    tags:      대괄호 접두 태그 — ("첨부정정",)
    body:      태그·괄호를 뺀 본체 (공백 제거)
    subtitles: 괄호 내용 (공백 제거)
    tail:      본체의 마지막 어미 토큰. 본체가 '~보고서' 껍데기이고 괄호가
               어미를 가지면 괄호 쪽 어미를 쓴다.
    compact:   태그를 뺀 전체 문자열 (공백 제거) — 부분 검사용
    """

    tags: tuple[str, ...]
    body: str
    subtitles: tuple[str, ...]
    tail: str
    compact: str


def _tail_of(text: str) -> str:
    """text가 TAILS 중 하나로 끝나면 그 어미를 반환. 긴 것 우선."""
    for cand in sorted(TAILS, key=len, reverse=True):
        if text.endswith(cand):
            return cand
    return ""


def parse_report_name(report_nm: str) -> ParsedName:
    """공시 제목을 {태그, 본체, 괄호부제, 어미}로 나눈다.

    공백은 전부 제거한다 — DART 표기가 '자회사의 주요경영사항'과
    '종속회사의주요경영사항'처럼 띄어쓰기가 섞여 오기 때문이다.
    """
    rest = (report_nm or "").strip()
    tags: list[str] = []
    while True:
        m = _TAG_RE.match(rest)
        if not m:
            break
        tags.append(m.group(1).strip())
        rest = rest[m.end():]

    compact = _WS_RE.sub("", rest)
    subtitles = tuple(s for s in _PAREN_RE.findall(compact) if s)
    body = _PAREN_RE.sub("", compact)

    tail = _tail_of(body)
    # '주요사항보고서(자기주식취득결정)'처럼 본체가 껍데기면 괄호 쪽을 본다.
    if tail == "보고서" and subtitles:
        inner = _tail_of(subtitles[-1])
        tail = inner or tail

    return ParsedName(
        tags=tuple(tags),
        body=body,
        subtitles=subtitles,
        tail=tail,
        compact=compact,
    )
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_qualifiers.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: 커밋**

```bash
git add dart_risk_mcp/core/qualifiers.py tests/test_qualifiers.py
git commit -m "feat(qualifiers): 공시 제목 구조 파서 추가

제목을 {태그, 본체, 괄호부제, 어미}로 나눈다. 공백은 제거해
'자회사의 주요경영사항'/'종속회사의주요경영사항' 표기차를 흡수한다.
어미는 긴 것 우선으로 매칭해 '결과보고서'가 '보고서'를 이기고,
'주요사항보고서(...)' 껍데기는 괄호 쪽 어미를 쓴다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: `qualify_signals` — 강등 규칙 R1~R5

**Files:**
- Modify: `dart_risk_mcp/core/qualifiers.py`
- Modify: `tests/test_qualifiers.py`

**Interfaces:**
- Consumes: `ParsedName`, `parse_report_name` (Task 2)
- Produces:
  - `Qualified` — frozen dataclass, 필드 `key: str`, `label: str`, `tier: str`, `reason: str`, `note: str`
  - `qualify_signals(signals: list[dict], parsed: ParsedName, filing: dict | None = None) -> list[Qualified]`
  - `is_false_amendment(parsed: ParsedName) -> bool`
  - `TIER_OBSERVED = "observed"`, `TIER_PROCEDURAL = "procedural"`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_qualifiers.py` 하단에 추가:

```python
from dart_risk_mcp.core.qualifiers import (  # noqa: E402
    TIER_OBSERVED,
    TIER_PROCEDURAL,
    is_false_amendment,
    qualify_signals,
)

SHAREHOLDER = {"key": "SHAREHOLDER", "label": "최대주주변경"}
TREASURY = {"key": "TREASURY", "label": "자사주매입/처분"}
PCA3 = {"key": "3PCA", "label": "제3자배정유상증자"}
INQUIRY = {"key": "INQUIRY", "label": "조회공시"}
CB_BW = {"key": "CB_BW", "label": "CB/BW발행"}


def _one(report_nm, signals, filing=None):
    """제목 하나를 파싱해 한정한 결과의 첫 항목."""
    return qualify_signals(signals, parse_report_name(report_nm), filing)[0]


# ── R1: 제출인이 회사가 아니면 강등 ──────────────────────────
def test_r1_demotes_when_filer_is_not_the_company():
    q = _one(
        "주식등의대량보유상황보고서(일반)", [SHAREHOLDER],
        {"corp_name": "삼성전자", "flr_nm": "국민연금공단"},
    )
    assert q.tier == TIER_PROCEDURAL
    assert "국민연금공단" in q.reason


def test_r1_keeps_when_filer_is_the_company_despite_suffix_diff():
    # ㈜·(주)·주식회사 표기차는 흡수한다
    q = _one(
        "최대주주변경", [SHAREHOLDER],
        {"corp_name": "아틀라스링크", "flr_nm": "주식회사 아틀라스링크"},
    )
    assert q.tier == TIER_OBSERVED


# ── R1b: flr_nm 없을 때 제목 기반 예비 ────────────────────────
def test_r1b_demotes_third_party_report_without_filer_field():
    q = _one("주식등의대량보유상황보고서(약식)", [SHAREHOLDER], None)
    assert q.tier == TIER_PROCEDURAL
    assert "제3자" in q.reason


def test_r1b_demotes_insider_holding_report():
    q = _one("임원ㆍ주요주주특정증권등소유상황보고서", [SHAREHOLDER], None)
    assert q.tier == TIER_PROCEDURAL


# ── R2: 사후·해제 국면 ───────────────────────────────────────
def test_r2_demotes_result_report():
    q = _one("자기주식취득결과보고서", [TREASURY])
    assert q.tier == TIER_PROCEDURAL
    assert "결과" in q.reason


def test_r2_demotes_cancellation():
    q = _one("최대주주변경을수반하는주식담보제공계약해제ㆍ취소등", [SHAREHOLDER])
    assert q.tier == TIER_PROCEDURAL


def test_r2_keeps_trust_termination_decision():
    """과잉 강등 방지 — '해지'가 들어있어도 '결정'으로 끝나면 새 결정이다."""
    q = _one("주요사항보고서(자기주식취득신탁계약해지결정)", [TREASURY])
    assert q.tier == TIER_OBSERVED


# ── R3: 자회사·특수관계인 사안 ───────────────────────────────
def test_r3_demotes_subsidiary_matter():
    q = _one("유상증자결정(종속회사의주요경영사항)", [PCA3])
    assert q.tier == TIER_PROCEDURAL
    assert "자회사" in q.reason


def test_r3_demotes_related_party_participation():
    q = _one("특수관계인의유상증자참여", [PCA3])
    assert q.tier == TIER_PROCEDURAL


# ── R4: 해명·미확정 ─────────────────────────────────────────
def test_r4_demotes_company_denial():
    q = _one("풍문또는보도에대한해명(미확정)", [INQUIRY])
    assert q.tier == TIER_PROCEDURAL


def test_r4_keeps_exchange_inquiry_request():
    """과잉 강등 방지 — 거래소가 요구한 조회공시는 남는다."""
    q = _one("조회공시요구(풍문또는보도)(감사의견비적정설)", [INQUIRY])
    assert q.tier == TIER_OBSERVED


# ── R5: 정정·후속 꼬리표 ─────────────────────────────────────
def test_r5_demotes_attachment_amendment():
    q = _one("[첨부정정]주요사항보고서(유상증자결정)", [PCA3])
    assert q.tier == TIER_PROCEDURAL
    assert "첨부정정" in q.reason


def test_r5_demotes_issue_terms_confirmation():
    q = _one("[발행조건확정]주요사항보고서(전환사채권발행결정)", [CB_BW])
    assert q.tier == TIER_PROCEDURAL


def test_false_amendment_detects_regulatory_order():
    """[정정명령부과]는 정정공시가 아니라 규제기관 조치다."""
    assert is_false_amendment(parse_report_name("[정정명령부과]증권신고서")) is True
    assert is_false_amendment(parse_report_name("[기재정정]유상증자결정")) is False
    assert is_false_amendment(parse_report_name("유상증자결정")) is False


def test_r5_keeps_regulatory_order():
    q = _one("[정정명령부과]증권신고서", [CB_BW])
    assert q.tier == TIER_OBSERVED


# ── 우선순위: R5가 R2·R3보다 먼저 ────────────────────────────
def test_amendment_tag_wins_over_other_rules():
    q = _one("[기재정정]자기주식취득결과보고서", [TREASURY])
    assert "기재정정" in q.reason


# ── 문제 기업 신호 보존 (회귀 방지) ──────────────────────────
def test_problem_company_signals_survive():
    kept = [
        "최대주주변경",
        "최대주주변경을수반하는주식양수도계약체결",
        "금전대여결정",
        "타인에대한채무보증결정(자율공시)",
        "주요사항보고서(유형자산양수결정)",
        "주요사항보고서(전환사채권발행결정)",
        "주식병합결정",
        "회생절차개시결정",
        "주요사항보고서(회생절차개시신청)",
        "자본잠식50%이상또는매출액50억원미만사실발생",
        "타인에대한담보제공결정",
        "소송등의제기ㆍ신청(경영권분쟁소송)(주주총회소집허가)",
    ]
    for nm in kept:
        q = _one(nm, [SHAREHOLDER])
        assert q.tier == TIER_OBSERVED, f"{nm} 이 잘못 강등됨: {q.reason}"


# ── 안전성 ──────────────────────────────────────────────────
def test_empty_signals_returns_empty():
    assert qualify_signals([], parse_report_name("아무거나"), None) == []


def test_missing_filing_keys_do_not_raise():
    q = _one("최대주주변경", [SHAREHOLDER], {})
    assert q.tier == TIER_OBSERVED
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_qualifiers.py -v`
Expected: FAIL — `ImportError: cannot import name 'qualify_signals'`

- [ ] **Step 3: 최소 구현**

`dart_risk_mcp/core/qualifiers.py`에 추가 (파일 상단 import에 `from .dart_client import _fold_corp_name` 추가).

> **`dart_client`에서 import하는 것은 의도된 선택이다.** `_fold_corp_name`은 이미
> `match_affiliate_row`가 쓰는 법인명 폴딩 유틸이고, 복제하면 두 곳이 갈라진다.
> `dart_client`가 모듈 수준에서 `requests`를 import하지만 이는 패키지의 기존
> 의존성이며, `qualifiers.py` 자체는 네트워크를 호출하지 않는다. 순환 참조도 없다
> (`dart_client`는 `qualifiers`를 import하지 않는다). **폴딩 로직을 복제하지 말 것.**

```python
from .dart_client import _fold_corp_name

TIER_OBSERVED = "observed"
TIER_PROCEDURAL = "procedural"

# R1b — 제3자가 회사에 대해 제출하는 보고서. 본체가 이것으로 시작하면
# 회사의 행위가 아니다(제출인은 국민연금·블랙록·개인 임원 등).
THIRD_PARTY_TITLES: tuple[str, ...] = (
    "주식등의대량보유상황보고서",
    "임원ㆍ주요주주특정증권등소유상황보고서",
    "최대주주등소유주식변동신고서",
)

# R2 — 이미 실행됐거나 되돌린 국면. 어미가 이것이면 새 사건이 아니다.
PHASETAILS: tuple[str, ...] = (
    "결과보고서", "해제ㆍ취소등", "해제", "취소", "철회", "해지", "중단",
)

# R3 — 공시 주체가 이 회사가 아닌 경우. 공백 제거 후 비교한다.
SUBSIDIARY_SUBTITLES: tuple[str, ...] = (
    "종속회사의주요경영사항",
    "자회사의주요경영사항",
    "관계회사의주요경영사항",
)
RELATED_PARTY_PREFIX = "특수관계인의"

# R5 — 기존 공시의 정정·후속. '[정정명령부과]'는 규제기관 조치라 여기 없다.
AMENDMENT_TAGS: tuple[str, ...] = (
    "기재정정", "첨부정정", "첨부추가", "정정", "발행조건확정", "연장결정",
)


def _is_amendment_tag(tag: str) -> bool:
    """R5 태그 판정 — 완전 일치 또는 '정정'으로 끝남.

    '정정명령부과'는 '정정'으로 시작할 뿐 끝나지 않으므로 걸리지 않는다.
    """
    t = (tag or "").strip()
    return t in AMENDMENT_TAGS or t.endswith("정정")


def is_false_amendment(parsed: ParsedName) -> bool:
    """_AMENDMENT_RE에는 걸리지만 실제 정정공시가 아닌 경우.

    match_signals는 '[정정명령부과]증권신고서'를 정정공시로 오판해 신호를
    통째로 삭제한다. 호출부는 이 함수가 True일 때만 접두를 벗겨 재매칭한다 —
    진짜 정정공시([기재정정] 등)의 기존 동작은 바뀌지 않는다.
    """
    if not parsed.tags:
        return False
    return not any(_is_amendment_tag(t) for t in parsed.tags)


@dataclass(frozen=True)
class Qualified:
    """한정된 신호 하나.

    key/label: 표시용. label은 보정될 수 있다(Task 4).
    tier:      TIER_OBSERVED | TIER_PROCEDURAL
    reason:    강등 사유 (사실 문장). observed면 "".
    note:      사실 주석 (방향 불일치 등). 없으면 "".
    """

    key: str
    label: str
    tier: str
    reason: str
    note: str


def _demotion_reason(parsed: ParsedName, filing: "dict | None") -> str:
    """강등 사유를 반환. 강등 대상이 아니면 빈 문자열.

    평가 순서 R1 → R1b → R5 → R2 → R3 → R4, 첫 매칭에서 멈춘다.
    R5를 앞에 두는 이유: 정정본은 내용과 무관하게 정정이다.
    """
    filing = filing or {}

    # R1 — 제출인이 회사가 아님
    filer = (filing.get("flr_nm") or "").strip()
    corp = (filing.get("corp_name") or "").strip()
    if filer and corp and _fold_corp_name(filer) != _fold_corp_name(corp):
        return f"회사가 낸 공시가 아닙니다 (제출인: {filer})"

    # R1b — flr_nm이 없을 때의 제목 기반 예비
    if not filer:
        for title in THIRD_PARTY_TITLES:
            if parsed.body.startswith(title):
                return "제3자가 회사에 대해 제출한 보고서입니다"

    # R5 — 정정·후속 꼬리표
    for tag in parsed.tags:
        if _is_amendment_tag(tag):
            return f"기존 공시의 정정·후속 보고입니다 ({tag})"

    # R2 — 사후·해제 국면
    if parsed.tail in PHASETAILS:
        if parsed.tail == "결과보고서":
            return "이미 실행된 건의 결과 보고입니다"
        return f"체결이 아니라 {parsed.tail}입니다"

    # R3 — 자회사·특수관계인 사안
    if any(s in SUBSIDIARY_SUBTITLES for s in parsed.subtitles):
        return "이 회사가 아니라 자회사 사안입니다"
    if parsed.body.startswith(RELATED_PARTY_PREFIX):
        return "회사가 아니라 특수관계인의 행위입니다"

    # R4 — 해명·미확정
    if parsed.tail == "해명" or "미확정" in parsed.subtitles:
        return "회사가 미확정으로 답한 해명 공시입니다"

    return ""


def qualify_signals(
    signals: list,
    parsed: ParsedName,
    filing: "dict | None" = None,
) -> "list[Qualified]":
    """match_signals 결과에 표시 계층(tier)과 사유를 붙인다.

    신호를 제거하지 않는다 — tier만 붙는다. 판단 불가하면 observed(기존
    동작)로 남긴다. 예외를 던지지 않는다.
    """
    reason = _demotion_reason(parsed, filing)
    tier = TIER_PROCEDURAL if reason else TIER_OBSERVED
    return [
        Qualified(
            key=sig.get("key", ""),
            label=sig.get("label", ""),
            tier=tier,
            reason=reason,
            note="",
        )
        for sig in (signals or [])
    ]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_qualifiers.py -v`
Expected: PASS (28 passed)

- [ ] **Step 5: 커밋**

```bash
git add dart_risk_mcp/core/qualifiers.py tests/test_qualifiers.py
git commit -m "feat(qualifiers): 강등 규칙 R1~R5 구현

제출인(R1/R1b)·사후해제(R2)·자회사(R3)·해명(R4)·정정(R5)으로
표시 계층을 나눈다. 신호는 지우지 않고 tier와 사유만 붙인다.

과잉 강등 방지를 테스트로 고정: '자기주식취득신탁계약해지결정'은
어미가 '결정'이라 유지, '조회공시요구'는 거래소 요구라 유지.
'[정정명령부과]'는 규제기관 조치이므로 정정 태그 목록에서 제외.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: 라벨 보정과 사실 주석

**Files:**
- Modify: `dart_risk_mcp/core/qualifiers.py`
- Modify: `tests/test_qualifiers.py`

**Interfaces:**
- Consumes: `Qualified`, `qualify_signals` (Task 3)
- Produces:
  - `LABEL_OVERRIDES: dict[str, dict]` — `{"3PCA": {"missing_marker": "제3자배정", "label": "유상증자(배정방식 미상)"}}`
  - `DIRECTION_NOTES: dict[str, dict]` — `{"CB_BW": {"markers": (...), "note": "..."}}`
  - `qualify_signals`가 `label`·`note`를 채워 반환 (시그니처 불변)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_qualifiers.py` 하단에 추가:

```python
# ── 라벨 보정 ───────────────────────────────────────────────
def test_label_softened_when_allocation_method_absent():
    """제목에 '제3자배정'이 없으면 그렇게 단정하지 않는다."""
    q = _one("주요사항보고서(유상증자결정)", [PCA3])
    assert q.label == "유상증자(배정방식 미상)"
    assert q.tier == TIER_OBSERVED


def test_label_kept_when_allocation_method_stated():
    q = _one("증권발행결과(자율공시)(제3자배정 유상증자)", [PCA3])
    assert q.label == "제3자배정유상증자"


def test_label_override_only_applies_to_3pca():
    q = _one("주요사항보고서(유상증자결정)", [CB_BW])
    assert q.label == "CB/BW발행"


# ── 사실 주석 ───────────────────────────────────────────────
def test_note_added_when_direction_is_reversed():
    q = _one("전환사채(해외전환사채포함)발행후만기전사채취득(제3회차)", [CB_BW])
    assert "취득" in q.note
    assert q.tier == TIER_OBSERVED   # 주석만 붙이고 강등하지 않는다


def test_note_added_for_bond_sale_decision():
    q = _one("주요사항보고서(자기전환사채매도결정)", [CB_BW])
    assert q.note != ""


def test_no_note_for_plain_issuance():
    q = _one("주요사항보고서(전환사채권발행결정)", [CB_BW])
    assert q.note == ""
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_qualifiers.py -v`
Expected: FAIL — `AssertionError: assert '제3자배정유상증자' == '유상증자(배정방식 미상)'`

- [ ] **Step 3: 최소 구현**

`dart_risk_mcp/core/qualifiers.py`에 추가:

```python
# 라벨 보정 — 제목이 확정해주지 못하는 수식어는 라벨에서 뺀다.
# 3PCA 키워드에 '유상증자'가 통째로 있어 일반공모·소액공모까지 '제3자배정'으로
# 표기되던 것을 막는다(셀트리온 헤드라인 오탐의 직접 원인).
LABEL_OVERRIDES: dict = {
    "3PCA": {
        "missing_marker": "제3자배정",
        "label": "유상증자(배정방식 미상)",
    },
}

# 사실 주석 — tier는 바꾸지 않고 사실만 덧붙인다. 신호 재배정은 하지 않는다.
DIRECTION_NOTES: dict = {
    "CB_BW": {
        "markers": ("사채취득", "사채매도"),
        "note": "발행이 아니라 사채 취득·매도 건입니다",
    },
}


def _adjusted_label(sig: dict, parsed: ParsedName) -> str:
    """제목이 뒷받침하지 못하는 수식어를 뺀 표시 라벨."""
    label = sig.get("label", "")
    rule = LABEL_OVERRIDES.get(sig.get("key", ""))
    if rule and rule["missing_marker"] not in parsed.compact:
        return rule["label"]
    return label


def _direction_note(sig: dict, parsed: ParsedName) -> str:
    """방향이 신호 라벨과 어긋날 때의 사실 주석."""
    rule = DIRECTION_NOTES.get(sig.get("key", ""))
    if not rule:
        return ""
    if any(m in parsed.compact for m in rule["markers"]):
        return rule["note"]
    return ""
```

그리고 `qualify_signals`의 반환 부분을 아래로 교체:

```python
    return [
        Qualified(
            key=sig.get("key", ""),
            label=_adjusted_label(sig, parsed),
            tier=tier,
            reason=reason,
            note=_direction_note(sig, parsed),
        )
        for sig in (signals or [])
    ]
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_qualifiers.py -v`
Expected: PASS (34 passed)

- [ ] **Step 5: 커밋**

```bash
git add dart_risk_mcp/core/qualifiers.py tests/test_qualifiers.py
git commit -m "feat(qualifiers): 라벨 보정과 방향 사실 주석

제목에 '제3자배정'이 없으면 '유상증자(배정방식 미상)'으로 표기해
일반공모·소액공모를 제3자배정으로 단정하던 것을 막는다.
사채 취득·매도 건에는 강등 없이 사실 주석만 붙인다(재배정 아님).

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: `AMBIGUOUS_SIGNAL_KEYS`와 헤드라인 선정

**Files:**
- Modify: `dart_risk_mcp/core/signals.py` (상수 추가만)
- Modify: `dart_risk_mcp/core/qualifiers.py`
- Modify: `dart_risk_mcp/core/__init__.py`
- Modify: `tests/test_qualifiers.py`

**Interfaces:**
- Consumes: `Qualified` (Task 3), `SIGNAL_TYPES` (기존)
- Produces:
  - `signals.AMBIGUOUS_SIGNAL_KEYS: frozenset[str]`
  - `qualifiers.pick_headline(qualified: list[Qualified], order: list[str]) -> Qualified | None`
    - `order`: 신호 키를 내부 우선순위 순으로 나열한 리스트. `None`이면 `qualified` 순서를 그대로 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_qualifiers.py` 하단에 추가:

```python
from dart_risk_mcp.core.qualifiers import pick_headline  # noqa: E402
from dart_risk_mcp.core.signals import (  # noqa: E402
    AMBIGUOUS_SIGNAL_KEYS,
    SIGNAL_TYPES,
)

_ORDER = [s["key"] for s in sorted(SIGNAL_TYPES, key=lambda x: -x["score"])]


def _q(key, label, tier=TIER_OBSERVED):
    from dart_risk_mcp.core.qualifiers import Qualified
    return Qualified(key=key, label=label, tier=tier, reason="", note="")


def test_ambiguous_keys_are_all_real_signal_keys():
    known = {s["key"] for s in SIGNAL_TYPES}
    assert AMBIGUOUS_SIGNAL_KEYS <= known


def test_ambiguous_keys_contents():
    assert AMBIGUOUS_SIGNAL_KEYS == frozenset(
        {"TREASURY", "TREASURY_TRUST", "EQUITY_SPLIT", "FUND_OUTFLOW", "ACQ_REVIEW"}
    )


def test_headline_is_none_when_all_observed_are_ambiguous():
    """삼성전자 케이스 — observed가 자사주뿐이면 헤드라인이 없다."""
    qs = [_q("TREASURY", "자사주매입/처분"), _q("TREASURY", "자사주매입/처분")]
    assert pick_headline(qs, _ORDER) is None


def test_headline_picks_non_ambiguous_even_if_lower_priority():
    """셀트리온 케이스 — 자사주 9건 + 경영권분쟁 1건이면 후자가 헤드라인."""
    qs = [_q("TREASURY", "자사주매입/처분"), _q("MGMT_DISPUTE", "경영권분쟁")]
    head = pick_headline(qs, _ORDER)
    assert head is not None and head.key == "MGMT_DISPUTE"


def test_headline_ignores_procedural():
    qs = [_q("CB_BW", "CB/BW발행", tier=TIER_PROCEDURAL)]
    assert pick_headline(qs, _ORDER) is None


def test_headline_respects_priority_order_among_candidates():
    qs = [_q("EXEC", "임원변동"), _q("CB_BW", "CB/BW발행")]
    head = pick_headline(qs, _ORDER)
    expected = min({"EXEC", "CB_BW"}, key=_ORDER.index)
    assert head.key == expected


def test_headline_empty_input():
    assert pick_headline([], _ORDER) is None
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_qualifiers.py -v`
Expected: FAIL — `ImportError: cannot import name 'AMBIGUOUS_SIGNAL_KEYS'`

- [ ] **Step 3: 최소 구현**

`dart_risk_mcp/core/signals.py` 맨 아래(`CAPITAL_EVENT_KEYS` 정의 근처)에 추가:

```python
# 양면적 신호 — 정상 기업활동으로도 빈발해 단독으로는 헤드라인이 되지 않는다.
#
# 새로운 판단을 만들지 않는다. 이 코드베이스가 이미 양면성을 서술하고 있는
# 신호만 담는다:
#   TREASURY/TREASURY_TRUST — explain.py "주주 환원으로 긍정적일 수도 있지만…"
#   EQUITY_SPLIT            — 정상 유동성 조치
#   FUND_OUTFLOW            — explain.py "대기업의 일상적 계열 지원과 구분 불가"
#   ACQ_REVIEW              — explain.py "정상적인 사업 인수도 이 유형"
#
# 목록·카테고리 집계·패턴 매칭에는 정상 참여한다. 헤드라인만 못 된다.
AMBIGUOUS_SIGNAL_KEYS: frozenset = frozenset({
    "TREASURY",
    "TREASURY_TRUST",
    "EQUITY_SPLIT",
    "FUND_OUTFLOW",
    "ACQ_REVIEW",
})
```

`dart_risk_mcp/core/qualifiers.py`에 추가 (상단 import에 `from .signals import AMBIGUOUS_SIGNAL_KEYS`):

```python
from .signals import AMBIGUOUS_SIGNAL_KEYS


def pick_headline(
    qualified: "list[Qualified]",
    order: "list[str] | None" = None,
) -> "Qualified | None":
    """헤드라인이 될 신호를 고른다. 없으면 None.

    후보 = observed 신호 중 AMBIGUOUS_SIGNAL_KEYS를 뺀 것.
    후보가 비면 None을 반환하고, 호출부는 중립 표기로 대체한다.

    ambiguous를 후보로 되돌리는 별도 조건은 두지 않는다 — non-ambiguous가
    하나라도 있으면 그것이 헤드라인이 되고, 없으면 중립 표기이므로
    ambiguous가 헤드라인이 되어야 할 경우가 존재하지 않는다.
    """
    candidates = [
        q for q in (qualified or [])
        if q.tier == TIER_OBSERVED and q.key not in AMBIGUOUS_SIGNAL_KEYS
    ]
    if not candidates:
        return None
    if not order:
        return candidates[0]
    rank = {k: i for i, k in enumerate(order)}
    return min(candidates, key=lambda q: rank.get(q.key, len(rank)))
```

`dart_risk_mcp/core/__init__.py`의 `from .signals import (...)` 블록에 `AMBIGUOUS_SIGNAL_KEYS`를 추가하고, 파일 하단에 신규 import 블록을 넣는다:

```python
from .qualifiers import (
    ParsedName,
    Qualified,
    TIER_OBSERVED,
    TIER_PROCEDURAL,
    is_false_amendment,
    parse_report_name,
    pick_headline,
    qualify_signals,
)
```

`__all__`에도 위 8개 + `AMBIGUOUS_SIGNAL_KEYS`를 추가한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_qualifiers.py -v && python -c "import dart_risk_mcp.server; print('OK')"`
Expected: PASS (41 passed), 그리고 `OK`

- [ ] **Step 5: 커밋**

```bash
git add dart_risk_mcp/core/signals.py dart_risk_mcp/core/qualifiers.py dart_risk_mcp/core/__init__.py tests/test_qualifiers.py
git commit -m "feat: 양면적 신호 정의와 헤드라인 선정 규칙

자사주·액면분할·자금유출·양수 5종은 정상 기업활동으로도 빈발해
단독으로는 헤드라인이 되지 않게 한다. 목록·집계·패턴 매칭에는
정상 참여한다. 목록의 근거는 explain.py가 이미 쓰고 있는 서술이다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: `signals-data.json` 내보내기

**Files:**
- Modify: `scripts/export_tool_data.py`
- Modify: `tests/test_export_tool_data.py`
- Regenerate: `docs/tool/signals-data.json`

**Interfaces:**
- Consumes: `qualifiers` 모듈 상수 (Task 3~4), `AMBIGUOUS_SIGNAL_KEYS` (Task 5)
- Produces: `signals-data.json`에 최상위 키 2개
  - `qualifier_rules`: `{third_party_titles, phase_tails, subsidiary_subtitles, related_party_prefix, amendment_tags, tails, label_overrides, direction_notes}`
  - `ambiguous_signal_keys`: `list[str]` (정렬됨)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_export_tool_data.py` 하단에 추가:

```python
def test_export_includes_qualifier_rules():
    from scripts.export_tool_data import build_signals_data
    from dart_risk_mcp.core import qualifiers as q

    data = build_signals_data()
    rules = data["qualifier_rules"]
    assert rules["third_party_titles"] == list(q.THIRD_PARTY_TITLES)
    assert rules["phase_tails"] == list(q.PHASETAILS)
    assert rules["subsidiary_subtitles"] == list(q.SUBSIDIARY_SUBTITLES)
    assert rules["related_party_prefix"] == q.RELATED_PARTY_PREFIX
    assert rules["amendment_tags"] == list(q.AMENDMENT_TAGS)
    assert rules["tails"] == list(q.TAILS)


def test_export_includes_label_overrides_and_notes():
    from scripts.export_tool_data import build_signals_data

    data = build_signals_data()
    rules = data["qualifier_rules"]
    assert rules["label_overrides"]["3PCA"]["label"] == "유상증자(배정방식 미상)"
    assert rules["direction_notes"]["CB_BW"]["markers"] == ["사채취득", "사채매도"]


def test_export_includes_ambiguous_keys():
    from scripts.export_tool_data import build_signals_data
    from dart_risk_mcp.core.signals import AMBIGUOUS_SIGNAL_KEYS

    data = build_signals_data()
    assert data["ambiguous_signal_keys"] == sorted(AMBIGUOUS_SIGNAL_KEYS)


def test_export_does_not_leak_score_or_severity():
    """무점수 원칙 — 기존 경계가 유지되는지 재확인."""
    from scripts.export_tool_data import build_signals_data

    blob = json.dumps(build_signals_data(), ensure_ascii=False)
    assert '"score"' not in blob
    assert '"severity"' not in blob
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_export_tool_data.py -v`
Expected: FAIL — `KeyError: 'qualifier_rules'`

- [ ] **Step 3: 최소 구현**

`scripts/export_tool_data.py`의 import 블록에 추가:

```python
from dart_risk_mcp.core import qualifiers as _q  # noqa: E402
from dart_risk_mcp.core.signals import AMBIGUOUS_SIGNAL_KEYS  # noqa: E402
```

`build_signals_data()`의 반환 dict에 두 키를 추가:

```python
        # 신호 한정층 규칙 — 데이터만 내보내고 로직은 뷰어 JS가 이식한다.
        # 문자열 목록의 이중 관리를 막는 것이 목적이다(키워드와 동일한 원칙).
        "qualifier_rules": {
            "third_party_titles": list(_q.THIRD_PARTY_TITLES),
            "phase_tails": list(_q.PHASETAILS),
            "subsidiary_subtitles": list(_q.SUBSIDIARY_SUBTITLES),
            "related_party_prefix": _q.RELATED_PARTY_PREFIX,
            "amendment_tags": list(_q.AMENDMENT_TAGS),
            "tails": list(_q.TAILS),
            "label_overrides": {
                k: dict(v) for k, v in _q.LABEL_OVERRIDES.items()
            },
            "direction_notes": {
                k: {"markers": list(v["markers"]), "note": v["note"]}
                for k, v in _q.DIRECTION_NOTES.items()
            },
        },
        "ambiguous_signal_keys": sorted(AMBIGUOUS_SIGNAL_KEYS),
```

- [ ] **Step 4: 통과 확인 + 산출물 재생성**

```bash
python -m pytest tests/test_export_tool_data.py -v
python scripts/export_tool_data.py
python -m pytest tests/test_export_tool_data.py -v
```
Expected: 첫 실행 PASS, 재생성 후에도 PASS

- [ ] **Step 5: 커밋**

```bash
git add scripts/export_tool_data.py tests/test_export_tool_data.py docs/tool/signals-data.json
git commit -m "feat(export): 한정층 규칙 데이터와 양면적 신호 키 내보내기

뷰어가 규칙 문자열을 자체 보유하지 않고 signals-data.json에서 읽게 한다.
로직만 JS로 이식하고 데이터는 core 단일 소스를 유지한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: `server.py` 배선 + 골든 재생성

**Files:**
- Modify: `dart_risk_mcp/server.py:717` 근처 (`analyze_company_risk` 신호 루프)
- Modify: `dart_risk_mcp/server.py:1488` 근처 (`build_event_timeline` 신호 루프)
- Regenerate: `tests/fixtures/sample_outputs/*.txt`
- Delete: `tmp/_spike/`

**Interfaces:**
- Consumes: `parse_report_name`, `qualify_signals`, `is_false_amendment`, `pick_headline` (Task 2~5)
- Produces: `signal_events` 원소에 `"tier"`·`"reason"`·`"note"` 키 추가. 기존 키(`key`·`label`·`score`·`report_nm`·`rcept_dt`·`rcept_no`·`is_amendment`)는 그대로 유지한다.

- [ ] **Step 1: `analyze_company_risk` 루프 교체**

`server.py:712-731`의 루프를 아래로 교체한다:

```python
    for d in disclosures:
        report_nm = d.get("report_nm", "")
        rcept_no = d.get("rcept_no", "")
        rcept_dt = d.get("rcept_dt", "")[:10]
        is_amendment = is_amendment_disclosure(report_nm)
        parsed = parse_report_name(report_nm)
        matched = match_signals(report_nm)
        # '[정정명령부과]증권신고서'처럼 _AMENDMENT_RE에 걸리지만 실제
        # 정정이 아닌 공시는 접두를 벗겨 재매칭한다. 진짜 정정공시의
        # 기존 동작(신호 없음)은 바뀌지 않는다.
        if not matched and is_amendment and is_false_amendment(parsed):
            matched = match_signals(strip_amendment_prefix(report_nm))
        qualified = qualify_signals(matched, parsed, d)

        for sig, q in zip(matched, qualified):
            signal_events.append(
                {
                    "key": sig["key"],
                    "label": q.label,
                    "score": 0 if is_amendment else sig["score"],
                    "report_nm": report_nm,
                    "rcept_dt": rcept_dt,
                    "rcept_no": rcept_no,
                    "is_amendment": is_amendment,
                    "tier": q.tier,
                    "reason": q.reason,
                    "note": q.note,
                }
            )
            if sig["key"] == "CB_BW" and not is_amendment and rcept_no:
                cb_rcept_nos.append(rcept_no)
```

`server.py` 상단 import에 추가:

```python
from .core.qualifiers import (
    TIER_OBSERVED,
    is_false_amendment,
    parse_report_name,
    pick_headline,
    qualify_signals,
)
from .core.signals import strip_amendment_prefix
```

(`strip_amendment_prefix`가 이미 import되어 있으면 중복 추가하지 않는다.)

- [ ] **Step 2: 집계·헤드라인을 `observed`로 제한**

`server.py:852`의 `if not signal_events:` **바로 앞**에 분리 코드를 넣는다.

⚠️ **`tier` 키가 없는 원소가 존재한다.** `signal_events`에는 공시에서 온 신호(717행 루프) 외에
플래그가 직접 append된다 — `server.py:764`(부실 이벤트)·`780`·`792`(재무 이상)·`807`(CAPITAL_CHURN)·
`839`(DIVIDEND_DRAIN). 이들은 제목이 없어 한정 대상이 아니다. **기본값을 `TIER_OBSERVED`로 두어
누락 원소가 조용히 사라지지 않게 한다.**

```python
    # 한정층 — 공시에서 온 신호만 tier를 갖는다. 재무·부실 플래그(764·780·
    # 792·807·839행에서 직접 append)는 제목이 없어 한정 대상이 아니므로
    # 기본값 observed로 남긴다.
    observed_events = [
        e for e in signal_events
        if e.get("tier", TIER_OBSERVED) == TIER_OBSERVED
    ]
    procedural_events = [
        e for e in signal_events
        if e.get("tier", TIER_OBSERVED) != TIER_OBSERVED
    ]
```

이후 아래 4곳의 `signal_events`를 `observed_events`로 바꾼다.

| 위치 | 원래 코드 | 바꿀 코드 |
|---|---|---|
| `server.py:852` | `if not signal_events:` | `if not observed_events:` |
| `server.py:865` | `sig_keys = list({e["key"] for e in signal_events if not e["is_amendment"]})` | `... for e in observed_events ...` |
| `server.py:897-901` | `top_signal = max((e for e in signal_events if not e["is_amendment"]), key=...)` | 아래 Step 2b로 교체 |
| `server.py:929` | `non_amend_events = [e for e in signal_events if not e["is_amendment"]]` | `... for e in observed_events ...` |
| `server.py:969` | `f"━━ 관찰된 신호 ({len(signal_events)}건) ━━"` | `f"━━ 관찰된 신호 ({len(observed_events)}건) ━━"` 및 그 아래 반복 대상도 `observed_events` |

- [ ] **Step 2b: `top_signal` 선정을 `pick_headline`으로 교체**

`server.py:897-901`을 아래로 교체한다. 기존 `max(...)`는 양면적 신호를 걸러내지 않아
삼성전자에 "자사주매입/처분"이 붙던 원인이다.

```python
    # 헤드라인 — 양면적 신호는 단독으로 후보가 되지 않는다.
    _order = [s["key"] for s in sorted(SIGNAL_TYPES, key=lambda x: -x["score"])]
    _cands = [
        Qualified(key=e["key"], label=e["label"], tier=TIER_OBSERVED, reason="", note="")
        for e in observed_events if not e["is_amendment"]
    ]
    _head = pick_headline(_cands, _order)
    top_signal = None
    if _head is not None:
        top_signal = next(
            (e for e in observed_events
             if e["key"] == _head.key and not e["is_amendment"]),
            None,
        )
```

`server.py` import에 `Qualified`와 `SIGNAL_TYPES`를 추가한다(`SIGNAL_TYPES`가 이미 있으면 생략).

- [ ] **Step 2c: 헤드라인이 없을 때의 문구**

`server.py:949`의 `if top_signal:` 블록에 `else` 분기를 추가한다.

```python
    if top_signal:
        s3 = _compose_top_signal_sentence(top_signal_label, top_signal_prose)
    elif observed_events:
        _types = sorted(
            {(e["key"], e["label"]) for e in observed_events if not e["is_amendment"]}
        )
        _txt = " · ".join(
            f"{label} {sum(1 for e in observed_events if e['key'] == key)}건"
            for key, label in _types
        )
        s3 = f"이 기간 관찰된 유형: {_txt}"
    else:
        s3 = (
            "이 기간 공시에서는 관찰 신호가 없습니다. "
            "공시 외 지표(재무·감사의견·연속적자)는 아래 블록에서 확인하세요."
        )
```

- [ ] **Step 2d: 절차·사후 보고 절 추가**

리포트 본문 조립부에서 "관찰된 신호" 절 **뒤에** 아래 블록을 삽입한다.

```python
    if procedural_events:
        parts.append(f"\n━━ 절차·사후 보고 ({len(procedural_events)}건) ━━")
        parts.append(
            "회사가 낸 사건 자체의 공시가 아니거나, 이미 끝난 건의 사후 보고입니다."
        )
        for e in procedural_events[:20]:
            parts.append(f"• {e['rcept_dt']} · {e['report_nm']}")
            parts.append(f"  → {e.get('reason', '')}")
        if len(procedural_events) > 20:
            parts.append(f"… 외 {len(procedural_events) - 20}건")
```

`parts`는 해당 함수가 실제로 쓰는 줄 누적 리스트 이름으로 맞춘다(`server.py:969` 주변에서 확인).

- [ ] **Step 3: `build_event_timeline` 루프 교체**

`server.py:1482-1493`의 루프를 아래로 교체한다:

```python
    for d in disclosures:
        report_nm = d.get("report_nm", "")
        rcept_dt = d.get("rcept_dt", "")[:10]
        rcept_no = d.get("rcept_no", "")
        parsed = parse_report_name(report_nm)
        if is_amendment_disclosure(report_nm) and not is_false_amendment(parsed):
            continue
        matched = match_signals(report_nm) or match_signals(
            strip_amendment_prefix(report_nm)
        )
        qualified = qualify_signals(matched, parsed, d)
        for sig, q in zip(matched, qualified):
            if q.tier != TIER_OBSERVED:
                continue
            phase = _PHASE_MAP.get(sig["key"], "심화기")
            events.append((rcept_dt, phase, sig["key"], q.label, report_nm, rcept_no))
            tax_ids = SIGNAL_KEY_TO_TAXONOMY.get(sig["key"], [])
            all_tax_ids.update(tax_ids)
```

- [ ] **Step 4: import 검증과 단위 테스트**

```bash
python -c "import dart_risk_mcp.server; print('OK')"
python -m pytest tests/ -q
```
Expected: `OK`, 그리고 골든 테스트를 제외한 전부 PASS

- [ ] **Step 5: 골든 재생성**

```bash
python scripts/regen_goldens.py
python -m pytest tests/test_golden_output_hygiene.py -v
```
Expected: hygiene 9/9 PASS

- [ ] **Step 6: 회귀 기대값 대조**

`git diff --stat tests/fixtures/sample_outputs/`로 바뀐 골든을 확인하고, 아래 표와 대조한다. **어긋나면 규칙이 과하거나 부족한 것이므로 커밋하지 말고 원인을 찾는다.**

| 회사 | 현재 신호 | 기대 observed | 기대 procedural | 헤드라인 |
|---|---|---|---|---|
| 아틀라스링크 | 36 | 21 | 15 | 유지 |
| 제이스코홀딩스 | 26 | 19 | 7 | 유지 |
| STX | 6 | 5 | 1 | 유지 |
| 삼성전자 | 8 | 2 | 6 | **없음** (전부 ambiguous) |
| 셀트리온 | 32 | 10 | 22 | **경영권분쟁소송** |
| 두산 | 10 | 1 | 9 | **없음** (전부 ambiguous) |
| 헬릭스미스 | 1 | 0 | 1 | **없음** → 0건 안내 문구 |

특히 확인할 것:
- 아틀라스링크의 `최대주주변경`·`금전대여결정`·`타인에대한채무보증결정`·`유형자산양수결정`이 전부 남아 있고 `capital_backflow` 패턴이 계속 발화하는가
- 제이스코의 `주요사항보고서(자기전환사채매도결정)` 7건에 사실 주석이 붙었는가
- 셀트리온에서 `유상증자결정(종속회사의주요경영사항)`이 procedural로 내려갔는가

- [ ] **Step 7: 스파이크 정리 후 커밋**

```bash
rm -rf tmp/_spike tmp/_an
git add dart_risk_mcp/server.py tests/fixtures/sample_outputs/
git commit -m "feat(server): 한정층 배선 + 골든 재생성

analyze_company_risk·build_event_timeline이 신호를 observed/procedural로
나눠 집계·헤드라인·패턴 매칭에 observed만 쓴다. procedural은 사유와 함께
리포트 말미에 접힌 목록으로 남는다.

골든 대조: 아틀라스링크 36→21(capital_backflow 유지), 제이스코 26→19,
STX 6→5. 삼성전자 8→2·두산 10→1은 전부 양면적 신호라 헤드라인이 사라진다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: 뷰어 JS — 파서·한정자 이식

**Files:**
- Modify: `docs/tool/index.html` (`matchSignals` 정의부 근처, 846행)

**Interfaces:**
- Consumes: `DATA.qualifier_rules`, `DATA.ambiguous_signal_keys` (Task 6)
- Produces: 전역 함수 3개
  - `parseReportName(nm)` → `{tags, body, subtitles, tail, compact}`
  - `qualifySignals(sigs, parsed, filing)` → `[{key, label, category, caution, taxonomies, prose, tier, reason, note}]`
  - `pickHeadline(qualified)` → `object | null`
  - 상수 `TIER_OBSERVED = "observed"`, `TIER_PROCEDURAL = "procedural"`

> **Python `Qualified`와 필드가 다른 것은 의도된 차이다.** JS 쪽은 반환 객체를 그대로
> 렌더에 넘기므로 `category`·`caution`·`taxonomies`·`prose`를 함께 실어 나른다. Python은
> 이 값들을 `SIGNAL_TYPES`·`TAXONOMY`에서 따로 조회하므로 `Qualified`에 담지 않는다.
> **판정에 쓰이는 필드(`tier`·`reason`·`label`·`note`)는 양쪽이 동일해야 한다.**
>
> `pickHeadline`이 인자 1개인 것도 의도된 차이다 — JS는 `DATA.signals`가 이미 우선순위
> 순으로 정렬돼 있어 order를 인자로 받을 필요가 없다.

- [ ] **Step 1: 파서·한정자 함수 추가**

`docs/tool/index.html`의 `matchSignals` 정의 **바로 아래**에 삽입한다. core `qualifiers.py`의 1:1 이식이며 **규칙 문자열은 전부 `DATA.qualifier_rules`에서 읽는다** — JS에 하드코딩하지 않는다.

```javascript
/* ── 신호 한정층 ──────────────────────────────────
   core/qualifiers.py의 1:1 이식. 규칙 문자열은 signals-data.json의
   qualifier_rules에서 읽어 이중 관리를 피한다. 로직만 여기 있다. */
const TIER_OBSERVED = "observed", TIER_PROCEDURAL = "procedural";

function qrules() { return (DATA && DATA.qualifier_rules) || {}; }

function tailOf(text) {
  const tails = (qrules().tails || []).slice().sort((a, b) => b.length - a.length);
  for (const t of tails) if (text.endsWith(t)) return t;
  return "";
}

function parseReportName(reportNm) {
  let rest = String(reportNm || "").trim();
  const tags = [];
  for (;;) {
    const m = rest.match(/^\[([^\]]*)\]\s*/);
    if (!m) break;
    tags.push(m[1].trim());
    rest = rest.slice(m[0].length);
  }
  const compact = rest.replace(/\s+/g, "");
  const subtitles = [];
  compact.replace(/\(([^()]*)\)/g, (_, s) => { if (s) subtitles.push(s); return ""; });
  const body = compact.replace(/\([^()]*\)/g, "");
  let tail = tailOf(body);
  // '주요사항보고서(자기주식취득결정)'처럼 본체가 껍데기면 괄호 쪽을 본다.
  if (tail === "보고서" && subtitles.length) {
    tail = tailOf(subtitles[subtitles.length - 1]) || tail;
  }
  return { tags, body, subtitles, tail, compact };
}

// core _fold_corp_name 이식 — 법인 표기(㈜/(주)/주식회사)·공백 차이를 흡수
function foldCorpName(name) {
  return String(name || "")
    .replace(/㈜|\(주\)|주식회사|\(유\)|유한회사/g, "")
    .replace(/\s+/g, "")
    .trim()
    .toUpperCase();
}

function isAmendmentTag(tag) {
  const tags = qrules().amendment_tags || [];
  const t = String(tag || "").trim();
  return tags.includes(t) || t.endsWith("정정");
}

function isFalseAmendment(parsed) {
  if (!parsed.tags.length) return false;
  return !parsed.tags.some(isAmendmentTag);
}

function demotionReason(parsed, filing) {
  const r = qrules(), f = filing || {};
  const filer = String(f.flr_nm || "").trim();
  const corp = String(f.corp_name || "").trim();
  // R1 — 제출인이 회사가 아님
  if (filer && corp && foldCorpName(filer) !== foldCorpName(corp)) {
    return `회사가 낸 공시가 아닙니다 (제출인: ${filer})`;
  }
  // R1b — flr_nm이 없을 때의 제목 기반 예비
  if (!filer) {
    for (const t of (r.third_party_titles || [])) {
      if (parsed.body.startsWith(t)) return "제3자가 회사에 대해 제출한 보고서입니다";
    }
  }
  // R5 — 정정·후속 꼬리표
  for (const tag of parsed.tags) {
    if (isAmendmentTag(tag)) return `기존 공시의 정정·후속 보고입니다 (${tag})`;
  }
  // R2 — 사후·해제 국면
  if ((r.phase_tails || []).includes(parsed.tail)) {
    return parsed.tail === "결과보고서"
      ? "이미 실행된 건의 결과 보고입니다"
      : `체결이 아니라 ${parsed.tail}입니다`;
  }
  // R3 — 자회사·특수관계인 사안
  if (parsed.subtitles.some((s) => (r.subsidiary_subtitles || []).includes(s))) {
    return "이 회사가 아니라 자회사 사안입니다";
  }
  if (r.related_party_prefix && parsed.body.startsWith(r.related_party_prefix)) {
    return "회사가 아니라 특수관계인의 행위입니다";
  }
  // R4 — 해명·미확정
  if (parsed.tail === "해명" || parsed.subtitles.includes("미확정")) {
    return "회사가 미확정으로 답한 해명 공시입니다";
  }
  return "";
}

function adjustedLabel(sig, parsed) {
  const rule = (qrules().label_overrides || {})[sig.key];
  if (rule && !parsed.compact.includes(rule.missing_marker)) return rule.label;
  return sig.label;
}

function directionNote(sig, parsed) {
  const rule = (qrules().direction_notes || {})[sig.key];
  if (!rule) return "";
  return (rule.markers || []).some((m) => parsed.compact.includes(m)) ? rule.note : "";
}

function qualifySignals(sigs, parsed, filing) {
  const reason = demotionReason(parsed, filing);
  const tier = reason ? TIER_PROCEDURAL : TIER_OBSERVED;
  return (sigs || []).map((s) => ({
    key: s.key,
    label: adjustedLabel(s, parsed),
    category: s.category,
    caution: s.caution,
    taxonomies: s.taxonomies,
    prose: s.prose,
    tier, reason,
    note: directionNote(s, parsed),
  }));
}

function pickHeadline(qualified) {
  const amb = new Set(DATA.ambiguous_signal_keys || []);
  const order = DATA.signals.map((s) => s.key);
  const cands = (qualified || []).filter(
    (q) => q.tier === TIER_OBSERVED && !amb.has(q.key));
  if (!cands.length) return null;
  return cands.slice().sort(
    (a, b) => order.indexOf(a.key) - order.indexOf(b.key))[0];
}
```

- [ ] **Step 2: 브라우저 콘솔로 동작 확인**

`preview_start`로 뷰어를 열고 콘솔에서:

```javascript
parseReportName("[첨부정정]유상증자결정(종속회사의주요경영사항)")
// → {tags:["첨부정정"], body:"유상증자결정", subtitles:["종속회사의주요경영사항"], tail:"결정", ...}

demotionReason(parseReportName("자기주식취득결과보고서"), null)
// → "이미 실행된 건의 결과 보고입니다"

demotionReason(parseReportName("주요사항보고서(자기주식취득신탁계약해지결정)"), null)
// → ""   ← 과잉 강등 방지

demotionReason(parseReportName("주식등의대량보유상황보고서(일반)"), null)
// → "제3자가 회사에 대해 제출한 보고서입니다"
```

네 줄 모두 위와 일치해야 한다. 어긋나면 `signals-data.json`이 재생성되지 않았거나(Task 6) 이식 로직이 core와 갈라진 것이다.

- [ ] **Step 3: 커밋**

```bash
git add docs/tool/index.html
git commit -m "feat(viewer): 한정층 파서·규칙 JS 이식

core/qualifiers.py의 1:1 이식. 규칙 문자열은 signals-data.json의
qualifier_rules에서 읽어 하드코딩하지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: 뷰어 렌더 — 두 층·헤드라인·묶음·0건

**Files:**
- Modify: `docs/tool/index.html` — `buildResult`(901행 근처), 피드 렌더(986행 근처), 요약 렌더(1232행 근처), `categoryBars`(1359행), 타임라인 SVG(1435행 근처)

**Interfaces:**
- Consumes: `parseReportName`, `qualifySignals`, `pickHeadline` (Task 8)
- Produces: `CUR`에 `observedEvents`·`proceduralEvents`·`headline`·`bulkHolding` 추가

- [ ] **Step 1: `buildResult`에서 신호를 한정한다**

`buildResult`의 항목 루프(908-914행)를 교체:

```javascript
  for (const it of items) {
    const nm = it.report_nm || "";
    const parsed = parseReportName(nm);
    const isAmend = AMEND_RE.test(nm);
    if (isAmend) amendCount++;
    // '[정정명령부과]'처럼 정정이 아닌 태그는 접두를 벗겨 재매칭한다.
    let sigs = isAmend ? [] : matchSignals(nm);
    if (!sigs.length && isAmend && isFalseAmendment(parsed)) {
      sigs = matchSignals(nm.replace(/^(\[[^\]]*\])+/, ""));
    }
    const qual = qualifySignals(sigs, parsed, { ...it, corp_name: name });
    if (qual.length) events.push({ date: it.rcept_dt, nm, rcept: it.rcept_no, signals: qual });
    rows.push({ date: it.rcept_dt, nm, rcept: it.rcept_no, signals: qual, isAmend });
  }
```

- [ ] **Step 2: 집계를 observed로 제한**

916-930행의 집계 블록을 교체:

```javascript
  // 절차·사후 보고는 집계·헤드라인·패턴 매칭에서 전부 빠진다.
  const obs = (e) => e.signals.filter((s) => s.tier === TIER_OBSERVED);
  const observedEvents = events.filter((e) => obs(e).length);
  const proceduralEvents = events.filter((e) => !obs(e).length);

  const detectedTax = new Set(
    observedEvents.flatMap((e) => obs(e).flatMap((s) => s.taxonomies || [])));
  const patterns = DATA.patterns.filter(
    (p) => p.signal_sequence.every((t) => detectedTax.has(t)));
  const capitalKeys = new Set(DATA.capital_event_keys);
  const capitalEvents = observedEvents.filter(
    (e) => obs(e).some((s) => capitalKeys.has(s.key)));
  const catCount = {};
  for (const e of observedEvents) for (const s of obs(e)) catCount[s.category] = (catCount[s.category] || 0) + 1;
  const typeCount = {};
  for (const e of observedEvents) for (const s of obs(e)) typeCount[s.key] = (typeCount[s.key] || 0) + 1;
  const detectedTypes = DATA.signals.filter((s) => typeCount[s.key]);
  const headline = pickHeadline(observedEvents.flatMap(obs));
  const heaviest = headline ? DATA.signals.find((s) => s.key === headline.key) || null : null;
  const crisisEvents = observedEvents.filter((e) => obs(e).some((s) => s.category >= 7));
```

`CUR`에 저장할 때 `observedEvents`·`proceduralEvents`·`headline`을 함께 넣는다.

이후 아래 3곳의 `events` 참조를 `observedEvents`로 바꾼다 — 절차·사후 보고가
분포 막대·타임라인에 그려지면 두 층으로 나눈 의미가 없어진다.

| 위치 | 함수 | 바꿀 것 |
|---|---|---|
| `index.html:1359` 근처 | `categoryBars(catCount)` | `catCount` 자체가 이미 observed 기준이라 **변경 불필요** — 확인만 |
| `index.html:1376` 근처 | 신호 그룹 묶음 (`groups.push`) | 입력 `events` → `observedEvents` |
| `index.html:1424·1435·1454` 근처 | 타임라인 SVG (`bucket.maxCat`, `cats`, `circle` 렌더) | 입력 `events` → `observedEvents` |

각 지점에서 `e.signals` 를 순회하는 코드는 `e.signals.filter((s) => s.tier === TIER_OBSERVED)`
로 감싼다 — 한 공시에 observed와 procedural 신호가 섞일 수는 없지만(사유는 공시 단위로
결정된다), 나중에 규칙이 신호별로 갈라져도 안전하도록 방어한다.

- [ ] **Step 3: 상단 카운터와 0건 안내**

요약 렌더(1232행 근처)의 헤드라인 블록을 교체:

```javascript
  html += `<div class="dim" style="font-size:0.9rem;margin-bottom:0.8rem">
    관찰 신호 <b style="color:var(--fg)">${observedEvents.length}건</b>
    · 절차·사후 보고 <b style="color:var(--fg)">${proceduralEvents.length}건</b>
  </div>`;

  if (heaviest) {
    /* 기존 헤드라인 카드 그대로 */
  } else if (observedEvents.length) {
    const types = detectedTypes.map((s) => `${esc(s.label)} ${typeCount[s.key]}건`).join(" · ");
    html += `<div class="card"><div class="dim">이 기간 관찰된 유형: ${types}</div></div>`;
  } else {
    html += `<div class="card"><div>이 기간 공시에서는 관찰 신호가 없습니다.</div>
      <div class="dim" style="margin-top:0.4rem">공시 외 지표(재무·감사의견·연속적자)는 아래 블록에서 확인하세요.</div></div>`;
  }
```

- [ ] **Step 4: 절차·사후 보고 접힌 층 + 대량보유 묶음**

피드 렌더 아래에 절차 층을 추가한다:

```javascript
function renderProcedural(proceduralEvents, totalCount) {
  if (!proceduralEvents.length) return "";
  const rules = qrules().third_party_titles || [];
  const bulk = proceduralEvents.filter(
    (e) => rules.some((t) => parseReportName(e.nm).body.startsWith(t)));
  let summary = "";
  if (bulk.length) {
    const dates = bulk.map((e) => e.date).sort();
    // 임계값을 두지 않는다 — 건수만으로는 아틀라스링크(15/61)와
    // 셀트리온(14/222)을 가를 수 없다. 분모를 함께 적어 사용자가 읽게 한다.
    summary = `<div class="dim" style="margin:0.4rem 0 0.8rem">
      대량보유상황보고 ${bulk.length}건 — 전체 공시 ${totalCount}건 중
      (${fmtDate(dates[0])}~${fmtDate(dates[dates.length - 1])})</div>`;
  }
  const rowsHtml = proceduralEvents.map((e) => `
    <div class="prow">
      <span class="mono dim">${fmtDate(e.date)}</span>
      <a href="${dartUrl(e.rcept)}" target="_blank" rel="noopener">${esc(e.nm)}</a>
      <div class="dim" style="font-size:0.8rem">→ ${esc(e.signals[0].reason)}</div>
    </div>`).join("");
  return `<details class="proc"><summary>절차·사후 보고 ${proceduralEvents.length}건</summary>
    ${summary}${rowsHtml}</details>`;
}
```

`<style>` 블록에 아래를 추가한다. 기존 CSS 변수만 쓰고 새 색을 만들지 않는다.

```css
.proc { margin-top: 1.2rem; border-top: 1px solid var(--line); padding-top: 0.8rem; }
.proc > summary { cursor: pointer; color: var(--dim); font-size: 0.9rem; padding: 0.3rem 0; }
.proc > summary:hover { color: var(--fg); }
.prow { padding: 0.45rem 0; border-bottom: 1px solid var(--line); font-size: 0.86rem; }
.prow:last-child { border-bottom: none; }
.prow a { color: var(--dim2); text-decoration: none; }
.prow a:hover { color: var(--fg); text-decoration: underline; }
```

`--line`·`--dim`·`--dim2`·`--fg`가 실제 존재하는 변수명인지 `<style>` 블록 상단의
`:root` 정의에서 확인하고, 다르면 그 파일의 실제 변수명으로 맞춘다.

- [ ] **Step 5: 사실 주석 표시**

피드 행 렌더에서 `s.note`가 있으면 라벨 뒤에 dim으로 붙인다:

```javascript
${s0 && s0.note ? `<div class="dim" style="font-size:0.78rem">※ ${esc(s0.note)}</div>` : ""}
```

- [ ] **Step 6: 브라우저 검증**

`preview_start`로 뷰어를 열고 **네 회사**를 실제로 스캔해 확인한다.

| 입력 | 확인할 것 |
|---|---|
| 삼성전자 | 상단 `관찰 신호 2건 · 절차·사후 보고 6건`, 헤드라인 카드 없음, "관찰된 유형: 자사주…" 표기 |
| 아틀라스링크 | `관찰 신호 21건`, 최대주주변경·금전대여 남음, 절차 층에 "대량보유상황보고 15건 — 전체 공시 N건 중" |
| 두산 | 헤드라인 없음, 해명 4건이 절차 층으로 |
| 헬릭스미스 | `관찰 신호 0건` + 0건 안내 문구 |

`read_console_messages`로 에러 0건, `computer{action:"screenshot"}`로 삼성전자·아틀라스링크 화면을 캡처해 남긴다.

- [ ] **Step 7: 커밋**

```bash
git add docs/tool/index.html
git commit -m "feat(viewer): 관찰 신호·절차 사후보고 두 층 렌더

집계·헤드라인·패턴 매칭에 observed만 쓰고, procedural은 사유와 함께
접힌 층으로 남긴다. 대량보유보고는 임계 없이 묶어 분모를 병기한다.
관찰 신호 0건이면 '안전'으로 오독되지 않게 안내 문구를 표기한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 10: 좁은 T2 — 펼칠 때만 원문 확인

**Files:**
- Modify: `docs/tool/index.html` (상세 패널 렌더, 1039-1070행 근처)

**Interfaces:**
- Consumes: `fetchDisclosureText(rcept)` (기존, 1150행), `LABEL_OVERRIDES` (Task 6)
- Produces: `confirmAllocation(rcept, rowIdx)` — 전역 함수

- [ ] **Step 1: 확인 버튼 렌더**

상세 패널에서 라벨이 보정된 신호(`s.label !== 원래 라벨`)에 버튼을 단다:

```javascript
${s0 && (qrules().label_overrides || {})[s0.key] && s0.label !== (DATA.signals.find((x) => x.key === s0.key) || {}).label
  ? `<button class="btn-sm" onclick="confirmAllocation('${r.rcept}')">원문 확인 ▾</button>`
  : ""}
```

- [ ] **Step 2: 확인 함수 구현**

```javascript
/* 좁은 T2 — 스캔 시점에는 호출 0건. 사용자가 이 버튼을 누를 때만
   원문 1건을 받는다. 기존 sessionStorage 캐시를 그대로 타므로
   이미 열람한 공시는 네트워크 호출이 없다. */
async function confirmAllocation(rcept) {
  const slot = document.getElementById("alloc-" + rcept);
  if (!slot) return;
  slot.innerHTML = `<span class="spinner"></span><span class="dim">원문 조회 중…</span>`;
  const j = await fetchDisclosureText(rcept);
  if (!j || j.error) {
    slot.innerHTML = `<span class="dim">원문을 불러오지 못했습니다 — DART 원문 링크를 이용하세요.</span>`;
    return;
  }
  const txt = String(j.text || j.content || "");
  const m = txt.match(/제\s*3\s*자\s*배정|주주배정|일반공모|주주우선공모/);
  slot.innerHTML = m
    ? `<span>원문 확인: <b>${esc(m[0])}</b></span>`
    : `<span class="dim">원문에서 배정 방식을 확인하지 못했습니다.</span>`;
}
```

버튼 옆에 `<span id="alloc-${r.rcept}"></span>` 슬롯을 함께 렌더한다.

- [ ] **Step 3: 브라우저 검증**

셀트리온을 스캔해 `유상증자(배정방식 미상)` 행을 펼치고 `원문 확인 ▾`을 누른다.

- `read_network_requests`로 `/api/doc` 호출이 **버튼을 누른 뒤에만** 1건 발생하는지 확인
- 같은 버튼을 다시 눌렀을 때 네트워크 호출이 **추가로 발생하지 않는지**(캐시 히트) 확인
- 실패 시 라벨·tier가 그대로 유지되는지 확인 (키를 비우고 재시도)

- [ ] **Step 4: 커밋**

```bash
git add docs/tool/index.html
git commit -m "feat(viewer): 배정방식 미상 행의 펼침 시 원문 확인

스캔 시점 추가 호출 0건. 사용자가 그 행을 펼 때만 원문 1건을 받아
배정 방식을 확인한다. 기존 sessionStorage 캐시를 재사용하고,
실패해도 이 블록만 조용히 실패한다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 11: 전체 검증과 프로덕션 확인

**Files:** 없음 (검증 전용)

**Interfaces:**
- Consumes: Task 1~10 전부
- Produces: 없음

- [ ] **Step 1: 전체 테스트**

```bash
python -m pytest tests/ -v
python -c "import dart_risk_mcp.server; print('OK')"
python -c "
from dart_risk_mcp.server import mcp
print(len(mcp._tool_manager.list_tools()), 'tools')
"
```
Expected: 전부 PASS, `OK`, `26 tools`

- [ ] **Step 2: MCP 종단 실행**

`analyze_company_risk("아틀라스링크")`와 `analyze_company_risk("삼성전자")`를 실제로 실행해:

- 아틀라스링크: `capital_backflow` 패턴이 여전히 발화하는가, 절차·사후 보고 절이 15건으로 나오는가
- 삼성전자: 헤드라인이 사라지고 관찰 신호 2건으로 나오는가
- 두 출력 모두 점수·등급 문구가 없는가

- [ ] **Step 3: 프로덕션 배포 확인**

머지·배포 후 실제 URL에서 삼성전자·아틀라스링크를 스캔한다.

**파일 내용이 맞다는 것과 화면이 동작한다는 것은 다르다.** 정적 검사가 전부 초록인데 화면이 죽어 있던 전례가 있다. `read_console_messages`로 에러 0건을 확인하고 스크린샷을 남긴다.

- [ ] **Step 4: CLAUDE.md 갱신**

`CLAUDE.md`의 "제목 수준 vs 내용 확인 감사표"에 한정층을 추가한다 — 어떤 신호가 제목만 보고 어떤 신호가 구조 확인을 받는지가 이 PR로 바뀌었다. `core/qualifiers.py`를 디렉토리 구조 절에도 추가한다.

- [ ] **Step 5: 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: 신호 한정층 반영 — 디렉토리 구조·감사표 갱신

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## 검증 로그

Task 1 실행 결과를 여기에 기록한다.

```
(Task 1 Step 3에서 채운다 — 실행 날짜, flr_nm 존재 여부, 표본 3줄)
```
