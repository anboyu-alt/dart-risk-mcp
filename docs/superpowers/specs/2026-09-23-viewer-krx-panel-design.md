# 뷰어 KRX 패널 — 사용자 본인 키 릴레이 「공시 전후 시장 반응」 (2026-09-23)

## 왜

v1.29.0이 MCP에 「공시 전후 시장 반응」(KRX 일별시세)을 붙였는데 공개 뷰어
(`docs/tool/index.html`)에는 없다. 뷰어를 보는 사람이 압도적으로 많다.
`docs/DEFERRED-DECISIONS.md` 15번을 실행한다.

**경계는 약관이다.** KRX Open API 약관 제11조 ②(제공받은 정보의 제3자 제공 금지)
때문에 **운영자 키로 받은 시세를 방문자에게 보여 줄 수 없다.** 그래서 이 패널은
**사용자 본인 KRX 키**로만 동작하고, 릴레이는 그 키를 받아 전달만 하며 **캐시하지
않는다**(`Cache-Control: no-store`). 서버 키 주입·쿼터·CDN 캐시 — DART 경로가 가진
셋 다 KRX 경로에는 없다.

**점수·등급·임계는 없다**(v0.8.5). 등락률·배수·회전율·일수를 사실로 적고, 시장경보
(KIND)는 뷰어에 붙이지 않는다(비공식 파싱을 우리 도메인이 프록시하면 KIND 쪽 차단
위험이 우리에게 걸린다) — 「시장경보는 MCP `track_market_reaction`에서」 한 줄로 넘긴다.

## 실측 전제 (v1.29.0 스펙에서)

- KRX 응답은 **하루 단위·시장 전체**(유가 942행 293KB · 코스닥 1,820행 596KB), 콜당
  ~1.0초, 동시 5콜까지 429 없음. 빈 배열은 휴장일과 **발표 전**을 구분하지 않는다
  (전 거래일이 익일 00:42에도 빈 배열이었다).
- 사건 하나의 창 = 기준선 60 + 전 5 + D0 + 후 5 ≈ 71거래일. 사건 3건 창 합집합은
  겹침에 따라 70~100거래일.
- 뷰어에는 corp_cls(유가/코스닥)가 없다.

## 하지 않기로 한 것

| 후보 | 왜 안 하나 |
|---|---|
| 릴레이가 시장 전체를 캐시해 방문자에게 재사용 | 제11조 ②. 사용자 키 응답도 캐시 키에 남의 키가 섞인다(DART 경로와 같은 이유) |
| 운영자 키 폴백 | 같은 이유. 키 없으면 표 대신 한 줄 안내 |
| KIND 시장경보 프록시 | 비공식 파싱 부하·차단이 우리 도메인에 걸린다. MCP로 넘긴다 |
| 사건 12건(단독 도구 규모) | 1년 창 ≈ 245콜·60~80초. 제작자 결정: **최근 3건**(MCP 흡수 블록과 동일) |
| 기준선 20거래일로 줄이기 | MCP(60)와 수치가 갈린다. 같은 회사가 화면마다 다른 배수를 말하면 안 된다 |
| 기존 DART 라우트 `api/[endpoint].js` 확장 | 키 전달이 헤더(`AUTH_KEY`)라 다르고, `test_dev_relay_env_key`가 그 파일의 문장 순서를 검사한다. 별도 라우트가 안전하다 |

## 구조

```
api/krx.js               Vercel — GET /api/krx?api=&basDd=&isu=  (X-KRX-Key → AUTH_KEY, no-store)
relay/worker.js          Cloudflare 미러 — 같은 계약의 분기
scripts/dev_relay.py     로컬 — 같은 계약의 분기
docs/tool/index.html     KRX 키 칸 · krxGet 헬퍼 · 순수 함수 쌍둥이 · MARKET REACTION 패널(지연 로드)
```

### 릴레이 계약 (3곳 동일)

`GET /api/krx?api={stk_bydd_trd|ksq_bydd_trd}&basDd=YYYYMMDD&isu=071950`
- 헤더 `X-KRX-Key: <사용자 키>`. 없으면 **400** `{"ok":false,"error":"missing_key"}`.
- `api`는 두 값만, `basDd`는 8자리 숫자, `isu`는 6자리 — 아니면 400.
- 업스트림 `https://data-dbg.krx.co.kr/svc/apis/sto/{api}?basDd=…` + 헤더 `AUTH_KEY`.
- 응답(항상 `Cache-Control: no-store`, CORS 허용 헤더에 `X-KRX-Key`):
  - `{"ok":true,"found":true,"row":{"date","close","fluc_rt","volume","value","mktcap","list_shrs","sect"}}`
    — 필드 정규화는 core `krx_client._normalize_row`와 같다(콤마 제거 후 숫자, `sect`는 빈 문자열→null).
  - `{"ok":true,"found":false,"empty":true}` — 빈 배열(휴장일 또는 발표 전).
  - `{"ok":true,"found":false,"empty":false}` — 그날 시장에 그 종목이 없다(다른 시장).
  - 업스트림 401 → **401** `{"ok":false,"error":"unauthorized"}`. 그 밖 비200·비JSON → **502**.
- 시장 전체를 받아 **한 행만** 돌려준다 — 브라우저가 600KB를 받지 않게 하는 것이 이
  라우트의 존재 이유다. 릴레이는 아무것도 저장하지 않는다.
- ⚠ Cloudflare 워커에서 KRX가 해외 IP를 막는지는 **재지 않았다**. 워커 분기는 넣되
  실패는 뷰어가 `fetchFailHTML`로 밝힌다.

### 뷰어

