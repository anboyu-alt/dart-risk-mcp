# 설계: known_actors 자동 갱신 파이프라인 + 원격 로드

- 날짜: 2026-06-14
- 범위: 자동 근거 확보(GitHub Actions) + 원격 데이터 즉시 반영
- 상태: 사용자 리뷰 대기

## 배경 / 문제

`known_actors` 레지스트리에 제작자 시드 5명(이준민·배상윤·원영식·온성준·Yoo Andy C)이
근거 없이(`maintainer_seed`) 등록돼 있다. 이들의 근거를 사람이 매일 검토할 여력이
없으므로, 시장 신규 CB/유상증자 공시에서 인수자를 자동 매칭해 근거를 사후 확보한다.

또한 자동 갱신이 의미를 가지려면 갱신된 데이터가 PyPI 릴리스 주기를 기다리지 않고
유저에게 즉시 반영돼야 한다.

## 핵심 결정 (확정)

1. **완전 자동(B안)** — 자동 매칭 결과는 사람 검토 없이 master에 자동 push. 단 안전을
   위해 자동 매칭 건은 `verified`가 아니라 `auto_matched`(동명이인 미확인)로 구분하고
   강한 경고를 동반한다.
2. **원격 로드(B안)** — 패키지는 GitHub raw의 최신 `known_actors.json`을 24h 캐시로
   로드하고, 네트워크 실패 시 동봉 데이터로 fallback. 중앙 서버 없음(정적 파일).
3. **등재 인물만 근거 확보** — 새 인물 자동 등재는 안 함. 시장 전체 인수자를 무차별
   등재하는 위험을 차단. 이미 등재된 인물의 근거만 사후 확보.

## status 3단계

| status | 의미 | 출처 |
|--------|------|------|
| `verified` | 회사 직접 조회로 확보된 근거 | 임원 겸직(신승수) 등 |
| `maintainer_seed` | 제작자가 모니터링 대상으로 등록(근거 미확보) | 제작자 5명 |
| `auto_matched` | 시장 공시 이름 자동 매칭(동명이인 미확인) | 시장 스캔 |

## 컴포넌트

### 1. 원격 로드 (`core/known_actors.py` 변경)

- 상수 `_REMOTE_URL = "https://raw.githubusercontent.com/anboyu-alt/dart-risk-mcp/master/dart_risk_mcp/data/known_actors.json"`
- 캐시 경로 `~/.cache/dart-risk-mcp/known_actors_remote.json`, TTL 24시간.
- `load_known_actors()` 우선순위:
  1. `DART_KNOWN_ACTORS_PATH` 환경변수 지정 시 → 그 파일만 사용(원격 스킵). 테스트·로컬 우선.
  2. 신선한(24h 이내) 원격 캐시가 있으면 → 캐시 사용.
  3. 없으면 `_REMOTE_URL` fetch(timeout 5s) → 성공 시 캐시 저장 + 사용.
  4. 네트워크/파싱 실패 시 → 동봉 `data/known_actors.json` fallback(기존 `importlib.resources`).
- 모든 경로에서 스키마 검증(`actors` dict) 실패 시 빈 구조. 예외 비전파.
- `requests`로 fetch(이미 의존). 원격 fetch는 `dart_client._retry` 미사용(독립 모듈 유지) —
  단순 `requests.get(timeout=5)` + try/except.

### 2. 시장 스캔 매칭 스크립트 (`scripts/refresh_known_actors.py`)

- 동작:
  1. `load_known_actors()`의 등재 인물명 집합 수집(동봉 데이터 기준 — 스크립트는 로컬 파일 직접 읽기).
  2. `fetch_market_disclosures`로 최근 `WINDOW_DAYS=2` CB/유상증자 신규 공시 목록 수집
     (정정공시 제외, `max_results` 상한).
  3. 각 공시: `match_signals` → CB(`CB_BW`/`EB`) 또는 유상증자(`3PCA`/`RIGHTS_UNDER`) 필터 →
     해당 시에만 인수자 추출(`extract_cb_investors`/`extract_rights_offering_investors`).
  4. 인수자명이 등재 인물명과 **정확 매칭**되면 `auto_matched` 근거를 그 인물 엔트리에 append:
     ```json
     { "source": "DART CB인수(자동매칭)", "status": "auto_matched",
       "evidence": "△△전자 CB 인수자로 등장", "url": "https://dart.fss.or.kr",
       "date": "2026-06", "rcept_no": "20260612000123",
       "tags": ["자동 매칭", "동명이인 미확인"] }
     ```
  5. **중복 방지**: 같은 인물에 동일 `rcept_no` 근거가 이미 있으면 스킵.
  6. 변경이 있으면 `dart_risk_mcp/data/known_actors.json` 저장(없으면 무변경).
