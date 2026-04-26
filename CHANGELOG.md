# Changelog

[Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 형식 준수. 버전은 [SemVer](https://semver.org/lang/ko/).

## Stability / Deprecation Policy (v1.0 GA부터 발효)

본 정책은 v1.0.0 GA에서 발효합니다. 마이너 릴리스(1.x)는 사용자에게 노출되는 모든 표면을 stable contract로 간주하며, 다음 규칙을 따릅니다.

### Stable contract 표면

1. **MCP 도구 시그니처** — 23개 도구의 함수명·파라미터명·기본값·반환 타입.
2. **사용자 출력 형식** — 첫 줄 패턴, 핵심 헤더, 한국어 표기 원칙(점수·등급·이모지·내부 flag·영문 약어 노출 금지). `tests/test_golden_output_hygiene.py` 9종 검증으로 기계적으로 보장.
3. **신호 키 카탈로그** — `SIGNAL_TYPES[*].key`, `SIGNAL_KEY_TO_TAXONOMY` 매핑, taxonomy ID(N.M) 체계.
4. **CLI 인터페이스** — `python -m dart_risk_mcp` 진입점·환경변수 `DART_API_KEY`·`scripts/regen_goldens.py` 인자.

### 변경 분류 + 최소 절차

| 변경 유형 | SemVer 영향 | 절차 |
|----------|:-:|------|
| 도구 시그니처 변경(파라미터 추가·이름 변경·기본값 변경) | minor | 최소 **1 minor 버전 동안 별칭(alias) 유지** + CHANGELOG `### Deprecated` 섹션 표기. 별칭 제거는 다음 minor에서. |
| 도구 제거 | major | CHANGELOG `### Removed` + 직전 minor에서 `### Deprecated` 1회 이상 공지 선행. |
| 사용자 출력 형식 변경(첫 줄·핵심 헤더·표기 원칙) | **major 또는 minor + 명시 공지** | hygiene 9종 회귀가 깨지는 변경은 stable output contract 위반. 의도적 변경 시 CHANGELOG `### Output Contract Change` 섹션으로 명시 + 골드 파일 일괄 갱신. |
| 신호 키 추가(`SIGNAL_TYPES`에 새 key) | minor | contract 변경 아님(추가 정보). CHANGELOG `### Added`. |
| 신호 키 제거 또는 라벨 변경 | minor | CHANGELOG `### Removed` 또는 `### Changed` + 직전 minor에서 `### Deprecated` 공지 권장. |
| MCP 도구 신규 추가 | minor | CHANGELOG `### Added`. **단, 도구 인플레이션 회피 — 흡수 우선**(v0.9.0 `analyze_company_risk` 부실 후속 흡수 사례 참고). |
| 내부 헬퍼·렌더러·캐시 구조 변경 | patch / minor | 출력 형식이 깨지지 않으면 contract 영향 없음. hygiene PASS 시 자유. |

### 비범위는 영구 비범위

[README.md](README.md) "이 도구가 하지 않는 것" 7개 항목은 v1.0 이후 어떤 마이너 릴리스에서도 도입하지 않습니다. 우회 PR은 거절됩니다.

---

## [Unreleased]

## [1.0.1] — 2026-04-26

**메인 메시지: v1.0 GA 후속 인프라 검증 종결.** 코드 변경 0(서버·도구·핵심 헬퍼). v1.0 GA 직후 분리한 인프라 검증 4건을 모두 종결하고 결과를 docs에 기록한다.

### Verified

- **PyPI 패키지명 `dart-risk-mcp` 사용 가능** — `https://pypi.org/pypi/dart-risk-mcp/json` HTTP 404 확인. `dart-risk-mcp-kr`(백업명)도 사용 가능. 정식 업로드는 사용자가 PyPI 토큰으로 `python -m twine upload dist/*` 실행.
- **빌드 무결성** — `python -m build` → `dart_risk_mcp-1.0.0-py3-none-any.whl`(170 KB) + `dart_risk_mcp-1.0.0.tar.gz`(502 KB) 생성. `python -m twine check dist/*` PASSED.
- **`fetch_market_disclosures` `pblntf_ty` 재검증** — A·B·C·D·E·F·G·H·I·J 10개 코드 모두 정상 응답(B 190건·C 659건·D 619건 등). v1.0 검증 시 보고된 빈 응답 이슈는 재현되지 않음 — 검증 종결, 코드 변경 불필요.

### Removed (영구 비범위)

- **DS007 증권신고서(`bdRs`·`mgRs`) 통합 폐기** — 5개 대형 회사(셀트리온·두산에너빌리티·셀트리온헬스케어·삼성바이오로직스·SK하이닉스) 2024-01-01 ~ 2026-12-31 3년 윈도우 모두 0건. iridescent plan #11에서 빈도 미확인으로 보류했던 항목을 영구 비범위로 확정. README "이 도구가 하지 않는 것" + CLAUDE.md "비범위" 표에 추가.

### Notes

- v1.0 GA stable contract(도구 23개·출력 형식·신호 키·CLI) 그대로 유지.
- 이번 릴리스로 iridescent plan v1.0.1 이관 4항목 모두 종결(GitHub Release 페이지 생성 포함).

## [1.0.0] — 2026-04-26 (GA)

**메인 메시지: 출력 표준의 계약화.** 새 MCP 도구 0개. v0.7.x~v0.9.0 동안 다듬어진 한국어 출력 형식이 마이너 릴리스에서도 깨지지 않음을 기계적으로 보증한다. 도구 카탈로그 23개 그대로 유지.

### Added — 골드 다양화

- **`scripts/regen_goldens.py`** 영구 승격 — `tmp/v1_feasibility/regen_v0XX.py` 4개 임시 패턴을 단일 진입점으로 통합. 6개 카테고리 회사 × 23개 도구 매트릭스를 코드에 명시. argparse CLI(`--companies`, `--tools`, `--dry-run`, `--quiet`).
- **6개 회사 카테고리 추가** — 셀트리온(대형주·바이오), 제이스코홀딩스(중소형·위험사례), 두산에너빌리티(대형 자회사·채무), 삼성전자(대형주 표준·페이지네이션), 헬릭스미스(관리종목·부실), 두산(지주사). iridescent plan 라인 211 사용자 승인.
- **rcept 자동 추출** — `analyze_company_risk` 결과의 첫 정상 공시(정정 제외) `rcept_no`를 자동 파싱해 4개 rcept 인자 도구(check_disclosure_risk·get_disclosure_document·list_disclosure_sections·view_disclosure)에 적용.
- **DS005 자동 탐지** — 회사별 DS005 키워드(타법인주식·합병·분할·영업양수도 등) 1건 자동 탐지(미발견 시 콘텐트 경고만, 발견 시 `decision_{rcept}.txt` 생성). v1.0 시점 6 회사 모두 미발견 — v1.0.1 데이터 가용성 추가 검증으로 이월.
- **회사 무관 도구** — `find_actor_overlap`(6 회사 한 번), `compare_financials`(6 회사 한 번), `find_risk_precedents`(신호 키 조합 3종), `search_market_disclosures`(preset 4종) 매트릭스 통합.
- **골드 파일 119개** — `tests/fixtures/sample_outputs/`에 24개 → 119개로 다양화.
- **`CLAUDE.md` "자주 있는 작업"** 절에 골드 재생성 명령 1단락 추가.

### Added — Stable Output Contract (hygiene 검증 3종)

- **`test_first_line_format_per_tool`** — 23개 단축명별 첫 줄 정규식 매핑(`_FIRST_LINE_PATTERNS`). 회사명 단순 13개 + 종목코드 1개 + rcept 4개 + 회사 무관 4개 + 기존 disclosure 1개. `_short_name(fname)` 헬퍼가 파일명 → 단축명 자동 추출(rcept 8자리 suffix 제거).
- **`test_core_headers_preserved`** — 사용자가 학습한 핵심 헤더 8종(`**시계열**`, `**전년 대비 추세 (DART 재무지표 기준)**`, `**공시 원문 목차**`, `**공시 원문**`, `**공시 리스크 분석**`, `**① 정정공시 비율**`, `**③ 공시의무 위반**`, `**⑤ 조회공시 빈도**`)이 골드 전체에서 살아 있어야 한다.
- **`test_no_unknown_internal_code_parens`** — v0.8.7에서 발견한 `(CAPITAL_CHURN)` 등 내부 flag 코드 괄호 인용 회귀 차단. 정규식 `\([A-Z][A-Z_]+\)` 매칭 + `_ALLOWED_PAREN_ABBREVS` 화이트리스트(CB·BW·EB·RCPS·IR·PE·MFDS·FSC·ROE·EBITDA·OECD·IFRS 등 24종) 외 모든 영문 코드 괄호 인용을 fail.

### Changed

- **hygiene 임계 ≥10 → ≥100** — `test_fixture_set_non_empty`. v1.0 GA 119개 골드 기준 충족.
- **README.md 비범위 절 신설** — "이 도구가 하는 것"(23 도구 6 그룹 분류) + "이 도구가 하지 않는 것"(7 영구 비범위 — 점수·등급/실시간 알림/매수 추천/업종 평균/해외상장/비상장 감사/시장 일일 자동 스캔). v0.7.x~v0.9.0 마이너 변경 5개 절·11개 릴리스 요약은 본 CHANGELOG로 일임.
- **CLAUDE.md "비범위" 표 신설** — 7항목 + 사유/검증 출처 컬럼. 도구 인플레이션 회피 안내.
- **CHANGELOG에 Stability/Deprecation Policy 명문화** — Stable contract 4표면(도구 시그니처·출력 형식·신호 키·CLI) 정의 + 변경 분류 7유형별 SemVer 영향·최소 절차 표. v1.0 GA부터 발효.
- **pyproject.toml** Development Status 분류 `3 - Alpha` → `5 - Production/Stable`.

### Removed

- `tmp/v1_feasibility/regen_v0{86,87,88,90}.py` 4개 임시 스크립트 — `scripts/regen_goldens.py` 단일 진입점으로 흡수 후 삭제.

### Notes

- **신규 MCP 도구 0개** — v1.0의 메인 메시지는 "새 기능 0개, 출력 표준 계약화"였음.
- **v1.0.1 이관 항목**: (1) DS007 데이터 가용성, (2) `fetch_market_disclosures` 호출법 점검(`pblntf_ty=B`/`C` 빈 응답), (3) PyPI 패키지명 점유 확인. iridescent plan 라인 142 분리 결정.
- **회귀 검증**: hygiene 9/9 PASS · 전체 157/157 PASS(DART_API_KEY 세팅 시).

## [0.9.0] — 2026-04-26

### Added
- **`fetch_distress_events(corp_code, api_key, lookback_years=3)`** — 부실 후속 4개 엔드포인트 통합:
  - `dfOcr`(부도발생) → `subtype="default"` (df_cn·df_amt·df_bnk 요약)
  - `bsnSp`(영업정지) → `subtype="business_susp"`
  - `ctrcvsBgrq`(회생절차 개시신청) → `subtype="rehabilitation"`
  - `dsRsOcr`(해산사유 발생) → `subtype="dissolution"`
  - 각 이벤트에 `key="DISTRESS_EVENT"` + 한글 `summary` 부착. rcept_dt 폴백·부분 실패 격리·캐시(20건/600초).
- **`fetch_dividend_history(corp_code, api_key, lookback_years=3)`** — `alotMatter`(배당에 관한 사항)을 분기 4코드 × N년 호출. 각 record에 `bsns_year`/`reprt_code` 부착.
- **`detect_dividend_drain(dividend_records, current_fs)`** — 적자 시점 배당 유출(DIVIDEND_DRAIN) 패턴 검출. 당기순이익 음수 + "주당 현금배당금" 양수 동시 발생 시 flag 부여. 분기 4회 호출 노이즈 dedup.
- **신호 키 2종 신규** (점수 가산 없음, 사실 표기만 — v0.8.5 원칙):
  - `DISTRESS_EVENT` (taxonomy 8.5) — 부실 단계 진입(부도/영업정지/회생/해산)
  - `DIVIDEND_DRAIN` (taxonomy 5.6) — 적자 시점 배당 유출
- **`tests/test_distress_dividend_v090.py`** — 14개 테스트.
- **골드 파일 6개 재생성** — 3개 기업 × {`_analyze.txt`, `_fund_usage.txt`}. `_fund_usage.txt`는 신규.

### Changed
- **`analyze_company_risk` 흡수** — `fetch_distress_events` 결과를 자동 통합. 발생 시 하단에 "**부실 단계 진입 — 주요사항보고서 발생**" 경고 블록과 일자별 사건 라인 추가. 점수 가산 없음.
- **`track_fund_usage` 보강** — 출력 하단에 "**배당 이력 (alotMatter)**" 블록 신설. 분기 4회 호출 dedup, 최근 사업연도 재무로 `detect_dividend_drain` 호출 후 적자 시점 배당이면 경고 라인 추가.

### Notes
- 신규 도구 추가 없음 — 도구 23개 그대로 유지(원 plan에서 검토했던 `track_distress_progression` 단독 도구는 빈도 낮음으로 폐기, 흡수 방식 채택).
- v1.0 로드맵 검증 결론에 따른 흡수 결정.

## [0.8.8] — 2026-04-26

### Added
- **`fetch_company_indicators(corp_code, api_key, bsns_year, reprt_code="11011")`** — 단일회사 주요 재무지표(`fnlttSinglIndx`)를 4개 카테고리로 호출해 합친 flat dict 반환:
  - `M210000` 수익성 / `M220000` 안정성 / `M230000` 성장성 / `M240000` 활동성
  - `idx_val=None` 또는 숫자 변환 불가 항목은 자동 제외, 일부 cl_code 실패는 격리.
  - 인메모리 LRU 캐시(`_company_indicators_cache`, 최대 40건, TTL 600초).
- **`detect_financial_anomaly`에 `current_indx` / `prior_indx` 옵션 추가** — 기존 4개 절대 임계 판정에 더해 핵심 7종 지표(순이익률·자기자본비율·부채비율·유동비율·매출액증가율·매출채권회전율·재고자산회전율)에 대해 YoY 변동률(delta_pct)을 metric에 부착. **flagged=False 유지**(절대 임계 없음, 사실 표기만).
- **`scan_financial_anomaly` 출력에 "전년 대비 추세 (DART 재무지표 기준)" 블록 신설** — 핵심 지표를 `12.30%p → 8.10%p (전년 대비 -34.1%)` 형식으로 한국어 표기. 기존 4지표 본 표(절대 임계 기준)와 분리.
- **`tests/test_financial_indx_v088.py`** — 8개 테스트(엔드포인트 통합·무효 값 스킵·부분 실패 격리·detect 옵션 호환·YoY 계산·분모 0 처리).

### Changed
- **v1.0 로드맵 #6 재정의 반영** — 원래 plan은 "업종 평균 정규화"였으나, 검증 결과 `fnlttSinglIndx`·`fnlttCmpnyIndx` 둘 다 단일 회사 지표만 반환하고 DART API가 업종 평균을 직접 제공하지 않음을 확인. 따라서 **회사 자체 YoY 추세**로 재정의해 false-positive를 완화. 절대 임계값(AR_SURGE ≥10%p 등)은 폴백으로 유지.

### Notes
- 도구 23개 그대로 유지(신규 도구 추가 없음).
- "업종 평균 대비 +Xσ" 표기는 v1.0 이후로도 영구 비범위(외부 데이터 의존성).

## [0.8.7] — 2026-04-25

### Added
- **`fetch_treasury_decisions(corp_code, api_key, lookback_years=3)`** — 자사주 결정 4개 엔드포인트 통합 조회:
  - `tsstkAqDecsn`         → `key=TREASURY`, `decision_type=acq` (자사주 취득 결정)
  - `tsstkDpDecsn`         → `key=TREASURY`, `decision_type=disp` (자사주 처분 결정)
  - `tsstkAqTrctrCnsDecsn` → `key=TREASURY_TRUST`, `decision_type=trust_cons` (신탁계약 체결)
  - `tsstkAqTrctrCcDecsn`  → `key=TREASURY_TRUST`, `decision_type=trust_canc` (신탁계약 해지)
  - 응답 누락 시 `rcept_no[:8]`로 `rcept_dt` 폴백, 일부 엔드포인트 실패는 격리.
  - 인메모리 LRU 캐시(`_treasury_decisions_cache`, 최대 20건, TTL 600초).
- **신호 키 `TREASURY_TRUST` (taxonomy `2.8`)** — 자사주 신탁 우회 매입 경로. base_score 0, severity OBSERVATION. `NON_DILUTIVE_CAPITAL_EVENTS`에 포함.
- **`signal_to_prose("TREASURY_TRUST")`** — "자사주 신탁계약 체결 또는 해지 공시입니다…" 한국어 해설.
- **`tests/test_treasury_decisions_v087.py`** — 12개 테스트(엔드포인트 정규화·rcept_dt 폴백·부분 실패 격리·캐시·신호 등록·detect_capital_churn 12개월 카운팅).
- **골드 파일 9개 재생성** — 셀트리온/제이스코홀딩스/두산에너빌리티 × {`_capital.txt`, `_analyze.txt`, `_timeline.txt`}.

### Changed
- **`track_capital_structure` — 키워드 매칭 의존을 줄이고 결정 공시 구조화 데이터로 보강**:
  - `match_signals`로 키워드 매칭한 자본 이벤트에 더해 `fetch_treasury_decisions` 결과를 자동 머지.
  - 기존 키워드 매칭으로 잡힌 동일 `rcept_no`는 중복 방지(`_existing_rcept` set).
  - 결정 이벤트는 `report_nm`이 `"자사주 취득 결정"` 등 한글 라벨로 노출.
- **`detect_capital_churn` 12개월 윈도우 카운팅** — 입력에 결정 공시가 자동으로 포함되므로 별도 코드 변경 없이 정확도 상승. `TREASURY_TRUST`는 `NON_DILUTIVE`로 분류돼 비희석 카운트에만 합산.

### Notes
- v1.0 로드맵 검증(`tmp/v1_feasibility/REPORT.md`) 결론에 따라 무상증자(`fricDecsn`)·유무상증자(`pifricDecsn`)·감자(`crDecsn`) 결정은 본 릴리스 범위에서 **제외**. 빈도가 낮아 v1.0 이후로 이월.
- 도구 개수 23개 그대로 유지(신규 도구 추가 없음).

## [0.8.6] — 2026-04-25

### Added
- **`fetch_insider_timeline` 분기 보고 데이터 통합** — 기존 `elestock`(5% 대량보유) + `hyslrSttus`(연 단위 최대주주)에 더해 신규 두 엔드포인트를 4개 분기 코드(`11011`·`11012`·`11013`·`11014`) × N년 루프로 통합:
  - `hyslrChgSttus` (최대주주 변동현황) — 분기별 보유 변동 보고
  - `tesstkAcqsDspsSttus` (임원·주요주주 자기주식 취득·처분 현황) — 회사 자기주식 활동
  - 각 record에 `source` 라벨(`elestock`·`hyslr`·`hyslr_chg`·`exec_treasury`) 부착, `bsns_year`·`reprt_code` 보존.
- **`detect_insider_pre_disclosure(insider_records, signal_events, window_days=30)`** — 매도 이벤트(Δ<0) 직후 ±30일 내 부정 공시(AUDIT/INSOLVENCY/EMBEZZLE/INQUIRY/GOING_CONCERN/DISCLOSURE_VIOL/DEBT_RESTR) 동시 발생 패턴 탐지 함수. 점수 가산 없음, 사실 표기만(v0.8.5 원칙).
- **신호 키 `INSIDER_PRE_DISCLOSURE` (taxonomy `3.6`)** — `signals.py`/`taxonomy.py` 신규 등록. base_score 0, severity OBSERVATION.
- **`tests/test_insider_v086.py`** — 13개 테스트(엔드포인트 통합·source 라벨·분기 4코드 호출·부분 실패 격리·detect 패턴·신호 등록).
- **골드 파일 3개 신규** — `셀트리온_insider.txt`/`제이스코홀딩스_insider.txt`/`두산에너빌리티_insider.txt`.

### Changed
- **`track_insider_trading` 렌더러 — 출력 품질 보정**:
  - source별 적절한 holder/ratio/date 필드 추출 헬퍼(`_extract_row`) 추가.
  - 합산 행("계"·"합계"·"Total"·"-"·빈값) 시계열에서 제외.
  - 인접 분기 동일 비율(<0.005%p 차이) **dedup** — 분기 4회 호출 노이즈 억제.
  - `lookback_years × 365`일 **윈도우 필터** — `hyslrChgSttus`가 전체 이력을 반환해도 윈도우 외 데이터는 제외.
  - `exec_treasury`(회사 자기주식 활동)는 보고자별 시계열에서 분리. 하단 안내로 `track_capital_structure` 연동 표시(예정).
  - source 라벨에 `최대주주 변동`·`임원·주요주주 자기주식` 신규 추가.

### Notes
- v1.0 로드맵 검증(`tmp/v1_feasibility/REPORT.md`) 결론에 따라 "이벤트 단위 거래 추적" 표현은 **분기 보고 단위**로 정정. DART API는 임원 거래일 단위 시계열을 직접 제공하지 않습니다.
- `tesstkAcqsDspsSttus` 응답은 회사 자기주식 활동(취득방법별 분류)이라 v0.8.6에서는 시계열 표기에서 제외하고 v0.8.7(자사주 결정 통합)에 흡수합니다.

## [0.8.5] — 2026-04-25

### Design Principle (신규 확정)
- **점수·등급 없음 원칙 확정** — 기업의 위험도를 정량화하거나 등급을 부여하는 모든 표기를 사용자 출력에서 제거합니다. 공시 기록에서 관찰된 **사실(건수·비율·날짜·공시명)**만 서술하며, 도구 작성자는 기업에 대한 정성·정량 평가의 권위자가 아닙니다. 내부에서는 `SIGNAL_TYPES[*].score`·`taxonomy.base_score`를 신호 우선순위 랭킹 목적으로 계속 사용하지만, 출력 경계를 절대 넘지 않습니다.

### Removed
- **`analyze_company_risk`** — "🔴 **위험 등급: 매우위험** (45점)" 헤더 라인 제거. 상단 요약의 둘째 문장을 "이 도구는 공시 기록에서 관찰된 사실만 서술합니다. 기업의 위험도를 정량화하거나 등급을 부여하지 않으며, 법적 판단이나 투자 결정의 근거가 아닙니다." 로 교체. 이벤트 리스팅의 ` · N점` 꼬리표 제거.
- **`find_risk_precedents`** — "🟠 이 신호 조합의 종합 위험도는 **고위험**입니다." 마감 라인 제거.
- **`check_disclosure_anomaly`** — "종합 스코어 N/100" 상단 라인과 각 지표 헤더의 "N/25점" 꼬리표 제거. 5개 구조 지표는 건수·비율만 나열. 감사의견 가산점(`+5점`/`+3점`)도 경고 문구만 남기고 점수 표기 제거. `total_score`·`grade`·`s_amend`·`s_audit`·`s_viol`·`s_capital`·`s_inquiry` 계산 전체를 삭제.
- **`build_event_timeline`** — 위상(진입기/심화기/탈출기) 이모지(🟢/🟡/🔴) 제거. `_PHASE_EMOJI` 상수 삭제. 단계 헤더는 `**[진입기] — 20250101 이후 N건**` 형태로 간소화.
- **`_risk_level`·`_risk_emoji` 헬퍼 삭제** — 더 이상 출력 경로가 없어 제거. 등급 명칭("매우위험"/"고위험"/"위험"/"주의")과 🔴🟠🟡🔵 이모지도 함께 제거.

### Added
- **`tests/test_golden_output_hygiene.py` — 점수/등급/이모지 회귀 검증 3종 추가**:
  - `test_no_score_or_grade_labels` — `\d+/\d+점`·`\d+점\s*$`·`위험 등급`·`종합 스코어`·`종합 위험도`·등급 명칭 regex 전수 검사.
  - `test_no_severity_emoji` — 🔴🟠🟡🟢🔵 이모지 전수 검사.
  - `"점" 단독 문자`는 "시점·관점·쟁점" 같은 정상 한국어와 충돌하므로 엄격한 숫자-연접 패턴으로만 검사(false-positive 방지).

### Changed
- **상단 요약 문장 표준화** — `analyze_company_risk`·`check_disclosure_anomaly`의 요약 블록에 "이 도구는 공시 기록에서 관찰된 사실만 서술합니다. 기업의 위험도를 등급화하지 않으며, 법적 판단이나 투자 결정의 근거가 아닙니다." 포지셔닝 고지를 고정 삽입.
- **이벤트 리스팅** — `• YYYY-MM-DD · 공시명` 형식으로 통일. 정정공시는 `· 정정공시(관찰 대상 제외)` 꼬리표.

### Golden File Update
- `tests/fixtures/sample_outputs/` 15개 골드 파일 전량 재생성(2026-04-25 실 API). 점수·등급·이모지 제거 후 샘플 3개 기업 출력이 v0.8.5 기준선으로 고정됨.

### Design Principles (업데이트)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.
5. **(신규) 기업 위험도를 정량화하거나 등급을 부여하지 않는다 — 관찰된 사실만 서술한다.**

## [0.8.0] — 2026-04-25

### Design Principle (확정)
- **단일 출력 원칙 확정** — v0.7.x 동안 모든 도구를 하나의 한국어 서술 출력로 통일했습니다. v0.8.0에서 expert/easy 모드 분기 가능성을 공식 폐기합니다. 향후 어떤 도구도 `level=`·`mode=`·`format=` 같은 분기 파라미터를 받지 않습니다. 사용자가 더 자세한 원시 데이터를 원하면 개별 도구(`get_disclosure_document`, `view_disclosure`, `list_disclosure_sections`)를 조합해 파이프라인을 구성합니다.

### Added — 탐지 정확도 업그레이드
- **`get_audit_opinion_history(company_name, lookback_years=5)`** (22번째 도구) — DART 감사의견 공시 3개 엔드포인트(`accnutAdtorNmNdAdtOpinion`·`adtServcCnclsSttus`·`accnutAdtorNonAdtServcCnclsSttus`)를 연도×엔드포인트 루프로 통합. 최근 5년(조정 가능 1~10년) 감사의견·감사인·연속 재직 연수, 감사인 교체 이력, 비감사용역 비중 30% 초과 연도 경고를 단일 한국어 출력으로 반환. 재직 연수는 과거→최신 방향으로 같은 감사인 연속 횟수를 누적.
- **`track_debt_balance(company_name, year="")`** (23번째 도구) — 채무증권 잔액 5개 엔드포인트(회사채·단기사채·기업어음·신종자본증권·조건부자본증권)를 통합 조회. 종류별 잔액 + 1년 이내 만기 도래 비중을 표시하며, 단기 만기 비중이 30%를 넘으면 차환 압박 경고.
- **`detect_debt_rollover(balance_history, capital_events)`** — 3년 이상 채무 잔액이 거의 변동 없이(YoY ≤ 10%) 유지되면서 해당 기간 CB 발행이 2건 이상이면 `CB_ROLLOVER` 플래그 발생. `track_capital_structure` 출력에 잔액 추이 블록으로 반영.

### Changed
- **`check_disclosure_anomaly` 지표 ② 보강** — 감사의견 이슈(20점) 집계 시, 최근 5년간 감사인 교체 2회 이상이면 +5점, 비감사용역 비중 30% 초과 연도가 있으면 +3점을 추가 가산. 근거 문장도 함께 노출(예: "⚠ 최근 5년간 감사인 교체 2회").
- **감사보수 절대 금액 표시 제거** — DART가 기업·연도별로 천원/백만원 단위를 혼용하여 신뢰할 수 있는 단위 정규화가 불가능. v0.8.0에서는 `audit_fee_okwon`·`non_audit_fee_okwon` 원시 값만 API 응답에 포함하고, 사용자 출력에는 비감사용역 **비중(%)**만 독립성 경고 섹션에서 제공.
- **`fetch_audit_opinion_history` 파싱 견고화** — ① 연도×엔드포인트 루프로 전환해 DART가 `bsns_year` 필터를 요구하는 문제 해결, ② `bsns_year` 응답 필드가 한글("제34기(당기)")이라 `stlm_dt`(결산일)로 연도 추출, ③ `mendng='-'` 폴백 체인(`adt_cntrct_dtls_mendng → real_exc_dtls_mendng`), ④ `servc_mendng`의 공백 없는 숫자 뭉침을 거부하는 엄격 정규식(`re.fullmatch(r"[\d,]+(?:\.\d+)?", line)`) + 건당 1조원 캡으로 파싱 오류 차단.
- **`track_capital_structure` 잔액 블록** — 시계열 위에 "최근 3년 채무증권 잔액 추이" 블록을 추가. 잔액이 거의 변하지 않으면서 CB 발행이 반복되면 `CB_ROLLOVER` 플래그와 함께 차환 의존 경고 문장.

### Added — 골드 파일
- `tests/fixtures/sample_outputs/셀트리온_audit_history.txt`, `셀트리온_debt_balance.txt` — v0.8.0 신규 도구 2개의 실 API 기준선.
- `tests/fixtures/sample_outputs/` 분석·사례 골드 파일 4종 갱신(카탈로그·감사 섹션 문구 변경 반영).

### Removed
- **Track C (비상장사 감사보고서 정량 추출) 공식 폐기** — DART 비상장사 감사보고서는 개별 건별 재무 XBRL이 없고, 구조화된 attachments도 제공되지 않아 정량 비교 가치가 낮다. 제안 단계에서 폐기하며 향후 릴리스에서도 재검토하지 않음.

### Design Principles (유지)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.

## [0.7.5] — 2026-04-24

### Changed
- **카탈로그 MD 본문 한글화** (`dart_risk_mcp/knowledge/manipulation_catalog/*.md` 8개 파일) — 그동안 영문으로만 남아 있던 `## N.M: English Title` / `### 정의` 본문 / `### Red Flags` 섹션을 전면 한글 번역. 제목 예: `1.1: Conversion Price Adjustment Exploitation` → `1.1: 전환가액 조정 악용`, `8.1: Engineered Insolvency` → `8.1: 인위적 부실화`. `### Red Flags` 헤더는 `### 위험 신호`로 통일. 금감원 적발 사례·법조·기존 기사 인용 블록은 원래부터 한글이라 그대로 유지.
- **`_strip_taxonomy_metadata` 필터 좁히기** (`dart_risk_mcp/core/catalog.py`) — v0.7.3에서 영문 방어 목적으로 `## N.M:` 서브섹션 전체를 제거하던 regex를 `- **Severity**` / `- **Base Score**` / `- **Crisis Timeline**` 세 줄만 핀포인트로 지우도록 축소. 결과적으로 `analyze_company_risk`·`find_risk_precedents`의 카탈로그 발췌에 한글화된 제목·정의·위험 신호 섹션이 처음으로 노출된다. 내부 전용 숫자 라벨 3종은 여전히 필터링되므로 `tests/test_golden_output_hygiene.py`의 기계적 회귀 검증은 통과.

### Added
- **v0.7.5 기준 골드 파일 재생성** (`tests/fixtures/sample_outputs/` 13개) — 카탈로그 한글화가 사용자 출력에 어떻게 스며드는지 고정. `tmp/v072_review/regen_fixtures.py`로 재수집.

### Design Principles (유지)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.

## [0.7.4] — 2026-04-24

### Changed
- **반복 prose 억제** (`analyze_company_risk`, `track_capital_structure`) — 같은 `signal_key`가 4번째부터 등장하면 `→ 한국어 해설` 라인을 생략하고 공시명·날짜·점수만 출력. 제이스코홀딩스처럼 전환사채 공시가 10건 이상 몰리는 기업에서 같은 문장이 10번 반복되던 피로감 해소. 임계값은 모듈 상단 `_PROSE_REPEAT_LIMIT = 3` 상수로 조정 가능. 영향 없는 곳: `build_event_timeline`(기존 `seen_keys` dedup으로 phase별 1회), `check_disclosure_risk`(단일 공시), `find_risk_precedents`(입력 `valid_keys` 순회).

### Added
- **골드 파일 회귀 기준선** (`tests/fixtures/sample_outputs/`) — 2026-04-24 3개 기업(셀트리온·제이스코홀딩스·두산에너빌리티) 13개 실 API 출력을 v0.7.4 기준선으로 고정. analyze×3 + timeline×3 + scan_fs×3 + list(셀트리온) + disclosure(셀트리온 첫 접수번호) + precedents(CB_BW/3PCA/SHAREHOLDER) + actor_overlap 커버. 재수집 스크립트: `tmp/v072_review/regen_fixtures.py`.
- **기계적 회귀 검증** (`tests/test_golden_output_hygiene.py`) — 골드 파일을 스캔해 ① 내부 flag 코드 10종(AR_SURGE·CAPITAL_CHURN 등), ② 카탈로그 영문 메타(`**Severity**`·`### Red Flags`·`## N.M: EnglishTitle` 헤더), ③ 영문 약어(`OCF `)가 사용자 출력에 노출되면 실패. 실 API 호출 없이 저장된 `.txt`만 검사하므로 CI에서 항상 실행 가능.

### Fixed
- **v0.7.0 시절 stale 테스트 2건 갱신** — `tests/test_v6_integration.py`와 `tests/test_find_actor_overlap.py`가 `self.assertIn("AR_SURGE"/"CAPITAL_CHURN"/"[CB, 유상증자]", out)`로 내부 코드·구(舊) 포맷 노출을 기대하던 것을 한글 라벨·현행 포맷(` · ` separator) 검증으로 갱신. 전체 81개 테스트 통과.

### Design Principles (유지)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.

## [0.7.3] — 2026-04-24

### Changed
- **실 DART API 출력 리뷰 반영 문구 다듬기** — 3개 기업(셀트리온·제이스코홀딩스·두산에너빌리티) 13개 출력 샘플을 사람이 눈으로 읽은 뒤, 내부 코드·영문 약어·어색한 반복을 제거:
  - **카탈로그 발췌 블록 한글화** (`find_risk_precedents`, `analyze_company_risk`) — `load_catalog_excerpt`가 반환하는 MD에서 `## N.M: English Title` / `- **Severity**` / `- **Base Score**` / `- **Crisis Timeline**` / `### 정의`(영문) / `### Red Flags`(영문) 블록을 regex(`_strip_taxonomy_metadata`)로 제거. 한글로 작성된 `### 금감원·금융위 적발 사례` · `### 적발 기법 종합` · `### 인용 법조` · `### 기존 현장 기사 인용` 섹션만 남김.
  - **`scan_financial_anomaly` — "OCF" 약어 제거** — 결과 표의 `순이익 X / OCF Y` 표기를 `순이익 X / 영업현금흐름 Y`로 치환(`server.py` 포매터 1곳).
  - **`analyze_company_risk` — 🎯 리드 문장 중복 해소** — `가장 무게 있는 신호는 'X'이며, X 공시입니다. ...` 꼴로 라벨과 산문 첫 문장이 같은 말을 반복하던 현상 수정. `_compose_top_signal_sentence` 헬퍼로 prose 첫 문장이 라벨 재소개형이면 생략 후 두 번째 문장부터 이어 붙임.
  - **공시 제목 내부 공백 정리** — DART 원본이 `전환가액의조정              (제4회차)`처럼 패딩된 공시명을 리스팅에 그대로 노출하던 문제 수정. `_clean_report_name`으로 2칸 이상 공백을 1칸으로 축약, 3개 렌더 지점(analyze_company_risk 이벤트, 최근 공시, build_event_timeline)에 적용.
  - **자금조달 이벤트 라벨 한글화** — `[자금:public 회차-]` 같은 디버그풍 표기를 `[자금조달(공모)]` / `[자금조달(공모) 제4회차]` 형태로 치환. `_fund_kind_korean` + `_fund_round_korean` + `_format_fund_event_name` + `_format_fund_year_prefix` 헬퍼 신설. DART API가 빈 회차를 리터럴 `"-"`로 돌려주는 케이스도 `_EMPTY_TM_VALUES` 센티넬로 흡수해 `회차-` 잔존 제거(`track_fund_usage`·`analyze_company_risk` 자금사용 블록 양쪽).

### Design Principles (유지)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.

## [0.7.2] — 2026-04-24

### Changed
- **v0.7.1 '쉬운 출력' 원칙을 남은 4개 도구로 확장** — 내부 flag/signal/pattern 키가 절대 사용자 출력에 노출되지 않도록 렌더러를 재작성:
  - `check_disclosure_risk` — `신호 유형: ... (CB_BW, 25점)` 형식의 내부 키/점수 노출 제거. `signal_to_prose`로 "이 공시가 왜 중요한가"를 문장으로 설명. DS005 주요결정 블록의 `플래그: DECISION_RELATED_PARTY, ...` 라인은 `flag_to_prose` 본문으로 치환("이 결정에서 주의할 점" 블록).
  - `find_risk_precedents` — `━━ 전환사채·신주인수권부사채 (CB_BW, 25점) ━━` 형식의 키/점수 노출 제거. 각 신호에 `signal_to_prose` 본문을 붙이고, 과거 위기 궤적은 "평균 약 N개월/손실 N%"로 문장화. 패턴 매칭 블록은 `pattern_to_prose`로 대체.
  - `build_event_timeline` — 맨 위 🎯 3문장 요약(분석 기간·가장 밀집된 단계·패턴 유사도) 신설. 단계(진입기/심화기/탈출기)에 한 줄 정의 머리말 추가. 각 이벤트의 첫 등장 신호 아래 `→ signal_to_prose` 한 줄 해설. 재무 징후 블록의 `**이상 플래그:** AR_SURGE, CASH_GAP` 라인을 `flag_to_prose` title+body 쌍으로 교체(`_METRIC_TO_FLAG`를 통해 지표→플래그 역추적).
  - `find_actor_overlap` — 맨 위 🎯 요약 추가(이 도구의 목적 + 오늘의 결과). "공통 행위자 없음"이 "세력이 없다"는 결론이 아님을 명시. 기업별 인수자 섹션 머리말·회사별 판정 문구를 모두 완전한 문장으로.

### Design Principles (유지)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.

## [0.7.1] — 2026-04-23

### Changed
- **비전문가가 읽어도 막힘 없는 출력** — 6개 도구의 렌더링 레이어를 완전 재작성. 내부 flag/signal/pattern 키(`AR_SURGE`, `CB_BW`, `CAPITAL_CHURN`, `DECISION_RELATED_PARTY`, `FUND_DIVERSION` 등)가 **사용자 출력에 더 이상 노출되지 않음**. 모든 코드 문자열은 렌더 직전 한국어 서술로 치환:
  - `analyze_company_risk` — 맨 위 🎯 3문장 요약 블록 신설(규모·등급·가장 무거운 신호). `• [KEY] ...` 형식 → `• YYYY-MM-DD · 공시명 → 왜 주목할 만한지 한 문장` 형식. 복합 패턴·재무이상·주요결정·자금사용 블록 모두 prose 기반.
  - `scan_financial_anomaly` — 판정 열(`🚩 AR_SURGE`) 제거. 지표별 "이 지표가 말하는 것" 단락으로 이상 신호 해설.
  - `check_disclosure_anomaly` — 5개 구조 지표 각각에 "이 지표가 뭘 재는지 + 지금 수준의 의미" 1~2문장 추가.
  - `track_fund_usage` — `⚠FUND_DIVERSION` 토큰 제거. 계획 vs 실제 불일치를 한국어 서술로 설명.
  - `track_capital_structure` — `🚩 CAPITAL_CHURN` 제거. 상단 요약에 churn 의미 3~4문장.
  - `get_major_decision` — `탐지 플래그: DECISION_*` 제거. "주목할 이유" 블록으로 대체.
- `load_catalog_excerpt` — 각 카테고리 발췌 앞에 "이 카테고리가 뭔가요" 2문장 머리말 자동 prepend.
- `README.md` — Section 7 "결과 읽는 법" 예시를 새 출력 형식으로 교체(후속 커밋).

### Added
- **`dart_risk_mcp/core/explain.py`** 신설 — plain-language 사전 모듈. 4개 공개 API: `flag_to_prose(flag, metric) → (title, body)`, `signal_to_prose(key, report_nm) → str`, `pattern_to_prose(pattern_key) → str`, `category_prose(category) → str`. 10개 flag + 31개 signal + 9개 pattern + 8개 category 사전 임베드. 외부 의존성 없음.
- `_metric_amendments()` 내부 헬퍼 — metric dict가 있을 때 본문 말미에 "이번 분석: 전년 8.0%에서 18.2%로 +10.2%포인트 움직였습니다." 같은 맥락 수치 삽입.

### Removed
- `_v6_flag_label()` 함수(server.py) — 영어 코드로 되돌리는 역방향 추상화. `flag_to_prose`로 대체.

### Design Principles (향후 유지)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.

## [0.7.0] — 2026-04-23

### Added
- **CB/BW/EB·유상증자 구조화 엔드포인트 래퍼 6종** — `fetch_cb_issue_decision`(`cvbdIsDecsn`), `fetch_bw_issue_decision`(`bdwtIsDecsn`), `fetch_eb_issue_decision`(`exbdIsDecsn`), `fetch_piic_decision`(`piicDecsn`), `fetch_fric_decision`(`fricDecsn`), `fetch_pifric_decision`(`pifricDecsn`). 파라미터는 DART 규격에 맞춰 `corp_code + bgn_de + end_de`.
- **DART ACODE 기반 HTML 테이블 파서** — `_extract_investor_table(name_acode, amount_acode)`. DART 표준 공시의 `<TE ACODE="X">` 컬럼 속성으로 인수자명·금액을 정확히 추출. CB는 `ISSU_NM/ISSU_AMT`, Rights는 `PART/ALL_CNT`.
- 릴리스 게이트 문서 `docs/superpowers/release_gates/2026-04-23-v0.7.0-gate.md` — G1~G4 실측 결과.
- 재무이상 임계값 재조정 근거 문서 `tmp/thresholds_v0.7_decision.md` — 25개 샘플 분포 기반.

### Changed
- **재무이상 임계값 재조정** — V.2 샘플로 측정한 실제 분포 기반:
  - `AR_SURGE`: ≥50%p → **≥10%p** (샘플 최대값 12.4%p, 50%p는 never-flag)
  - `INVENTORY_SURGE`: ≥50%p → **≥10%p** (샘플 최대값 12.6%p, 동일 논리)
  - `CAPITAL_IMPAIRMENT`: < 50% → **< 200%** (자본 버퍼 취약 경계)
  - `CASH_GAP`: 이분법 유지
- `extract_cb_investors(rcept_no, api_key, corp_code="")` / `extract_rights_offering_investors(rcept_no, api_key, corp_code="")` — `corp_code` 인자 추가. 구조화 엔드포인트 우선 시도 후 HTML 폴백.
- `fetch_major_decision(rcept_no, corp_cls, decision_type, corp_code="")` — `corp_code` 인자 추가. DS005 12개 엔드포인트를 `corp_code+bgn_de+end_de` 조합으로 호출.
- `server.py` — `extract_cb_investors`·`extract_rights_offering_investors`·`fetch_major_decision` 호출부에 `corp_code` 전달.

### Fixed
- **DART 구조화 엔드포인트 파라미터 불일치** — v0.7.0 신규 추가된 6개 발행결정 엔드포인트가 `rcept_no` 단독으로 호출되어 DART API가 `status:100 필수값(corp_code,bgn_de,end_de)이 누락되었습니다`를 반환하던 버그. 단위 테스트는 mock으로 가려졌고 라이브 게이트에서 발견.
- **`_fetch_text`/`_fetch_rights_html_text` 20,000자 truncation 제거** — 실제 공시에서 인수자 섹션이 char 23,000+ 이후 등장하는 샘플 존재(예: 하이드로리튬 CB 23,102; 핑거 Rights 28,681). 섹션 누락 원인.
- **HTML 테이블 파싱 false positive 제거** — 이전 heuristic이 "선정경위" 프로즈 텍스트를 인수자로 오인했음. ACODE 기반 파싱으로 해결.
- **재무이상 G2 측정 버그** — 사전 측정에서 `fetch_financial_statements`(요약만)를 사용해 CF 계정이 누락되어 CASH_GAP이 계산되지 않았음. 라이브 게이트에서 `fetch_financial_statements_all`로 교정.

### Infra
- `_TE_CELL_RE` 정규식 + `_CB_NAME_ACODE`/`_CB_AMOUNT_ACODE`/`_RIGHTS_NAME_ACODE`/`_RIGHTS_AMOUNT_ACODE` 상수 `cb_extractor.py`에 집약.
- 단위 테스트 4개 신규/갱신 — `test_cb_extractor_structured.py`, `test_dart_client_capital_decisions.py`, `test_dart_client_issue_decisions.py`, `test_investor_extractor.py`. 총 77 PASS.

## [0.6.1] — 2026-04-22

### Changed
- `CAPITAL_EVENT_KEYS` 희석성(`DILUTIVE_CAPITAL_EVENTS`, 8종: 3PCA·RIGHTS_UNDER·GAMJA_MERGE·REVERSE_SPLIT·CB_BW·EB·RCPS·CB_ROLLOVER) / 비희석성(`NON_DILUTIVE_CAPITAL_EVENTS`, 3종: TREASURY·CB_BUYBACK·TREASURY_EB)으로 이원화. 하위 호환용 `CAPITAL_EVENT_KEYS` 유지.
- `detect_capital_churn` 판정 규칙 변경 — `희석성 ≥ 3건` 또는 `희석성 ≥ 2 + 비희석성 ≥ 2` 조건에서만 `CAPITAL_CHURN` 플래그 (기존: 자본 이벤트 합계 ≥ 3건). 대형주 자사주 매입 반복 시나리오의 거짓양성 제거 — 삼성전자 검증 완료.
- `CROSS_SIGNAL_PATTERNS` 2개 확장:
  - `zombie_ma` signal_sequence에 `2.7`(CAPITAL_CHURN) 추가
  - `delisting_evasion` signal_sequence에 `2.7`(CAPITAL_CHURN)·`8.2`(CAPITAL_IMPAIRMENT) 추가

### Fixed
- `analyze_company_risk`·`build_event_timeline`·`scan_financial_anomaly`의 재무이상 탐지가 v0.6.0에서 0/5였던 근본 원인 수정 — `/api/fnlttSinglAcnt.json`은 주요 10개 계정만 반환해 매출채권·재고자산·현금흐름 계정이 결측이었음. `fetch_financial_statements_all` 도입(`/api/fnlttSinglAcntAll.json`, 전체 XBRL 계정)으로 교체. `get_financial_summary`·`compare_financials`는 기존 엔드포인트 유지.

### Infra
- `detect_capital_churn` 반환 dict에 `max_dilutive_12m`·`max_non_dilutive_12m` 필드 추가.
- `tmp/thresholds_decision.md` — V.2 5개 샘플 실측 분포 및 임계값 재조정 연기 근거 기록.

### Deferred (v0.7.x로 이연)
- 재무이상 임계값 경험적 재조정 — V.2 5개 샘플 중 2개 상폐·나머지 분포가 현재 임계값 재조정에 불충분. 10~20개 확장 샘플 필요.

## [0.6.0] — 2026-04-22

### Added
- **신규 MCP 도구 2개** (총 19개 → 21개):
  - `track_capital_structure` — 자본 이벤트(증자·감자·자사주·CB/BW/EB/RCPS 9종)를 시간순 집계. 12개월 내 3건 이상 발생 시 `CAPITAL_CHURN` 플래그
  - `scan_financial_anomaly` — 재무제표 4개 지표 YoY 이상 탐지(`AR_SURGE`·`INVENTORY_SURGE`·`CASH_GAP`·`CAPITAL_IMPAIRMENT`)
- **신규 신호 키 5개**: `CAPITAL_CHURN`(2.7), `AR_SURGE`(6.1), `INVENTORY_SURGE`(6.1), `CASH_GAP`(6.1), `CAPITAL_IMPAIRMENT`(8.2)
- **신규 taxonomy 2.7** (Category 2 자본구조) — 자본 이벤트 과다 반복
- **신규 복합 패턴 1개**: `capital_churn_anomaly` (2.7 + 4.3)
- `detect_capital_churn`, `detect_financial_anomaly` — 순수 계산 함수. 신규 DART 엔드포인트 0개

### Changed
- `analyze_company_risk` — 자본 churn·재무이상 플래그를 signal_events에 자동 합산. 리포트에 자본 변동 타임라인·재무 이상 스캔 섹션 2개 추가
- `build_event_timeline` — 신규 5개 키 `_PHASE_MAP` 매핑 추가, 말미에 "재무 징후" 블록 렌더링

### Infra
- `CAPITAL_EVENT_KEYS` 상수 추가 (자본 이벤트 신호 9개 집합)
- 재무 응답 어댑터 `_fs_response_to_periods` 추가 (DART `fnlttSinglAcnt.json` list → 당기/전기 dict 변환)

## [0.5.0] — 2026-04-22

### Added
- **신규 MCP 도구 2개** (총 17개 → 19개):
  - `track_fund_usage` — 유상증자·CB 자금 사용 계획 vs 실제 집행 대조 (DS002 `/api/prstInvstmEntrCptalUseDtls.json`·`/otrCptalUseDtls.json`). 용도 변경(`FUND_DIVERSION`), 미보고(`FUND_UNREPORTED`) 이상 플래그 탐지
  - `get_major_decision` — 타법인주식·영업·자산 양수도, 합병·분할 등 12개 DS005 주요 결정 공시의 상대방·규모·외부평가 공시 조회. 특수관계 거래(`DECISION_RELATED_PARTY`), 자산총액 대비 과대(`DECISION_OVERSIZED`), 외부평가 미시행(`DECISION_NO_EXTVAL`) 플래그 탐지
- **신규 신호 키 5개**: `FUND_DIVERSION`(5.3/8.1), `FUND_UNREPORTED`(4.3), `DECISION_RELATED_PARTY`(4.2), `DECISION_OVERSIZED`(5.3), `DECISION_NO_EXTVAL`(4.3)
- `fetch_fund_usage`, `fetch_major_decision`, `resolve_decision_type` — DS002/DS005 엔드포인트 래퍼 + LRU+TTL 메모리 캐시 (fund_usage 20건/10분, major_decision 50건/10분)

### Changed
- `check_disclosure_risk` — 주요 결정 공시(DS005) 탐지 시 자금 흐름·상대방 섹션 자동 첨부
- `analyze_company_risk` — 자금사용내역·주요 결정 상대방 플래그를 신호 이벤트에 합산해 최종 점수·복합 패턴 판정에 반영
- `build_event_timeline` — 이벤트 튜플을 6-튜플로 확장(접수번호 포함)해 주요 결정 상대방 정보를 렌더링에 포함. 신규 5개 신호 키 단계 매핑 추가

### Infra
- `dart_client._fund_usage_cache`·`_major_decision_cache` — OrderedDict LRU + TTL 범용 캐시 헬퍼(`_cache_get`·`_cache_set`) 추가

## [0.4.0] — 2026-04-21

### Added
- **금감원·금융위 카탈로그 자동 첨부** — `analyze_company_risk`, `check_disclosure_risk`, `find_risk_precedents` 응답 끝에 탐지된 taxonomy ID가 속한 카테고리의 실제 적발 사례 MD 발췌가 자동 삽입됨
- `core/catalog.py` — taxonomy ID → 카테고리 → MD 파일 로더 (`load_catalog_excerpt`); 파일 부재 시 graceful degradation
- `knowledge/manipulation_catalog/` — 금감원·금융위 보도자료(2021~2026) 기반 8개 카테고리 MD 번들 (30건 분류, 54건 수집 후 제외)
- **신규 복합 패턴 4개** (기존 4개 → 8개):
  - `zombie_ma` — 무자본 M&A 세력의 사모CB 대량발행 + 허위 신사업 + 주가부양 후 고가매도 (타임라인 12개월)
  - `audit_insider_dump` — 감사의견거절 미공개정보 이용 임원·최대주주 매도 (타임라인 6개월)
  - `delisting_evasion` — 자본잠식 기업의 연말 가장납입성 유상증자로 상폐요건 면탈 + 횡령 (타임라인 9개월)
  - `fake_new_biz` — 2차전지·AI·우주항공 등 주업 무관 테마사업 허위 발표 후 주가급등 매도 (타임라인 6개월)

### Changed
- `SIGNAL_TYPES` 11개 신호 키워드 보강 — 금감원 실제 적발 사례에서 반복 등장하는 용어 추가
  - `CB_BW` +콜옵션, 사모전환사채 / `CB_REPAY` +자회사배당, 내부배당 / `EB` +EB배임
  - `CB_ROLLOVER` +연속차입 / `3PCA` +가장납입, 상폐요건면탈 / `SHAREHOLDER` +무자본M&A, 대량보유상황보고
  - `EMBEZZLE` +미공개정보이용, 미공개중요정보, 선행매매, 차명 / `THEME_STOCK` +정치테마주, 핀플루언서
  - `REVENUE_IRREG` +선수금, 미수금급증, 매출과대계상 / `DISCLOSURE_VIOL` +발행철회, 공시철회 / `INQUIRY` +조회공시요구, 거래량급증
- `TAXONOMY` 7개 신호의 `field_evidence`를 placeholder/미흡한 사례에서 실제 금감원 보도자료 근거로 교체 (1.2, 2.4, 4.3, 4.4, 6.1, 7.1, 8.1)

## [0.3.0] — 2026-04-20

### Added
- 시장 전체 preset 배치 스캔 (`search_market_disclosures`) — 12개 preset으로 당일~90일 위험 공시 필터
- 공시 구조 이상 스코어 (`check_disclosure_anomaly`) — 정정비율·감사이슈·공시위반·자본스트레스·조회공시 0~100 집계
- 임원 보수 현황 조회 (`get_executive_compensation`) — 5억이상·개인별·미등기·주총한도 4섹션
- 임원·대주주 지분 변동 시계열 (`track_insider_trading`) — 30일 매수/매도 클러스터 탐지
- `fetch_market_disclosures` — corp_code 없이 DART /list.json 시장 전체 호출
- `fetch_executive_compensation` — 보수 4개 엔드포인트 통합
- `fetch_insider_timeline` — elestock + hyslrSttus 연도별 시계열 통합

## [0.2.0] — 2026-04-20

### Added
- 공시 원문 섹션별/페이지 단위 조회 도구 (`list_disclosure_sections`, `view_disclosure`, `get_disclosure_document`)
- 종목코드로 공시 목록 조회 (`list_disclosures_by_stock`)
- 기업 개요 조회 (`get_company_info`)
- 재무제표 조회 — 단일/다중 비교 (`get_financial_summary`, `compare_financials`)
- 최대주주·대량보유 현황 조회 (`get_shareholder_info`)
- 이벤트 타임라인 서사 분석 (`build_event_timeline`)
- 세력 추적 — 공통 CB 인수자 탐지 (`find_actor_overlap`)
- 신호 taxonomy 확장 — 28개 → 37개 (Category 1~8 전반)
- DART API status 코드 분류 (`020/900/800` → WARNING 로그)
- ZIP 메타데이터 인코딩 `cp949` 설정 (한글 파일명 대응)

### Fixed
- `SIGNAL_KEY_TO_TAXONOMY` 매핑에만 있고 `SIGNAL_TYPES`에 키워드가 없던 9개 키의 실제 탐지 누락 (ACTIVIST, CAPITAL_RED 등)
- `match_signals`가 정정공시(`[기재정정]`)를 제외하지 않아 복합 도구에서 이중 집계되던 문제
- `fetch_company_disclosures` 500건 하드캡 상향 (→ 1000건) + 초과 시 경고 로그
- `_retry` 3회 실패 후 4xx/5xx 응답을 그대로 반환해 호출측 `.json()`이 silent 실패하던 문제
- `_REPORT_CODES`의 `"semi"` vs 외부 docstring의 `"half"` 키 불일치로 반기 보고서 요청 시 연간 보고서로 조용히 대체되던 문제
- `cb_extractor` 인수자 regex의 경계 문자 부족으로 한글 법인명이 끊기던 문제

### Changed
- 외부 라이브러리 최소화 원칙 유지 (`mcp`, `requests`만 사용)

## [0.1.0] — 초기 릴리스

### Added
- MCP 서버 기본 구조 + DART API 클라이언트
- 종합 위험 분석 (`analyze_company_risk`)
- 개별 공시 분석 (`check_disclosure_risk`)
- 신호 유형 선례 조회 (`find_risk_precedents`)
- 28개 신호 taxonomy + 4개 복합 패턴 (`founder_fade`, `debt_spiral`, `reverse_split_spiral`, `related_party_hollowing`)
- CB/BW 인수자명 추출 (`extract_cb_investors`)
- 공시 원문 단순 텍스트 조회 (`fetch_document_text`)
