# Task 6 보고서: 최대주주 변동현황·임원 자기주식 — 빈 표 의미 없음 수정

> 이 파일의 이전 내용은 다른 계획(SE-4d, "나머지 섹션 차트")의 Task 6
> 보고서였다. 이번 계획의 `task-6-brief.md` 지시에 따라 같은 경로에 새
> 보고서로 덮어쓴다(이 저장소에서 반복된 관례 — task-2-report.md 상단
> 주석 참고).

## 상태: DONE

## 원인 규명 (실측)

브리프가 이미 지목한 원인(오케스트레이터가 사전에 직접 API를 호출해 확인한
결과)을 `.env.local`의 `DART_API_KEY`로 다시 직접 재현했다 —
`hyslrChgSttus`·`tesstkAcqsDspsSttus`를 엔켐·삼성전자로
`bsns_year=2025`·`reprt_code=11011`(2025 사업보고서)로 호출:

- **엔켐 `hyslrChgSttus`**: 1건. `rcept_no`·`corp_cls`·`corp_code`·
  `corp_name`·`stlm_dt` 밖의 모든 필드(`change_on`·`mxmm_shrholdr_nm`·
  `posesn_stock_co`·`qota_rt`·`change_cause`·`rm`)가 **문자열 `"-"`** —
  null도 빈 문자열도 아니다.
- **삼성전자 `hyslrChgSttus`**: 1건, 엔켐과 똑같이 전부 `"-"` (삼성전자도
  이 분기엔 변동이 없다 — 회사 문제가 아니라 그 분기에 보고할 변동이
  없다는 뜻).
- **삼성전자 `tesstkAcqsDspsSttus`**: 18건, 다수 행에 실제 수량(`bsis_qy`
  `29,700,000` 등)·구분(`stock_knd` "보통주" 등)이 있다.

**핵심 발견 — 브리프의 셋 중 1번(DART가 실제로 빈 값을 준다)이 맞지만, "빈
값"의 실제 형태가 null/빈 문자열이 아니라 DART 관행 표기 `"-"`였다.**
`formatValue`가 `"-"`를 그대로 `"-"`로 보여주고, 기존 `dropAllEmptyColumns`는
`formatValue(...) === ""` 기준이라 `"-"`인 열을 걸러내지 못했다 — 그 결과
"전부 `-`"인 행이 마치 채워진 데이터처럼 표에 남았다. 이것이 사용자가
"의미를 알 수 없다"고 지적한 진짜 원인이다. 코드가 필드를 잘못 읽거나
렌더가 열을 빠뜨린 것이 아니었다(브리프의 2·3번 아님).

## 판단 기준

1. **"실데이터 없음" 판정**: 값이 `null`/`undefined`/공백 문자열/문자열
   `"-"`(trim 후) 중 하나면 `isNoDataMarker(v)`가 참(app.js 신규). 기존
   `dropAllEmptyColumns`의 열 제거 기준을 이걸로 교체 — 0과 `false`는
   문자열이 아니므로 여전히 보존된다.
2. **"메타 전용 레코드" 판정**: `META_ONLY_KEYS = {rcept_no, corp_cls,
   corp_code, corp_name, stlm_dt, bsns_year, reprt_code}` 밖의 키가 모든
   레코드에서 전부 `isNoDataMarker`면 `isMetaOnlyRecords(records)`가 참.
   이 목록은 브리프가 준 후보를 그대로 확정한 게 아니라, 위 실측 응답 +
   `docs/superpowers/plans/2026-07-27-se-4c-field-inventory.json`을 직접
   대조해 "섹션마다 반복되지만 그 자체로는 사건을 서술하지 않는" 필드만
   추린 것이다 — `rcept_dt`(접수일자)는 다른 source(elestock 등)에서는
   실제로 "언제 일어난 일인지"를 서술하는 값이라 포함하지 않았다(그리고
   hyslr_chg·exec_treasury 실측 응답에는 애초에 나타나지도 않는다).

## 어디에 붙였는지

- `docs/tool/se/app.js`
  - `isNoDataMarker(v)` 신규 — DART `"-"` 관행 표기 판정.
  - `dropAllEmptyColumns`가 `formatValue(...) === ""` 대신
    `isNoDataMarker(r[k])`를 쓰도록 교체(기존 null/빈 문자열 처리를
    포함하는 상위 집합이라 회귀 없음).
  - `META_ONLY_KEYS`·`isMetaOnlyRecords(records)` 신규.
  - `sourceGroupedBlocks`(insider_timeline이 쓰는, **source 필드 기준**의
    범용 표 분리 함수 — hyslr_chg·exec_treasury 문자열에 하드코딩된 게
    아니다): `dropAllEmptyColumns`로 정리한 뒤 `isMetaOnlyRecords`가
    참이면 `block.note = "해당 기간에 보고된 내역이 없습니다."`를
    붙인다. **표 자체는 지우지 않는다** — 남은 메타 필드(`rcept_no`
    포함)로 만든 작은 표가 그대로 붙어, 접수번호를 클릭해 원문을 열 수
    있는 기존 배선(`tableEl`의 `rcept_no` 클릭 처리)이 그대로 작동한다.
