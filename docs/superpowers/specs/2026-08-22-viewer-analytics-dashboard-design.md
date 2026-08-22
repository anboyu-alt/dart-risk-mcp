# 공개 뷰어 접속 분석 대시보드 — 설계

작성일: 2026-08-22

## 목적

공개 리스크 뷰어(`docs/tool/index.html`)에 누가 들어와서 어떤 회사를 조회하는지
운영자만 볼 수 있는 대시보드를 만든다. 뷰어는 정적 페이지라 서버 로그가 남지
않고, 회사 조회는 SPA 내부 동작이라 URL에도 흔적이 없다 — 지금은 방문자 수조차
알 수 없다.

## 수집 범위 (운영자 결정)

원본 IP·쿠키·UA 원본을 모두 저장한다. 브레인스토밍 과정에서 익명화 안(IP 해시,
UA 미저장)을 제시했으나 운영자가 전체 수집을 선택했다.

| 항목 | 값 | 출처 |
|---|---|---|
| 접속 IP | 원본 (`inet`) | `x-forwarded-for` 첫 항목 |
| 방문자 ID | UUID v4, 쿠키 1년 | 클라이언트 발급 |
| 지역 | 국가·지역·도시 | `x-vercel-ip-country/-country-region/-city` |
| 기기 | UA 원본 + 브라우저·OS·기기·모바일 여부 | `user-agent` 파싱 |
| 유입 | referrer (쿼리스트링 제거) | `document.referrer` |
| 행동 | 이벤트 종류, 조회 회사명·종목코드 | 클라이언트 |
| 환경 | 화면 해상도, 언어, 경로 | 클라이언트 |

**고지**: 뷰어 면책 문구 끝에 한 줄을 추가한다 —
`접속 기록·쿠키·기기 정보를 수집합니다.` 팝업·동의 배너는 두지 않는다.

이 범위는 국내법상 개인정보 처리에 해당한다. 처리방침 고지·보관기간 정책은
운영자 판단 영역이며 이 스펙의 범위가 아니다.

## 아키텍처

### 채택안: 전용 수집 엔드포인트

브라우저가 이벤트를 `/api/track`으로 POST하고, 서버가 요청 헤더에서 IP·지역을
붙여 Supabase에 저장한다.

기각한 대안 둘:

- **브라우저가 Supabase에 직접 insert** — 브라우저는 자기 공인 IP를 모르고,
  anon 키가 페이지 소스에 노출된다.
- **Vercel Edge Middleware 전역 로깅** — 페이지뷰는 자동으로 잡히지만 "어떤
  회사를 조회했는지"가 URL에 없어 핵심 데이터를 못 얻는다.

### 신뢰 경계 — 릴레이를 건드리지 않는다

`api/[endpoint].js`는 주석에 "키·파라미터·응답을 저장하거나 로그로 남기지
않는 무상태 통과"를 명시한 신뢰 경계다. 여기에 로깅을 끼워 넣으면 그 약속이
깨진다. 수집은 **별도 엔드포인트**로만 한다.

같은 이유로 사용자의 DART API 키는 어떤 경로로도 수집·저장하지 않는다.

### 파일 구성

기존 `api/doc.py`(껍데기) + `tool_server/doc.py`(몸통) 패턴을 그대로 따른다.
껍데기는 HTTP 파싱만 하고 로직은 몸통에 둬야 단위 테스트가 된다.

| 파일 | 역할 |
|---|---|
| `tool_server/schema_analytics.sql` | 테이블·인덱스·집계 뷰 정의 |
| `tool_server/track.py` | 이벤트 정규화·검증·저장 (순수 로직) |
| `api/track.py` | `POST /api/track` HTTP 껍데기 |
| `tool_server/stats.py` | 토큰 검사·집계 조회 |
| `api/stats.py` | `GET /api/stats` HTTP 껍데기 |
| `docs/tool/ops-762b24e0.html` | 대시보드 화면 |
| `docs/tool/index.html` | 수집 스니펫 + 면책 한 줄 |
| `docs/tool/robots.txt` | 대시보드 경로 차단 |

## 데이터 모델

단일 테이블 `viewer_events`. 집계 테이블은 만들지 않는다 — 이 규모에서 불필요하고,
원본이 남아 있어야 나중에 다른 질문을 던질 수 있다.

```sql
create table if not exists viewer_events (
  id          bigserial primary key,
  ts          timestamptz not null default now(),
  event       text not null,          -- pageview | scan | compare | doc
  visitor_id  text,                   -- 쿠키 UUID
  ip          inet,
  country     text,
  region      text,
  city        text,
  ua          text,
  browser     text,
  os          text,
  device      text,                   -- desktop | mobile | tablet | bot
  is_mobile   boolean,
  referrer    text,                   -- 쿼리스트링 제거
  corp_name   text,
  stock_code  text,
  path        text,
  screen      text,                   -- "1920x1080"
  lang        text
);
```

인덱스 3개: `(ts desc)`, `(visitor_id, ts)`, `(corp_name)` — 네 화면을 모두 커버한다.

RLS를 켜고 정책을 두지 않는다. service_role 키만 RLS를 우회하므로 서버 함수
외에는 읽을 수도 쓸 수도 없다 (`se_cache`와 동일 원칙).

### 집계 뷰

