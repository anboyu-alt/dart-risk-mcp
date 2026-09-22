# KRX Open API + KIND 시장경보 — 「공시 전후 시장 반응」 설계 (2026-09-22)

## 왜

이 도구는 DART 공시만 읽는다 — 「무슨 일이 있었는가」까지다. 불공정거래 신호는
**그 일 전후로 시장이 어떻게 움직였는가**와 붙여야 서는데, 시세·거래량·회전율은
레포에 **0줄**이다(2026-09-22 grep). 제작자가 KRX Open API 키(9종 승인 — 유가·코스닥
일별매매정보, 종목기본정보, 신주인수권증권·증서 매매, KRX·KOSPI·KOSDAQ 지수)를
갖고 있어 이를 붙인다.

**점수·등급은 여전히 매기지 않는다**(v0.8.5). 시장 반응은 **사실 블록**이다 —
임계값·「급등/급락/이상/과열」 같은 우리 어휘 없이 등락률·배수·회전율·일수만 적는다.
신호·패턴 입력으로 쓰지 않는다(제작자 결정 2026-09-22).

## 실측·문서로 확정한 사실

### KRX Open API

- 요청: `https://data-dbg.krx.co.kr/svc/apis/sto/{apiId}?basDd=YYYYMMDD`, 헤더
  `AUTH_KEY: <키>`. 페이지의 샘플 키로 두드리니 **401 JSON**
  `{"respMsg":"Unauthorized API Call","respCode":"401"}` — 호스트·경로는 확인됐고
  응답 본문이 JSON이라 실패 판별이 가능하다. 정상 응답은 `OutBlock_1` 배열(문서 기준).
- apiId: `stk_bydd_trd`(유가증권 일별매매정보) · `ksq_bydd_trd`(코스닥) ·
  `stk_isu_base_info` · `ksq_isu_base_info` · `sw_bydd_trd`(신주인수권증권) ·
  `sr_bydd_trd`(신주인수권증서). 마지막 셋은 이번 범위 밖.
- **하루 단위 · 시장 전체** 응답이다. 종목별 기간 조회가 없다 → 한 회사 1년 ≈ 245콜.
  그래서 **날짜별 시장 전체를 디스크에 캐시**하면 두 번째 회사부터 0콜이다.
- 약관(2025-12-26 시행): 제8조 ④ **키당 1일 10,000회** · 제6조 ② **비상업 목적** ·
  제10조 ③ 화면에 **「한국거래소 통계정보」** 명시 · **제11조 ② 제공받은 정보를 제3자에게
  제공할 수 없다**.
  → 공개 뷰어에 **운영자 키로 받은 시세를 싣지 않는다.** 뷰어는 사용자 본인 키 경로만
  (다음 PR). MCP는 사용자 기기에서 사용자 키로 돌므로 해당 없음.
- ⚠ **미측정**(키가 아직 환경에 없다): 콜당 지연 · 응답 크기 · 필드명 전수 · 휴장일
  응답 모양 · 코스닥 `SECT_TP_NM` 값 분포. 구현은 공개 명세의 필드명
  (`BAS_DD`·`ISU_CD`·`ISU_NM`·`MKT_NM`·`SECT_TP_NM`·`TDD_CLSPRC`·`CMPPREVDD_PRC`·
  `FLUC_RT`·`TDD_OPNPRC`·`TDD_HGPRC`·`TDD_LWPRC`·`ACC_TRDVOL`·`ACC_TRDVAL`·`MKTCAP`·
  `LIST_SHRS`)으로 쓰되, **키가 들어오면 0단계 실측으로 대조**하고
  `tests/fixtures/api/krx_response_keys.json`에 고정한다. 대조 전까지 그 픽스처는
  `"unverified": true`를 단다 — 「재지 않은 값을 실측이라 적지 않는다」.

### KRX Open API에 없는 것

