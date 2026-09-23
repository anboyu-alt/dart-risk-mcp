# 뷰어 「공시와 시장」 차트 — 구현 계획

스펙: `docs/superpowers/specs/2026-09-23-viewer-market-chart-design.md`. 브랜치 하나·PR 하나(파일이 갈려 병렬 작업 가능: 릴레이 3곳 ↔ 뷰어).

## 작업 A — 릴레이 지수 2종 (core 상수 + 3곳 + 테스트)

1. `dart_risk_mcp/core/krx_client.py`
   - `KRX_INDEX_BASE = "https://data-dbg.krx.co.kr/svc/apis/idx"`
   - `KRX_INDEX_API_IDS = {"Y": "kospi_dd_trd", "K": "kosdaq_dd_trd"}` · `KRX_INDEX_NAMES = {"kospi_dd_trd": "코스피", "kosdaq_dd_trd": "코스닥"}`
   - `_normalize_index_row(date8, raw) -> {"date", "close"(CLSPRC_IDX), "fluc_rt"(FLUC_RT), "mktcap"(MKTCAP)}` — `_to_number` 재사용. fetch 함수는 만들지 않는다.
   - `tests/fixtures/api/krx_response_keys.json`의 `apis`에 `kospi_dd_trd`·`kosdaq_dd_trd`(basDd 20260918 · n_rows 54/40 · fields 12종 · 「코스피」/「코스닥」 행 1개씩 samples). `test_no_dead_fields`가 걸리면 그 픽스처 경로로 해결(우회 금지).
2. `api/krx.js` — `ALLOWED_APIS`에 지수 2종. api → `{base, kind}` 표(`sto`/`idx`). 지수면 `isu`를 요구하지 않고(있어도 무시) `IDX_NM === KRX_INDEX_NAMES[api]` 행 하나를 `normalizeIndexRow`로 돌려준다. 빈 배열 → `{ok, found:false, empty:true}` 그대로.
3. `relay/worker.js` — 같은 변경(`KRX_ALLOWED_APIS`·`krxNormalizeIndexRow`).
4. `scripts/dev_relay.py` — `_KRX_ALLOWED_APIS |= set(KRX_INDEX_API_IDS.values())`, 지수 분기는 core `_normalize_index_row`·`KRX_INDEX_BASE`를 import해 쓴다.
5. `tests/test_viewer_krx_relay.py` — 세 곳 허용 api = core 종목 2 + 지수 2 · 지수 요청은 `isu` 없이 200 · `IDX_NM` 정확 일치(「코스피 (외국주포함)」을 고르지 않는다) · 정규화 행이 core `_normalize_index_row`와 일치 · `no-store`·서버 키 0 유지.

## 작업 B — 뷰어 차트

6. 상수: `KRX_CALL_BUDGET` 120 → 320, `KRX_INDEX_CALL_BUDGET = 260`, `KRX_ROWS_MAX = 6000`(리터럴 3000 두 곳 교체), `KRX_EVENT_MAX` 3 → 12, `KRX_CHART_DAYS = 365`.
7. `krxFetchSeries`에 `budget` 옵션(기본 `KRX_CALL_BUDGET`) — 지수 조회가 같은 함수를 쓴다. 지수 캐시 키는 `${api}|${d8}|IDX`(isu 자리에 상수). `krxGet`은 지수 api면 `isu`를 보내지 않는다.
8. 순수 함수 `marketChartModel(rows, idxRows, events, opts)`:
   - 입력 rows(종목, 오름차순, `gap_before` 포함), idxRows(지수), events(`pickMarketEvents` 결과 + `priority`), opts `{startDd, endDd, sectChanges, breaks}`.
   - 출력 `{days:[{date, close, volume, gap}], idx:[{date, value}|null], markers:[{date, x-index, label, count, priority, rcept, origDate, shifted}], breaks, haltBands:[{from,to,n}], sectMarks, xTicks:[{index,label}], yTicks, volTicks, yMin,yMax, volMax, uncoveredDays}`.
   - 지수 정규화: 구간 경계 = 창 시작 + 각 `breaks[].date`. 구간 첫 거래일 t0에서 `stock.close[t0] * idx[t]/idx[t0]`. 종목·지수 중 하나가 없는 날은 null(선 끊김).
   - 마커의 거래일 배치: 접수일 ≥ 인 첫 거래일(`eventWindowFacts`와 같은 규칙), 창 밖이면 버리고 `droppedMarkers`로 센다.
   - haltBands: `volume === 0` 연속 구간.
