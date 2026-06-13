# 설계: 임원 겸직 차원을 `find_actor_overlap`에 흡수

- 날짜: 2026-06-14
- 범위: 1단계 (워치리스트는 별도 spec으로 후속)
- 상태: 사용자 리뷰 대기

## 배경 / 문제

`find_actor_overlap`은 여러 회사의 CB/BW/EB·유상증자 **인수자 이름**을 대조해
2개사 이상에 공통 등장하는 행위자를 찾는다. 그러나 무자본 M&A 세력은
인수마다 **새 SPC/사모조합을 만들어** 들어오므로(예: "르퓨쳐 코스닥벤처 일반사모투자신탁
제2호/제3호"), 조합명이 매번 달라 이름 대조로는 묶이지 않는다.

라이브 검증(2026-06-14)에서 신승수·오종원·김준범 연관 17개 기업을 대조했으나
공통 인수자 0건. 원인은 윈도우(365일)가 아니라 **조합명 비고정성**으로 규명됐다.

## 핵심 통찰

조합명은 변해도 **사람 이름은 고정점**이다. 같은 세력은 인수한 회사들에
**등기임원으로 반복 등장**한다. DART `exctvSttus.json`(임원현황)으로 이를 자동 포착할 수 있다.

라이브 입증 (2026-06-14, 다년 합집합):
- **신승수 — 4개사 겸직**: CG인바이츠(2019–2023)·제이케이시냅스(2024)·헬스커넥트(2021)·티쓰리(2022)
- 보너스: 윤원도·정인철(CG인바이츠↔헬스커넥트) — CASSANDRA 수기 위키에 없던 동행 인물까지 발굴

단년 스냅샷으로는 안 잡히고 **다년 합집합이 필수**다(`find_actor_overlap`의 lookback 교훈과 동일).

## 아키텍처 결정

1. **호스트 Claude 위임:** 우리 도구는 "겸직 사실"이라는 원재료(회사·연도)를 모아주고,
   배후 세력 판단은 도구를 호출한 Claude가 한다. 별도 LLM API·외부 라이브러리 불필요
   (`requests`+`mcp`만 원칙 유지).
2. **흡수 우선:** 신규 도구를 만들지 않고 기존 `find_actor_overlap`에 [임원] 차원을 통합한다.
   도구 카탈로그 23개 유지. "돈을 댄 사람(인수자) + 경영에 앉은 사람(임원)"을 한 화면에 교차 비교.
3. **점수·등급 없음(v0.8.5) 유지:** 겸직 사실(회사명·연도)만 표기. 점수/등급/이모지 회귀 없음.

## 컴포넌트

### 신규: `dart_client.fetch_executive_roster(corp_code, api_key, lookback_years=1)`

- `exctvSttus.json`을 `bsns_year` × `reprt_code=11011`(사업보고서)로 최근 N년 루프 호출
- 응답 `list`의 각 행에서 임원 성명(`nm`)을 추출. 직위(`ofcps`)·등기여부(`rgist_exctv_at`)는
  부가 표기용으로 보존(구현 시 실제 필드명·값 형태를 라이브로 재확인).
- 반환: `dict[str, set[str]]` = `{임원명: {연도, ...}}`
- 오류 처리: 호출 실패/빈 응답이면 해당 연도 건너뜀(예외 비전파 — 기존 원칙).
- 합산행·빈 이름은 스킵.

### 변경: `server.find_actor_overlap(company_names, lookback_years=1)`

- 각 회사 처리 루프에 임원 수집을 추가: `fetch_executive_roster(corp_code, api_key, lookback_years)`
- `actor_map`에 임원을 `source="임원"`으로 통합.
  - 기존 entry 튜플: `(corp_name, source, amount, rcept_no)`
  - 임원 entry: `(corp_name, "임원", 연도라벨, "")` — rcept_no 없음, amount 자리에 연도(예: "2019–2023")
- 공통 행위자 판정은 기존 그대로: 2개사 이상에 등장(인수자 **또는** 임원)
- 출력:
  - 공통 행위자 라인에 `[임원]` 소스 태그가 기존 `[CB]`/`[유상증자]`와 함께 표기
  - 회사별 명단에 `[임원] {이름} ({연도})` 추가
  - 안내 문구에 임원현황도 다년 수집 대상임을 1줄 보강

## 데이터 흐름

```
company_names → resolve_corp → corp_code
  ├─ fetch_company_disclosures(lookback_days) → match_signals → CB/유상증자 인수자  (기존)
  └─ fetch_executive_roster(lookback_years)   → 등기임원 명단                      (신규)
        ↓ 통합 actor_map (source ∈ {CB, 유상증자, 임원})
  공통 행위자(2개사 이상) + 회사별 명단 렌더 → 호스트 Claude가 배후 추론
```

## 오류 처리

- 기존 패턴 유지: API 실패 시 빈 결과, 예외를 도구 레벨로 전파하지 않음.
- 임원현황이 없는 회사(비상장 기간 등)는 "임원현황 없음"으로 명단에서 자연 제외.

## 테스트 (TDD)

단위 테스트:
1. `fetch_executive_roster`: 다년 응답 mock → `{이름: {연도}}` 합집합 형태 검증
2. `find_actor_overlap` 임원 통합: 2개사에 같은 임원 → `[임원]` 태그 + 공통 행위자로 탐지
3. 임원-인수자 혼합: A사 임원 = B사 인수자가 동일인 → 공통 행위자로 묶임
4. 기본 동작 회귀: 임원 데이터 없을 때 기존 출력 형식 유지(골드 호환)

라이브 검증:
- 신승수군(이엠앤아이·제이케이시냅스·CG인바이츠·헬스커넥트·티쓰리) `lookback_years=3`
  → 신승수 4개사 겸직 탐지 확인
- 성공 시 `tests/fixtures/sample_outputs/actor_overlap.txt` 골드 갱신,
  hygiene 9/9 PASS 후 CLAUDE.md 라이브 검증 매트릭스에서 `find_actor_overlap` ⚠ 제거

## 비범위 (이번 단계 제외)

- 워치리스트(인물↔회사군 영속 매핑, `manage_watchlist` 도구) — 2단계 별도 spec
- 실시간 알림·일일 자동 스캔 — 영구 비범위(정책 유지)
- 임원 겸직에 대한 점수·등급 부여 — v0.8.5 원칙 위반, 사실 표기만

## CLAUDE.md 갱신 항목

- 도구 #5 `find_actor_overlap` 설명에 임원 겸직 차원·`lookback_years` 파라미터 반영
- 핵심 내부 함수 표에 `fetch_executive_roster` 추가
- DART 엔드포인트 표에 `GET /api/exctvSttus.json` 추가
- 라이브 검증 매트릭스에서 `find_actor_overlap` ⚠ → ✅ (신승수군 골드 근거)