관리종목·시장경보·불성실공시·조회공시·매매거래정지는 **이 API에 없다**(서비스 목록
전수 확인 — 지수·주식·증권상품·채권·파생·일반상품·ESG뿐). 이 중 넷은 DART
`list.json`이 거래소공시로 이미 담고 있고(1년 코퍼스: 불성실공시 337 · 매매거래정지
377 · 관리종목 201) 기존 신호(`INQUIRY`·`WATCH_ISSUE`·`DELISTING_RISK`·
`DISCLOSURE_VIOL`)가 잡는다. **빠진 것은 시장경보(투자주의·경고·위험)뿐** — DART
코퍼스 0건, KIND 웹에만 있다.

### KIND 시장경보 (실측 2026-09-22 — 비공식 웹 파싱)

- `POST https://kind.krx.co.kr/investwarn/investattentwarnrisky.do`, 폼
  `method=investattentwarnriskySub` · `forward` = `invstcautnisu_sub`(주의,
  `menuIndex=1`) / `invstwarnisu_sub`(경고, 2) / `invstriskisu_sub`(위험, 3) ·
  `startDate`/`endDate`(`YYYY-MM-DD`) · `currentPageSize` · `pageIndex` ·
  `orderMode=4` · `orderStat=D`. 헤더 `X-Requested-With: XMLHttpRequest`, `Referer`.
- **종목 필터는 `repIsuSrtCd="A"+종목코드` + `searchCodeType="char"`**만 먹는다.
  `searchCorpName` 단독은 필터하지 않는다(피델릭스로 실측 — 이름만 주면 49건 전부,
  코드를 주면 1건). 페이지 크기 5,000까지 받아진다(2MB).
- 행: 주의 = `번호|종목명|유형(지정사유)|공시일|지정일`, 경고·위험 =
  `번호|종목명|공시일|지정일|해제일`(해제 전 `-`). 열 이름은 응답 꼬리의
  `fn_InitTitle("번호,종목명,유형,공시일,지정일", …)`에 실려 온다 — 파서는 이것으로
  열 배치를 검증한다. 총 건수는 `전체 <em>4,900</em>건`.
- 결과 없음: `조회된 결과값이 없습니다.` 한 행. **창이 3년을 넘으면 본문 길이 0**
  (2025-08-18 시스템 부하 사유로 제한). 콜당 ~1.7초.
- 픽스처: `tests/fixtures/kind/*.html` 8종 + `README.json`(파라미터·건수).
- 주의 유형 실측 예: 매매관여과다종목 · 소수지점/계좌 · 소수계좌 매수관여 과다 ·
  상한가잔량 · **투자경고 지정예고**.

## 하지 않기로 한 것

| 후보 | 왜 안 하나 |
|---|---|
| 시장 반응을 신호·패턴 입력으로 | 임계를 정해야 하고 그게 곧 판정이 된다. 분포를 재고 나서 별도 판단 |
| 지수 대비 초과수익 | 지수 API는 승인돼 있으나 「시장 대비」는 해석 층이 하나 더 든다. 이연 |
| 신주인수권증권 매매 ↔ 메자닌 블록 | 별도 PR. 이연 |
| 뷰어 KRX 패널 | 약관 제11조 — 사용자 키 릴레이 3곳 동시 수정이 필요. 다음 PR |
| 공개 레포·vercel에 시세 캐시 배포 | 제11조 제3자 제공. 캐시는 사용자 기기 `~/.cache`뿐 |
| KIND 관리종목·불성실공시 페이지 파싱 | DART가 이미 준다(위 건수). 중복 출처를 만들지 않는다 |

## 구조

```
core/krx_client.py      KRX Open API — 날짜별 디스크 캐시, 일일 호출 계수, fetch_failed
core/kind_client.py     KIND 시장경보 3종 POST + 표 파서 — 10분 메모리 캐시
core/market_context.py  순수 함수 — 사건 창 사실, 경보↔공시 정렬, 창 개괄
server.py               도구 34 track_market_reaction + _market_reaction_block(analyze·timeline 흡수)
```

