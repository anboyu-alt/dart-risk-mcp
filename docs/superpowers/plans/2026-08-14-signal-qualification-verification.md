# 신호 한정층 — 검증 현황 (2026-08-15, Task 11)

이 문서는 `docs/superpowers/specs/2026-08-14-signal-qualification-design.md`(설계)와
`docs/superpowers/plans/2026-08-14-signal-qualification.md`(구현 계획, Task 1~11)로
구현된 신호 한정층(`dart_risk_mcp/core/qualifiers.py` + `server.py` 배선 +
`docs/tool/index.html` 이식)이 **무엇으로 검증됐고 무엇이 아직 검증되지 않았는지**를
정직하게 기록한다.

이 워크트리(`actor-network-duplicate-entities-d0687a`)에는 `DART_API_KEY`가 없다
(`tmp/_apikey.txt` 부재, 환경변수 미설정). 그래서 실제 DART 응답으로 끝까지 도는
경로(MCP 도구 종단 실행, 골든 재생성, 프로덕션 배포 스캔)는 이번 라운드에서
**시도조차 하지 않았다** — 키가 없는 상태에서 만든 "성공" 기록은 검증이 아니라
조작이기 때문이다.

---

## 1. 라이브로 검증됨 (실제 DART 데이터)

| 검증 항목 | 무엇이 증명했는가 |
|---|---|
| `flr_nm`/`rm` 필드가 `/api/list.json` 응답에 실존 | 컨트롤러가 `korean-dart` MCP의 `dart_raw(operation="list")`로 직접 조회, 2026-08-14, 삼성전자(`00126380`) 20260410~20260425, 응답 7건 전수. 응답 키: `corp_code, corp_name, stock_code, corp_cls, report_nm, rcept_no, flr_nm, rcept_dt, rm` |
| R1(제출인이 회사와 다르면 강등)이 실환경에서 걸리는 사례 | 같은 7건 중 `주식등의대량보유상황보고서(일반)` ×3(`flr_nm="삼성물산"`), `임원ㆍ주요주주특정증권등소유상황보고서` ×2(`flr_nm="임지운"`/`"김민우"`) — 전부 `corp_name`("삼성전자")과 다른 제출인 |
| R2(결과보고서 → 사후 국면)가 실환경에서 걸리는 사례 | 같은 7건 중 `자기주식취득결과보고서`(`flr_nm="삼성전자"`, R1 통과 후 R2로 강등) |
| **계획 결함 발견·수정**: R1b가 `if not filer:` 가드 안에 있어 `flr_nm`이 존재하는 실환경에서 실행되지 않던 문제 | 같은 7건 중 `최대주주등소유주식변동신고서`(`flr_nm="삼성전자"`, 회사 자신) — R1으로는 안 걸리는데 지분 보고 3종 중 하나라 사건 공시가 아님. 가드를 제거하고 "지분 보유·변동 신고서입니다" 사유로 통일했다(`dart_risk_mcp/core/qualifiers.py`의 `_demotion_reason` R1b 블록, 코드 내 주석에도 이 실측을 남김) |
| `report_nm`에 후행 공백이 실제로 붙어 온다 | 같은 조회에서 `"현금ㆍ현물배당결정              "` 관찰(부수 관찰, 파서가 공백 제거하므로 동작 영향 없음) |
| `rm` 값 실측 | `"공"`(공정위) · `"유"`(유가) · `""` 세 값 관찰(이번 범위에서 `rm`은 사용하지 않음) |

이 표의 7건은 `docs/superpowers/plans/2026-08-14-signal-qualification.md` 하단
"검증 로그 → Task 1"에도 동일하게 기록돼 있다.

---

## 2. 단위 테스트로만 검증됨

- `tests/test_qualifiers.py` — 42개 케이스, 전부 **수기로 추적한 실측 공시 제목**을
  입력으로 쓴다(합성 dict 아님, 실제 DART 표기 그대로: `ㆍ`(U+318D) 포함 표기,
  "종속회사의주요경영사항"/"자회사의 주요경영사항" 공백 혼재 등). 하지만 이 테스트가
  검증하는 것은 **파서·규칙 함수의 순수 로직**이지, 이 제목들이 실제로 오늘 시장에
  존재한다는 것이 아니다 — 제목 문자열은 과거 실측을 손으로 옮겨 적은 것이고, 매 실행마다
  DART를 다시 조회하지 않는다.
