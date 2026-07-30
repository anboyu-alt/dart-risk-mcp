# SE-9: 2차 실사용 피드백 — 각주 문구·열 순서 붕괴·메타-only 표·배당 그룹핑 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) 문법으로 추적한다.

**Goal:** 사용자가 SG(00963976)를 SE-8 반영 배포본으로 재분석하며 남긴 2차 피드백 3건(각주 문구 장황, 지배구조 표 열 순서·구성 붕괴, 배당 표 반복·빈칸)을 원인 수준에서 해결한다.

**Architecture:** 전부 SE 프론트(`docs/tool/se/app.js`·`ui.js`)의 표 조립 계층 수정. 핵심 발견은 **Supabase jsonb가 모든 섹션 레코드의 키 순서를 파괴한다**는 것 — 열 순서를 삽입 순서에 의존하지 않는 명시 규칙으로 바꾸는 것이 이번 계획의 척추다.

**Tech Stack:** 기존과 동일 (순수 JS, 의존성 0, pytest + node 서브프로세스 테스트)

## Global Constraints

- **판정 어휘 금지 (v0.8.5)**: 새 문구는 사실만. "위험"·"의심"·"주의" 등 금지. 기존 어휘 검사 스위트 통과.
- **정보는 보존, 배치만 조정** — 단, 이번 계획은 두 가지 예외를 명시적으로 둔다(각각 해당 태스크에 근거 기재): ① 메타-only 표의 본문 숨김(Task 3), ② 사실이 0개인 패딩 행 생략(Task 3). 둘 다 "무엇을 생략했는지"를 화면에 표기해 정직성을 유지한다.
- **`dart_risk_mcp/` 코어 무변경**, 새 의존성 금지.
- **jsonb 순서로 시뮬레이션한 픽스처로 테스트** — 로컬 dict 순서(=DART 원 순서)로만 테스트하면 배포본에서만 깨지는 회귀를 또 놓친다. 이번 발견의 교훈을 테스트에 직접 박는다.
- 실렌더 검증(`run_render_section`), 소스 grep 검증 금지.
- 커밋마다 `python -m pytest tests/ -q` 무회귀.

---

## 배경: 실측으로 확인한 것 (`.superpowers/sdd/se9-investigation.md` 전문 참조)

### 핵심 발견 — Supabase jsonb가 열 순서를 파괴한다

`se_server/jobs/schema.sql:6`의 `state jsonb not null`. Postgres jsonb는 객체 키를 **길이순→바이트순**으로 재정렬해 저장한다. 스크린샷의 "이상한" 열 순서가 정확히 이 정렬이다:

- 임원·주요주주 자기주식 스크린샷: `비고(rm,2자) → 기초수량(bsis_qy,7) → 결산일(stlm_dt,7) → 접수번호(rcept_no,8) → 취득방법1~3(acqs_mth*,9) → 사업연도(bsns_year,9) → 주식종류(stock_knd,9) → 기말수량(trmend_qy,9) → 보고서구분(reprt_code,10) → 취득수량(change_qy_acqs,14)` — jsonb 정렬과 완전 일치
- 최대주주 변동현황 스크린샷: `결산일(7) → 접수번호(8) → 사업연도(9) → 보고서구분(10)` — 역시 길이순

`tableLayout`(app.js:552~)은 first-seen 삽입 순서로 열을 만들므로, **배포본의 모든 표는 DART 원 순서가 아니라 jsonb 정렬 순서로 렌더된다.** 조사 서브에이전트의 로컬 트레이스(Python dict, 순서 보존)가 "비고는 11번째"라고 계산해 재현 실패한 이유가 이것이다. SE-8 Task 8의 배당 우선순위 4키(`DIVIDENDS_PRIORITY_KEYS`)처럼 **명시 재배열을 거친 키만** 배포본에서 순서가 살아남는다.

### 항목별 사실

