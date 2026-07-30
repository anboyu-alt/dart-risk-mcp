# SE-13: 불공정거래 패턴 — SE 이식(상세) + 근거 데이터 보강 + 공개 뷰어 보강 + 죽은 배선 수정 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) 문법으로 추적한다.

**Goal:** 금감원 보도자료·제작자 기사에서 추출한 불공정거래 패턴(core `CROSS_SIGNAL_PATTERNS` 9종 + 카탈로그 MD)을 **SE에 상세하게 이식**하는 것이 주 목표다(사용자 확인: 공개 뷰어에 패턴 매칭이 있는 건 알고 있고, SE에도 넣고 더 자세하게 나오길 원함). 부차로 공개 뷰어의 기존 패턴 패널에도 근거를 보강하고, 조사 중 발견된 core의 죽은 카탈로그 발췌 배선을 고친다.

**Architecture:** core 정적 데이터(패턴·카탈로그)는 완성돼 있다. ① export 스크립트가 근거(`field_evidence`)를 내보내도록 확장(두 뷰어 공용 데이터 기반) → ② SE에 상세 패턴 블록 신설(주 목표) → ③ 공개 뷰어 패널에 근거 추가(부차) → ⓪ core 죽은 배선은 독립 선행 수정.

## Global Constraints

- **판정 어휘 금지 (v0.8.5)**: `severity`(CRITICAL 등)는 **어느 뷰어에도 절대 내보내지 않는다** — `scripts/export_tool_data.py`가 이미 데이터 계층에서 구조적으로 제외하고 있고, 이 제외를 유지한다. 사례 인용(`field_evidence`)은 사실이므로 표기 가능하되, **인용문 자체에 판정 어휘가 섞여 있는지 실측 검사 후** 포함 방식을 정한다(원문 그대로 vs 인용 범위 축소 — 없는 말을 만들지 않는다).
- **매칭 로직 무변경**: `find_pattern_match`는 부분집합 매칭(순서 무시)이다 — "sequence"라는 이름과 달리 시간 순서를 검사하지 않는다. 이 동작 변경은 범위 밖(공개 뷰어·MCP 도구 3종이 같은 규칙을 공유). **뷰어 간 매칭 규칙은 반드시 동일**해야 한다 — SE-12의 Python↔JS 동치 검증 전례처럼, 같은 입력에 같은 매칭 결과를 테스트로 고정한다.
- **`dart_risk_mcp/`는 Task 1의 버그 수정만** — 기존 26개 도구 시그니처·정상 동작 파괴 금지.
- **면책 문구 유지**: 기존 공개 뷰어·MCP 도구가 쓰는 "사실 표기 — 판정 아님" 면책을 새 표기에도 동일하게 붙인다.
- 실렌더 검증(SE는 `run_render_section` + `jsonb_sorted()` 픽스처, 공개 뷰어는 해당 테스트 관례 확인 후 동일 수준), 소스 grep 검증 금지.
- 커밋마다 `python -m pytest tests/ -q` 무회귀.

---

## 배경: 실측으로 확인한 것 (`.superpowers/sdd/se13-investigation.md` 전문 참조)

### 현황 지도

- **공개 뷰어(`docs/tool/index.html`)**: 첫 기능 커밋부터 클라이언트 신호 매칭(`matchSignals`, :564-572) + 패턴 부분집합 매칭 + "PATTERN MATCH" 패널(:627-628, :832-838) 보유. 데이터는 `signals-data.json`(`scripts/export_tool_data.py`의 `build_signals_data()`, **수동 실행** — CI 강제 여부 미확인). severity·field_evidence는 v0.8.5 근거로 의도적 제외. **근거(사례 인용·카탈로그 프로즈)는 화면에 전혀 없음.**
- **SE(`docs/tool/se/`)**: 같은 `signals-data.json`을 로드하지만 `patterns` 필드를 한 번도 안 읽는다(app.js·ui.js·se_server 전체 grep 0건). SE-7이 공시 신호 분류(표시용 재매칭)를 이미 하고 있어 신호 탐지 입력은 존재.
- **core 자산**: `taxonomy.py:1101-1201` `CROSS_SIGNAL_PATTERNS` 9종(founder_fade·debt_spiral·reverse_split_spiral·related_party_hollowing·zombie_ma·audit_insider_dump·delisting_evasion·fake_new_biz·capital_churn_anomaly), 각각 `signal_sequence`(taxonomy ID 목록)·`severity`·`field_evidence`(금감원 보도자료 사례 인용). `taxonomy.py:1269-1289` `find_pattern_match`: 부분집합 매칭, `analyze_company_risk`·`find_risk_precedents`·`build_event_timeline`이 호출. `catalog.py:48` `load_catalog_excerpt(taxonomy_ids)`: 카테고리별 `knowledge/manipulation_catalog/*.md` 발췌 — field_evidence와 별개·상보 자산.
- **죽은 배선(라이브 재현 완료)**: `server.py:2905`(`track_fund_usage`)가 `load_catalog_excerpt(["zombie_ma", "fake_new_biz"])`를 호출 — 함수는 taxonomy ID를 기대하므로 패턴 키는 전부 miss, **항상 빈 문자열**(패턴 키 0자 vs 올바른 ID 3,328자). CLAUDE.md에 문서화된 기능이 한 번도 렌더된 적 없다. 이 계열 여덟 번째 죽은 배선이고 테스트는 전부 초록이었다.
- **라이브 매칭 전례**: `capital_churn_anomaly`가 제이스코홀딩스에서 라이브 매칭(CLAUDE.md 검증 매트릭스 ✅) — 실렌더 검증용 기준 회사.