### `core/krx_client.py`

- `KRX_BASE = "https://data-dbg.krx.co.kr/svc/apis/sto"`,
  `KRX_API_IDS = {"Y": "stk_bydd_trd", "K": "ksq_bydd_trd"}`(DART `corp_cls` → apiId;
  `N`·`E`는 대상 아님), `KRX_DAILY_CAP = 10_000`, `KRX_SOFT_CAP = 9_000`.
- `krx_get_daily(api_id, bas_dd, api_key) -> list[dict] | None` — `requests.get`,
  헤더 `AUTH_KEY`, timeout 15, 429/5xx 지수 백오프 3회(`dart_client._retry` 규칙).
  **로그에 헤더·키·응답 본문을 남기지 않는다.** 401·비JSON·`OutBlock_1` 부재 → `None`.
- 디스크 캐시: `_resolve_corp_cache_dir()/krx/{api_id}/{basDd}.json.gz`.
  저장 필드는 `ISU_CD`·`TDD_CLSPRC`·`FLUC_RT`·`ACC_TRDVOL`·`ACC_TRDVAL`·`MKTCAP`·
  `LIST_SHRS`·`SECT_TP_NM` 8종만. 과거 날짜는 **TTL 없음**(불변). 빈 배열(휴장일)은
  `{"empty": true}`로 캐시. **당일(기기 로컬 날짜)은 캐시하지 않는다.** 실패는 캐시하지
  않는다.
- 일일 계수: `krx/quota_{YYYYMMDD}.json` `{"calls": n}`. `KRX_SOFT_CAP` 도달 시 더
  부르지 않고 결과에 `quota_hit=True`.
- `fetch_price_series(stock_code, corp_cls, start_dd, end_dd, api_key, *,
  budget=KRX_CALL_BUDGET) -> dict`:
  `{"rows": [{"date","close","fluc_rt","volume","value","mktcap","list_shrs"} …
  날짜 오름차순], "days_requested", "days_fetched", "days_cached", "days_uncovered":
  [date …], "quota_hit", "fetch_failed", "api_id"}`. 거래일 후보(월~금)를 **최근부터**
  훑고, 예산 소진 시 나머지를 `days_uncovered`에 적는다. 하루 응답에서 해당 종목 행만
  뽑되 **전체를 캐시**한다.
- `KRX_CALL_BUDGET` 초기값 80 — 0단계 실측 뒤 대기 1분 예산에 맞춰 조정.

### `core/kind_client.py`

- `fetch_market_alerts(stock_code, start_date8, end_date8) -> dict`:
  `{"alerts": [ … 지정일 내림차순 ], "by_kind": {"caution": n, "warning": n, "risk": n},
  "clamped": bool, "clamp_start": date8|None, "failed_kinds": [...], "parse_failed":
  bool, "fetch_failed": bool}`. 3종을 각각 POST(page size 100, 다음 페이지 있으면 최대
  3페이지 — 한 종목이 100건을 넘기는 일은 실측에 없다). 창이 3년을 넘으면 최근 3년으로
  자르고 `clamped=True`.
- 레코드: `{"kind": "caution"|"warning"|"risk", "name", "reason"(주의만), "announced":
  date8, "designated": date8, "released": date8|None}`.
- `parse_kind_alert_table(html, kind) -> tuple[list[dict], dict]` 순수 함수. 열 배치는
  `fn_InitTitle` 문자열로 검증 — 기대와 다르면 `parse_failed=True`(구조 변경 감지).
  「조회된 결과값이 없습니다」 → 빈 결과·정상. 본문 길이 0 → 실패(창 초과 등).
- 10분 메모리 캐시(`_cache_get/_cache_set`), 실패는 미캐시. 헤더 `X-Requested-With`·
  `Referer`·`User-Agent`.

### `core/market_context.py` (순수 함수)