- **① 각주 문구**: `footnoteMarkerNote`(app.js:394-399)가 `"주1) (공시 원문의 각주로만 제공됩니다 — 본문은 DART 구조화 데이터에 없습니다)"`를 생성. 호출부 3곳(458 rm, 467 dffrnc_resn 원본 표, 2108 fundChain 카드). 테스트 3곳(test_se_app_js.py:1029, 1062, 1106-1107)이 부분 문자열 `"각주"`를 고정 — 문구 변경 시 함께 갱신.
- **②-1 최대주주 변동현황**: SG 실측 — 전 레코드의 실질 필드 6종(`change_on`·`mxmm_shrholdr_nm`·`posesn_stock_co`·`qota_rt`·`change_cause`·`rm`)이 전부 `"-"`. `dropAllEmptyColumns`가 그 6열을 지우고 메타 4열(결산일·접수번호·사업연도·보고서구분)만 남은 표가 렌더됨. `isMetaOnlyRecords` → `block.note`("해당 기간에 보고된 내역이 없습니다.")가 **표에 더해질 뿐 표를 대체하지 않음** — SE-4f Task 6의 의도적 결정(app.js:896-901 "표는 지우지 않는다"). 사용자 피드백은 이 결정을 뒤집으라는 신호로 읽힘(안내문이 이미 "없다"고 말하는데 22행짜리 식별자 표가 밑에 깔림). **결정 필요 — 아래 Task 3 참조.**
- **②-2 임원·주요주주 자기주식**: (a) 열 순서 붕괴는 jsonb(위). (b) `소계`/`총계` 마커가 `acqs_mth3` 필드에 옴 — `isAggregateRow`(app.js:1183-1186)는 `nm`만 검사하고, `splitAggregateRows`는 `hyslr` 분기에서만 호출되므로 exec_treasury 합계 행은 상세 행 사이에 섞여 렌더. (c) 쌍둥이 빈 행: `(rcept_no, acqs_mth1~3)` 그룹 145레코드 중 72그룹이 "보통주(값 있음) + stock_knd `-`(전 수량 `-`)" 쌍 — DART가 활동 없는 주식종류 조합도 빈 행으로 채워 보내는 원본 형태(파이프라인 버그 아님).
- **③ 배당 표**: `dividends`는 `source` 필드가 없어 `sourceGroupedBlocks`에 못 들어가고 평면 배열 분기(app.js:1249-1276)로 렌더 — 그룹핑·빈행 처리 메커니즘이 아예 안 닿음. SG 실측: (a) 2026/1분기(11013) 7행은 `thstrm`·`frmtrm`·`lwfr` 전부 `"-"` — **주당액면가액 포함, DART 원본이 그렇게 옴**(파이프라인 드랍 아님). (b) 중복 항목 4종(현금배당수익률·주식배당수익률·주당 현금배당금·주당 주식배당)이 보고서마다 정확히 2벌 — 두 벌 모두 `stock_knd="-"`로 **완전 동일한 중복 레코드**(보통주/우선주 구분 아님). (c) 기존 그룹핑 전례: `sourceGroupedBlocks`(그룹별 제목+표 형태) + `fundChain`(Map/groupOrder 필드값 그룹핑) — 배당엔 둘을 합친 새 메커니즘 필요.

## File Structure

| 파일 | 변경 |
|---|---|
| `docs/tool/se/app.js` | `footnoteMarkerNote` 문구, 열 우선순위 일반화(`reorderRecordFields`), 메타-only 표 숨김, aggregate 필드 일반화, 패딩 행 생략, 배당 그룹핑(`dividendPeriodBlocks`) |
| `docs/tool/se/ui.js` | 그룹 블록 렌더(기존 블록 렌더 재사용 가능하면 무변경 목표 — 실배선 확인 후) |
| `tests/se/test_se_app_js.py` | 태스크별 테스트 + **jsonb 순서 픽스처** |
| `dart_risk_mcp/` | **무변경** |

---

### Task 1: 각주 안내 문구 간결화

**Files:**
- Modify: `docs/tool/se/app.js:394-399` (`footnoteMarkerNote`)
- Test: `tests/se/test_se_app_js.py` (1029, 1062, 1106-1107의 `"각주"` 고정 3곳)

**요구사항:**

- 본문 없음 안내를 `" (공시 원문 참고)"`로 줄인다: `"주1) (공시 원문 참고)"`.
- `rcept_no` 접미부도 `" · 접수번호 20250318000939"`로 줄인다(뒤의 "의 원문에서 확인 가능" 제거).
- 마커 원문(`주1)`) 보존 원칙은 유지. `isFootnoteMarkerOnly` 게이트 무변경.
- `"각주"`를 고정한 테스트 3곳을 새 고정 토큰(`"원문 참고"`)으로 갱신 — 검증 강도를 낮추지 않는다(마커 존재 + 안내 존재 + bare 마커 부재 3중 검사 유지).

- [ ] **Step 1: 테스트 3곳의 고정 토큰을 먼저 바꿔 실패 확인 → 구현 → 통과 → 전체 회귀 → 커밋**

---

### Task 2: 열 순서를 명시 규칙으로 — jsonb 순서 파괴 대응 (이번 계획의 척추)

**Files:**
- Modify: `docs/tool/se/app.js` (`reorderDividendsRecord`를 일반화한 `reorderRecordFields(record, priorityKeys, tailKeys)` + 소스별 우선순위 테이블)
- Test: `tests/se/test_se_app_js.py`

