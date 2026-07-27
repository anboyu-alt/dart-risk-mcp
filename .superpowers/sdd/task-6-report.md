# Task 6 보고서: 나머지 섹션 차트 (SE-4d, `dividends`·`debt_balance`·`disclosures`)

## 상태: DONE

이 계획(SE-4d 시각화)의 마지막 구현 태스크. 이전 리포트(`.superpowers/sdd/task-6-report.md`
구버전, "공시 원문 최소 가공")는 다른 회차(SE-4c)의 잔재였다 — 이번 작업으로
같은 파일을 SE-4d Task 6 내용으로 갈아썼다.

## 요약

세 섹션 모두 앞의 두 섹션(`insider_timeline`·`fund_usage`)과 형태가 달라 각각의
함정을 먼저 실측·코드로 확인한 뒤 구현했다. `docs/tool/se/ui.js`는 **전혀 건드리지
않았다** — `renderChart(wrap, key, records)`가 이미 `CHART_SPECS[key]` 조회만으로
완전히 일반화돼 있어, `app.js`에 스펙과 순수 함수만 추가하면 기존 렌더 경로가
자동으로 새 섹션을 그린다(diff가 이를 증명한다: 수정 파일이 `app.js`와
테스트뿐이다).

## 세 섹션 각각 차트를 만들었는가

- **`dividends` → 만들었다(부분).** `se`(항목)에 "주당액면가액(원)"(원)·
  "현금배당수익률(%)"(%)·"현금배당금총액(백만원)"(백만원)이 한 목록에 섞여
  있다(alotMatter 실측 형태, `dart_client.py`의 `detect_dividend_drain`이 이미
  "현금배당금" 문자열 필터로 이 혼재를 다루고 있었다). 원/%를 같은 축에 그리면
  `financials`를 뺀 것과 같은 부류의 거짓말이 되므로, **끝이 정확히 "(원)"인
  항목만** 계열로 만든다(`groupFilterSuffix: "(원)"`, `name.slice(-suffix.length)`
  비교 — `indexOf`였다면 "(백만원)"도 "원"을 포함해 새어 들어왔을 것이다). 제외된
  항목은 차트에서만 빠지고 표(`block.records`)에는 그대로 남는다.
- **`debt_balance` → 만들었다.** `by_kind`가 dict({종류: {total,
  maturity_under_1y}})라 레코드 리스트가 아니다 — `normalizeDebtByKind`로 종류를
  `debt_kind` 열로 뒤집어 레코드화하고(`normalizeRoster`와 같은 패턴), `label()`로
  종류 이름을 미리 한국어로 바꿔 저장했다(표·차트 x축에 `"corporate_bond"`가 그대로
  노출되지 않도록). `sectionBlocks`에 `d===0 && key==="debt_balance" && k==="by_kind"`
  게이트를 추가해 이 하나의 dict만 특수 처리한다 — 기존에 종류마다 조각나던 1행
  표 5개를 종류를 나란히 비교하는 표 1개로 바꿨다(값이 사라지는 변경이 아니라
  더해지는 변경: `total`·`maturity_under_1y`는 그대로 남고 비교 가능성만 늘었다).
- **`disclosures` → 만들었다(월별 집계, 표는 원본 유지).** `chartData`에
  `spec.monthlyCountOf`를 추가해 `rcept_dt`를 6자리(YYYYMM)로 묶어 **건수만** 센다
  (`monthlyCounts`). 순위·강조는 만들지 않는다 — 계열은 "건수" 하나뿐이고, 색은
  다른 차트와 똑같이 `--c0`~`--c8` 순환색이다(값에 따라 바뀌는 색 없음, `--red`
  미사용). **집계는 `chartData` 내부 파생값일 뿐, `sectionBlocks`가 만드는 표와
  `block.records`는 개별 공시 건수 그대로다** —
  `test_disclosures_table_records_stay_individual_not_aggregated`가 이를 직접
  확인한다(3건 입력 → 표 3행, 차트는 2개월로 집계).

## 구현 내용

### `docs/tool/se/app.js`

1. **`CHART_SPECS`에 3개 스펙 추가** — `dividends`(line, groupBy="se" +
   groupFilterSuffix), `debt_balance`(bar, series=[total, maturity_under_1y]),
   `disclosures`(bar, monthlyCountOf="rcept_dt"). 셋 다 `xScale: "category"`
   (기존 `test_no_spec_uses_a_time_scale`이 모든 스펙에 이 값을 강제한다).
