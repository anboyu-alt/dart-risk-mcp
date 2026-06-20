# 조회 기간 다년 확장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `lookback_days`로 1년에 강제 클램프되던 4개 도구를 `lookback_years`(1~5)로 통일하고, 코어 페이지네이션 상한을 다년 조회에 맞춰 상향하며, 다년 조회 시 예상 출력 규모 푸터를 추가한다.

**Architecture:** 도구 레이어(server.py)에서 `lookback_years`를 받아 `lookback_days = years*365`로 환산해 기존 코어 함수에 전달(코어 시그니처 유지). 코어 `fetch_company_disclosures`에 `max_pages` 파라미터를 추가하고 다년 호출부가 `years*10`을 넘긴다. `years==1` 출력은 기존 골드와 동일하게 유지(라벨 "365일")하고, `years>1`에만 푸터를 붙인다.

**Tech Stack:** Python 3.11+, mcp, requests (외부 라이브러리 추가 금지). 테스트는 pytest + monkeypatch(네트워크 없음).

---

## File Structure

- `dart_risk_mcp/core/dart_client.py` — `fetch_company_disclosures`에 `max_pages` 파라미터 추가 (Task 1)
- `dart_risk_mcp/server.py` — 출력 크기 추정 헬퍼 2종 추가(Task 2) + 4개 도구 시그니처/라벨/푸터 변환 (Task 3~6)
- `tests/test_multi_year_lookback.py` — 신규 단위 테스트 (Task 1·2·5)
- `scripts/regen_goldens.py` — 4개 도구 호출 인자 갱신 (Task 7)
- `tests/fixtures/sample_outputs/*` — 골든 재생성 (Task 7)
- `CLAUDE.md`, `README.md`, `tests/fixtures/sample_outputs/README.md` — 문서 갱신 (Task 8)

---

### Task 1: 코어 페이지네이션 상한 파라미터화

**Files:**
- Modify: `dart_risk_mcp/core/dart_client.py:141-183`
- Test: `tests/test_multi_year_lookback.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_multi_year_lookback.py` 생성:

```python
import dart_risk_mcp.core.dart_client as dc


def test_fetch_company_disclosures_respects_max_pages(monkeypatch):
    """max_pages 만큼만 페이지를 돌고 멈춘다 (total이 더 커도)."""
    calls = {"n": 0}

    class _Resp:
        def json(self):
            # 매 페이지 100건, total은 항상 큼(절대 자연 종료 안 함)
            return {
                "status": "000",
                "total_count": 100000,
                "list": [{"rcept_no": f"{calls['n']:04d}"} for _ in range(100)],
            }

    def _fake_retry(method, url, **kwargs):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(dc, "_retry", _fake_retry)
    # 기본 max_pages=10
    rows = dc.fetch_company_disclosures("00126380", "KEY", lookback_days=365)
    assert calls["n"] == 10
    assert len(rows) == 1000
    # max_pages=30 명시
    calls["n"] = 0
    rows = dc.fetch_company_disclosures("00126380", "KEY", lookback_days=1825, max_pages=30)
    assert calls["n"] == 30
    assert len(rows) == 3000
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_multi_year_lookback.py::test_fetch_company_disclosures_respects_max_pages -v`
Expected: FAIL — `max_pages`는 아직 파라미터가 아니므로 `TypeError: unexpected keyword argument 'max_pages'`.

- [ ] **Step 3: 최소 구현**

`dart_client.py`의 함수 시그니처를 수정:

```python
def fetch_company_disclosures(
    corp_code: str,
    api_key: str,
    lookback_days: int = 90,
    max_pages: int = 10,
) -> list[dict]:
```

`while page_no <= 10:` 를 다음으로 교체:

```python
    while page_no <= max_pages:
```

루프 내 종료 가드(현재 177-179)를 다음으로 교체:

```python
        if page_no >= max_pages and len(results) < total:
            log.warning("공시목록 %d건 초과 기업 (corp_code=%s, total=%d) — 일부 누락", max_pages * 100, corp_code, total)
            break
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_multi_year_lookback.py::test_fetch_company_disclosures_respects_max_pages -v`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add dart_risk_mcp/core/dart_client.py tests/test_multi_year_lookback.py
git commit -m "feat(core): fetch_company_disclosures에 max_pages 파라미터 추가"
```

---

### Task 2: 출력 크기 추정 헬퍼

**Files:**
- Modify: `dart_risk_mcp/server.py:72` (직후에 헬퍼 추가)
- Test: `tests/test_multi_year_lookback.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_multi_year_lookback.py`에 추가:

```python
from dart_risk_mcp import server as srv


def test_estimate_output_size():
    chars, tokens = srv._estimate_output_size("가" * 250)
    assert chars == 250
    assert tokens == 100  # round(250 / 2.5)


def test_append_size_footer_only_for_multiyear():
    body = "본문" * 100
    # 1년 이하: 변화 없음
    assert srv._append_size_footer(body, 1) == body
    # 다년: 푸터 1줄 추가
    out = srv._append_size_footer(body, 3)
    assert out.startswith(body)
    assert "예상 출력 규모" in out
    assert "토큰" in out
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_multi_year_lookback.py -k estimate -v` 및 `-k footer`
Expected: FAIL — `AttributeError: module ... has no attribute '_estimate_output_size'`.

- [ ] **Step 3: 최소 구현**

`server.py`의 `_DART_API_KEY: str = ...`(72행) 바로 다음에 추가:

```python


def _estimate_output_size(text: str) -> tuple[int, int]:
    """렌더된 출력의 문자 수와 대략적 토큰 수를 추정한다.

    정밀 토크나이저가 아니라 문자 수 기반 휴리스틱이다(외부 의존성 없음).
    한국어·마크다운 혼합 기준 대략 글자 2.5개당 1토큰으로 환산한다.
    """
    chars = len(text)
    tokens = round(chars / 2.5)
    return chars, tokens


def _append_size_footer(text: str, lookback_years: int) -> str:
    """다년 조회(lookback_years > 1)일 때만 예상 출력 규모 푸터를 덧붙인다."""
    if lookback_years <= 1:
        return text
    chars, tokens = _estimate_output_size(text)
    return text + f"\n\n📊 예상 출력 규모: 약 {chars:,}자 / ~{tokens:,}토큰 (대략적 추정)"
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_multi_year_lookback.py -k "estimate or footer" -v`
Expected: PASS (2개)

- [ ] **Step 5: 커밋**

```bash
git add dart_risk_mcp/server.py tests/test_multi_year_lookback.py
git commit -m "feat(server): 출력 크기 추정 헬퍼(_estimate_output_size/_append_size_footer) 추가"
```

---

### Task 3: analyze_company_risk 변환

**Files:**
- Modify: `dart_risk_mcp/server.py:187-208, 258, 352, 405, 429, 592`

- [ ] **Step 1: 시그니처 + docstring + 클램프 교체**

`server.py:187-197` 영역. 다음 old → new.

old:
```python
def analyze_company_risk(company_name: str, lookback_days: int = 90) -> str:
    """기업명 또는 종목코드로 최근 공시 기반 투자 위험도를 분석한다.

    Args:
        company_name: 기업명 (예: "에코프로") 또는 종목코드 6자리 (예: "086520")
        lookback_days: 조회 기간 (기본 90일, 최대 365일)
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    lookback_days = min(max(lookback_days, 1), 365)
```
new:
```python
def analyze_company_risk(company_name: str, lookback_years: int = 1) -> str:
    """기업명 또는 종목코드로 최근 공시 기반 투자 위험도를 분석한다.

    Args:
        company_name: 기업명 (예: "에코프로") 또는 종목코드 6자리 (예: "086520")
        lookback_years: 조회 기간(년). 기본 1년, 1~5년 범위.
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    lookback_years = min(max(lookback_years, 1), 5)
    lookback_days = lookback_years * 365
    window_phrase = f"{lookback_days}일" if lookback_years == 1 else f"{lookback_years}년"
```

- [ ] **Step 2: 공시 조회에 max_pages 전달**

old (`server.py:208`):
```python
    disclosures = fetch_company_disclosures(corp_code, _DART_API_KEY, lookback_days)
```
new:
```python
    disclosures = fetch_company_disclosures(corp_code, _DART_API_KEY, lookback_days, max_pages=lookback_years * 10)
