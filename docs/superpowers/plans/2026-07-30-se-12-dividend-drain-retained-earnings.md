# SE-12: DIVIDEND_DRAIN 연도별 매칭 수정 + 배당 vs 이익잉여금 조인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) 문법으로 추적한다.

**Goal:** ① `dart_risk_mcp` core의 `DIVIDEND_DRAIN`(적자 시점 배당 유출) 탐지가 "가장 최근 1개 연도 순이익만 전 배당 연도에 재사용"하는 구조적 결함을 고쳐 실제로 발화할 수 있게 하고, SE에도 배선한다. ② SE에 배당 vs 이익잉여금 비교를 새로 추가한다.

**Architecture:** core 버그 수정(`dart_risk_mcp/core/dart_client.py`의 `detect_dividend_drain` + `server.py`의 호출부) + SE 프런트엔드 확장(`docs/tool/se/app.js`). "자산매각 규모"는 이번 계획에서 명시적으로 제외한다(사용자 승인됨 — 이유는 아래 배경 참고).

## Global Constraints

- **판정 어휘 금지 (v0.8.5)**: 새 문구는 사실만.
- **`dart_risk_mcp/`는 추가 또는 버그 수정만, 기존 26개 도구의 시그니처·정상 동작 파괴 금지.** `detect_dividend_drain`은 MCP 도구로 직접 노출되지 않는 내부 헬퍼라 시그니처를 바꿔도 무방하나, `track_fund_usage` MCP 도구 자체의 파라미터·정상 출력 포맷은 그대로 유지한다(발화 조건만 고친다).
- **연결/별도(CFS/OFS)를 섞지 않는다** — 기존 원칙(`indexAccountsByDiv` 계열). 두 값이 다른 부호일 수 있음이 실측으로 확인됐다(두산 2022 CFS 적자·OFS 흑자). 하나로 합쳐 "적자다/아니다"를 판정하지 않고 CFS·OFS 각각을 사실로 표기한다.
- **연도 매칭은 alotMatter(배당 원본) 자체가 이미 bundling한 당기순이익 값을 재사용한다 — 새 DART 호출·새 stage1 추가 없음.** 아래 배경 참고.
- 실렌더 검증(SE 쪽 `run_render_section`), 소스 grep 검증 금지. core 쪽은 실 API 호출로 라이브 검증(두산 00117212 필수).
- 커밋마다 `python -m pytest tests/ -q`(core) 와 SE 테스트 무회귀.

---

## 배경: 실측으로 확인한 것 (`.superpowers/sdd/se12-investigation.md` 전문 참조)

### 핵심 발견 — alotMatter 응답 자체가 다년 당기순이익을 이미 갖고 있다

`fetch_dividend_history`(SE `dividends` stage1이 이미 lookback_years만큼 수집)가 부르는 DART `alotMatter.json`은 배당 정보뿐 아니라 그 사업연도의 **`(연결)당기순이익(백만원)`·`(별도)당기순이익(백만원)`을 같은 배열 안 별개 `se`(항목) 행으로 함께 준다.** `dividendVsIncome()`(SE-4f, `app.js:2587`)가 이미 이 사실에 기대 `(bsns_year, reprt_code)`로 그룹핑해 배당 대 순이익을 비교하고 있다 — **`financials`(재무제표) 섹션을 전혀 안 쓴다.**

그런데 core의 `detect_dividend_drain`(`dart_client.py:3816`)은 이 사실을 안 쓰고, 호출부(`server.py:2911` `track_fund_usage`)가 **별도로 `fetch_financial_statements_all`을 딱 한 해치만**(`datetime.now().year - 1`, CFS→OFS 폴백) 불러 `current_fs`로 넘긴다. `detect_dividend_drain` 내부는 이 단일 연도 순이익을 **모든 배당 연도에 그대로 재사용**한다 — 2020년 배당 기록이 있어도 2020년 순이익이 아니라 "가장 최근 연도" 순이익과 짝짓는다.