- `tests/test_qualification_wiring.py` — Task 7이 골든 재생성 대신 작성한 대체 검증.
  `server.py`가 `qualify_signals`/`pick_headline`을 호출부에 올바르게 배선했는지
  (observed/procedural 분리, 헤드라인 후보 좁히기, 패턴 매칭 입력 제한)를 합성 이벤트
  리스트로 확인한다. 실제 MCP 도구 실행이 아니다.
- `tests/test_export_tool_data.py` — `signals-data.json`이 core 상수(`LABEL_OVERRIDES`,
  `DIRECTION_NOTES`, `AMBIGUOUS_SIGNAL_KEYS`, `confirm_markers` 등)와 값이 일치하는지만
  본다. 뷰어가 그 JSON을 브라우저에서 올바르게 렌더하는지는 별도 항목(§3).
- `tests/se/test_se_app_js.py` — 아래 §4 참고. 통과하지만 한정층을 검증하지 못한다.

---

## 3. 합성 브라우저 데이터로만 검증됨 (뷰어)

`docs/tool/index.html`의 한정층 렌더(Task 8~10)는 **실시간 DART 스캔이 아니라
합성 `buildResult` 호출**로만 검증됐다:

- Task 9: 삼성전자·아틀라스링크·헬릭스미스 3케이스를 흉내낸 합성 `report_nm`/`flr_nm`
  배열을 `buildResult()`에 직접 넣어 관찰/절차 두 층 렌더, 헤드라인 소멸, 카운터 일치,
  0건 안내 문구를 확인했다. 실제 회사명으로 스캔 버튼을 눌러 DART 응답을 받은 적은 없다.
- Task 10: `3PCA` 라벨 보정 행에서만 "원문 확인" 버튼이 뜨는지, 버튼이 안 뜨는 행에는
  안 뜨는지를 합성 2행(`"주요사항보고서(유상증자결정)"` / `"증권발행결과(자율공시)
  (제3자배정 유상증자)"`)으로 확인했다.
- 두 태스크 모두 `read_network_requests`로 스캔 시점 `/api/doc` 호출이 0건임을
  라이브로 확인했다(이 부분은 실제 네트워크 계측이므로 §1에 준하는 신뢰도) — 하지만
  스캔 자체가 합성 데이터 기반이라는 사실은 바뀌지 않는다.

**미실행**: 실제 `search_market_disclosures`류 스캔이나 뷰어의 실제 기업 검색 →
스캔 버튼 클릭 → 진짜 DART 응답 렌더 흐름은 이번 라운드에서 한 번도 돌지 않았다.

---

## 4. 원문 확인(document-confirm) — 성공 경로는 스텁, 실패 경로만 라이브

Task 10이 구현한 "원문 확인" 버튼(`confirmAllocation`)의 검증은 명확히 갈린다
(`.superpowers/sdd/2026-08-14-signal-qualification/task-10-report.md` 참고):

| 시나리오 | 검증 방식 |
|---|---|
| 스캔 시점 `/api/doc` 호출 0건 | **라이브** |
| 버튼이 라벨 보정된 행에만 렌더 | **라이브**(DOM 검사) |
| 클릭 → 실제 fetch → 정적 서버가 `/api/doc` 라우트를 못 찾아 **404** → 슬롯에 한국어 실패 안내, 라벨·tier 불변 | **라이브** — 단 "실패"가 검증된 것이지 "성공"이 아니다 |
| 클릭 → 원문에서 마커(제3자배정/주주배정/일반공모/주주우선공모)를 찾아 성공적으로 표시 | **스텁** — `setDocCache(rcept, {...})`로 `DOC_CACHE`에 합성 응답을 직접 주입해 캐시 히트 분기를 강제로 태운 것. 실제 DART 원문을 받아온 적 없음 |
| 캐시 히트 시 추가 네트워크 호출 0건 | 스텁으로 채운 캐시를 재사용하는 것을 라이브 계측(`read_network_requests`)으로 확인 — 계측은 라이브지만 캐시 내용 자체는 스텁 |