PostgREST는 GROUP BY를 직접 지원하지 않으므로 SQL 뷰로 서버에서 집계한다.
행 전체를 끌어와 Python에서 세면 데이터가 쌓일수록 응답이 무거워진다.

| 뷰 | 내용 |
|---|---|
| `v_corp_ranking` | 회사별 조회수·순방문자수 (일자 포함, 기간 필터는 조회 시) |
| `v_traffic_daily` | 일별 방문자·조회수 |
| `v_referrer_summary` | referrer·국가·브라우저·기기별 집계 |
| `v_visitor_sessions` | 방문자별 최초/최종 접속, 이벤트 수, 마지막 IP |

방문자 타임라인 상세는 뷰가 아니라 `viewer_events`를 `visitor_id`로 직접
조회한다 (행 그대로 필요).

## 이벤트 수집 (클라이언트)

`docs/tool/index.html`에 약 40줄을 추가한다.

- 쿠키 `dv_id` 없으면 `crypto.randomUUID()`로 발급, `max-age=31536000`,
  `SameSite=Lax`
- 페이지 진입 시 `pageview` 1회
- `analyze()` 성공 시 `scan` (회사명·종목코드 동반)
- `find_actor_overlap` 상당의 겸직 비교 실행 시 `compare`
- 원문 열람(`/api/doc` 호출) 시 `doc`

전송은 `navigator.sendBeacon`. 페이지를 떠나도 전달되고 응답을 기다리지 않는다.
없으면 `fetch(..., {keepalive: true})`로 폴백한다.

**격리 원칙**: 전체를 `try/catch`로 감싸고 실패를 삼킨다. 수집이 죽어도 뷰어
기능은 그대로 동작해야 한다. 수집 코드는 뷰어 로직 어디에도 값을 되돌려주지
않는다.

## 대시보드

`docs/tool/ops-762b24e0.html` — 추측 불가한 파일명. 뷰어와 같은 단일 파일·무빌드
방식을 따른다.

네 화면을 탭으로 전환한다.

1. **조회 회사 순위** — TOP N + 기간 필터(오늘/7일/30일/전체). 회사명·조회수·순방문자수
2. **유입·지역·기기** — referrer 호스트별 유입, 국가·도시 분포, 브라우저·OS·모바일 비율
3. **트래픽 추이** — 일별 방문자·조회수 꺾은선 (인라인 SVG, 외부 차트 라이브러리 없음)
4. **방문자 상세** — 방문자 목록(최종 접속·이벤트 수·IP·지역) → 클릭 시 그 방문자가
   어떤 회사를 어떤 순서로 봤는지 타임라인. IP로 검색 가능

토큰은 최초 1회 입력받아 `localStorage`에 보관하고 `X-Ops-Token` 헤더로 보낸다.

## 보안

- **인증**: `OPS_TOKEN` 환경변수. `hmac.compare_digest`로 상수시간 비교해
  타이밍 공격을 막는다. 토큰 미설정 시 `/api/stats`는 503으로 닫는다 (열린 채
  배포되는 사고 방지)
- **노출 억제**: `robots.txt`에 `Disallow: /ops-762b24e0.html`, 응답에
  `X-Robots-Tag: noindex`. 파일명이 새어도 토큰 없이는 데이터가 나오지 않는다
- **`/api/track` 남용 방지**: 공개일 수밖에 없으므로 페이로드 1KB 제한,
  필드 화이트리스트(모르는 키는 버림), 값 길이 절단, `event`는 열거값만 허용,
  `Origin`이 허용 도메인일 때만 저장
- **자격증명**: `SUPABASE_SERVICE_KEY`는 서버 함수에만. 대시보드 HTML에는
  Supabase URL조차 넣지 않는다 — 모든 조회가 `/api/stats`를 거친다

## 테스트

`tests/test_tool_server_track.py`, `tests/test_tool_server_stats.py`
(`test_tool_server_doc.py` 패턴).

- UA 파싱: Chrome/Safari/Firefox/Edge, iOS/Android/Windows/macOS, 봇
- referrer 정규화: 쿼리스트링 제거, 자기 도메인 유입 제외, 빈 값
- 이벤트 검증: 미허용 `event` 거부, 미지의 필드 제거, 과길이 절단, 페이로드 초과 거부
- IP 추출: `x-forwarded-for` 다중 값에서 첫 항목, 없을 때 null
- 토큰: 정확 일치만 통과, 미설정 시 503, 빈 토큰 거부
- 집계 응답 형태: 각 화면이 기대하는 키 존재

네트워크는 타지 않는다 — Supabase 호출은 주입 가능한 함수로 두고 테스트에서
가짜를 넣는다.

## 범위 밖

- 실시간 알림 (기존 비범위 정책과 동일)
- 봇 트래픽 자동 필터 — UA에 봇 표시만 남기고 판단은 사람이
- 보관기간 자동 삭제 — 필요해지면 그때 cron으로
- 기존 SE 인증 체계 통합 — 신뢰 모델이 달라 토큰 하나로 분리 유지

## 회귀 영향

- 뷰어: 면책 한 줄 + 격리된 수집 스니펫. 기존 기능 경로 미변경
- 릴레이(`api/[endpoint].js`): **변경 없음** — 무상태 통과 계약 유지
- SE 서버: **변경 없음** — 별도 테이블·별도 엔드포인트
- `docs/tool/signals-data.json`, corp-map 등 데이터 파이프라인: 무관