**결과**: 6개 회사 매트릭스(+SG) 전부 0/7 발화 — CLAUDE.md 표의 근거. 그런데 연도별로 제대로 짝지어 재확인하니 **두산(00117212)이 2022년(CFS 순이익 −5,811.7억원)·2023년(OFS 순이익 −1,118.7억원)에 각각 배당(357.72억원)과 겹쳐 실제로 발화하는 사례였다** — "발화가 희귀해서 후순위"가 아니라 "구현이 최근 1년만 봐서 못 잡았을 뿐"이었다는 뜻이다.

### 수정 설계 — 새 fetch 없이 alotMatter 자체 데이터로 연도별 매칭

- `detect_dividend_drain`을 `dividend_records`(alotMatter 배열)만 받도록 바꾼다(`current_fs` 파라미터 제거 또는 옵션화). 함수 내부에서 `(bsns_year, reprt_code)`별로 `"(연결)당기순이익(백만원)"`·`"(별도)당기순이익(백만원)"` 행을 찾아 그 **같은 연도**의 현금배당 행과 짝짓는다 — `dividendVsIncome()`의 그룹핑 로직과 대응(포팅이 아니라 "같은 원리", 언어가 다르니 그대로 복붙은 안 됨).
- CFS·OFS는 따로따로 검사하고 플래그도 각각 낸다(둘 다 음수일 필요 없음, 하나만 음수여도 그 구분으로는 발화 — 실측 두산 사례가 정확히 이 모양).
- `server.py`의 `track_fund_usage`는 이제 `_current_fs`용 별도 `fetch_financial_statements_all` 호출이 필요 없다 — 그 블록을 지운다(호출 수가 줄어드는 부수적 개선).
- **`se` 문자열 재조사 필요**: 기존 Python 코드는 `"현금배당금" in se`로 느슨하게 매칭하고 `rec["thstrm"]`을 그대로 float 변환한다(단위 주석 없음). JS `dividendVsIncome`은 `"현금배당금총액(백만원)"`(총액, 백만원 단위)을 명시적으로 쓴다. 이 둘이 같은 개념을 가리키는지, 단위가 뭔지(총액 vs 주당, 백만원 vs 원) **Task 1에서 두산 실측으로 재확인하고 하나로 통일한다** — 추측 금지.

### 이익잉여금 — 단일 연도 비교로 스코핑 (다년 아님, 정직하게 표기)

`이익잉여금`은 alotMatter에 안 들어있고 `financials`(SE가 이미 수집)에만 있다. **SE의 `financials` stage1은 최근 1개 사업연도만 수집한다**(`Stage1Spec("financials", ..., ("corp_code",))` — `lookback_years` 파라미터가 없음, SE-10이 이미 확인한 사실과 동일 구조). 따라서 이익잉여금 비교는 **"이번 사업연도"** 한 시점만 가능하고, 배당은 다년(alotMatter)이라 "이번 연도 이익잉여금 vs 이번 연도 배당"만 비교 가능하다 — 다년 추이 비교가 아니다. **화면 문구가 이 사실을 정직하게 반영해야 한다**("올해 이익잉여금" 같은 표현, "추이"라는 말을 쓰지 않는다).

### 자산매각 규모 — 이번 계획에서 제외 (사용자 승인됨)

`get_major_decision`은 단건 조회 전용이라 "기간 합산" 오케스트레이션이 통째로 없고, 만들어도 SG+6사/365일 실측 0/7건 — 가치를 입증할 사례가 없다. 별개 항목으로 남겨두고 이번엔 손대지 않는다.

## File Structure

| 파일 | 변경 |
|---|---|
| `dart_risk_mcp/core/dart_client.py` | `detect_dividend_drain` 재설계(연도별 매칭, CFS/OFS 분리, `dividend_records`만 입력) |
| `dart_risk_mcp/server.py` | `track_fund_usage`의 `_current_fs` 별도 조회 블록 제거, 새 `detect_dividend_drain` 호출로 교체 |
| `tests/test_dart_client.py`(또는 기존 core 테스트 파일 — 실제 파일명 확인 후 사용) | 신규 함수 단위 테스트 |
| `docs/tool/se/app.js` | `dividendDrainFlags`(신설, dividends 배열만 소비) + `dividendVsRetainedEarnings`(신설, financials+dividends 단일연도 조인) |
| `docs/tool/se/ui.js` | 두 신설 파생 블록을 `dividendVsIncome` 옆에 렌더 배선 |
| `tests/se/test_se_app_js.py` | 태스크별 테스트 |