이유: 이 워크트리(정적 로컬 서버 `se-static-rooted`, 8932포트)에는 `/api/doc` 라우트가
없어 모든 fetch가 404로 떨어진다. 또한 `DART_API_KEY`가 없어 설령 릴레이가 있어도
성공 응답을 받을 수 없다. **"성공 시 렌더 로직이 옳다"는 것은 스텁으로만 증명됐고,
진짜 DART 원문에 저 4개 마커 중 하나가 실제로 그 표기 그대로 등장하는지는 확인되지
않았다.**

---

## 5. 전혀 실행되지 않음

### 5.1 7개 회사 회귀표 (골든 재생성 미실행)

설계 문서·계획의 골든 대조 표(회사별 현재 신호 → 기대 observed/procedural, 헤드라인
존속 여부)는 **한 번도 실행되지 않았다**:

| 회사 | 현재 신호 | 기대 observed | 기대 procedural | 헤드라인 |
|---|---|---|---|---|
| 아틀라스링크 | 36 | 21 | 15 | 유지 |
| 제이스코홀딩스 | 26 | 19 | 7 | 유지 |
| STX | 6 | 5 | 1 | 유지 |
| 삼성전자 | 8 | 2 | 6 | 없음(전부 ambiguous) |
| 셀트리온 | 32 | 10 | 22 | 경영권분쟁소송 |
| 두산 | 10 | 1 | 9 | 없음(전부 ambiguous) |
| 헬릭스미스 | 1 | 0 | 1 | 없음 → 0건 안내 문구 |

이 표의 "현재 신호" 열은 **한정층 도입 이전 골든 픽스처의 기존 값**이고, 기대
observed/procedural 열은 **설계 단계의 수기 추정치**다. `scripts/regen_goldens.py`를
돌려 실제 DART 응답으로 이 숫자들을 재현한 적이 없다 — 이 표 전체가 "무엇을 확인해야
하는가"의 사양이지 "확인됐다"는 기록이 아니다. `tests/fixtures/sample_outputs/`의
골든 파일은 이번 라운드에서 커밋되지 않았다(브리프 지시대로 의도적으로 건너뜀).

### 5.2 MCP 도구 종단 실행

`analyze_company_risk("아틀라스링크")`, `analyze_company_risk("삼성전자")`,
`build_event_timeline(...)` 등 MCP 도구를 실제로 호출해 "capital_backflow 패턴이
여전히 발화하는가", "절차·사후 보고 절이 15건으로 나오는가", "헤드라인이 사라지고
관찰 신호 2건으로 나오는가" 같은 계획의 검증 질문에 답한 적이 없다(브리프 Step 2,
`DART_API_KEY` 부재로 스킵 지시받음).

### 5.3 프로덕션 배포 확인

머지·배포 후 실제 URL(`docs/tool/index.html`이 서빙되는 프로덕션 도메인)에서 삼성전자·
아틀라스링크를 스캔해 `read_console_messages` 에러 0건과 스크린샷을 남기는 절차(계획
Step 3)도 실행하지 않았다 — 이 브랜치는 아직 머지·배포되지 않았다(브리프 지시대로
스킵).

---

## 6. 알려진 한계 — `docs/tool/se/app.js`에는 한정층이 없다

**이 항목은 향후 유지보수자가 반드시 알아야 한다.**

설계 문서 §12("이번 범위 밖")에 `docs/tool/se/` 반영이 명시적으로 제외돼 있다.
그 결과 `docs/tool/se/app.js`(SE — 인가제 심층 분석 웹 서비스)는 이번 신호 한정층을
전혀 이식받지 않았다 — `parseReportName`/`qualifySignals`/`pickHeadline`에 대응하는
어떤 코드도 없다.

**등가성 테스트(`tests/se/test_se_app_js.py`)가 통과하는 이유는 두 계층이 일치해서가
아니라, 현재 등가성 스위트의 픽스처가 단 하나도 강등 규칙(R1/R1b/R2/R3/R4/R5)을
트리거하지 않기 때문이다.** 즉 한정층이 존재하지 않는 `se/app.js` 쪽에서도 우연히
"전부 observed 취급"과 같은 결과가 나와 `index.html`(한정층 적용됨)의 출력과 겉보기
일치가 유지될 뿐이다. 이는 `.superpowers/sdd/2026-08-14-signal-qualification/
progress.md`의 Task 9 항목에 "KNOWN LIMITATION"으로 명시적으로 기록돼 있다:

> `docs/tool/se/app.js`에는 한정층이 없다(스펙 12절 비범위). 등가성 테스트가 통과하는
> 이유는 두 계층이 합의해서가 아니라 픽스처가 강등을 하나도 트리거하지 않아 한정층이
> no-op이기 때문. 강등되는 픽스처를 추가하면 의도된 divergence가 실패로 보인다.

**향후 유지보수자가 해야 할 일**:

1. `tests/se/test_se_app_js.py`에 강등 규칙을 트리거하는 픽스처(예: 대량보유상황보고서,
   자기주식취득결과보고서, `[기재정정]` 접두 등)를 추가하기 전에, 그 테스트가 무엇을
   비교하는지(패턴 매칭 블록 vs 렌더 전체) 먼저 확인한다. 추가하는 순간 `index.html`은
   해당 신호를 procedural로 접고 `se/app.js`는 계속 observed로 취급해 **의도된
   divergence가 테스트 실패로 나타난다** — 이것은 버그가 아니라 두 계층의 실제 차이가
   드러난 것이다.
2. `docs/tool/se/`에 한정층을 이식할지는 별도 설계·계획 문서로 다뤄야 한다(이번
   설계 문서 §12가 명시적으로 범위 밖으로 남겼다). 이식하지 않기로 한다면 그 결정과
   이유를 SE 쪽 문서에도 남겨, "왜 SE 사용자는 삼성전자를 스캔하면 오탐 8건을 그대로
   보는가"에 답할 수 있게 한다.
3. 이식하기로 한다면 `core/qualifiers.py`가 이미 순수 함수 2개(`parse_report_name`,
   `qualify_signals`)와 JSON export(`signals-data.json`의 `qualifier_rules`)로
   정리돼 있으므로, `docs/tool/index.html`(Task 8이 이미 이식한 JS 포트)을 그대로
   `se/app.js`에 옮기는 것이 가장 빠른 경로다.

---

## 7. 키가 확보됐을 때 실행할 체크리스트

`DART_API_KEY`(및 필요 시 `tmp/_apikey.txt`)가 준비되면, 이 순서로 §5의 미검증 항목을
좁힌다:

```bash
# 1. 골든 재생성 + 회귀 표 대조 (§5.1)
python scripts/regen_goldens.py
python -m pytest tests/test_golden_output_hygiene.py -v
git diff --stat tests/fixtures/sample_outputs/
# → 위 7개 회사 표의 observed/procedural 건수·헤드라인 존속 여부를 실측과 대조.
#   어긋나면 규칙이 과하거나 부족한 것이므로 원인을 찾을 때까지 커밋하지 않는다.

# 2. MCP 종단 실행 (§5.2)
# analyze_company_risk("아틀라스링크") — capital_backflow 패턴 발화 여부,
#   절차·사후 보고 15건 여부를 확인
# analyze_company_risk("삼성전자") — 헤드라인 소멸, 관찰 신호 2건 여부를 확인
# 두 출력 모두 점수·등급 문구가 없는지 재확인 (v0.8.5 hygiene)

# 3. 뷰어 실스캔 (§3)
# 로컬 또는 프로덕션 index.html에서 실제 기업명으로 스캔 버튼을 눌러
# read_console_messages 에러 0건, 관찰/절차 두 층·헤드라인·0건 안내가
# 합성 데이터가 아닌 실제 DART 응답으로도 동일하게 렌더되는지 확인

# 4. 원문 확인 성공 경로 (§4)
# 3PCA 라벨 보정 행에서 "원문 확인" 버튼을 눌러 실제 DART 원문에서
# confirm_markers(제3자배정/주주배정/일반공모/주주우선공모) 중 하나가
# 정말 그 표기로 등장하는지, markerPattern 매칭이 실물에서도 성립하는지 확인

# 5. 프로덕션 배포 확인 (§5.3) — 머지·배포 이후에만
# 실제 URL에서 삼성전자·아틀라스링크 스캔 → read_console_messages 에러 0건 +
# 스크린샷
```

---

*이 문서는 `.superpowers/sdd/2026-08-14-signal-qualification/task-11-brief.md`가
지시한 "Replacement step"으로 작성됐다. Step 2(MCP 종단 실행)·Step 3(프로덕션 확인)·
골든 재생성은 이 워크트리에 `DART_API_KEY`가 없어 스킵했다(브리프 명시 지시) — 이
문서가 그 공백을 대체한다.*