```

- [ ] **Step 3: 부실 이벤트 연수 계산 단순화**

old (`server.py:256-259`):
```python
    distress_events = fetch_distress_events(
        corp_code, _DART_API_KEY,
        max(1, (lookback_days // 365) + 1),
    )
```
new:
```python
    distress_events = fetch_distress_events(
        corp_code, _DART_API_KEY,
        lookback_years + 1,
    )
```
(주: 기존 `lookback_days=365`일 때 값이 2였고, `lookback_years=1`이면 `1+1=2`로 동일 — 골드 호환.)

- [ ] **Step 4: 사용자 라벨 3곳을 window_phrase로 교체**

`server.py:352` old → new:
```python
            f"최근 {lookback_days}일간 탐지된 의심 공시가 없습니다.\n"
```
```python
            f"최근 {window_phrase}간 탐지된 의심 공시가 없습니다.\n"
```

`server.py:405` old → new:
```python
        f"지난 {lookback_days}일 동안 **{corp_name}**의 공시 "
```
```python
        f"지난 {window_phrase} 동안 **{corp_name}**의 공시 "
```

`server.py:429` old → new:
```python
        f"조회 기간: 최근 {lookback_days}일 | 전체 공시 {len(disclosures)}건 검토",
```
```python
        f"조회 기간: 최근 {window_phrase} | 전체 공시 {len(disclosures)}건 검토",
```

- [ ] **Step 5: 최종 반환에 푸터 적용**

`server.py:589-592` old → new:
```python
    if catalog:
        lines += ["", catalog]

    return "\n".join(lines)
```
```python
    if catalog:
        lines += ["", catalog]

    return _append_size_footer("\n".join(lines), lookback_years)
```

- [ ] **Step 6: import 스모크 + years 파싱 확인**

Run:
```bash
python -c "import dart_risk_mcp.server as s; print(s.analyze_company_risk.__doc__.splitlines()[0])"
```
Expected: docstring 첫 줄 정상 출력, import 에러 없음.

- [ ] **Step 7: 커밋**

```bash
git add dart_risk_mcp/server.py
git commit -m "feat(analyze_company_risk): lookback_years(1~5)로 통일 + 다년 푸터"
```

---

### Task 4: build_event_timeline 변환

**Files:**
- Modify: `dart_risk_mcp/server.py:826-839, 852, 877, 909, 1038`

- [ ] **Step 1: 시그니처 + docstring + 클램프 교체**

old (`server.py:826-839`):
```python
def build_event_timeline(company_name: str, lookback_days: int = 365) -> str:
    """기업의 공시 이벤트를 시간순으로 정렬해 조작 흐름의 서사를 구성한다.

    각 이벤트를 진입기(자금 조달/경영권 진입), 심화기(지배구조 변화),
    탈출기(의심/수사/부실) 단계로 분류하고, 알려진 위기 패턴과 매칭한다.

    Args:
        company_name: 기업명 (예: "에코프로") 또는 종목코드 6자리 (예: "086520")
        lookback_days: 조회 기간 (기본 365일, 최대 365일)
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    lookback_days = min(max(lookback_days, 1), 365)
```
new:
```python
def build_event_timeline(company_name: str, lookback_years: int = 1) -> str:
    """기업의 공시 이벤트를 시간순으로 정렬해 조작 흐름의 서사를 구성한다.

    각 이벤트를 진입기(자금 조달/경영권 진입), 심화기(지배구조 변화),
    탈출기(의심/수사/부실) 단계로 분류하고, 알려진 위기 패턴과 매칭한다.

    Args:
        company_name: 기업명 (예: "에코프로") 또는 종목코드 6자리 (예: "086520")
        lookback_years: 조회 기간(년). 기본 1년, 1~5년 범위.
    """
    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    lookback_years = min(max(lookback_years, 1), 5)
    lookback_days = lookback_years * 365
    window_phrase = f"{lookback_days}일" if lookback_years == 1 else f"{lookback_years}년"
```

- [ ] **Step 2: 공시 조회에 max_pages 전달**

old (`server.py:848`):
```python
    disclosures = fetch_company_disclosures(corp_code, _DART_API_KEY, lookback_days)
```
new:
```python
    disclosures = fetch_company_disclosures(corp_code, _DART_API_KEY, lookback_days, max_pages=lookback_years * 10)
```

- [ ] **Step 3: 라벨 3곳 교체**

`server.py:852` `f"최근 {lookback_days}일간 공시가 없습니다."` → `f"최근 {window_phrase}간 공시가 없습니다."`

`server.py:877` `f"최근 {lookback_days}일간 위험 신호 이벤트가 없습니다.\n"` → `f"최근 {window_phrase}간 위험 신호 이벤트가 없습니다.\n"`

`server.py:909` `f"- 최근 {lookback_days}일 동안 위험 신호로 분류된 공시 "` → `f"- 최근 {window_phrase} 동안 위험 신호로 분류된 공시 "`

- [ ] **Step 4: 최종 반환에 푸터 적용**

old (`server.py:1037-1038`):
```python
    lines.append("⚠️ 이 타임라인은 공시 제목 기반 자동 분류이며, 실제 상황과 다를 수 있습니다.")
    return "\n".join(lines)
```
new:
```python
    lines.append("⚠️ 이 타임라인은 공시 제목 기반 자동 분류이며, 실제 상황과 다를 수 있습니다.")
    return _append_size_footer("\n".join(lines), lookback_years)
```

- [ ] **Step 5: import 스모크**

Run: `python -c "import dart_risk_mcp.server"`
Expected: 에러 없음.

- [ ] **Step 6: 커밋**

```bash
git add dart_risk_mcp/server.py
git commit -m "feat(build_event_timeline): lookback_years(1~5)로 통일 + 다년 푸터"
```

---

### Task 5: list_disclosures_by_stock 변환 (+ 인자 전달 캡처 테스트)

**Files:**
- Modify: `dart_risk_mcp/server.py:1410-1437, 1441, 1446, 1460`
- Test: `tests/test_multi_year_lookback.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_multi_year_lookback.py`에 추가:

```python
def test_list_disclosures_passes_years_to_core(monkeypatch):
    """lookback_years -> lookback_days(years*365), max_pages(years*10) 전달 확인."""
    captured = {}

    monkeypatch.setattr(srv, "_DART_API_KEY", "KEY")
    monkeypatch.setattr(srv, "resolve_corp", lambda q, k: ("테스트사", {"corp_code": "00000000", "stock_code": "012345"}))

    def _fake_fetch(corp_code, api_key, lookback_days, max_pages=10):
        captured["lookback_days"] = lookback_days
        captured["max_pages"] = max_pages
        return [{"rcept_no": "20240101000001", "report_nm": "사업보고서", "rcept_dt": "20240101"}]

    monkeypatch.setattr(srv, "fetch_company_disclosures", _fake_fetch)

    out = srv.list_disclosures_by_stock("012345", lookback_years=3)
    assert captured["lookback_days"] == 3 * 365
    assert captured["max_pages"] == 3 * 10
    assert "최근 3년" in out  # 다년 라벨
    assert "예상 출력 규모" in out  # years>1 푸터
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `python -m pytest tests/test_multi_year_lookback.py::test_list_disclosures_passes_years_to_core -v`
Expected: FAIL — 현재 시그니처는 `lookback_days`이고 `lookback_years` 키워드를 받지 못함(`TypeError`).

- [ ] **Step 3: 시그니처 + docstring + 클램프 교체**

old (`server.py:1410-1428`):
```python
def list_disclosures_by_stock(stock_code: str, lookback_days: int = 90) -> str:
    """종목코드로 최근 공시의 접수번호(rcept_no) 목록을 조회한다.

    반환된 접수번호는 get_disclosure_document, view_disclosure,
    check_disclosure_risk 등에 바로 사용할 수 있다.

    Args:
        stock_code: 종목코드 6자리 (예: "086520")
        lookback_days: 조회 기간 (기본 90일, 최대 365일)
    """
    import re as _re

    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    if not _re.match(r"^\d{6}$", stock_code):
        return "❌ 종목코드는 6자리 숫자여야 합니다. 예: '086520'"

    lookback_days = min(max(lookback_days, 1), 365)
```
new:
```python
def list_disclosures_by_stock(stock_code: str, lookback_years: int = 1) -> str:
    """종목코드로 최근 공시의 접수번호(rcept_no) 목록을 조회한다.

    반환된 접수번호는 get_disclosure_document, view_disclosure,
    check_disclosure_risk 등에 바로 사용할 수 있다.

    Args:
        stock_code: 종목코드 6자리 (예: "086520")
        lookback_years: 조회 기간(년). 기본 1년, 1~5년 범위.
    """
    import re as _re

    if not _DART_API_KEY:
        return "❌ DART_API_KEY 환경변수가 설정되지 않았습니다."

    if not _re.match(r"^\d{6}$", stock_code):
        return "❌ 종목코드는 6자리 숫자여야 합니다. 예: '086520'"

    lookback_years = min(max(lookback_years, 1), 5)
    lookback_days = lookback_years * 365
    window_phrase = f"{lookback_days}일" if lookback_years == 1 else f"{lookback_years}년"
```

- [ ] **Step 4: 공시 조회 + 라벨 2곳 교체**

old (`server.py:1437`):
```python
    disclosures = fetch_company_disclosures(corp_code, _DART_API_KEY, lookback_days)
```
new:
```python
    disclosures = fetch_company_disclosures(corp_code, _DART_API_KEY, lookback_days, max_pages=lookback_years * 10)
```

`server.py:1441` `f"최근 {lookback_days}일간 공시가 없습니다."` → `f"최근 {window_phrase}간 공시가 없습니다."`

`server.py:1446` `f"조회 기간: 최근 {lookback_days}일 | 총 {len(disclosures)}건",` → `f"조회 기간: 최근 {window_phrase} | 총 {len(disclosures)}건",`

- [ ] **Step 5: 최종 반환에 푸터 적용**

old (`server.py:1457-1460`):
```python
        "💡 접수번호로 원문을 읽으려면: get_disclosure_document(rcept_no=\"...\")",
    ]

    return "\n".join(lines)
```
new:
```python
        "💡 접수번호로 원문을 읽으려면: get_disclosure_document(rcept_no=\"...\")",
    ]

    return _append_size_footer("\n".join(lines), lookback_years)
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `python -m pytest tests/test_multi_year_lookback.py::test_list_disclosures_passes_years_to_core -v`
Expected: PASS

- [ ] **Step 7: 커밋**

```bash
git add dart_risk_mcp/server.py tests/test_multi_year_lookback.py
git commit -m "feat(list_disclosures_by_stock): lookback_years(1~5)로 통일 + 다년 푸터"
```

---

### Task 6: check_disclosure_anomaly 변환

**Files:**
- Modify: `dart_risk_mcp/server.py:2398-2419, 2422, 2467, 2474, 2545`

- [ ] **Step 1: 시그니처 + docstring + 클램프/환산 추가**

old (`server.py:2398-2419`)에서 시그니처·docstring 교체:
```python
def check_disclosure_anomaly(company_name: str, lookback_days: int = 365) -> str:
```
→
```python
def check_disclosure_anomaly(company_name: str, lookback_years: int = 1) -> str:
```

docstring의
```python
        lookback_days: 조회 기간 (기본값 365일)
```
→
```python
        lookback_years: 조회 기간(년). 기본 1년, 1~5년 범위.
```

`corp_code = meta["corp_code"]` 다음 줄(공시 조회 직전)에 환산 블록 삽입. old:
```python
    corp_code = meta["corp_code"]

    disclosures = fetch_company_disclosures(corp_code, _DART_API_KEY, lookback_days)
```
new:
```python
    corp_code = meta["corp_code"]

    lookback_years = min(max(lookback_years, 1), 5)
    lookback_days = lookback_years * 365
    window_phrase = f"{lookback_days}일" if lookback_years == 1 else f"{lookback_years}년"

    disclosures = fetch_company_disclosures(corp_code, _DART_API_KEY, lookback_days, max_pages=lookback_years * 10)
```

- [ ] **Step 2: 라벨 3곳 교체**

`server.py:2422` `f"[{corp_name}] 최근 {lookback_days}일 공시 없음 — 스코어 산출 불가."` → `f"[{corp_name}] 최근 {window_phrase} 공시 없음 — 스코어 산출 불가."`

`server.py:2467` `f"📋 최근 {lookback_days}일 동안 **{corp_name}**의 공시 "` → `f"📋 최근 {window_phrase} 동안 **{corp_name}**의 공시 "`

`server.py:2474` `f"조회기간: 최근 {lookback_days}일 / 총 공시 {total}건 (정정공시 {amendment_count}건)",` → `f"조회기간: 최근 {window_phrase} / 총 공시 {total}건 (정정공시 {amendment_count}건)",`

- [ ] **Step 3: 최종 반환에 푸터 적용**

old (`server.py:2542-2545`):
```python
        "   법적 판단이나 투자 결정의 근거로 사용할 수 없습니다.",
        "💡 세부 분석: analyze_company_risk(company_name=...)",
    ]
    return "\n".join(lines)
```
new:
```python
        "   법적 판단이나 투자 결정의 근거로 사용할 수 없습니다.",
        "💡 세부 분석: analyze_company_risk(company_name=...)",
    ]
    return _append_size_footer("\n".join(lines), lookback_years)
```

- [ ] **Step 4: import 스모크**

Run: `python -c "import dart_risk_mcp.server"`
Expected: 에러 없음.

- [ ] **Step 5: 커밋**

```bash
git add dart_risk_mcp/server.py
git commit -m "feat(check_disclosure_anomaly): lookback_years(1~5)로 통일 + 다년 푸터"
```

---

### Task 7: 골든 재생성 스크립트 갱신 + 골든 재생성 + hygiene 검증

**Files:**
- Modify: `scripts/regen_goldens.py:91, 92, 100, 107`
- Regenerate: `tests/fixtures/sample_outputs/*`

- [ ] **Step 1: 호출 인자 갱신 (years 시맨틱 반영)**

`scripts/regen_goldens.py`에서 4개 항목의 두 번째 위치 인자를 연수로 교체.

old:
```python
    ("analyze",       lambda c: analyze_company_risk(c["name"], 365)),
    ("timeline",      lambda c: build_event_timeline(c["name"], 365)),
```
new:
```python
    ("analyze",       lambda c: analyze_company_risk(c["name"], 1)),
    ("timeline",      lambda c: build_event_timeline(c["name"], 1)),
```

old (`:100`):
```python
    ("anomaly",       lambda c: check_disclosure_anomaly(c["name"], 365)),
```
new:
```python
    ("anomaly",       lambda c: check_disclosure_anomaly(c["name"], 1)),
```

old (`:107`):
```python
STOCK_TOOL = ("list", lambda c: list_disclosures_by_stock(c["stock"], 90))
```
new:
```python
STOCK_TOOL = ("list", lambda c: list_disclosures_by_stock(c["stock"], 1))
```

(주: analyze/timeline/anomaly는 years=1 → 365일 → 기존 골드와 라벨·윈도우 동일. `list`만 90일→365일로 윈도우가 넓어져 골드가 정당하게 바뀐다.)

- [ ] **Step 2: 전체 단위 테스트 먼저 통과 확인 (골든 외)**

Run: `python -m pytest tests/test_multi_year_lookback.py -v`
Expected: 4개 PASS (Task 1·2·5 테스트).

- [ ] **Step 3: 골든 재생성**

API 키 필요(`tmp/_apikey.txt` 또는 `DART_API_KEY`). 먼저 dry-run으로 매트릭스 확인 후, CLAUDE.md에 문서화된 `--tools <필터>` 단일값 형식(예: `--tools capital`)으로 도구별 4회 재생성:

```bash
python scripts/regen_goldens.py --dry-run
python scripts/regen_goldens.py --tools analyze
python scripts/regen_goldens.py --tools timeline
python scripts/regen_goldens.py --tools anomaly
python scripts/regen_goldens.py --tools list
```

Expected: `tests/fixtures/sample_outputs/*_analyze.txt`·`*_timeline.txt`·`*_anomaly.txt`는 변화 없음(또는 무시 가능한 차이), `셀트리온_list.txt`는 윈도우 확대로 갱신.

- [ ] **Step 4: hygiene 회귀 검증**

Run: `python -m pytest tests/test_golden_output_hygiene.py -v`
Expected: 9/9 PASS (점수·등급·이모지 회귀 없음).

- [ ] **Step 5: 커밋**

```bash
git add scripts/regen_goldens.py tests/fixtures/sample_outputs/
git commit -m "test: 골든 재생성 스크립트를 lookback_years 시맨틱으로 갱신 + 골든 재생성"
```

---

### Task 8: 문서 갱신

**Files:**
- Modify: `CLAUDE.md` (도구 카탈로그 #1·#4·#6·#15)
- Modify: `README.md`
- Modify: `tests/fixtures/sample_outputs/README.md`

- [ ] **Step 1: CLAUDE.md 도구 카탈로그 갱신**

다음 4개 도구 헤더의 시그니처를 갱신(grep으로 위치 확인 후):
- `analyze_company_risk(company_name, lookback_days=90)` → `analyze_company_risk(company_name, lookback_years=1)`
- `build_event_timeline(company_name, lookback_days=365)` → `build_event_timeline(company_name, lookback_years=1)`
- `list_disclosures_by_stock(stock_code, lookback_days=90)` → `list_disclosures_by_stock(stock_code, lookback_years=1)`
- `check_disclosure_anomaly(company_name, lookback_days=365)` → `check_disclosure_anomaly(company_name, lookback_years=1)`

각 본문 설명에 "1~5년 범위, 기본 1년. 다년 조회 시 예상 출력 규모 푸터 표기" 한 줄을 추가한다.

Run(위치 확인): `grep -nE "lookback_days=(90|365)" CLAUDE.md`

- [ ] **Step 2: README.md 갱신**

Run: `grep -nE "lookback_days|analyze_company_risk|build_event_timeline|list_disclosures_by_stock|check_disclosure_anomaly" README.md`
검색 결과에서 위 4개 도구의 `lookback_days` 표기를 `lookback_years`(1~5, 기본 1)로 갱신. 다른 도구(`track_*`, `find_actor_overlap` 등)의 `lookback_years`는 건드리지 않는다.

- [ ] **Step 3: sample_outputs/README.md 갱신**

old:
```
| `셀트리온_analyze.txt` · `제이스코홀딩스_analyze.txt` · `두산에너빌리티_analyze.txt` | `analyze_company_risk` | lookback_days=180 |
| `셀트리온_timeline.txt` · `제이스코홀딩스_timeline.txt` · `두산에너빌리티_timeline.txt` | `build_event_timeline` | lookback_days=365 |
```
new(실제 재생성 인자에 맞춤 — analyze/timeline 모두 years=1):
```
| `셀트리온_analyze.txt` · `제이스코홀딩스_analyze.txt` · `두산에너빌리티_analyze.txt` | `analyze_company_risk` | lookback_years=1 |
| `셀트리온_timeline.txt` · `제이스코홀딩스_timeline.txt` · `두산에너빌리티_timeline.txt` | `build_event_timeline` | lookback_years=1 |
```
old:
```
| `셀트리온_list.txt` | `list_disclosures_by_stock` | stock_code=068270, lookback_days=90 |
```
new:
```
| `셀트리온_list.txt` | `list_disclosures_by_stock` | stock_code=068270, lookback_years=1 |
```

- [ ] **Step 4: 최종 import 스모크 + 도구 목록 확인**

Run:
```bash
python -c "import dart_risk_mcp.server; print('OK')"
python -c "from dart_risk_mcp.server import mcp; print(len(mcp._tool_manager.list_tools()), 'tools')"
```
Expected: `OK` + 도구 개수 변동 없음(25개).

- [ ] **Step 5: 커밋**

```bash
git add CLAUDE.md README.md tests/fixtures/sample_outputs/README.md
git commit -m "docs: 4개 도구 lookback_years 통일 반영"
```

---

## 검증 요약 (전체 완료 후)

```bash
python -m pytest tests/test_multi_year_lookback.py tests/test_golden_output_hygiene.py -v
python -c "import dart_risk_mcp.server; print('import OK')"
```
Expected: 신규 테스트 + hygiene 전부 PASS, import 정상.