- **키**: `localStorage["dart_tool_krx_key"]`. 설정 패널(`#setupPanel`)에 DART 키 칸과
  나란히 KRX 키 칸(발급처 `openapi.krx.co.kr` 링크 + 「유가증권·코스닥 일별매매정보
  활용 신청」 한 줄). DART 키와 독립 — KRX 키만 있어도, 없어도 나머지 화면은 그대로.
  릴레이가 공용 DART 키를 갖는 경우에도 KRX는 **본인 키가 없으면 안 된다**(약관).
- **헬퍼** `krxGet(api, basDd, isu)`: `relayBase()+"/api/krx"`에 헤더 `X-KRX-Key`.
  400 `missing_key`·401은 각각 문구로 가른다.
- **시장 판별** `krxResolveMarket(isu)`: 최근 거래일 후보(오늘부터 거꾸로 최대 7일)에
  stk·ksq를 두드려 `found`인 쪽. 둘 다 `empty`면 다음 날짜. 결과는
  `localStorage["dart_tool_krx_mkt"]`에 `{isu: api}`로 기억(재판별 없음).
- **시계열** `krxFetchSeries(api, isu, startDd, endDd, onProgress)`: 월~금 후보를
  **최근부터** 동시 4콜. (api, basDd, isu) 단위 결과를 `localStorage["dart_tool_krx_rows"]`
  에 남긴다(최대 3,000건, 오래된 것부터 버림; `empty`는 **오늘부터 7일 안이면 저장하지
  않는다** — 발표 전일 수 있다, core `KRX_EMPTY_GRACE_DAYS`와 같은 규칙). 진행은
  「N/M거래일 수신」으로 표시. 예산 상한 120콜 — 넘는 날짜는 `uncovered`로 밝힌다.
- **순수 함수 쌍둥이**(core와 같은 입력·출력, `test_viewer_twin_parity` 등록):
  `eventWindowFacts(rows, eventDate8, {pre,post,baseline,minBaseline})`,
  `windowOverview(rows)`, `weekdayCandidates(startDd, endDd)`.
- **패널** `#marketCore` — `.deepgrid` 안, `<details>` 펼침 시 조회(`dataset.loaded`
  재진입 가드, 「펼쳐서 조회」 문구, 스피너는 펼친 뒤에만). 제목
  `panelTitleHTML("MARKET REACTION — 공시 전후 시장 반응")`.
  - KRX 키 없음: 「KRX 키를 넣으면 이 자리에 시세·거래량 대조가 붙습니다 — 설정에서
    입력」 한 줄(설정 패널로 가는 링크). 조회하지 않는다.
  - 관찰 이벤트(`CUR.observedEvents`) 최근 **3건**(정정 제외, 같은 날·같은 신호 접기)의
    표(`factTableHTML`): 접수일 | 신호 | D0 등락 | D-5→D-1 | D0→D+5 | 거래량 배수(전 5일/당일)
    | 회전율(전 5일 합) | 시총. 각주는 core `_market_fact_notes`와 같은 문장(휴장일 접수 ·
    D±5 중 N일 자료 · 기준선 부족 · 거래량 0 거래일 N/M · 미조회 구간).
  - 창 개괄: 거래량 0인 거래일 N/M · 코스닥 소속부(변동이 있으면 이동) · 관리종목
    규정선 대조(「이 도구의 임계가 아니라 규정 수치」).
  - 고지: 「한국거래소 통계정보」(제10조 ③) · 접수일≠사건일·장 마감 후 접수는 D+1부터 ·
    「최근 3건만 · 시장경보는 MCP `track_market_reaction`」 · 「N거래일 중 M일 미조회」.
  - 증감 셀은 `deltaHTML`을 쓰되 **색은 없다**(`sense:"none"`) — 등락 방향에 좋고
    나쁨이 없다(`METRIC_PROSE["market"]`이 이미 그렇게 적었다).
  - 「지표 읽는 법」은 `metricProseHTML("market")`.
- **실패 표기**: 릴레이 실패·401·미조회는 `fetchFailHTML`/사실 문구. 「자료 없음」과
  「못 받았다」를 가른다(뷰어 규칙).

## 테스트

- `tests/test_viewer_krx_relay.py`(신설): 3곳이 ① `/api/krx` 경로를 갖고 ② `X-KRX-Key`를
  `AUTH_KEY`로 넘기며 ③ `no-store`를 달고 ④ `DART_API_KEY`·`KRX_API_KEY`·서버 키를
  참조하지 않고 ⑤ 허용 `api` 두 값이 core `KRX_API_IDS`와 같은지 — 정적 대조.
  로컬 릴레이는 실제로 띄워 400/401 경로를 두드린다(업스트림은 mock).
- `tests/test_viewer_twin_parity.py`에 세 쌍둥이 등록(합성 rows 9케이스: 정상·휴장일
  접수·덜 찬 창·기준선 부족·거래량 0·소속부 변동·주말·오늘 경계).
- `tests/test_viewer_key_panel.py`: KRX 키 칸이 DART 키 상태와 독립.
- `tests/test_viewer_deep_grid.py` `_LAZY_IDS`에 `marketCore` 추가 · `test_viewer_notice_facts.py`
  catch 개수 갱신 · `test_viewer_render_invariants.py` 통과.
- 라이브 전·후 대조(코아스·제이스코홀딩스·삼성전자 1년): 패널 값이 MCP `track_market_reaction`
  같은 사건과 **일치**(D0·전후 등락·배수·회전율·시총), 콘솔 오류 0.

## 후속(이번 범위 밖)

- 「더 보기」로 12건 확장 · 지수 병기 · 워런트 매매(`DEFERRED-DECISIONS` 16·17).
