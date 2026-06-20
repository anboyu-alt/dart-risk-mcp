# 조회 기간 다년 확장 설계 (multi-year lookback)

- 작성일: 2026-06-20
- 상태: 설계 확정 (구현 전)

## 문제

`analyze_company_risk`, `build_event_timeline`, `list_disclosures_by_stock`,
`check_disclosure_anomaly` 4개 도구의 공시 조회 기간이 `lookback_days`로
받되 `min(max(x, 1), 365)`로 **1년에 강제 클램프**된다. 사용자가 더 긴 기간을
넣어도 365일로 잘려, 다년에 걸친 위기 사이클(자금조달 → 경영권 변동 → 부실)을
한 번에 보기 어렵다.

`lookback_years` 기반 도구들(`find_actor_overlap`, `track_capital_structure`,
`track_insider_trading`, `get_audit_opinion_history` 등)은 이미 1~5년(감사이력
1~10년)까지 열려 있어 문제 없음. 본 작업은 위 **4개 도구만** 대상으로 한다.

추가로 코어 함수 `fetch_company_disclosures`는 `while page_no <= 10`
(100건/페이지 × 10 = **1000건**) 하드코딩 상한이 있어, 다년 조회 시 활성
기업은 일부 공시가 조용히 누락될 수 있다.

## 결정 사항 (확정)

1. **인터페이스 통일**: 4개 도구를 `lookback_years: int = 1` (범위 1~5)로 교체.
   `lookback_days` 파라미터는 제거. 1년 미만 세분 조회(예: 90일)는 포기하고
   기본값을 1년으로 통일(사용자 합의).
2. **페이지 상한 상향**: 코어 함수의 1000건 상한을 다년 조회에 맞춰 상향.
3. **토큰 안내 푸터**: `lookback_years > 1`일 때만 결과 하단에 예상 출력 규모를
   표기(외부 라이브러리 없이 문자 수 휴리스틱).

## 설계

### 1. 도구 인터페이스 통일 (`dart_risk_mcp/server.py`)

| 도구 | 변경 전 | 변경 후 |
|------|---------|---------|
| `analyze_company_risk` | `lookback_days=90` (cap 365) | `lookback_years=1` (1~5) |
| `build_event_timeline` | `lookback_days=365` (cap 365) | `lookback_years=1` (1~5) |
| `list_disclosures_by_stock` | `lookback_days=90` (cap 365) | `lookback_years=1` (1~5) |
| `check_disclosure_anomaly` | `lookback_days=365` | `lookback_years=1` (1~5) |

- 각 도구 진입부에서 `lookback_years = min(max(lookback_years, 1), 5)`로 검증 후
  `lookback_days = lookback_years * 365`로 환산해 기존 코어 함수에 전달.
  → 코어 호출 시그니처는 그대로 유지(변경 최소화).
- 출력 기간 라벨은 코드베이스에 이미 있는 `find_actor_overlap` 관례를 재사용:
  `window_label = "최근 365일" if lookback_years == 1 else f"최근 {lookback_years}년"`.
  1년일 때 기존 "최근 365일" 문구를 유지해 골드 호환을 확보하고, 다년은 정직 표기.
- `analyze_company_risk`의 연수 계산(현 `lookback_days // 365 + 1`, server.py:258)은
  `lookback_years`를 직접 사용하도록 단순화.
- docstring의 "기본 90일, 최대 365일" 류 문구를 "기본 1년, 1~5년"으로 갱신.

### 2. 코어 페이지네이션 상한 상향 (`dart_risk_mcp/core/dart_client.py`)

`fetch_company_disclosures(corp_code, api_key, lookback_days=90)`에
`max_pages: int = 10` 파라미터를 추가하고 `while page_no <= 10`을
`while page_no <= max_pages`로 교체.

- 기본 `max_pages=10` → 기존 호출부(90일·기타 호출) 하위호환 유지.
- 다년 조회 호출부는 `max_pages = lookback_years * 10` 전달
  (5년 → 50페이지 → 최대 5000건). 짧은 스캔은 그대로 저렴, 다년만 깊게.
- 기존 `time.sleep(0.25)` throttle과 초과 누락 경고 로그(`log.warning`)는 유지해
  DART 호출 한도를 보호. 경고 메시지의 "1000건" 하드코딩 문구는 `max_pages*100`
  기준으로 일반화.

기존 `lookback_years` 기반 호출부(track_capital_structure 등 `lookback_years*365`로
부르는 곳)도 동일한 `max_pages` 인자를 넘기면 다년 누락이 줄어든다(선택 반영).

### 3. 토큰 안내 푸터 (`years > 1`일 때만)

- 소형 헬퍼 `_estimate_output_size(text) -> tuple[int, int]` 추가:
  문자 수와 대략적 토큰 수를 반환. 토큰은 문자 기반 휴리스틱
  (예: `tokens ≈ ceil(len(text) / 2.5)`)으로 산출하며, 정밀 토크나이저가 아님을
  명시. 외부 의존성 없음.
- 4개 도구에서 최종 렌더 문자열을 만든 뒤, `lookback_years > 1`인 경우에만
  한 줄 푸터를 덧붙인다:
  `📊 예상 출력 규모: 약 {chars:,}자 / ~{tokens:,}토큰 (대략적 추정)`
- `years == 1`(기본) 경로는 출력이 바뀌지 않으므로 기존 골드에 영향 없음.

### 4. 비범위 / 원칙 준수 확인

- 점수·등급 부여 아님(v0.8.5 원칙 유지). 토큰 푸터는 위험도 정량화가 아닌
  출력 메타 정보이므로 원칙과 무관.
- 외부 라이브러리 추가 없음(`requests`+`mcp`만 — 토큰 추정은 순수 산술).

## 영향 범위 / 부수 작업

- **문서**: `CLAUDE.md`(도구 카탈로그 4개 항목의 파라미터·기본값),
  `README.md`, `tests/fixtures/sample_outputs/README.md`(lookback 표기).
- **골든**: `scripts/regen_goldens.py`로 재생성 후
  `tests/test_golden_output_hygiene.py` 9/9 PASS 회귀 검증.
- **테스트 호환**: 테스트 `.py`에서 4개 도구를 `lookback_days` 키워드로 직접
  호출하는 곳은 없음(확인 완료 — 매칭은 `find_actor_overlap`과 코어 함수
  시그니처뿐). 코어 함수의 `lookback_days` 시그니처는 유지되므로
  `test_find_actor_overlap.py`의 mock(`def _disclosures(corp_code, api_key, lookback_days)`)은
  영향 없음. 단, `max_pages` 기본 인자 추가는 기존 호출과 호환됨.

## 성공 기준

1. 4개 도구가 `lookback_years` 1~5를 받아 다년 공시를 실제로 스캔한다
   (라이브 또는 mock으로 `fetch_company_disclosures`에 전달된
   `lookback_days == years*365`, `max_pages == years*10` 검증).
2. `years == 1` 출력이 기존 골드와 동일(라벨 "최근 365일" 유지).
3. `years > 1` 출력에만 토큰 안내 푸터가 1줄 추가된다.
4. `python -c "import dart_risk_mcp.server"` 정상 import.
5. `tests/test_golden_output_hygiene.py` 9/9 PASS.
6. 문서 3종 갱신 완료.