9. 순수 함수 `marketChartSVG(model, opts)` → 문자열. viewBox 760×300(가격 200 + 거래량 70 + 축 30). 선 2px `--tx`, 지수 1.5px `--dim`, 거래량 막대 `--faint`, 격자 1px `--line` 실선, 조정일·소속부 점선 `--dim2`, 거래량 0 띠 빗금 패턴, 마커 `--amber`(◆●○, 2px 표면 링 `--panel`), 텍스트 `--dim` 11px, `tabular-nums` 축. 마커는 `<a href=dartUrl>` + `<title>`. `data-i`로 십자선 대상.
10. 호버: `attachMarketChartHover(container, model)` — `pointermove`로 가장 가까운 거래일 인덱스를 잡아 `<line class="mkt-xhair">` 이동 + `.mkt-tip`(textContent로 채움). `pointerleave`로 숨김. 마커 `focus`도 같은 툴팁.
11. `loadMarketReaction` 재편: 시장 판별 → 종목 시계열(`startDd = 창 시작 − 100일`, `endDd = 오늘`) → **차트 먼저 그림**(지수 null) → 지수 시계열(창 안) → 지수 덧그림(모델 재계산 후 SVG 교체, 호버 재부착). 진행 문구 「종목 N/M거래일 · 지수 N/M」. 스캔 창이 365일을 넘으면 최근 365일만 + 고지.
12. `marketReactionHTML`: 표 위에 차트 + 범례 + 고지, 표는 12건, 「관찰 N건 중 최근 12건 · K건 생략」(`pickMarketEvents(events, KRX_EVENT_MAX)`가 자르므로 전체 수를 따로 받아 적는다). 절 제목 「MARKET REACTION — 공시와 시장 (1년)」, 펼침 문구 갱신.
13. CSS: `.mkt-wrap{position:relative}` `.mkt-tip` `.mkt-xhair` `.mkt-legend`. `.deepgrid` 트랙 폭에서 SVG `width:100%`.

## 작업 C — 테스트·문서

14. `tests/test_viewer_market_chart.py`(신규): `marketChartModel` node 하네스 — 빈틈·휴장 접수 마커 이동·같은 날 묶기·거래량 0 띠·소속부 표지·조정일 구간별 지수 정규화(분할 전후 지수가 종목에 다시 맞는다)·지수 없음·창 밖 마커 dropped. `marketChartSVG` — 태그 균형·판정어 0·업다운 색 없음·마커 `<a href>`·`<title>`·범례 존재·격자 점선 없음.
15. `tests/test_viewer_market_panel.py` — 상한 12·「K건 생략」 고지·예산 상수·캐시 6000·펼침 문구.
16. `tests/test_viewer_notice_facts.py` — 층① 앵커 「${...}일 미조회」·「최근 ${KRX_EVENT_MAX}건 · ${...}건 생략」, 층④ `.slice`.
17. `tests/test_viewer_twin_parity.py` — 새 함수가 core 이름과 짝지어지지 않는지(`Model`/`SVG` 접미) 확인만.
18. `docs/DEFERRED-DECISIONS.md` 17 → 처리됨(병기 선택지, 이 PR). `CLAUDE.md` 뷰어 절에 항목 추가(마커 인코딩 실측·정규화 규칙·예산). `README`의 뷰어 설명 한 줄.
19. 라이브: 로컬 릴레이 + 프로덕션 릴레이(relay override) — 코아스·CSA 코스믹·삼성전자 스크린샷, 콘솔 오류 0, 지수 선이 종목 시작점에 맞는지·분할일 뒤 다시 맞는지.
