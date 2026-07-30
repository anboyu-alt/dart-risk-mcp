# SE-10: 재무 표 "당기/전기/전전기" → 실제 연도 + 표 구조 정리 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) 문법으로 추적한다.

**Goal:** 사용자가 SE-9 반영 배포본을 SG(00963976)로 3차 재분석하며 남긴 재무 표 2건(재무 파생 지표 표, 원본 재무제표 표)의 "당기/전기/전전기" 서수 표기를 실제 연도로 바꾸고, 그룹핑되지 않은 평면 표를 이해 가능한 구조로 재편한다.

**Architecture:** SE 프론트(`docs/tool/se/app.js`·`ui.js`)만 수정. 두 표 모두 원본 DART 레코드에 실제 연도가 이미 있는데(단일 호출·단일 사업연도라 `bsns_year`가 배열 전체에서 상수) 렌더 계층이 그 값을 안 쓰고 서수 라벨만 쓰고 있었다는 것이 공통 원인이다.

**Tech Stack:** 기존과 동일 (순수 JS, 의존성 0, pytest + node 서브프로세스 테스트)

## Global Constraints

- **판정 어휘 금지 (v0.8.5)**: 새 문구는 사실만.
- **정보는 보존, 표기만 정리** — 날짜 필드를 연도로 축약해도 원본 정밀도(기수명 "제 17 기" 등)는 캡션에 이미 있으므로 손실이 아니다. 손실이 발생하는 변경(예: 표 병합으로 개별 값이 안 보이게 되는 것)은 하지 않는다.
- **`dart_risk_mcp/` 코어 무변경**, 새 의존성 금지.
- **연도는 실측(단일 호출·단일 사업연도 구조 보장)에서 계산** — 회사마다 다른 연도를 가정하지 않는다. `se_server/jobs/registry.py`가 `financials` 섹션을 연도 파라미터 없이 단일 호출하는 구조 자체가 "배열 전체에서 bsns_year가 상수"를 보장한다(`.superpowers/sdd/se10-investigation.md` Q1a 참조) — 이 보장이 깨지는 변경(예: 다년 조회 추가)은 이번 계획의 범위 밖이다.
- 실렌더 검증(`run_render_section`), 소스 grep 검증 금지.
- 커밋마다 `python -m pytest tests/ -q` 무회귀.
- **차트 순서 보존**: `financial_ratios` 차트는 기간을 "전전기→전기→당기"(과거→현재) 순 범주축으로 쓴다(app.js:2136-2144 주석). 연도 문자열로 바꿔도 이 시간 순서가 깨지면 안 된다(연도가 4자리 동일 길이 숫자 문자열이라 사전순=시간순이 자동 성립하지만, 반드시 실렌더로 확인).

---

## 배경: 실측으로 확인한 것 (`.superpowers/sdd/se10-investigation.md` 전문 참조)

### 공통 원인 — 연도 데이터는 이미 있는데 렌더 계층이 안 쓴다

`fetch_financial_statements`가 반환하는 30개 레코드 전부 `bsns_year: "2025"`로 상수(SE 백엔드가 연도 파라미터 없이 단일 호출하는 구조라 항상 성립 — 특정 회사 우연이 아니라 구조적 보장). 같은 레코드에 `thstrm_dt`(당기, "2025.12.31 현재" 또는 "2025.01.01 ~ 2025.12.31")·`frmtrm_dt`(전기, 2024)·`bfefrmtrm_dt`(전전기, 2023)도 있어 두 경로 모두 실제 연도를 계산할 수 있다. 그런데:

- **재무 파생 지표 표**: `RATIO_PERIODS`(app.js:2145-2149)가 `{period: "전전기"|"전기"|"당기"}` 리터럴만 쓰고, `computeRatio`/`computeCapitalImpairment`는 입력에 `bsns_year`가 있는데도 한 번도 안 읽는다. 결과: 30행짜리 평면 표 하나, 정렬은 구분(연결→별도)이 바깥, 기간(전전기→전기→당기)이 안쪽 — 사용자가 지적한 정확히 그 구조.
- **원본 재무제표 표**: 제목이 아예 없다(`sectionBlocks`가 `title: null` 하드코딩, app.js:1465-1466). `당기 기간`·`전기 기간`·`전전기 기간` 3열이 원본 날짜 문자열("2025.12.31 현재" 등)을 그대로 보여준다 — 12개 표시 열 중 3개가 이 형태. **연결·별도가 한 표에 섞여 있다**: DART `/fnlttSinglAcnt.json?fs_div=CFS` 호출이 실제로는 fs_div 필터링을 안 하고 CFS 15행+OFS 15행을 한 응답에 같이 준다(DART 자체 특성, 우리 버그 아님) — `fs_div` 열이 12개 열 중 8번째(계정과목 바로 옆이 아님)라 경계가 안 보인다.

