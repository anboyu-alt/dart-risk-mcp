# 설계: 공개기록 행위자 레지스트리 (known_actors)

- 날짜: 2026-06-14
- 범위: MVP (매일 cron 자동화는 후속 별도 spec)
- 상태: 사용자 리뷰 대기

## 배경 / 문제

`find_actor_overlap`은 여러 회사의 CB/유상증자 인수자 + 등기임원 겸직을 교차 비교해
공통 행위자를 찾는다. 그러나 MCP 사용자는 "어떤 인물이 문제 상장사에 반복
등장하는가"에 대한 사전 지식(세력 명단)이 없다. 매번 백지에서 시작한다.

해법: **출처가 명확한 공개기록 기반**으로, 특정 인물이 어느 상장사에 투자자(CB·유상증자
인수자) 또는 등기임원으로 등장했는지를 **사실 + 근거 + 출처**로 정리한 레지스트리를
패키지에 동봉한다. `find_actor_overlap`이 공시에서 뽑은 인물을 이 레지스트리에 대조해
"이 인물은 OOO 공개기록에 등장" 사실을 표면화한다.

## 비전 vs 이번 MVP

전체 비전: 매일 시장 CB/유상증자 공시를 수집해 신규 인수자를 발굴·갱신하는 자동
큐레이션 DB. 그러나 자동화의 **엔진은 근거 집계 로직**이다. 이번 MVP는 그 엔진과
조회 경로를 만들고, 매일 cron 자동화(GitHub Actions)는 토대 위에 얹는 후속으로 분리한다.

## 핵심 원칙 (법적 안전장치)

1. **판정 없음** — "세력/문제 인물"로 분류하지 않는다. source/evidence/url/date만 담는다.
   tags는 사실 분류("다수 상장사 등기임원 겸직")까지, 단정 금지.
2. **출처 필수** — 출처 없는 추정은 등재 불가. 모든 엔트리에 검증 가능한 근거.
3. **면책 동반** — 출력 시 항상 "사실 표기·판정 아님 / 동명이인 가능 / 원본 공시 확인 권장".
4. **점수·등급 없음(v0.8.5)** 유지. **중앙 서버 없음** — 패키지 동봉, pip update로 갱신.

## 추적 차원 (임원 + 투자자 양쪽)

- **임원** — `fetch_executive_roster`(exctvSttus). 회사를 알아야 인물이 나온다. 연 1회 갱신.
  조합명 비고정성을 우회하는 고정점.
- **투자자** — CB/BW/EB 인수자(`extract_cb_investors`) + 유상증자 인수자
  (`extract_rights_offering_investors`). 공시에 인수자명이 직접 적혀 신규 공시에서
  인물을 발견할 수 있다(역검색 우회). 단 조합명(SPC)은 매번 달라 개인명만 안정 추적.

두 차원은 상호보완이다. 레지스트리는 양쪽 근거를 모두 담는다.

## 컴포넌트

### 1. 데이터 `dart_risk_mcp/data/known_actors.json` (패키지 동봉)

```json
{
  "version": 1,
  "updated": "2026-06-14",
  "actors": {
    "신승수": [
      {
        "source": "DART 임원현황",
        "evidence": "CG인바이츠·제이케이시냅스·헬스커넥트 등기임원 (2019–2024)",
        "url": "https://dart.fss.or.kr",
        "date": "2019-2024",
        "tags": ["다수 상장사 등기임원 겸직"]
      }
    ]
  }
}
```

- `pyproject.toml`에 패키지 데이터 포함 설정(hatchling — `dart_risk_mcp/data/*.json`).
- 인물명은 정확 매칭 키. 한 인물에 복수 기록(임원·CB·유상증자 출처별) 가능.

### 2. 모듈 `core/known_actors.py` (순수 데이터, 표준 라이브러리만)

- `load_known_actors() -> dict` — `importlib.resources`로 동봉 JSON 로드. 손상/부재 시
  `{"version": 1, "actors": {}}` 반환(예외 비전파). 환경변수 `DART_KNOWN_ACTORS_PATH`로
  오버라이드(테스트·확장).
- `lookup_actor(name) -> list[dict]` — 인물명 정확 매칭 → 기록 리스트(없으면 []).

### 3. 부트스트랩 스크립트 `scripts/build_known_actors.py`

