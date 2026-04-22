# Changelog

[Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 형식 준수. 버전은 [SemVer](https://semver.org/lang/ko/).

## [Unreleased]

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
