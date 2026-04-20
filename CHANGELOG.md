# Changelog

[Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 형식 준수. 버전은 [SemVer](https://semver.org/lang/ko/).

## [Unreleased]

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