### 재사용 가능한 전례

- **연도 계산**: `dividendVsIncome()`(app.js:2371-2402, SE-4f)이 이미 "실제 bsns_year를 계산해 파생 행에 심는다"를 해봤다 — 같은 패턴 재사용.
- **그룹당 표 + 제목**: `dividendPeriodBlocks`(app.js:2081, SE-9)의 Map+groupOrder+제목 메커니즘이 구조적으로 정확히 맞는 형태다. 다만 `financialRatios()`의 출력 행에는 그룹 키로 쓸 `bsns_year` 같은 필드가 아직 없다 — 연도 계산을 먼저 심어야 그룹핑을 걸 수 있다.
- **상수 열 캡션 승격**: `tableLayout`은 전 행에서 값이 같은 열을 자동으로 캡션 칩으로 올린다(기존 메커니즘, 무변경). 날짜 문자열을 연도 4자리로 축약하면 BS행("...현재")과 IS행("...~...")이 서로 다른 원본 문자열이라도 앞 4자리는 똑같아지므로, **부수효과로 이 세 날짜 열이 자동으로 캡션에 올라간다** — 새 메커니즘을 안 만들어도 표가 저절로 단순해진다(실렌더로 확인 필요, 가정 금지).

## File Structure

| 파일 | 변경 |
|---|---|
| `docs/tool/se/app.js` | `RATIO_PERIODS`에 연도 계산 추가, `computeRatio`/`computeCapitalImpairment`가 연도 값 방출, `financialRatiosByYear`(신설, dividendPeriodBlocks 패턴 재사용) 그룹핑, `financials` 원본 표 fs_div 그룹핑 + 날짜→연도 축약 |
| `docs/tool/se/ui.js` | `buildFinancialRatiosBlock`이 그룹 블록을 렌더 |
| `tests/se/test_se_app_js.py` | 태스크별 테스트 |
| `dart_risk_mcp/` | **무변경** |

---

### Task 1: 재무 파생 지표 표 — 연도를 실제 값으로, 연도별 표 분리

**Files:**
- Modify: `docs/tool/se/app.js`(`RATIO_PERIODS`, `computeRatio`, `computeCapitalImpairment`, `financialRatios`, 신설 `financialRatiosByYear`), `docs/tool/se/ui.js`(`buildFinancialRatiosBlock`)
- Test: `tests/se/test_se_app_js.py`

**요구사항:**

- `financialRatios(records)`가 받는 `records`에서 `bsns_year`를 한 번 계산(Q1a 방식: 상수이므로 첫 유효값 사용, 없으면 기존 서수 라벨로 안전 폴백 — 판정 불가 시 지우지 않는다 원칙). 당기=`bsns_year`, 전기=`bsns_year-1`, 전전기=`bsns_year-2`.
- 각 지표 행의 `기간` 값을 서수 문자열("전기" 등) 대신 실제 연도 문자열("2024")로 채운다. **결정 사항 — 이대로 진행:** 연도별로 별도 표를 만들면 표 안에서 `기간` 열은 정보가 제목에 이미 있어 중복이므로, 그룹 후 행에서 제거한다(원칙: 그룹 제목으로 승격된 정보는 행에서 제거 — SE-9 Task 4와 동일 패턴).
- `financialRatiosByYear(ratios)` 신설: `dividendPeriodBlocks`와 같은 Map+groupOrder 메커니즘으로 연도(내림차순, 최신 먼저 — 기존 화면 표시 순서 유지)별로 묶어 `{title: "2025년", table}` 블록을 만든다. **결정 사항 — 이대로 진행:** 연도 표 안에서는 `구분`(연결/별도)을 행의 첫 열로 유지한다(표를 연결/별도로 다시 쪼개지 않음 — 3년×2구분=6개 미니 표로 쪼개는 것보다 가독성이 낫다고 판단). *사용자가 연결/별도도 별도 표로 쪼개길 원하면 이 결정만 뒤집으면 된다.*
- `buildFinancialRatiosBlock`이 단일 `tableLayout` 대신 연도별 블록 목록을 렌더하도록 배선.
- **차트 x축 순서 보존**: `CHART_SPECS.financial_ratios`가 기간을 과거→현재 순으로 쓰는 로직(app.js:2136-2144)이 연도 문자열로도 동일하게 동작하는지 실렌더로 확인. 깨지면 정렬 키를 연도 오름차순으로 명시.
- **Beneish 변수 블록(app.js 다른 곳에서 `기간`을 소비하는 지점이 있는지 확인)**: `financialRatios`의 출력 형태를 바꾸므로, 이 함수를 소비하는 다른 코드(정렬·필터·차트 외)가 있는지 점검하고 있으면 무회귀 테스트를 추가한다.
- SG 실측(연결 3년+별도 3년=6개 구분×기간 조합, 지표별)으로 연도 값이 실제 2025/2024/2023과 일치하는지 최종 확인.