- `event_window_facts(rows, event_date8, *, pre=5, post=5, baseline=60,
  min_baseline=20) -> dict | None`. rows 오름차순. D0 = 사건일 이후 첫 거래일
  (`d0_shifted=True`면 사실로 표기). 반환 `d0_date`, `d0_close`, `d0_fluc_rt`,
  `pre_return_pct`(D-pre 종가 → D-1 종가), `post_return_pct`(D0 → 가용 마지막),
  `pre_vol_ratio`, `d0_vol_ratio`(분모 = 기준선 평균; 기준선 < `min_baseline`이면
  `None` + `baseline_note`), `turnover_pre_pct`(합), `turnover_d0_pct`, `mktcap_d0`,
  `days_pre_avail`, `days_post_avail`, `baseline_avail`. 거래량 0·상장주식수 0은 값을
  내지 않고 사유를 남긴다.
- `align_alerts_with_events(alerts, observed_events, days=10)` — 지정일 ±days 안의
  관찰 공시(날짜·신호 키·제목) 목록.
- `window_overview(rows)` — 시작·끝 종가와 날짜, 창 안 최고·최저 종가와 날짜, 평균 일
  회전율, 끝 시총, **관리종목 규정선 대조**(시총 < 200억 / 종가 < 1,000원인 거래일 수 —
  규정 수치라 허용. 우리 임계가 아니다).

### `server.py`

- `_KRX_API_KEY` + `_krx_api_key()` — `_api_key`와 같은 모양·우선순위.
  `tests/test_api_key_single_source.py`를 두 키로 파라미터화.
- 도구 34 `track_market_reaction(company_name, lookback_years=1, lookback_days=0,
  from_date="", to_date="", rcept_no="")`:
  ① 「📈 공시 전후 시장 반응」 — 관찰 신호 최근 12건 표(초과는 「관찰 N건 중 최근 12건 ·
  K건 생략」), `rcept_no`면 그 한 건(pre/post 10일) ② 「🚨 시장경보 이력 (KIND)」 —
  지정·해제·사유 + 지정일 ±10일 관찰 공시. 0건 「이 창에는 없음」 / 실패 「확인 불가」를
  가른다 ③ 「📊 창 개괄」. 고지: 접수일≠사건일 · 장 마감 후 접수는 D+1부터 · 정정 제외 ·
  「N거래일 중 M일 조회 · K일 미조회」 · 한도 도달 · **「한국거래소 통계정보」** · KIND
  출처 URL·비공식 파싱.
- `_market_reaction_block(observed_events, stock_code, corp_cls, api_key, alerts,
  max_check=3)` — 형제 블록 관례(최근 3건 · 정정 제외 · 실패 시 생략). 키 없으면 한 줄
  안내. 지도 모드(400일↑) 생략. `analyze_company_risk`·`build_event_timeline` 양쪽.
- `explain.METRIC_PROSE["market"]` 5항목(D0 등락·전후 누적 등락·거래량 배수·회전율·
  시총) — `sense`는 전부 `"none"`(방향에 좋고 나쁨이 없다). `GLOSSARY` 「시장경보」·
  「거래량 배수」 추가.

## 테스트 경계

- `tests/conftest.py` 가드 확장: KRX 호스트(헤더 `AUTH_KEY` ≠ env `KRX_API_KEY`면 401
  JSON 가짜 응답 + leak) · KIND 호스트(무조건 「조회된 결과값이 없습니다」 가짜 응답 +
  leak, `allow_kind` 픽스처로만 허용). `STRUCTURED_FETCH_STUBS`에 `fetch_price_series`·
  `fetch_market_alerts` 추가.
- 골든 매트릭스 +1(`market`), hygiene 첫 줄 패턴, 문서 33 → 34.

## 검증 (구현 뒤 채운다)

- 0단계 실측 수치(지연·크기·필드·휴장·SECT_TP_NM) — 대기 중.
- 라이브: 제이스코홀딩스·코아스·삼성전자 1년 + 위험 지정 이력 종목 1곳(피델릭스 032580 —
  2026-05 위험·2026-09 경고 실측).