---

### Task 1: core — `detect_dividend_drain` 연도별 매칭으로 재설계

**Files:**
- Modify: `dart_risk_mcp/core/dart_client.py`(`detect_dividend_drain`), `dart_risk_mcp/server.py`(`track_fund_usage`)
- Test: core 테스트 스위트(기존 파일 위치 확인 후 추가)

**요구사항:**

- **먼저 두산(00117212)의 alotMatter 실측으로 `se` 문자열·단위를 확정한다** — `"(연결)당기순이익(백만원)"`·`"(별도)당기순이익(백만원)"`·현금배당 항목(총액 vs 주당, 단위)이 실제로 어떤 문자열·단위로 오는지 라이브 호출로 재확인하고, 기존 Python 함수의 느슨한 `"현금배당금" in se`·JS의 `"현금배당금총액(백만원)"` 중 어느 쪽이 맞는지(혹은 둘 다 다른 걸 가리키는지) 판정한다. **추측으로 통일하지 않는다.**
- `detect_dividend_drain(dividend_records)`로 시그니처 변경(`current_fs` 제거 — 필요 없어짐을 실측으로 확인 후 제거, 호출부 유지 필요시 옵션 인자로 남기되 미사용 경고).
- `(bsns_year, reprt_code)`로 그룹핑해 같은 그룹 안의 당기순이익(연결·별도 각각)과 현금배당을 짝짓는다. 분기 4회 중복 호출은 기존 dedup 방식(`(bsns_year, se, stock_knd)`)을 유지한다.
- CFS 발화·OFS 발화를 별개 플래그로 낸다(`fs_div`를 플래그 dict에 포함). 한쪽만 음수여도 그 구분에 대해 발화.
- `server.py`의 `track_fund_usage`에서 `_current_fs` 조회 블록(별도 `fetch_financial_statements_all` 호출 2번)을 지우고 `detect_dividend_drain(dividend_records)`로 교체. 출력 문구("⚠ 적자 시점 배당 유출...")에 이제 CFS/OFS 구분을 명시한다.
- **라이브 검증(필수)**: 두산(00117212)에 대해 실제로 2022·2023년 발화하는지, 6사 매트릭스(SG·두산에너빌리티·삼성전자·셀트리온·제이스코·헬릭스미스)에서 새로 생긴 오탐이 없는지 전부 확인.

- [ ] **Step 1: 두산 실측으로 se 문자열·단위 확정 (구현 전 필수)**
- [ ] **Step 2: 실패하는 테스트(두산 2022·2023 발화, 기존 매트릭스 무오탐, CFS/OFS 별개 플래그) → 구현 → 통과**
- [ ] **Step 3: `python -m pytest tests/ -q` 전체 회귀 + `test_golden_output_hygiene.py` 통과 확인 → 커밋**

---

### Task 2: SE — DIVIDEND_DRAIN 배선 + 배당 vs 이익잉여금 조인

**Files:**
- Modify: `docs/tool/se/app.js`(`dividendDrainFlags`, `dividendVsRetainedEarnings` 신설), `docs/tool/se/ui.js`(렌더 배선)
- Test: `tests/se/test_se_app_js.py`

**요구사항 A — DIVIDEND_DRAIN (JS 포팅, 새 stage1 불필요)**