**Interfaces:**
- Consumes: 기존 `reorderDividendsFields`/`reorderDividendsRecord`(app.js:1674-1699, SE-8 Task 4·8이 만든 패턴), `META_ONLY_KEYS`(app.js:777-780)
- Produces: `reorderRecordFields(record, priorityKeys, tailKeys)` — Task 3·4가 소비

**요구사항:**

- **일반 규칙(전 표 공통):** 메타 키(`stlm_dt`·`bsns_year`·`reprt_code`·`rcept_no`)는 실질 열 **뒤로**, `rm`(비고)은 **맨 뒤로**. 이 tail 규칙을 `sourceGroupedBlocks` 경로(insider_timeline·shareholders 등 source 있는 전 그룹)와 평면 배열 경로 양쪽에 적용한다. 기존 `reorderDividendsRecord`의 "우선 키를 앞으로" 로직에 "tail 키를 뒤로"를 더한 일반 함수로 만들고, 배당 기존 동작은 그 일반 함수의 특수화로 재구현(동작 무변경 회귀 테스트 필수).
- **소스별 우선순위(실측 순서로 명시):** `exec_treasury`: `stock_knd → acqs_mth1 → acqs_mth2 → acqs_mth3 → bsis_qy → change_qy_acqs → change_qy_dsps → change_qy_incnr → trmend_qy`. `hyslr_chg`: `change_on → mxmm_shrholdr_nm → posesn_stock_co → qota_rt → change_cause`. (다른 소스는 tail 일반 규칙만으로 시작 — 추측으로 우선순위를 만들지 않는다. 필드명·의미는 `opendart_api_guide.md` 대조.)
- **jsonb 픽스처 테스트:** 키를 길이순으로 정렬한 레코드(배포본 형태)를 넣어 열 순서가 명시 규칙대로 나오는지 실렌더로 검증한다. 이 픽스처 헬퍼(`jsonb_sorted(record)`)는 이후 태스크도 재사용.
- `ALWAYS_VISIBLE_KEYS`·`splitVisibleFolded`·캡션 승격과의 상호작용 확인: 재배열 후 접힘 대상이 메타 키가 되는지(실질 열이 접히면 안 된다).

- [ ] **Step 1: jsonb 정렬 픽스처로 실패 테스트(exec_treasury 첫 열이 rm이 되는 현상 재현) → 구현 → 통과**
- [ ] **Step 2: 배당 기존 동작 무변경 회귀 + 전체 회귀 → 커밋**

---

### Task 3: 메타-only 표 숨김 + exec_treasury 합계 분리·패딩 행 생략

**Files:**
- Modify: `docs/tool/se/app.js` (`sourceGroupedBlocks`, `isAggregateRow`/`splitAggregateRows` 일반화)
- Test: `tests/se/test_se_app_js.py`

**Interfaces:**
- Consumes: `isMetaOnlyRecords`(app.js:797-807), `splitAggregateRows`(app.js:1190-1198), Task 2의 `reorderRecordFields`

**요구사항:**

- **3a (결정 반영 — SE-4f Task 6 뒤집기):** `isMetaOnlyRecords`가 참이면 표를 렌더하지 않고 안내문만 남긴다: `"해당 기간에 보고된 내역이 없습니다. (보고서 N건 확인)"`. 근거: 안내문이 이미 "없다"고 말하는데 식별자만 남은 22행 표가 밑에 깔리는 것이 사용자 피드백의 대상. 원문 접근성(접수번호)은 공시 목록 탭이 이미 제공. **app.js:896-901의 기존 결정 주석을 이 계획 참조로 갱신**(왜 뒤집었는지 남긴다).
- **3b (합계 행 분리):** `isAggregateRow`에 검사 필드를 매개변수화(기본 `nm` — 기존 hyslr 동작 무변경)하고, `exec_treasury`는 `acqs_mth3`의 `소계`/`총계`를 합계로 분리해 hyslr과 같은 "· 합계" 블록으로 렌더. "계상혁" 오탐 가드 회귀 유지.
- **3c (패딩 행 생략):** `stock_knd === "-"` 이고 수량 필드 전부(`bsis_qy`·`change_qy_acqs`·`change_qy_dsps`·`change_qy_incnr`·`trmend_qy`)와 `rm`이 `"-"`인 행은 생략하되, 캡션에 `"내용 없는 행 N건 생략"`을 표기한다(정직성). 값이 하나라도 있으면 생략하지 않는다. 전 행이 생략 대상이면 3a의 메타-only 경로로 수렴하는지 확인.
- SG 실측(lookback 2년: 145행, 쌍둥이 72그룹)으로 생략 건수·합계 분리 건수를 재고 보고에 기록.