- 입력: 인물명 + 후보 회사군(CLI 인자 또는 내장 시드 맵).
- 동작: 각 회사에 대해
  - `fetch_executive_roster` → 그 인물이 등기임원인 회사·연도 집계
  - `fetch_company_disclosures` + `match_signals` + `extract_cb_investors`/
    `extract_rights_offering_investors` → 그 인물이 인수자인 회사·연도 집계
  - 인물명이 등장한 (회사, 차원, 연도)만 근거로 채택
- 출력: `known_actors.json` 엔트리를 source/evidence/url/date와 함께 생성·병합.
  **사람은 회사 단서만 주고, 근거는 코드가 DART에서 집계**.
- API 키는 기존 `regen_goldens.py`와 동일 경로(`tmp/_apikey.txt` 또는 `DART_API_KEY`).

### 4. 신규 도구 `lookup_known_actor(name)` (25개째)

- `lookup_actor(name)` 결과를 사람이 읽는 한국어로 렌더. 없으면 "공개기록 없음" 안내.
- 출력에 면책 문구 항상 포함. 점수·등급 없음.

### 5. `find_actor_overlap` 연동

- 공통 행위자 + 회사별 명단의 인물명을 `lookup_actor`로 대조.
- 매칭되면 출력 끝에 참고 섹션 추가:
  ```
  📎 공개기록 참고 (사실 표기 — 판정 아님):
    • 신승수 — DART 임원현황(2019–2024): CG인바이츠·제이케이시냅스·헬스커넥트 등기임원
      ⚠ 원본 공시로 사실 확인 권장 · 동명이인 가능성 있음
  ```
- 매칭 0이면 섹션 생략. 기존 출력·골드는 시드에 없는 회사면 불변.

### 6. 초기 시드

- 부트스트랩을 **회사 단서가 있는 인물**(CASSANDRA `knowledge-base.json`의 신승수·
  오종원·김준범)에 돌려 실제 근거를 집계해 채운다. CASSANDRA의 "도주중" 같은 단정
  표현은 쓰지 않고, **우리 도구가 DART에서 집계한 사실**만 담는다(출처=DART).
- resolve 안 되는 회사(옛 사명 등)는 건너뛰고 가능한 근거만.
- 회사 단서 없는 7명은 보류 — 단서 확보 시 같은 스크립트로 추가.

## 데이터 흐름

```
[부트스트랩] 인물 + 회사단서 → fetch_executive_roster + 인수자 추출 → known_actors.json
[조회]       lookup_known_actor(name) → lookup_actor → 렌더 + 면책
[연동]       find_actor_overlap → 탐지 인물 → lookup_actor 대조 → 참고 섹션 + 면책
```

## 오류 처리

- 데이터 부재/손상 → 빈 레지스트리(예외 비전파). `lookup`은 "공개기록 없음".
- 부트스트랩의 개별 회사 실패는 건너뜀(graceful), 가능한 근거만 기록.

## 테스트 (TDD)

`core/known_actors.py` (`DART_KNOWN_ACTORS_PATH`를 tmp로 패치):
1. load: 정상/부재/손상 → 적절한 dict
2. lookup_actor: 매칭/미매칭/[] 반환

`lookup_known_actor` 도구:
3. 등재 인물 → evidence·출처·면책 렌더
4. 미등재 → "공개기록 없음"

`find_actor_overlap` 연동:
5. 탐지 인물이 시드에 있으면 참고 섹션 + 면책 출현
6. 시드에 없으면 참고 섹션 미출현(기존 출력 불변)

hygiene: 점수·등급·이모지 회귀 없음(📎⚠는 기존 허용 장식, severity 등급 아님 — 확인).

## 비범위 (이번 MVP 제외)

- **매일 cron 자동화 / 시장 신규 인수자 발굴** — 후속 별도 spec(GitHub Actions). 엔진
  (부트스트랩)이 이번에 완성되므로 후속은 얇은 스케줄러 레이어.
- 중앙 서버 호스팅 — 패키지 동봉만.
- 인물 판정·점수·등급 — v0.8.5 원칙.
- 조합명(SPC) 정규화로 같은 배후 묶기 — 별도 난제, 비범위.

## CLAUDE.md / README 갱신 항목

- 도구 목록에 `lookup_known_actor` 추가(25개로)
- 도구 #5 `find_actor_overlap`에 공개기록 참고 연동 1줄
- 디렉토리 구조에 `core/known_actors.py`, `data/known_actors.json`, `scripts/build_known_actors.py`
- 등재 기준(공개 출처 필수·판정 없음·면책·이의제기 경로) 명시
