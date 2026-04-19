# Changelog

[Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 형식 준수. 버전은 [SemVer](https://semver.org/lang/ko/).

## [Unreleased]

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