## File Structure

| 파일 | 변경 |
|---|---|
| `dart_risk_mcp/server.py` | Task 1 — `track_fund_usage`의 `load_catalog_excerpt` 호출 인자 수정 |
| `scripts/export_tool_data.py` | Task 2 — `field_evidence`·설명 등 근거 필드 내보내기 추가(severity 계속 제외) |
| `docs/tool/signals-data.json` | Task 2 — 재생성 |
| `docs/tool/se/app.js` | Task 3 — 패턴 매칭(`matchCrossPatterns` 류) + 상세 파생 블록 |
| `docs/tool/se/ui.js` | Task 3 — 렌더 배선 |
| `docs/tool/index.html` | Task 4 — 기존 패턴 패널에 근거 접힘 표시 |
| `tests/` | 태스크별 테스트 |

---

### Task 1: core — `track_fund_usage`의 죽은 카탈로그 발췌 수정

**Files:**
- Modify: `dart_risk_mcp/server.py`(2905 부근)
- Test: core 테스트 스위트(기존 위치 확인 후 추가)

**요구사항:**

- `load_catalog_excerpt(["zombie_ma", "fake_new_biz"])` → 두 패턴의 `signal_sequence`에 든 taxonomy ID들로 교체(`CROSS_SIGNAL_PATTERNS`에서 가져와 하드코딩 중복 회피 — 방식은 구현자 판단, 단 `load_catalog_excerpt` 시그니처는 무변경).
- **회귀 테스트는 "발췌가 실제로 비어 있지 않음"을 검증한다** — 호출 존재만 grep하는 테스트 금지(그게 여덟 번째까지 못 잡은 원인).
- `load_catalog_excerpt`의 "알 수 없는 키 조용히 무시" 동작 검토: 시그니처·동작은 유지하되 함정을 주석/테스트로 다음 사람에게 문서화.
- 다른 `load_catalog_excerpt` 호출부 전수 검사 — 같은 실수가 또 있으면 함께 수정.
- 라이브 검증: 이상 신호가 발화하는 회사로 `track_fund_usage` 실행, 발췌가 실제 출력에 나타나는지 확인.

- [ ] **Step 1: 실패 테스트(발췌 비어 있지 않음) → 수정 → 통과 → 전체 회귀 → 커밋**

---

### Task 2: export — 근거 데이터 내보내기 (두 뷰어 공용 기반)

**Files:**
- Modify: `scripts/export_tool_data.py`
- Regenerate: `docs/tool/signals-data.json`
- Test: export 검증 테스트(기존 관례 확인 후)

**요구사항:**

- **먼저 `field_evidence` 9종 전체 원문을 실측 검사한다** — 인용문에 판정 어휘가 섞여 있는지. 결과에 따라: 전부 사실 서술이면 원문 그대로, 판정 어휘가 있으면 인용 범위 축소(왜곡 금지). 검사 결과와 결정을 보고에 기록.
- `build_signals_data()`의 patterns 항목에 근거 필드 추가: `field_evidence`(사례 인용) + 패턴 `description`(이미 있는지 확인 — 없으면 추가). **severity는 계속 제외**, docstring의 v0.8.5 근거 주석 유지·갱신.
- **SE가 필요로 하는 매핑 완비 확인**: SE-7의 신호 분류 결과(신호 키)에서 taxonomy ID로 가는 매핑이 `signals-data.json`에 이미 있는지 확인 — 없으면 이번에 추가(Task 3의 입력이 된다). 공개 뷰어가 지금 어떤 필드로 매칭하는지 읽고 같은 구조를 유지.
- `signals-data.json` 재생성. **공개 뷰어(index.html)와 SE 양쪽의 기존 로드 경로가 새 필드로 깨지지 않는지 실렌더/실구동으로 확인**(기능 추가 전에 데이터만 바뀐 상태로 무회귀).
- 재생성 동기화 방식 확인(수동/CI): 수동이면 "core 패턴 변경 시 재생성 필요"를 어디에 남길지 판단해 기록.

- [ ] **Step 1: field_evidence 원문 실측 검사 → 포함 방식 확정 (구현 전 필수)**
- [ ] **Step 2: 실패 테스트 → export 확장 + 재생성 → 통과 → 양쪽 뷰어 로드 무회귀 → 커밋**

---

### Task 3: SE — 패턴 상세 블록 이식 (주 목표)

**Files:**
- Modify: `docs/tool/se/app.js`(매칭 + 파생 블록), `docs/tool/se/ui.js`(렌더 배선)
- Test: `tests/se/test_se_app_js.py`