2. **`chartData`에 두 가지 일반 확장을 추가**했다(섹션 전용 특수 코드가 아니라
   스펙 필드로 켜지는 범용 기능이라 기존 `insider_timeline`/`fund_usage`는
   영향받지 않는다):
   - `spec.groupFilterSuffix`: groupBy 계열 중 이 접미어로 끝나지 않는 이름은
     건너뛴다.
   - `spec.monthlyCountOf`: 레코드를 `monthlyCounts()`로 먼저 집계하고,
     `x:"month", series:[{key:"count"}]`인 파생 스펙으로 바꿔 기존 series 경로를
     그대로 재사용한다(새 렌더 분기 없음).
3. **`normalizeDebtByKind(value)`** 신설(`normalizeRoster` 패턴 재사용).
4. **`monthlyCounts(rows, field)`** 신설 — 월 단위 건수 집계 순수 함수.
5. **`axisLabel`에 6자리(YYYYMM) 케이스 추가** — "202604" → "2026.04". 8자리·
   하이픈 패턴보다 뒤에 둬서 기존 두 케이스와 겹치지 않게 했다.
6. **`sectionBlocks`의 `nestedKeys` 루프에 debt_balance 전용 게이트 추가**
   (executive_roster와 같은 depth-0 + key 게이트 방식 — 하위 재귀 호출에는 key가
   전달되지 않으므로 다른 섹션의 우연한 `by_kind`나 깊이>0인 `by_kind`는 영향받지
   않는다).
7. **`LABELS`에 `debt_kind: "채무 종류"` 추가** — 기존 라벨과 충돌 없음
   (`test_no_label_collides_with_a_different_raw_key`로 확인).
8. `module.exports`에 `normalizeDebtByKind`·`monthlyCounts` 추가.

### `docs/tool/se/ui.js`

**수정 없음.** `renderChart`가 이미 `CHART_SPECS[key]`만으로 완전히 일반화돼
있어 새 스펙을 추가하는 것만으로 기존 렌더 경로(`renderSection` →
`renderChart(el, key, block.records)`)가 자동으로 새 차트를 그린다.

## 테스트

`tests/se/test_se_app_js.py`에 24건 추가(226 → 250 in 파일 자체, 전체
1138 → 1162):

- `TestNormalizeDebtByKind`(4) — 순수 함수: 한국어 라벨 변환, 미등록 종류
  원본 보존, 비객체 입력 방어, 종류 값이 dict가 아닐 때 방어.
- `TestDebtBalanceWiredIntoSectionBlocks`(4) — `sectionBlocks(value, 0,
  "debt_balance")` 실제 진입점: 종류가 표 하나로 합쳐지는지, 스칼라 필드
  (year/total)가 살아있는지, key가 다르면 특수 경로를 안 타는지, depth>0인
  `by_kind`는 영향 없는지.
- `TestMonthlyCounts`(4) — 월 집계 순수 함수: 기본 집계, 하이픈/숫자 두 형태
  동일 취급, 짧거나 없는 값 스킵(0으로 세지 않음), 빈 입력.
- `TestChartDataForDividendsDebtDisclosures`(9) — `chartData` + 3개 스펙:
  dividends 원 단위만 필터링·백만원 오탐 방지·연도 정렬·전량 필터 시 null,
  debt_balance 정규화 레코드로 차트·비정규화 dict는 null, disclosures 월별
  집계·유효 날짜 없으면 null·**표는 집계 안 됨**.
- `TestChartRenderExecution`(3, 기존 클래스에 추가) — `_CHART_RENDER_HARNESS`를
  확장해 실제 `renderSection` → `renderChart` → `Chart` 생성자 호출까지
  end-to-end로 확인(카운트 스냅샷 before/after로 "차트가 실제로 생겼는지"를
  직접 검증 — 안 그러면 이전 차트의 낡은 참조를 잘못 통과시키는 함정이 있다).

## 뮤테이션 검증

3곳을 각각 `if (false && ...)`로 무력화한 뒤 관련 테스트만 돌려 실패를
확인하고 원복했다:

1. **`groupFilterSuffix` 필터를 무력화** → dividends 관련 4건 즉시 실패
   (퍼센트 항목이 섞여 들어옴, 전량 % 케이스에서 null 대신 차트가 생김).