- [ ] **Step 1: 실패 테스트(기간 값이 여전히 "전기" 문자열, 연도별 그룹 미분리, 차트 순서) → 구현 → 통과**
- [ ] **Step 2: 전체 회귀 → 커밋**

---

### Task 2: 원본 재무제표 표 — 제목 부여 + 날짜→연도 축약 + 연결/별도 분리

**Files:**
- Modify: `docs/tool/se/app.js`(`sectionBlocks`의 `financials` 분기, 날짜 필드 축약 헬퍼 신설)
- Test: `tests/se/test_se_app_js.py`

**요구사항:**

- `financials` 레코드를 `fs_div`(CFS/OFS)로 그룹핑해 표 2개(있는 만큼만 — 별도만 있는 회사면 1개)로 분리. 그룹 제목은 `fs_nm`(레코드에 이미 있음, "연결재무제표"/"재무제표") + 계산된 연도: 예 `"2025년 연결재무제표"`. `dividendPeriodBlocks`와 동일한 Map+groupOrder 패턴 재사용(신설 함수 이름은 구현자 재량, 기존 패턴과 일관되게).
- `thstrm_dt`·`frmtrm_dt`·`bfefrmtrm_dt` 값을 원본 날짜 문자열 대신 앞 4자리(연도)로 축약(regex `^\d{4}`, BS의 "...현재"·IS의 "...~..." 둘 다 앞 4자리가 연도라 동일하게 동작 — 실측 확인됨). **이 축약이 세 열을 그룹 내에서 상수로 만들어 기존 `tableLayout` 캡션 승격 메커니즘이 저절로 캡션으로 올릴 것으로 예상 — 실렌더로 검증하고, 예상과 다르면 왜 다른지 보고에 남긴다(가정으로 넘어가지 않는다).**
- `thstrm_nm`·`frmtrm_nm`·`bfefrmtrm_nm`(기수명, 이미 캡션 승격됨)은 무변경.
- 열 정보 손실 없음 확인: 축약 전 원본 날짜 문자열이 필요한 사용처가 있으면(없을 것으로 예상 — 확인) 유지.
- SG 실측(연결 15행/별도 15행, 축약 후 두 표 다 캡션에 "당기 2025 · 전기 2024 · 전전기 2023" 류로 표시되는지)으로 최종 확인.

- [ ] **Step 1: 실패 테스트(표 제목 없음, 연결/별도 혼재, 날짜 열이 원본 문자열) → 구현 → 통과**
- [ ] **Step 2: 전체 회귀 → 커밋**

---

## 범위 밖으로 명시 — 이번엔 안 건드림

- **배당 표 그룹 내부의 "당기 값"/"전기 값"/"전전기" 열 라벨** (`LABELS` app.js:195, `thstrm`/`frmtrm`/`lwfr`): SE-9가 이미 그룹 제목에 실제 연도를 달아놔서 서수 라벨이 남아 있어도 혼란이 상대적으로 적다(조사 Q4 "부분적으로 이미 완화됨"). 이번 계획은 사용자가 스크린샷으로 지적한 두 표에 집중하고 이건 건드리지 않는다 — 필요하면 후속 계획.

## 마무리

- [ ] 전 태스크 후: SG 실 데이터로 두 표 화면 재검증(`#main[hidden]` 함정 유의)
- [ ] 전체 브랜치 최종 리뷰(Opus) → PR

## Self-Review

- **두 표의 근본 원인이 같다** — 연도 데이터는 이미 레코드에 있는데 렌더 계층이 서수 라벨만 썼다. 이게 계획을 두 개의 독립 작업이 아니라 하나의 계획으로 묶은 이유다.
- **연도 계산은 회사마다 다르게 동작하지 않는다** — `bsns_year`가 배열 전체에서 상수인 건 특정 회사의 우연이 아니라 SE 백엔드가 연도 파라미터 없이 단일 호출하는 구조적 보장(Global Constraints에 명시). 이 가정이 깨지는 변경은 범위 밖으로 뒀다.
- **날짜→연도 축약이 캡션 자동 승격을 유발할 것이라는 예상은 검증 필요 항목으로 명시했다** — 기존 메커니즘의 부수효과를 이용하는 설계라 "될 것 같다"가 아니라 실렌더로 확인하고, 안 되면 보고에 이유를 남기도록 Task 2에 못박았다.
- **재무 파생 지표의 "연결/별도를 표로 또 쪼갤지" 여부는 판단이 갈리는 지점이라 명시적으로 결정하고 이유를 남겼다** — 사용자가 다르게 원하면 그 결정만 뒤집으면 되는 구조로 설계했다.