**요구사항:**

- **매칭**: 공개 뷰어와 동일 규칙(부분집합 매칭)을 app.js에 구현. 입력은 SE-7의 기존 공시 신호 분류 결과(새 분류기 금지) → 신호 키→taxonomy ID(Task 2가 완비한 매핑) → 탐지 ID 집합. **공개 뷰어와의 매칭 동치를 테스트로 고정**: 같은 신호 집합 입력에 두 구현이 같은 패턴 목록을 내는지(공개 뷰어의 매칭 함수를 같은 테스트에서 함께 구동할 수 있는지 확인 — index.html 인라인 스크립트라 어려우면 매칭 케이스 표를 공유 픽스처로 고정).
- **표시 — "더 자세하게"가 이 태스크의 핵심 요구**: 매칭된 패턴마다 ① 패턴명·설명 ② **이 회사에서 실제 탐지된 구성 신호 목록**(패턴의 signal_sequence 중 어떤 신호가 어떤 공시에서 잡혔는지 — 매칭의 근거를 공시 단위로 역추적 표시, 접수번호 링크 포함 가능하면) ③ 사실 근거(Task 2의 field_evidence — 금감원 보도자료 사례 인용) ④ 면책 문구. 공개 뷰어의 얇은 패널보다 한 단계 깊게 — 다만 severity·점수는 절대 없음.
- ②의 "공시 단위 역추적"은 SE-7 분류 결과의 데이터 형태를 먼저 확인하고 설계 — 신호 키만 있고 공시 연결이 없으면 가능한 수준(신호 키 나열)까지만 정직하게 표시(억지로 연결을 만들지 않는다).
- 매칭 없으면 블록 자체가 안 나온다(과시적 "이상 없음" 금지 — SE 관례).
- 표시 위치: 공시 목록/신호 요약 근처(SE-7 분류가 보이는 곳) — 실배선 지점은 구현자가 renderSection 구조 확인 후 결정.
- SE 관례 준수: 실렌더 테스트, `jsonb_sorted()` 픽스처, 판정 어휘 검사 통과.
- 라이브 검증: 제이스코홀딩스(capital_churn_anomaly 라이브 매칭 전례) 실 데이터로 매칭·상세 표시 확인. 미매칭 회사(삼성전자 등)에서 블록이 안 나오는 것도 확인.

- [ ] **Step 1: 실패 테스트(매칭 동치, 상세 표시 실렌더, 미매칭 시 침묵) → 구현 → 통과**
- [ ] **Step 2: 전체 회귀 → 커밋**

---

### Task 4: 공개 뷰어 — 기존 패턴 패널에 근거 보강 (부차)

**Files:**
- Modify: `docs/tool/index.html`
- Test: 공개 뷰어 테스트 관례 확인 후 동일 수준

**요구사항:**

- 기존 "PATTERN MATCH" 패널의 매칭된 패턴 아래 "실제 사례 근거(금감원 보도자료 등)" 접힘(details/summary 류) 표시 — Task 2가 내보낸 field_evidence 사용. **패널 재설계 금지** — 기존 구조·면책 문구 유지, 근거만 추가.
- SE(Task 3)와 표기 어휘·면책 문구를 일치시킨다(같은 사실을 두 화면이 다른 말로 부르지 않는다).
- 라이브 검증: 제이스코홀딩스로 공개 뷰어 실 구동 확인.

- [ ] **Step 1: 실패 테스트 → 구현 → 통과 → 전체 회귀 → 커밋**

---

## 마무리

- [ ] 전 태스크 후: 공개 뷰어·SE 실 데이터 화면 재검증(`#main[hidden]` 함정 유의)
- [ ] 전체 브랜치 최종 리뷰(Opus) — 특히 공개 뷰어 JS↔SE JS 매칭 동치를 독립 실행으로 대조(SE-12 전례)
- [ ] PR

## Self-Review

- **우선순위를 사용자 확인대로 재배열했다**: SE 상세 이식(Task 3)이 주 목표, 공개 뷰어 보강(Task 4)은 부차. export(Task 2)는 둘 다의 데이터 기반이라 선행. core 버그(Task 1)는 독립이라 맨 앞.
- **"더 자세하게"를 구체 요구로 번역했다**: 패턴명·설명 + 이 회사에서 실제 잡힌 구성 신호의 공시 단위 역추적 + 사례 인용 + 면책. 단 역추적은 SE-7 데이터 형태가 허용하는 수준까지만 — 억지 연결 금지를 명시했다.
- **severity 제외는 데이터 계층 설계를 유지** — 이 계획은 사실 인용만 더한다. field_evidence 원문 검사를 Task 2 첫 단계로 못박았다.
- **Task 1의 회귀 테스트 요구("비어 있지 않음")를 명시했다** — 여덟 번 반복된 죽은 배선의 공통점은 "호출 존재"만 검사한 테스트였다.
- **매칭 로직 개선(시간 순서)은 의도적 범위 밖** — 규칙 변경은 MCP 도구 3종·두 뷰어에 동시 파급되므로 별도 계획으로.
