# 임원 겸직 흡수 (find_actor_overlap) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `find_actor_overlap`이 인수자(CB/유상증자)뿐 아니라 등기임원 겸직까지 교차 비교해, 조합명이 매번 달라도 '같은 사람'으로 세력을 묶도록 한다.

**Architecture:** DART `exctvSttus.json`(임원현황)을 다년 수집하는 `fetch_executive_roster`를 신규 추가하고, 그 결과를 기존 `find_actor_overlap`의 통합 actor_map에 `[임원]` 소스로 합친다. 배후 판단은 도구를 호출한 호스트 Claude가 하고, 도구는 '겸직 사실'(회사·연도)만 제공한다(점수·등급 없음).

**Tech Stack:** Python 3.11+, `requests`(기존 `_retry` 헬퍼 경유), `unittest`+`pytest`. 외부 라이브러리 추가 없음.

---

## File Structure

- `dart_risk_mcp/core/dart_client.py` — `fetch_executive_roster` 신규 함수 추가
- `dart_risk_mcp/core/__init__.py` — export 추가
- `dart_risk_mcp/server.py` — `find_actor_overlap`에 임원 차원 통합 (import + 수집 루프 + 출력)
- `tests/test_executive_roster.py` — `fetch_executive_roster` 단위 테스트 (신규)
- `tests/test_find_actor_overlap.py` — 임원 통합 테스트 추가 (기존 파일)
- `tests/fixtures/sample_outputs/actor_overlap.txt` — 라이브 골드 갱신
- `CLAUDE.md` — 도구#5·함수표·엔드포인트표·검증매트릭스 갱신

---

## Task 1: `fetch_executive_roster` — 임원현황 다년 수집

**Files:**
- Modify: `dart_risk_mcp/core/dart_client.py` (신규 함수 추가, `DART_AUDIT`/`fetch_audit_opinion_history` 근처)
- Test: `tests/test_executive_roster.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_executive_roster.py`:

```python
import unittest
from unittest.mock import patch, MagicMock


def _resp(payload):
    m = MagicMock()
    m.json.return_value = payload
    return m


class TestFetchExecutiveRoster(unittest.TestCase):
    def test_collects_names_across_years_as_union(self):
        from dart_risk_mcp.core.dart_client import fetch_executive_roster

        # 연도별로 다른 임원 명단 — _retry는 (method, url, params=...) 로 호출됨
        def _fake_retry(method, url, params=None, timeout=None):
            year = params["bsns_year"]
            if year == "2023":
                return _resp({"status": "000", "list": [
                    {"nm": "신승수", "ofcps": "사내이사", "rgist_exctv_at": "사내이사"},
                    {"nm": "조중명", "ofcps": "대표이사", "rgist_exctv_at": "사내이사"},
                ]})
            if year == "2024":
                return _resp({"status": "000", "list": [
                    {"nm": "신승수", "ofcps": "사내이사", "rgist_exctv_at": "사내이사"},
                ]})
            return _resp({"status": "013", "list": []})  # 그 외 연도: 데이터 없음

        with patch("dart_risk_mcp.core.dart_client._retry", side_effect=_fake_retry):
            roster = fetch_executive_roster("00407814", "key", lookback_years=3)

        # 합집합: 신승수는 2023·2024 모두, 조중명은 2023만
        self.assertIn("신승수", roster)
        self.assertEqual(roster["신승수"], {"2023", "2024"})
        self.assertEqual(roster["조중명"], {"2023"})

    def test_empty_inputs_return_empty(self):
        from dart_risk_mcp.core.dart_client import fetch_executive_roster
        self.assertEqual(fetch_executive_roster("", "key"), {})
        self.assertEqual(fetch_executive_roster("c", ""), {})

    def test_skips_blank_and_total_rows(self):
        from dart_risk_mcp.core.dart_client import fetch_executive_roster

        def _fake_retry(method, url, params=None, timeout=None):
            return _resp({"status": "000", "list": [
                {"nm": " "}, {"nm": "계"}, {"nm": "합계"}, {"nm": "양민성"},
            ]})

        with patch("dart_risk_mcp.core.dart_client._retry", side_effect=_fake_retry):
            roster = fetch_executive_roster("c", "key", lookback_years=1)

        self.assertEqual(list(roster.keys()), ["양민성"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_executive_roster.py -q`