- [ ] **Step 1: 실패 테스트(메타-only 표 잔존, acqs_mth3 소계 미분리, 패딩 행 잔존 각각) → 구현 → 통과**
- [ ] **Step 2: hyslr 기존 동작(분리·오탐 가드) 무회귀 + 전체 회귀 → 커밋**

---

### Task 4: 배당 표 보고서 단위 그룹핑

**Files:**
- Modify: `docs/tool/se/app.js` (`dividendPeriodBlocks` 신설, 평면 분기에서 `dividends`를 그룹 블록으로 라우팅), 필요 시 `docs/tool/se/ui.js`(블록 렌더가 기존 `{title, table, note}` 형태를 그대로 받으면 무변경)
- Test: `tests/se/test_se_app_js.py`

**Interfaces:**
- Consumes: `fundChain`의 Map/groupOrder 그룹핑 기법(app.js:2054-2064), `sourceGroupedBlocks`의 그룹별 `{title, table}` 출력 형태, Task 2의 `reorderRecordFields`, Task 3a의 빈 그룹 안내 처리
- Produces: `dividendPeriodBlocks(records)` — `(bsns_year, reprt_code, stlm_dt)` 그룹당 블록 1개

**요구사항:**

- 그룹 키 `(bsns_year, reprt_code, stlm_dt)`, 그룹 제목 예: `"2025 사업보고서 (결산일 2025-12-31)"` — `reprt_code`→보고서명은 기존 `REPRT_CODE_LABELS` 재사용. 그룹 순서는 최신 우선(현 표시 순서 유지).
- 그룹 내부 행에서 `bsns_year`·`stlm_dt`·`reprt_code`(·상수인 `rcept_no`)를 제거해 제목으로 승격 — 반복 제거가 사용자 요구의 핵심.
- **완전 동일 중복 레코드 dedup**: 전 필드가 동일한 레코드 쌍(SG 실측 16쌍)은 1건만 남긴다. 필드 하나라도 다르면 남긴다(보통주/우선주 구분 가능성 보존).
- **전부 `"-"`인 그룹(2026 1분기)**: 행을 나열하지 않고 그룹 제목 + `"해당 기간에 보고된 내역이 없습니다."`(Task 3a와 동일 문구·동일 처리) — 주당액면가액 빈칸 의문의 답이 이것이다(DART 원본이 미기재; 실측 확인).
- `dividendVsIncome`(SE-4f 파생 블록) 무변경 — 회귀 테스트 필수.
- 차트(`CHART_SPECS`의 dividends 항목)가 원본 records 배열을 소비한다면 그룹핑이 차트 입력을 바꾸지 않는지 확인(표시 계층만 변경).
- SG 실 데이터(67레코드·5그룹·16중복쌍·빈 그룹 1)로 실렌더 재검증.

- [ ] **Step 1: 실패 테스트(그룹 제목 부재, 연도 열 반복, 중복 잔존, 빈 그룹 행 나열) → 구현 → 통과**
- [ ] **Step 2: dividendVsIncome·차트 무회귀 + 전체 회귀 → 커밋**

---

## 마무리

- [ ] 전 태스크 후: SG 실 데이터 + **jsonb 정렬 시뮬레이션**으로 3개 피드백 항목 화면 재검증 (`#main[hidden]` 함정 유의)
- [ ] 전체 브랜치 최종 리뷰(Opus) → PR

## Self-Review

- **jsonb 발견이 계획의 절반이다.** 조사 서브에이전트의 로컬 트레이스가 "비고는 11번째"라고 계산했지만 스크린샷은 1번째였다 — 로컬(dict 순서 보존)과 배포(jsonb 길이 정렬)의 차이. 이걸 놓치고 "소스별 우선순위만" 넣었으면 우선순위에 없는 열들이 배포본에서 계속 임의 순서로 나왔을 것이다. tail 일반 규칙 + jsonb 픽스처 테스트가 재발 방지 장치다.
- **3a는 기존 결정(SE-4f Task 6 "표는 지우지 않는다")을 뒤집는다.** 기계적 수정이 아니라 제품 결정이므로 사용자 승인 항목으로 표기했다.
- **패딩 행 생략(3c)·중복 dedup(4)은 "정보 보존" 원칙의 예외다.** 둘 다 사실이 0개인 행(전 필드 "-" 또는 완전 동일 사본)에 한정하고, 생략 사실을 화면에 표기한다.
- **추측 금지 지점:** hyslr_chg 외 소스의 우선순위는 실측 없이 만들지 않는다(tail 규칙만). 배당 중복은 "완전 동일"만 지운다(주식종류가 다른 쌍은 남긴다).