2. **`debt_balance` sectionBlocks 게이트를 무력화** → 2건 실패
   (`test_debt_balance_key_combines_by_kind_into_one_table`,
   `test_debt_balance_chart_reads_the_normalized_by_kind_records` — 표가
   다시 조각나고 렌더 경로에서 차트가 아예 안 생김). `chartData` 자체를
   `normalizeDebtByKind` 결과로 직접 부르는 순수 함수 테스트는 이 게이트와
   무관하므로 실패하지 않음 — 계층이 의도대로 분리돼 있음을 재확인했다.
3. **`monthlyCountOf` 처리를 무력화** → 2건 실패(labels가 None, 렌더 경로에서
   차트 카운트 불변).

세 뮤테이션 모두 확인 후 원복, `python -m pytest tests/ -q`로 1162 passed
재확인.

## 검증 결과

```
python -m pytest tests/se/test_se_app_js.py -q
226 passed  (수정 전, 뮤테이션 확인용 개별 실행 포함 총 250개 케이스 존재)

python -m pytest tests/ -q
1162 passed, 46 subtests passed
```

기준선 1138 + 신규 24건 = 1162로 정합. 회귀 없음.

## 회귀 영향 분석

- 수정 파일: `docs/tool/se/app.js`(CHART_SPECS 3종 추가, chartData 확장 2건,
  normalizeDebtByKind·monthlyCounts 신설, axisLabel 확장, sectionBlocks
  게이트 추가, LABELS 1건 추가), `tests/se/test_se_app_js.py`. **`ui.js`
  무변경**, `dart_risk_mcp/` core 무변경, `se_server/` API 계약 무변경(순수
  프론트엔드 소비 작업 — BLOCKED 사유 없음).
- **기존 스펙 하위 호환**: `groupFilterSuffix`·`monthlyCountOf`는 스펙에
  해당 필드가 없으면(`undefined`) 조건이 거짓이 되어 기존 `insider_timeline`
  (`groupBy` 사용, `groupFilterSuffix` 없음)·`fund_usage`(`series` 사용,
  `monthlyCountOf` 없음)는 코드 경로가 전혀 바뀌지 않는다 — 기존 차트
  테스트 전량(`TestChartData` 원본 케이스들) 무변경으로 통과 확인.
- **`sectionBlocks`의 debt_balance 게이트는 depth 0 + key==="debt_balance"로만
  발화** — 기존 `test_mixed_flat_and_nested_keeps_both`(키 없이 호출, 일반
  dict-of-dicts 펼치기 검증)는 그대로 통과한다(이 테스트는 key를 넘기지
  않으므로 게이트 조건이 항상 거짓).
- **라벨 충돌 없음**: `debt_kind: "채무 종류"`는 기존 "종류별 잔액"·"주식
  종류"와 겹치지 않는다 — `test_no_label_collides_with_a_different_raw_key`
  통과로 확인.
- `git add -A` 사용 안 함(저장소 루트 `nul` 잔재 회피) — `docs/tool/se/app.js`
  와 `tests/se/test_se_app_js.py` 두 파일만 개별 `git add`.
- 외부 CDN·빌드·npm 의존성 추가 없음. 데이터가 섞인 `innerHTML` 등 없음(이번
  태스크는 `app.js` 순수 함수만 다뤄 DOM API를 아예 건드리지 않았다). 점수·
  등급·판정 어휘 없음 — disclosures 차트는 "몇 건"만 말하고 "몰렸다"는 말하지
  않는다.

## 우려사항

- **dividends의 "(원)" 필터는 실 API 응답으로 검증하지 못했다**(이 환경에 실
  DART API 키 접근이 없다, `task-6-brief.md`의 field-inventory에도 `se`의
  전체 값 목록은 없고 예시 하나뿐이었다). `dart_client.py`의
  `detect_dividend_drain`이 이미 "현금배당금" 부분 문자열로 이 혼재를
  다루고 있다는 사실과, DART `alotMatter` API의 공개 필드 관례(주당액면가액·
  주당순이익·주당 현금배당금은 "(원)", 총액류는 "(백만원)", 수익률류는
  "(%)")를 근거로 접미어 규칙을 정했다 — `scripts/regen_goldens.py`가 실
  API로 골든을 재생성할 때 `se` 실측값 전체를 한 번 확인하는 것을 권장한다.
- **debt_balance 표 구조를 바꿨다**(5개 조각 표 → 1개 비교 표). 이전 형태를
  기대하던 다른 코드/문서가 있다면(현재 저장소 검색으로는 없음) 영향받을 수
  있다.