Expected: FAIL — `ImportError: cannot import name 'fetch_executive_roster'`

- [ ] **Step 3: 최소 구현**

`dart_risk_mcp/core/dart_client.py`에 추가 (모듈 상단에 `datetime`, `DART_BASE`, `_retry` 이미 존재):

```python
def fetch_executive_roster(
    corp_code: str,
    api_key: str,
    lookback_years: int = 1,
) -> dict[str, set[str]]:
    """임원현황(exctvSttus)을 최근 N개 사업연도 수집해 {임원명: {연도}} 합집합 반환.

    임원현황은 사업보고서(reprt_code=11011) 기재 항목이라 당해년도는 아직 미제출일 수
    있다. 루프 범위를 current_year 까지 포함하되 미제출 연도(status!='000')는 건너뛴다.
    조합명이 매번 달라도 '사람 이름'은 고정점이므로, 다년 합집합으로 겸직을 포착한다.

    Args:
        corp_code: DART 기업 고유번호
        api_key: DART API 키
        lookback_years: 조회할 직전 사업연도 수 (1~5)
    """
    roster: dict[str, set[str]] = {}
    if not corp_code or not api_key:
        return roster
    if not isinstance(lookback_years, int) or not (1 <= lookback_years <= 5):
        lookback_years = 1

    current_year = datetime.now().year
    for year_int in range(current_year - lookback_years, current_year + 1):
        try:
            resp = _retry("GET", f"{DART_BASE}/exctvSttus.json", params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bsns_year": str(year_int),
                "reprt_code": "11011",
            }, timeout=15)
            data = resp.json() if resp is not None else {}
            if data.get("status") != "000":
                continue
            for row in data.get("list", []):
                nm = (row.get("nm") or "").strip()
                if not nm or nm in ("계", "합계"):
                    continue
                roster.setdefault(nm, set()).add(str(year_int))
        except Exception:
            continue
    return roster
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_executive_roster.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add dart_risk_mcp/core/dart_client.py tests/test_executive_roster.py
git commit -m "feat(dart_client): add fetch_executive_roster for multi-year director rosters"
```

---

## Task 2: `core/__init__.py` export

**Files:**
- Modify: `dart_risk_mcp/core/__init__.py`

- [ ] **Step 1: export 추가**

`dart_risk_mcp/core/__init__.py`에서 `dart_client` import 블록과 `__all__`에 `fetch_executive_roster`를 추가한다. (기존 `fetch_audit_opinion_history` 등이 나열된 위치 옆에 동일 형식으로 한 줄씩 추가)

```python
from .dart_client import (
    ...,
    fetch_executive_roster,
    ...,
)
```

그리고 `__all__` 리스트에 `"fetch_executive_roster",` 추가.

- [ ] **Step 2: import 검증**

Run: `python -c "from dart_risk_mcp.core import fetch_executive_roster; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 커밋**

```bash
git add dart_risk_mcp/core/__init__.py
git commit -m "chore(core): export fetch_executive_roster"
```

---

## Task 3: `find_actor_overlap`에 임원 차원 통합

**Files:**
- Modify: `dart_risk_mcp/server.py` (import 라인 + `find_actor_overlap` 수집 루프 + 회사별 명단 출력)
- Test: `tests/test_find_actor_overlap.py` (기존, 테스트 추가)

기존 import: `server.py`는 `from .core import (...)` 또는 `from .core.dart_client import (...)` 로 함수를 들여온다. 구현 시 `find_actor_overlap`이 참조하는 다른 함수(`fetch_company_disclosures`, `extract_cb_investors` 등)와 같은 import 블록에 `fetch_executive_roster`를 추가한다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_find_actor_overlap.py`의 `TestFindActorOverlapMerging` 클래스에 추가:

```python
    def test_director_overlap_detected_across_companies(self):
        # 두 회사에 같은 임원(겸직) — 공시(인수자)는 없고 임원만으로 공통 행위자 탐지
        from dart_risk_mcp.server import find_actor_overlap

        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        def _roster(corp_code, api_key, lookback_years):
            if corp_code == "a":
                return {"신승수": {"2023", "2024"}, "김갑": {"2024"}}
            if corp_code == "b":
                return {"신승수": {"2022"}, "이을": {"2022"}}
            return {}

        with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
             patch("dart_risk_mcp.server.fetch_company_disclosures", return_value=[]), \
             patch("dart_risk_mcp.server.fetch_executive_roster", side_effect=_roster), \
             patch.dict("os.environ", {"DART_API_KEY": "test_key"}):
            result = find_actor_overlap(["a", "b"], lookback_years=3)

        # 신승수는 2개사 공통 행위자로, [임원] 경로로 표기
        self.assertIn("신승수", result)
        self.assertIn("[임원]", result)
        self.assertIn("2개 회사에", result)
        # 단일 회사 임원은 공통 행위자가 아님
        self.assertNotIn("⚠️ **김갑**", result)

    def test_director_and_investor_same_person_merge(self):
        # A사 임원 = B사 인수자가 동일인이면 공통 행위자로 묶인다
        from dart_risk_mcp.server import find_actor_overlap

        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        def _disclosures(corp_code, api_key, lookback_days):
            if corp_code == "b":
                return [{"rcept_no": "B001", "report_nm": "전환사채권발행결정",
                         "rcept_dt": "20240401"}]
            return []

        def _match_signals(report_nm):
            if "전환사채" in report_nm:
                return [{"key": "CB_BW", "label": "CB/BW발행", "score": 3}]
            return []

        def _roster(corp_code, api_key, lookback_years):
            if corp_code == "a":
                return {"양민성": {"2024"}}
            return {}

        with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
             patch("dart_risk_mcp.server.fetch_company_disclosures", side_effect=_disclosures), \
             patch("dart_risk_mcp.server.match_signals", side_effect=_match_signals), \
             patch("dart_risk_mcp.server.fetch_executive_roster", side_effect=_roster), \
             patch("dart_risk_mcp.server.extract_cb_investors",
                   return_value=[{"name": "양민성", "type": "사모", "amount": "1"}]), \
             patch.dict("os.environ", {"DART_API_KEY": "test_key"}):
            result = find_actor_overlap(["a", "b"])

        self.assertIn("양민성", result)
        self.assertIn("2개 회사에", result)
        # 두 경로가 함께 표기됨
        self.assertIn("[CB · 임원]", result)
```

기존 테스트들이 `fetch_executive_roster`를 patch하지 않으면 실제 함수가 호출된다. 따라서 **기존 테스트 4개**(`test_merges_*`, `_capture_lookback`, `_run_empty`, `test_single_company_*`)에도 `fetch_executive_roster`를 빈 dict로 patch하는 데코레이터를 추가해야 한다. `_capture_lookback`·`_run_empty` 헬퍼와 `test_merges_cb_and_rights_investors_with_source_tags`의 `with patch(...)` 블록에 다음 한 줄을 추가:

```python
             patch("dart_risk_mcp.server.fetch_executive_roster", return_value={}), \
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_find_actor_overlap.py -q`
Expected: FAIL — 새 두 테스트가 `[임원]`/`[CB · 임원]` 미발견으로 실패 (그리고 patch 대상 `fetch_executive_roster`가 server에 아직 import 안 되어 AttributeError 가능)

- [ ] **Step 3: 구현 — import + 수집 + 출력**

(3a) `server.py` import 블록에 `fetch_executive_roster` 추가 (find_actor_overlap이 쓰는 함수들과 같은 블록).

(3b) `find_actor_overlap` 회사 처리 루프 내, 인수자(`investors`) 수집 직후·`actor_map` 적재 직전에 임원 수집을 추가한다. 기존 코드(server.py 약 1106행, `for source, inv, rn in investors:` 루프) **앞**에 삽입:

```python
        # 등기임원 겸직 수집 (조합명 비고정성 우회 — 사람 이름은 고정점)
        roster = fetch_executive_roster(corp_code, api_key, lookback_years) or {}
        for exec_name, years in roster.items():
            name = (exec_name or "").strip()
            if not name:
                continue
            year_label = ", ".join(sorted(years))
            entry = (corp_name, "임원", year_label, "")
            actor_map.setdefault(name, []).append(entry)
            per_company_solo.setdefault(corp_name, []).append((name, "임원", year_label, ""))
```

이로써 임원은 기존 `(corp_name, source, amount, rcept_no)` 튜플 형식과 호환되며(amount 자리에 연도라벨, rcept_no는 빈 문자열), 공통 행위자 판정(`len({e[0] for e in entries}) >= 2`)·소스 태그 집계(`source_set`)가 그대로 동작한다.

(3c) 회사별 명단 출력에 연도 병기. 기존 코드(server.py 약 1188행):

```python
    lines.append("━━ 회사별 전체 인수자 명단 (중복 제거) ━━")
    for corp_name, entries in per_company_solo.items():
        unique = sorted({(n, s) for n, s, _, _ in entries})
        if not unique:
            continue
        lines.append(f"  • {corp_name} — 총 {len(unique)}명:")
        for name, source in unique[:10]:
            lines.append(f"      [{source}] {name}")
```

를 다음으로 교체 (임원은 연도라벨을 괄호로 병기):

```python
    lines.append("━━ 회사별 전체 인수자·임원 명단 (중복 제거) ━━")
    for corp_name, entries in per_company_solo.items():
        # (name, source) 단위로 묶고, 임원은 연도라벨을 합집합으로 모은다
        seen: dict[tuple, set] = {}
        for n, s, amt, _ in entries:
            seen.setdefault((n, s), set())
            if s == "임원" and amt:
                seen[(n, s)].update(amt.split(", "))
        if not seen:
            continue
        lines.append(f"  • {corp_name} — 총 {len(seen)}명:")
        for (name, source), years in sorted(seen.items())[:10]:
            if source == "임원" and years:
                lines.append(f"      [임원] {name} ({', '.join(sorted(years))})")
            else:
                lines.append(f"      [{source}] {name}")
```

(3d) 안내 문구 1줄 보강 — 맨 끝 `⚠️` 안내 문구에 임원현황도 포함됨을 명시. 기존 `window_label` 문구 뒤에 임원 차원을 덧붙이는 방식으로, server.py의 마지막 `lines.append("⚠️ ...")` 블록을 다음으로 교체:

```python
    lines.append(
        f"⚠️ 이 결과는 DART 공개 API 범위 내 분석입니다. {window_label} 이내 "
        "CB/BW/EB/유상증자 공시 인수자와 임원현황(등기임원) 겸직을 함께 대조하며, "
        "회사당 CB 최대 3건 + 유상증자 최대 3건으로 제한됩니다. 따라서 '공통 "
        "행위자 없음'이 '세력이 없다'는 결론으로 이어지지는 않습니다."
    )
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_find_actor_overlap.py -q`
Expected: PASS (9 passed — 기존 7 + 신규 2)

- [ ] **Step 5: 전체 스위트 + hygiene 회귀 확인**

Run: `python -m pytest tests/ -q`
Expected: 기존 통과 테스트 전부 PASS. (사전 존재 실패 `test_audit_opinion_history.py::TestCheckDisclosureAnomalyAuditBonus` 2건은 env 미설정 결함으로 무관 — 변동 없어야 함)

- [ ] **Step 6: 커밋**

```bash
git add dart_risk_mcp/server.py tests/test_find_actor_overlap.py
git commit -m "feat(find_actor_overlap): merge director-overlap dimension via fetch_executive_roster"
```

---

## Task 4: 라이브 검증 + 골드 갱신 + ⚠ 제거 + 문서

**Files:**
- Modify: `tests/fixtures/sample_outputs/actor_overlap.txt`
- Modify: `CLAUDE.md`
- Temp cleanup: `tmp/_director_probe.py`, `tmp/_roster_fields.py` 삭제

- [ ] **Step 1: 라이브 재검증 (신승수군, 3년)**