- Task 1에서 확정한 `se` 문자열·단위 규칙을 그대로 JS로 옮긴다(`dividendVsIncome`과 같은 그룹핑 키 재사용 — 신규 그룹핑 로직 발명 금지, 기존 걸 확장).
- `dividendDrainFlags(records)`: `dividends` 원본 배열만 입력, CFS/OFS 별개 사실로 플래그. 문구는 사실만("이 사업연도 (연결)당기순이익 음수 + 현금배당 존재") — "위험"·"유출" 같은 core MCP 도구용 강한 표현은 SE의 무판정 원칙(v0.8.5)에 맞게 순화한다(core는 자유 텍스트 응답이라 허용되는 어투가 SE 표에는 과할 수 있음 — 기존 SE 강조 문구 톤과 맞춘다, 예: SE-8의 `"보고된 집행 ≠ 계획"`류).
- `dividendVsIncome` 블록 옆(또는 그 안)에 렌더. 배당 기록이 없거나 발화 조건이 없으면 아무것도 안 나온다(과시적 "이상 없음" 문구 금지 — 기존 SE 관례).

**요구사항 B — 배당 vs 이익잉여금 (단일 연도)**

- `dividendVsRetainedEarnings(financialsRecords, dividendRecords)`: `financials`(단일 최근 사업연도)에서 `account_nm === "이익잉여금"`을 CFS/OFS 각각 추출(원 단위), `dividends`에서 같은 `bsns_year`의 현금배당총액(백만원)을 찾아 **단위를 맞춰**(백만원→원 또는 원→백만원, 어느 쪽이 화면에서 더 읽기 쉬운지는 구현자 판단, 기존 SE 표기 관례 확인 후 결정) 병기.
- **연도가 안 겹치면(financials의 사업연도와 dividends 최신 연도가 다르면) 조인하지 않고 그 사실을 표기한다** — 억지로 다른 연도끼리 비교하지 않는다.
- 문구는 "이번 사업연도"로 명시하고 "추이"라는 말을 쓰지 않는다(배경 절 참고 — 다년 비교가 아니므로).
- SG(00963976) 실측(2024 CFS 이익잉여금 −167.4억원, OFS −218.8억원)으로 최종 확인.

- [ ] **Step 1: 실패 테스트(두산 실측 재현 — DIVIDEND_DRAIN 발화, SG 실측 — 이익잉여금 조인) → 구현 → 통과**
- [ ] **Step 2: `dividendVsIncome` 기존 동작 무회귀 + 전체 회귀 → 커밋**

---

## 마무리

- [ ] 두 태스크 후: 두산·SG 실 데이터로 화면 재검증
- [ ] 전체 브랜치 최종 리뷰(Opus) → PR

## Self-Review

- **alotMatter가 다년 당기순이익을 이미 bundling한다는 발견이 이 계획의 척추다.** 처음엔 "core에 다년 재무제표 조회를 새로 만들어야 하나" 걱정했는데, `dividendVsIncome`이 이미 그 문제를 풀어놓은 걸 확인하고 나서야 새 DART 호출·새 stage1이 필요 없다는 걸 알았다 — 만약 이 확인 없이 바로 구현했으면 불필요한 백엔드 작업(새 다년 재무 stage1)을 추가할 뻔했다.
- **CFS/OFS를 하나로 합쳐 판정하지 않는다는 원칙을 이번에도 지킨다** — 두산 실측이 정확히 "한쪽만 적자" 사례라 병합하면 놓치거나 왜곡된다.
- **이익잉여금은 다년이 아니라 단일 연도 비교임을 화면 문구에 정직하게 반영한다** — SE의 `financials`가 최근 1년만 수집하는 구조적 한계를 사용자에게 숨기지 않는다.
- **`se` 문자열·단위 재조사를 Task 1의 첫 단계로 못박았다** — 기존 core 코드(느슨한 매칭)와 SE의 기존 코드(명시적 매칭)가 서로 다른 가정을 갖고 있어서, 통일하지 않고 그냥 갖다 쓰면 둘 중 하나가 조용히 틀린 값을 낼 수 있다.
- **자산매각 규모는 사용자 승인으로 범위에서 뺐다** — 데이터 소스가 근본적으로 다른 성격(단건 조회, 집계 함수 없음, 실측 0건)이라 이 계획과 섞으면 이익잉여금 파트의 낮은 리스크까지 같이 흐려진다.
