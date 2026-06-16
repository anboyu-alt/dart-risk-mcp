# 설계: 문제 회사 기반 행위자 자동 발굴 (actor discovery)

- 날짜: 2026-06-17
- 범위: 시장 문제 회사 인수자 누적(sightings) → 반복 등장 인물 자동 발굴
- 상태: 사용자 리뷰 대기

## 배경 / 문제

현재 `refresh_known_actors.py`는 **이미 등재된 인물**(제작자 시드 5명 등)만 시장 공시와
매칭한다. 새 인물은 발굴하지 않는다. 사용자의 원래 비전은 "문제 상장사에 반복 등장하는
인명을 자동 발굴"하는 것이다.

핵심 통찰: 시장 전체를 보면 정상 인물이 잡음으로 들어온다. **"문제 회사"(불안정 신호
동반 CB/유상증자 발행사)로 범위를 좁히고, 그 안에서 여러 문제 회사에 반복 등장하는
인수자**를 찾으면 신호 대비 잡음이 크게 개선된다.

## 핵심 결정 (확정)

1. **문제 회사 정의 = (나) 중간 강도** — CB/유상증자 발행 + 불안정 신호 동반
   (최대주주변경·감자·상호변경·조회공시·감사이슈 중 1+).
2. **반복 임계 N=2** — 서로 다른 문제 회사 2곳+ 에 인수자로 등장하면 후보 등재.
3. **자동 등재 = A안** — N=2 도달 인물을 `known_actors.json`(public)에 `auto_matched`로
   직접 등재. 유저도 `lookup_known_actor`·`find_actor_overlap`에서 봄(강한 경고 동반).
4. **sightings(1회 포함)는 비공개** — 별도 **private repo**에 누적. 미검증 1회 인물은
   유저에 노출 안 함. 제작자는 private repo에서 직접 검토(취재 판단용).
5. **인수자 중심·개인명만** — 임원은 자동 발굴 제외(연 1회 사업보고서라 일별 부적합).
   조합/SPC명은 제외(매번 달라 반복 무의미).
6. **누적 윈도우 12개월** — sightings는 최근 12개월만 유지(파일 크기 안정).
7. **이메일** — N=2 신규 등재 시 제작자에게 통지(기존 `send_mail` 재사용).

## 데이터 노출 경계

| 데이터 | 위치 | 누가 봄 |
|---|---|---|
| sightings (1회 포함 전체 관찰) | **private repo** | 제작자만 |
| known_actors (N=2 등재 + 기존 verified/seed) | public repo (동봉/원격) | 유저 + 제작자 |

## 컴포넌트

### 1. 신규 `scripts/discover_actors.py`

순수 함수 + main 오케스트레이션. 핵심 함수(단위 테스트 대상):

- `company_signal_keys(corp_code, api_key, lookback_days) -> set[str]`
  - `fetch_company_disclosures` + `match_signals`로 그 회사 최근 공시의 신호 키 집합 반환.
- `is_problem_company(signal_keys) -> bool`
  - 자금조달 신호(`CB_BW`/`EB`/`3PCA`/`RIGHTS_UNDER`) **and** 불안정 신호
    (`SHAREHOLDER`/`REVERSE_SPLIT`/`GAMJA_MERGE`/`INQUIRY`/`AUDIT` 중 1+)가 함께 있으면 True.
    (실제 signal key는 구현 시 `signals.py`에서 확인·정합. 상호변경 등 키 부재 시 가용 키로 대체.)
- `collect_problem_sightings(api_key, window_days, max_pages) -> list[dict]`
  - `fetch_market_disclosures`(최근 window_days, CB/유상증자)로 회사 목록 수집 →
    각 회사 `company_signal_keys`로 문제 회사 판별 → 문제 회사만 인수자 추출
    (`extract_cb_investors`/`extract_rights_offering_investors`) → 개인명만
    sighting 레코드 생성: `{name, corp, corp_code, date, rcept_no, signals}`.
  - 조합/법인 패턴(주식회사·조합·투자·신탁·유한 등 포함) 이름은 제외.
- `merge_sightings(sightings_data, new, window_months=12) -> bool`
  - `{name: [sighting...]}`에 new를 병합. 동일 `(name, rcept_no)` 중복 스킵.
    `date` 기준 window_months 초과 레코드 제거. 변경 여부 반환.
- `promote_repeat_actors(sightings_data, known_data, n=2) -> list[str]`
  - sightings에서 **서로 다른 corp_code 가 n개 이상**인 인물 → `known_data["actors"]`에
    `auto_matched` 엔트리로 등재(이미 있으면 스킵). evidence 예:
    `"문제 회사 N곳 인수자 반복 등장: A·B (자동 발굴)"`. 신규 승격 인물명 리스트 반환.
