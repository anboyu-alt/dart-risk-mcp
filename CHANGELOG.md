# Changelog

[Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 형식 준수. 버전은 [SemVer](https://semver.org/lang/ko/).

## [Unreleased]

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