API 키는 메인 워크트리 `tmp/_apikey.txt`. 다음을 실행해 신승수 4개사 겸직이 공통 행위자로 잡히는지 확인:

```bash
cd <worktree>
PYTHONIOENCODING=utf-8 DART_API_KEY="$(cat /c/Users/anboy/vibecoding/dart-risk-mcp/tmp/_apikey.txt | tr -d '[:space:]')" \
python -c "from dart_risk_mcp.server import find_actor_overlap; print(find_actor_overlap(['이엠앤아이','제이케이시냅스','CG인바이츠','헬스커넥트','티쓰리'], lookback_years=3))"
```

Expected: 출력의 "동시에 등장한 인수자" 섹션에 `⚠️ **신승수** — 4개 회사에 [임원] 경로로 등장: CG인바이츠, 제이케이시냅스, 티쓰리, 헬스커넥트` (윤원도·정인철도 2개사로 표기될 수 있음).

- [ ] **Step 2: 골드 파일 갱신**

위 Step 1 출력을 그대로 `tests/fixtures/sample_outputs/actor_overlap.txt`에 저장한다(점수·등급·내부코드·이모지 회귀가 없는지 육안 확인). 회사명 입력은 골드 헤더 규칙상 첫 줄이 `🔍 **여러 회사를 동시에 드나든 ...` 형식이어야 한다(기존 hygiene 정규식 충족).

- [ ] **Step 3: hygiene 검증**

Run: `python -m pytest tests/test_golden_output_hygiene.py -v`
Expected: 9/9 PASS

- [ ] **Step 4: CLAUDE.md 갱신**

다음 4곳을 편집:

1. **도구 #5 `find_actor_overlap`** 설명에 임원 겸직·`lookback_years` 반영:
   - 시그니처를 `find_actor_overlap(company_names, lookback_years=1)`로
   - "CB/BW 인수자 + 유상증자 인수자 + **등기임원 겸직**(exctvSttus 다년)을 통합 비교" 취지로 한 줄 추가
   - "조합명이 매번 달라도 임원 이름은 고정점 — 다년 합집합으로 겸직 포착" 설명 추가

2. **핵심 내부 함수 표**에 행 추가:
   `| fetch_executive_roster(corp_code, api_key, lookback_years) | 임원현황(exctvSttus) 다년 수집 → {임원명: {연도}} 합집합. 조합명 비고정성 우회용 고정점 |`

3. **DART API 엔드포인트 표**에 행 추가:
   `| GET /api/exctvSttus.json | 임원 현황 (corp_code, bsns_year, reprt_code) — 겸직 탐지 |`

4. **라이브 검증 매트릭스**에서 `find_actor_overlap` 행의 ⚠ → ✅ 로 변경하고 비고를 "신승수군 임원 겸직 4개사 라이브 매칭, 골드 `actor_overlap.txt`"로 갱신. 매트릭스 하단 ⚠ 목록 설명에서 해당 항목 제거.

- [ ] **Step 5: 임시 파일 정리**

```bash
git rm -f --ignore-unmatch tmp/_director_probe.py tmp/_roster_fields.py
rm -f tmp/_director_probe.py tmp/_roster_fields.py
```

(tmp/가 .gitignore면 `rm`만으로 충분)

- [ ] **Step 6: 커밋**

```bash
git add tests/fixtures/sample_outputs/actor_overlap.txt CLAUDE.md
git commit -m "docs+test: live director-overlap gold (신승수군), remove find_actor_overlap ⚠"
```

---

## 검증 체크리스트 (완료 전)

- [ ] `fetch_executive_roster` 단위 테스트 3개 PASS
- [ ] `find_actor_overlap` 테스트 9개 PASS (기존 7 + 신규 2)
- [ ] 전체 스위트: 신규 회귀 0 (사전 존재 env 실패 2건 외)
- [ ] hygiene 9/9 PASS (점수·등급·이모지 회귀 없음)
- [ ] 라이브: 신승수 4개사 겸직이 공통 행위자로 표기됨
- [ ] CLAUDE.md 4곳 갱신, ⚠ 제거
- [ ] 임시 probe 스크립트 삭제
```
