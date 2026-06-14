# 설계: 워치리스트 (인물↔회사군 영속 매핑 + manage_watchlist)

- 날짜: 2026-06-14
- 범위: 2단계 (1단계 임원 겸직 흡수는 PR #1로 완료)
- 상태: 사용자 리뷰 대기

## 배경 / 문제

`find_actor_overlap`의 근본 제약: DART API는 인물명 역검색이 불가능해, 분석할
회사 목록을 매번 직접 입력해야 한다. 감시 대상 인물(예: 신승수)의 연관 회사군은
시간이 지나며 바뀌고, 매번 손으로 회사명을 나열하는 것은 비효율적이다.

해법: 인물명↔회사군 매핑을 **영속 데이터 파일**로 저장하고, 이를 관리하는 MCP
도구(`manage_watchlist`)와 `find_actor_overlap` 연동을 추가한다. CASSANDRA AI의
주식셀럽 위키를 MCP 서버 아키텍처에 맞게(웹 페이지가 아니라 데이터 파일 + 도구)
구현한 것이다.

## 아키텍처 결정

1. **페이지가 아니라 데이터+도구:** 우리는 UI 없는 stdio MCP 서버다. 영속 JSON
   파일 + MCP 관리 도구로 구현한다.
2. **저장 + 수동 조회까지만:** 실시간 알림·자동 스캔은 영구 비범위(정책 유지).
   저장된 명단을 사용자가 부를 때만 조회한다.
3. **흡수 우선:** 조회는 새 도구를 만들지 않고 기존 `find_actor_overlap`에
   `watchlist` 파라미터로 흡수. 관리 도구 `manage_watchlist` 1개만 신설(24개째).
4. **순수 파일 I/O 모듈 분리:** 저장 로직은 `core/watchlist.py`로 분리(requests
   무관, 독립 테스트 가능).

## 컴포넌트

### 신규: `core/watchlist.py` (순수 파일 I/O)

저장 위치: `~/.config/dart-risk-mcp/watchlist.json`. 환경변수
`DART_WATCHLIST_PATH`로 오버라이드(테스트·커스텀).

파일 구조:
```json
{
  "version": 1,
  "persons": {
    "신승수": {
      "companies": ["CG인바이츠", "제이케이시냅스", "헬스커넥트", "티쓰리"],
      "note": "코스닥 다수 등기임원 겸직",
      "updated": "2026-06-14"
    }
  }
}
```

함수:
- `_watchlist_path() -> Path` — 환경변수 우선, 없으면 기본 경로
- `load_watchlist() -> dict` — 파일 없거나 JSON 손상 시 `{"version": 1, "persons": {}}` 반환(예외 비전파)
- `save_watchlist(data) -> None` — 부모 디렉토리 생성 후 UTF-8 JSON 기록(ensure_ascii=False)
- `add_person(person, companies, note="") -> dict` — 기존 인물이면 companies를 **합집합 병합**(순서 보존), note는 비어있지 않으면 갱신, updated 갱신. 반환: 갱신된 인물 엔트리
- `remove_person(person) -> bool` — 삭제 성공 여부
- `get_person_companies(person) -> list[str]` — 인물의 회사군(없으면 빈 리스트)
- `list_persons() -> list[tuple[str, int]]` — [(인물명, 회사수)] 정렬 목록

날짜는 MCP 서버 런타임에서 `datetime.now().strftime("%Y-%m-%d")` 사용(서버는
일반 런타임이라 제약 없음). 단위 테스트는 `DART_WATCHLIST_PATH`를 tmp 경로로
패치해 실제 홈 디렉토리를 건드리지 않는다.

### 신규 도구: `server.manage_watchlist(action, person="", companies=None, note="")`

- `action` 허용값: `list` | `show` | `add` | `remove`
- `list` — `list_persons()` 결과를 "인물명 — N개사" 형식으로 렌더
- `show` — `get_person_companies(person)` + note를 렌더. 없으면 안내
- `add` — person·companies 필수 검증 → `add_person` → 병합 결과 렌더("N개사로 갱신")
- `remove` — `remove_person` → 성공/없음 렌더
- 입력 검증: action 유효성, add 시 person 비어있지 않음·companies 1개 이상
- 점수·등급 없음 원칙 유지(사실 표기만)

### 변경: `find_actor_overlap(company_names=None, lookback_years=1, watchlist="")`

- `watchlist` 지정 시 `get_person_companies(watchlist)`로 회사군 로드 →
  `company_names`와 **합집합**(순서 보존, 중복 제거)으로 분석 대상 구성
- watchlist 이름을 못 찾으면(빈 회사군) 안내 1줄 추가
- 합산 후 2~5개 범위 검증은 기존 로직 재사용. 합집합이 5개 초과면 기존
  "2~5개" 입력 오류 메시지로 안내(과대 입력 방지)
- `company_names`만 주는 기존 호출은 그대로 동작 — 하위호환, 골드 불변
- `company_names` 기본값을 `None`으로 두되 내부에서 `[]`로 정규화(가변 기본값 회피)

## 데이터 흐름

```
manage_watchlist(add, "신승수", [회사군])  →  watchlist.json 영속 저장
                                                      │
find_actor_overlap(watchlist="신승수")  →  get_person_companies  →  회사군 로드
                                                      │
                          기존 인수자+임원 겸직 분석 → 호스트 Claude 추론
```

전형적 흐름: 1단계 임원 겸직 결과(신승수 3개사) → `manage_watchlist(add, ...)`로
저장 → 이후 `find_actor_overlap(watchlist="신승수")`로 재조회.

## 오류 처리

- 파일 없음/JSON 손상 → 빈 워치리스트(예외 비전파, 기존 원칙)
- `save_watchlist` 디렉토리 생성 실패 등은 도구 레벨에서 안내 메시지로 degrade
- 동시성: stdio 단일 프로세스 가정, 파일 락 불필요(YAGNI)

## 테스트 (TDD)

`core/watchlist.py` 단위 (`DART_WATCHLIST_PATH`를 tmp로 패치):
1. add → load round-trip (회사군·note·updated 보존)
2. add 재호출 시 companies 합집합 병합(중복 제거·순서 보존)
3. remove_person 성공/실패
4. load: 파일 없음 → 빈 구조, 손상 JSON → 빈 구조(예외 없음)
5. get_person_companies: 미등록 → []

`manage_watchlist` 도구:
6. add → list → show → remove 시나리오, 각 렌더 검증
7. 입력 검증: 잘못된 action, add 시 person/companies 누락

`find_actor_overlap` 연동:
8. watchlist 지정 → 저장된 회사군 로드되어 분석(fetch 호출이 해당 회사로 일어남)
9. watchlist + company_names 합집합
10. watchlist 미등록 이름 → 안내 메시지

라이브: 신승수 회사군을 add 후 `find_actor_overlap(watchlist="신승수")` →
1단계와 동일한 겸직 결과 재현.

## 비범위

- 실시간 알림·일일 자동 스캔 — 영구 비범위
- 회사군 자동 발굴(DART 역검색 불가) — 사용자/Claude가 채움
- 특정 회사만 부분 제거 — 인물 단위 삭제만(YAGNI). 필요 시 add로 덮어쓰기
- 점수·등급 부여 — v0.8.5 원칙

## CLAUDE.md 갱신 항목

- 도구 목록에 `manage_watchlist` 추가(24개로)
- 도구 #5 `find_actor_overlap`에 `watchlist` 파라미터 반영
- 핵심 내부 함수/모듈에 `core/watchlist.py` 추가
- 캐시/저장 구조 표에 `watchlist.json`(영속, 비휘발) 추가
- 디렉토리 구조에 `core/watchlist.py` 추가