- `docs/tool/se/ui.js`
  - `blockEl(block)`이 `block.note`를 표/텍스트보다 먼저 `<p class="note">`
    로 그린다(표와 배타적이지 않음 — 표는 그대로 두고 문구만 얹는다).

## "특정 섹션에만 하드코딩하지 말라" 반영

`isNoDataMarker`·`META_ONLY_KEYS`·`isMetaOnlyRecords` 모두 섹션 키를 검사하지
않는다 — 값의 **모양**만 본다. 적용 지점(`sourceGroupedBlocks`)도 `source`
필드가 있는 레코드 배열이면 어떤 섹션이든 타는 기존 범용 경로다
(`recordsHaveSourceField` 게이트 — insider_timeline 외 다른 섹션이 앞으로
`source`를 쓰게 되어도 그대로 동작).

`distress` 섹션(0건일 때)도 별도 확인했다 — `fetch_distress_events`는 이벤트가
없으면 `"-"`로 채운 자리표시 레코드가 아니라 **빈 배열 `[]`** 자체를 준다.
`sectionBlocks`의 `toRecords([])` → `null` → `tableLayout([])` → `null`이라
`blocks.length === 0`이 되고, `renderSection`이 이미 기존 "표시할 데이터가
없습니다."를 정직하게 보여준다 — 이번 변경 없이도 이미 올바르다. 브리프의
"distress도 비슷한 처지" 언급은 (실측 결과) distress 자체에 결함이 있다는
뜻이 아니라, 이번 수정을 hyslr_chg·exec_treasury 문자열에 매지 말라는
일반화 요구로 해석해 그렇게 구현했다.

## 검증

- TDD: `tests/se/test_se_app_js.py`에 `TestMetaOnlyRecordsGetNoDataNote`
  (4건)·`TestMetaOnlyNoteRendersInDom`(2건) 추가, 총 6건 신규. 구현 전
  실행 → 예상대로 2건 실패(나머지 4건은 "이미 옳아야 하는" 대조군이라
  구현 전에도 통과) 확인 후 구현.
- **픽스처는 실측**이다 — 엔켐 `hyslrChgSttus`(전부 `"-"`)·삼성전자
  `tesstkAcqsDspsSttus`(실수량 포함) 두 개는 2026-07-28 실제 API 응답을
  그대로 테스트에 옮겼다. 세 번째(값이 있는 `hyslrChgSttus`)는 사용자가
  화면에서 실제로 본 값(17.40%·"기존 최대주주의 시간외 장외매도로 인한
  변경")을 같은 스키마로 재현한 대조군이다.
- 되돌림 검증: `git stash`로 app.js·ui.js만 되돌려 신규 6건 중 정확히
  2건(`note` 발화를 직접 검증하는 두 건)이 실패하는 것을 확인 후 복원.
- 전체 스위트: `python -m pytest tests/ -q` → **1241 passed**(기준선 1235 +
  신규 6건, subtests 46개 그대로). 기존 insider_timeline 테스트
  (`TestInsiderTimelineSourceSplit` 전체)도 그대로 통과 — `dropAllEmptyColumns`
  판정 기준 교체가 null/빈 문자열 기존 동작을 깨지 않았다.

## 하위 호환 · 회귀 영향

- `dropAllEmptyColumns`의 판정 기준을 `formatValue(...) === ""`에서
  `isNoDataMarker(r[k])`로 바꿨다 — 후자는 전자의 상위 집합(null·빈
  문자열은 그대로 포함하고 `"-"` 하나만 추가)이라, 기존에 이 함수가
  걸러내던 열은 여전히 걸러내고 새로 `"-"`만 채워진 열도 추가로 걸러진다.
  숫자 0·불리언 `false`는 문자열이 아니므로 영향 없음.
- `sourceGroupedBlocks`가 돌려주는 block 객체에 `note` 키가 추가될 수
  있다 — 기존 호출부(`renderSection`)는 `block.table`·`block.records`만
  읽던 자리에 새 선택적 키가 늘어난 것뿐이라 하위 호환.
- `blockEl`에 `block.note` 처리가 추가됐지만 기존 블록(`note` 없음)은
  분기 자체가 스킵되므로 영향 없음.
- `se_server` API 계약·`dart_risk_mcp/` core는 건드리지 않았다.
- `git add -A` 사용 안 함(저장소 루트 `nul` 잔재 회피) — 수정 파일만
  개별 `git add`.