- API 키: `DART_API_KEY` 환경변수(GitHub Actions Secret) 또는 `tmp/_apikey.txt`.
- 새 인물 등재 안 함. 등재 인물(`load`된 actors 키)만 대상.

### 3. GitHub Actions (`.github/workflows/refresh-known-actors.yml`)

- 트리거: `schedule`(cron `0 19 * * *` = UTC 19시 = 한국 새벽 4시) + `workflow_dispatch`(수동).
- 권한: `contents: write`.
- steps:
  1. checkout(`actions/checkout`)
  2. setup python(`actions/setup-python`, 3.11)
  3. `pip install -e .`
  4. `python scripts/refresh_known_actors.py` (env `DART_API_KEY: ${{ secrets.DART_API_KEY }}`)
  5. 변경 감지 시 `git add data/known_actors.json && git commit && git push`
     (커밋 메시지 예: `chore(known_actors): auto-refresh evidence [skip ci]`).
- `DART_API_KEY`는 repo Secret으로 사용자가 등록(구현 후 안내).

### 4. 렌더 (auto_matched 강한 경고)

- `lookup_known_actor`·`find_actor_overlap` 공개기록 섹션에서 `status == "auto_matched"`인
  항목은 라벨 `[자동 매칭 · 동명이인 미확인]`을 붙이고, seed 면책과 별도로
  "시장 공시 이름 자동 매칭 — 동일인 여부 미확인, 원본 공시로 반드시 확인" 경고 추가.

## 데이터 흐름

```
[GitHub Actions cron 매일]
  fetch_market_disclosures(최근 2일 CB/유상증자)
    → 인수자 추출 → 등재 인물명 매칭
    → auto_matched 근거 append → known_actors.json → master push
                                          │
[유저 호출]
  load_known_actors() → GitHub raw 최신(24h 캐시) → lookup/find_actor_overlap 표면화
```

## 오류 처리

- 원격 fetch 실패 → 동봉 fallback(유저는 항상 동작).
- 스크립트의 개별 공시/인수자 추출 실패 → 건너뜀(graceful).
- GitHub Actions 실패 → 그날 갱신 누락, 다음날 윈도우(2일)가 커버.

## 테스트 (TDD)

`core/known_actors.py` 원격 로드(`requests.get` mock):
1. `DART_KNOWN_ACTORS_PATH` 지정 시 원격 미호출(로컬 우선).
2. 신선 캐시 존재 시 원격 미호출.
3. 캐시 없음 + 원격 성공 → 원격 데이터 반환 + 캐시 저장.
4. 원격 실패(timeout/HTTP 오류) → 동봉 fallback(예외 없음).

`lookup_known_actor`·`find_actor_overlap`:
5. `auto_matched` 항목 → `[자동 매칭 · 동명이인 미확인]` + 강한 경고 출현.

`scripts/refresh_known_actors.py`(핵심 매칭 로직 함수 단위, fetch mock):
6. 등재 인물이 인수자로 매칭 → `auto_matched` 근거 추가.
7. 미등재 인물(시장 인수자)은 추가 안 됨.
8. 동일 rcept_no 중복 스킵.

라이브: 스크립트를 실제 DART로 1회 실행해 동작 확인(매칭 0건이어도 정상 종료).

## 비범위

- **유저 MCP 도구로 시장 자동 스캔 노출** — 영구 비범위. 운영 큐레이션은 GitHub Actions 전용.
- **새 인물 자동 발굴·등재** — 등재 인물 근거 확보만.
- **자동 승격(auto_matched → verified)** — auto_matched는 verified로 자동 변환 안 함.
  사람이 확인하면 수동 승격(별도, 비범위).
- **점수·등급·판정** — v0.8.5 유지.

## CLAUDE.md / README 갱신 항목

- `core/known_actors.py` 원격 로드 동작 + 캐시(`known_actors_remote.json`, 24h) 기술
- `scripts/refresh_known_actors.py` + GitHub Actions 워크플로우 설명
- status 3단계(`verified`/`maintainer_seed`/`auto_matched`) 표기
- 등재 기준 절에 "자동 매칭은 동명이인 미확인, verified 아님" 명시
- `DART_API_KEY` repo Secret 등록 안내(운영자용)