- `main()`:
  - sightings 경로(env `SIGHTINGS_PATH`, private repo checkout 경로)·known_actors 경로 로드
  - `collect_problem_sightings` → `merge_sightings`(sightings 갱신)
  - `promote_repeat_actors` → known_actors 갱신
  - 신규 승격이 있으면 `build_change_summary`+`send_mail`(기존 함수 재사용)로 제작자 통지
  - sightings/known_actors 변경 여부를 stdout으로 표시(워크플로우가 커밋 판단)

### 2. sightings 데이터 (private repo)

- 파일: private repo의 `sightings.json`. 구조:
  ```json
  {"version": 1, "updated": "2026-06-17",
   "sightings": {"홍길동": [{"corp": "△△전자", "corp_code": "00123456",
     "date": "2026-06", "rcept_no": "20260612000123",
     "signals": ["CB_BW", "SHAREHOLDER"]}]}}
  ```
- env `SIGHTINGS_PATH`로 경로 지정(워크플로우가 private repo를 checkout한 경로).
  미지정 시 로컬 기본 경로(개발용).

### 3. 워크플로우 `.github/workflows/refresh-known-actors.yml` 확장

기존 cron job에 단계 추가(또는 별도 job):
- private repo checkout (PAT):
  ```yaml
  - uses: actions/checkout@v5
    with:
      repository: <OWNER>/dart-risk-mcp-sightings
      token: ${{ secrets.SIGHTINGS_REPO_TOKEN }}
      path: _sightings
  ```
- `discover_actors.py` 실행: `env: SIGHTINGS_PATH=_sightings/sightings.json` (+ 기존 `DART_API_KEY`/`MAIL_*`)
- sightings 변경 시 private repo(`_sightings`)에 commit+push
- known_actors 변경 시 public repo에 commit+push(기존 로직)

### 4. 호출량

- 매일 CB/유상증자 신규 공시 회사(최근 2일) 각각 `company_signal_keys` 1회 + 문제 회사만
  인수자 추출. 회사 수 × (1~2) 호출 = 하루 수십~백. DART 일일 한도 내. `max_pages` 상한 유지.

## 데이터 흐름

```
[cron 매일]
  fetch_market_disclosures(최근 2일, CB/유상증자)
    → 각 회사 company_signal_keys → is_problem_company?
       → 문제 회사: 개인명 인수자 추출 → sighting
  merge_sightings(private sightings.json, 12개월 윈도우)
  promote_repeat_actors(N=2) → known_actors.json(public) auto_matched 등재
    → 신규 승격 시 제작자 이메일
  push: sightings→private repo, known_actors→public repo
```

## 오류 처리

- 개별 회사/인수자 추출 실패 → 건너뜀(graceful).
- private repo checkout/push 실패 → 그날 sightings 갱신 누락(다음날 윈도우가 일부 커버),
  known_actors는 영향 최소화.
- 자격증명(`SIGHTINGS_REPO_TOKEN`·`MAIL_*`) 미설정 → 해당 단계 스킵.

## 테스트 (TDD)

`tests/test_discover_actors.py`(신규, fetch/extract mock):
1. `is_problem_company` — 자금조달+불안정 → True, 자금조달만/불안정만 → False.
2. `collect_problem_sightings` — 문제 회사 인수자만 sighting, 정상 회사 제외, 조합명 제외.
3. `merge_sightings` — 중복 rcept_no 스킵, 12개월 초과 제거, 변경 플래그.
4. `promote_repeat_actors` — 서로 다른 회사 2곳+ → known_actors auto_matched 등재,
   1곳만 → 미등재, 이미 등재 → 스킵.

라이브: `discover_actors.py` 1회 실행(매칭 0이어도 정상 종료) — 호출·필터 동작 확인.

## 비범위

- 임원 자동 발굴 — 인수자 중심.
- 유저 MCP 도구의 시장 자동 스캔 — 운영 큐레이션 전용(GitHub Actions).
- 조합명 정규화로 같은 배후 묶기 — 별도 난제.
- 점수·등급·판정 — auto_matched는 사실+경고만(v0.8.5 유지).

## 운영 안내 (구현 후)

- **private repo 생성**: `dart-risk-mcp-sightings`(빈 repo, `sightings.json` 초기 커밋).
- **PAT 발급**: 그 private repo에 write 권한 → public repo Secret `SIGHTINGS_REPO_TOKEN` 등록.
- 기존 `DART_API_KEY`·`MAIL_*` Secret 그대로 사용.

## 버전

- 자동 발굴은 운영 파이프라인(스크립트+워크플로우). MCP 패키지 코드(서버 도구·known_actors.py
  로직)는 불변 → **버전업 없음**(1.3.0 유지). 단 `discover_actors.py`가 `core` 함수를 재사용만 함.
