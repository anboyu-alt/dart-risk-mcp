# 회사→인물 레지스트리 역방향 대조 섹션 설계

- 날짜: 2026-07-12
- 상태: 설계 확정 (사용자 승인 대기)
- 관련 스펙: `2026-06-14-known-actors-design.md`, `2026-06-17-actor-discovery-design.md`

## 목적

회사 분석 도구가 공개기록 행위자 레지스트리(비공개 Notion, opt-in)를 **회사명 기준으로 역방향 조회**해, 조회한 회사에 등장 기록이 있는 등재 행위자를 리포트에 자동 표면화한다. 사용자가 인물의 존재를 모르는 상태에서도 "이 회사에 등재 행위자가 등장한 공개기록이 있다"는 사실이 다른 위험 신호와 같은 리포트에 나타나게 하는 것이 핵심이다.

기존에는 인물→회사 방향(`lookup_known_actor`, `find_actor_overlap`의 인물 대조)만 있었다. 레지스트리 DB의 `관련기업` multi_select 속성(→ 캐시 JSON의 `companies` 필드)은 처음부터 회사별 필터링을 위해 설계된 것으로, 이번 기능이 그 첫 소비자다.

## 범위

- **대상 도구 2개**: `analyze_company_risk`, `build_event_timeline` (사용자 확정)
- **신규 MCP 도구 없음** — 기존 도구에 섹션 흡수 (도구 인플레이션 회피 원칙)
- 상세 드릴다운은 기존 `lookup_known_actor`로 안내

## 비범위

- sightings 데이터(private repo, 미검증 1회 등장 포함)는 절대 사용하지 않는다. 데이터 원천은 검토 워크플로우를 거치는 Notion 레지스트리(및 그 24h 캐시)뿐이다.
- 위험 판정·점수·등급 없음 (v0.8.5 원칙). 사실 표기 + status별 면책만.
- `find_actor_overlap`·기타 회사 분석 도구로의 확장은 이번 범위 아님 (헬퍼 구조상 추후 한 줄 추가로 가능).

## 아키텍처 (접근 A — 공용 함수 2개)

### 1. `core/known_actors.py` — `lookup_actors_by_company(company_name: str) -> list[tuple[str, dict]]`

- `load_known_actors()`로 레지스트리 로드 후 전체 인물을 순회, 각 기록의 `companies` 리스트에 조회 회사명이 있으면 `(인물명, 기록)` 수집.
- 회사명 비교는 기존 `normalize_name` 재사용(공백·대소문자 정규화). 양쪽 모두 DART corp_name 유래라 정확 일치가 기본이고 정규화는 표기 흔들림 방어.
- 빈 입력·레지스트리 미설정(빈 actors) 시 `[]` 반환. 예외 비전파(기존 모듈 관례).
- 반환 정렬: 인물명 오름차순 (렌더 결정성 — 골드 테스트 안정성).

### 2. `server.py` — `_registry_company_section(corp_name: str) -> list[str]`

- `lookup_actors_by_company(corp_name)` 호출, 0건이면 `[]` (섹션 자체 생략 — 출력 오염 없음, opt-in 미설정 사용자도 동일).
- 1건 이상이면 `find_actor_overlap`의 기존 "📎 공개기록 참고 (사실 표기 — 판정 아님)" 포맷을 따라 렌더:
  - 헤더: `📎 공개기록 참고 (사실 표기 — 판정 아님): 이 회사에 등장 기록이 있는 등재 행위자`
  - 행: `  • {인물명} — {source}({date}): {evidence}` (해당 회사가 태깅된 기록만; 그 인물의 다른 회사 기록은 표시하지 않음)
  - 인물별로 레지스트리 전체 기록 수가 표시 기록 수보다 많으면: `    (레지스트리 전체 기록 N건 — 자세히: lookup_known_actor("{인물명}"))`
  - status별 경고(기존 문구 그대로): `auto_matched` 포함 시 동일인 미확인 경고, `maintainer_seed` 포함 시 제작자 등록 고지, 공통으로 원본 확인·동명이인 면책.

### 3. 호출 지점

- `analyze_company_risk`: 리포트 최말미 — 금감원 카탈로그 발췌 블록 뒤, `return` 직전에 섹션 append.
- `build_event_timeline`: 마지막 면책 라인(`⚠️ 이 타임라인은 공시 제목 기반 자동 분류이며…`) **직전**에 섹션 append.
- 두 도구 모두 `resolve_corp`가 돌려준 정식 `corp_name`으로 조회 (사용자 입력 원문이 아님 — 레지스트리 태그도 DART corp_name이므로 일치).

## 데이터 흐름

```
사용자 → analyze_company_risk("회사명")
  → resolve_corp → corp_name
  → (기존 신호 분석 …)
  → _registry_company_section(corp_name)
      → lookup_actors_by_company(corp_name)
          → load_known_actors()  # Notion 24h 캐시 or DART_KNOWN_ACTORS_PATH or 동봉(빈)
      → 매칭 기록 렌더 or []
  → 리포트 반환
```

추가 네트워크 비용 0 (레지스트리는 기존 24h 캐시를 통째 로드해 로컬 매칭).

## 오류 처리

- 레지스트리 로드 실패·미설정·빈 스켈레톤 → `lookup_actors_by_company`가 `[]` → 섹션 무출력. 도구 레벨로 예외 전파 없음.
- `companies` 필드 없는 구(舊) 기록 → `record.get("companies") or []`로 안전 처리.

## 테스트

1. **단위 (`tests/test_known_actors.py` 확장 또는 신규)**: `DART_KNOWN_ACTORS_PATH`로 로컬 JSON 주입 —
   - 회사명 정확 일치 매칭 / 정규화 일치(공백·대소문자) 매칭
   - `companies`에 없는 회사 → 미매칭
   - 빈 입력·빈 레지스트리 → `[]`
   - 다건 매칭 시 인물명 정렬
2. **렌더 단위**: `_registry_company_section` — 0건 시 `[]`, auto_matched/maintainer_seed 경고 발화, 전체 기록 수 안내 라인.
3. **회귀**: `python -m pytest tests/test_golden_output_hygiene.py -v` — 점수·등급·이모지 hygiene 통과. 기존 골드는 레지스트리 미주입 환경에서 생성되므로 섹션 무출력 → 골드 변경 없음이 기대값.

## 문서 갱신

- `CLAUDE.md`: 도구 1·4 설명에 레지스트리 역방향 대조 섹션 한 줄 추가, 핵심 내부 함수 표에 `lookup_actors_by_company` 추가.
- `README.md`: 해당 도구 설명에 "공개기록 참고 섹션(레지스트리 opt-in 시)" 언급 — 포지셔닝 문구는 "공시 기반 불공정거래 위험 모니터링" 범위 유지.
