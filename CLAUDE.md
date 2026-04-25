# DART 리스크 분석 MCP — 개발자 가이드

AI 어시스턴트와 개발자를 위한 프로젝트 내부 가이드입니다.

---

## 프로젝트 개요

한국 금융감독원 DART 전자공시 시스템에서 공시 데이터를 가져와 불공정거래 위험 신호를 탐지하는 MCP 서버입니다.

- **언어:** Python 3.11+
- **의존성:** `mcp>=1.0.0`, `requests>=2.28.0` (외부 라이브러리 최소화 원칙)
- **실행:** `python -m dart_risk_mcp` (stdio 전송)
- **API 키:** 환경변수 `DART_API_KEY` 필수

---

## 디렉토리 구조

```
dart_risk_mcp/
├── __init__.py          # 패키지 버전 (0.1.0)
├── __main__.py          # 진입점 → server.main() 호출
├── server.py            # MCP 서버 + 13개 도구 정의
└── core/
    ├── __init__.py      # 공개 API export
    ├── dart_client.py   # DART API 클라이언트 (핵심)
    ├── signals.py       # 37개 신호 유형 (8개 카테고리) + 키워드 매칭 (v0.4.0 카탈로그 기반 보강)
    ├── catalog.py       # 금감원·금융위 MD 카탈로그 로더 (load_catalog_excerpt)
    ├── cb_extractor.py  # CB/BW 인수자명 추출
    └── taxonomy.py      # 27개 신호 분류 + 위험 점수 + 패턴
```

---

## MCP 도구 23개

### 1. `analyze_company_risk(company_name, lookback_days=90)`

기업명 또는 종목코드로 최근 공시 전체를 스캔해 종합 위험 리포트를 반환합니다.

- 내부 흐름: `resolve_corp` → `fetch_company_disclosures` → `match_signals` × N → `calculate_risk_score` → `find_pattern_match` → `extract_cb_investors`
- 반환: 위험 등급, 탐지 신호 목록, 복합 패턴, CB 인수자, 위기 타임라인

### 2. `check_disclosure_risk(rcept_no="", report_name="")`

개별 공시 하나를 분석합니다. 접수번호가 있으면 원문 500자 미리보기도 포함합니다.

- 접수번호 또는 공시 제목 중 하나만 있어도 작동
- CB/BW 공시면 자동으로 인수자 추출

### 3. `find_risk_precedents(signal_types, lookback_days=90)`

신호 유형 목록을 받아 각 신호의 의미, 위기 타임라인, 복합 패턴을 반환합니다.

- 실제 과거 공시 검색은 하지 않음 (taxonomy 정적 데이터 조회)
- `SIGNAL_KEY_TO_TAXONOMY`로 신호 키 → taxonomy ID(1.1~8.4) 매핑 후 조회
- 사용 가능한 신호 키 (28개, 8개 카테고리):

  | 카테고리 | 키 목록 |
  |---------|---------|
  | Cat 1 CB/채권 | `CB_BW`, `CB_REPAY`, `EB`, `RCPS`, `CB_ROLLOVER`, `CB_BUYBACK`, `TREASURY_EB` |
  | Cat 2 자본구조 | `REVERSE_SPLIT`, `GAMJA_MERGE`, `3PCA`, `RIGHTS_UNDER`, `TREASURY` |
  | Cat 3 경영권 | `SHAREHOLDER`, `EXEC`, `MGMT_DISPUTE`, `CIRCULAR` |
  | Cat 4 거버넌스 | `RELATED_PARTY`, `AUDIT` |
  | Cat 5 기업활동 | `ASSET_TRANSFER`, `DEMERGER`, `MGMT` |
  | Cat 6 회계/재무 | `REVENUE_IRREG`, `CONTINGENT` |
  | Cat 7 시장조작 | `INQUIRY`, `EMBEZZLE` |
  | Cat 8 위기/부실 | `INSOLVENCY`, `DEBT_RESTR`, `GOING_CONCERN` |

### 4. `build_event_timeline(company_name, lookback_days=365)` ✨

기업의 공시 이벤트를 시간순 서사 구조로 구성합니다.

- 진입기(CB_BW, 3PCA, MGMT), 심화기(SHAREHOLDER, EXEC), 탈출기(INQUIRY, AUDIT, EMBEZZLE) 3단계 분류
- `CROSS_SIGNAL_PATTERNS`(taxonomy.py)과 매칭하여 알려진 위기 패턴 식별
- CB 인수자(행위자) 정보도 함께 표시
- 정정공시는 자동 제외

### 5. `find_actor_overlap(company_names)` ✨

여러 기업(2~5개)의 CB/BW 인수자를 비교해 공통 행위자를 탐지합니다.

- 기업별 최근 365일 CB 공시에서 인수자 추출 (최대 3건/기업)
- 2개 이상 기업에 등장하는 인수자 = 공통 행위자로 표시
- DART API 제약: 행위자 이름으로 역검색 불가, 기업 목록을 직접 입력해야 함

### 6. `list_disclosures_by_stock(stock_code, lookback_days=90)` ✨

종목코드(6자리)로 최근 공시 목록과 접수번호를 반환합니다.

- `resolve_corp` → `fetch_company_disclosures` 순서로 호출
- 반환: 접수번호·날짜·공시명 한 줄씩 목록
- 하단에 `get_disclosure_document` 연동 안내 자동 포함
- 입력 검증: 6자리 숫자 여부, API키, 기업 존재 여부

### 7. `get_disclosure_document(rcept_no, max_chars=8000)` ✨

접수번호로 공시 원문 전체를 단일 호출로 반환합니다.

- ZIP 내 가장 큰 HTML/XML 파일을 주 문서로 자동 선정
- HTML → 마크다운 형식 구조 보존 변환 (`_html_to_structured_text`)
- `max_chars` 상한: 내부에서 20,000자로 강제
- 잘린 경우 잘림 안내 + `view_disclosure` 사용 안내 표시

### 8. `list_disclosure_sections(rcept_no)` ✨

공시 ZIP 내 파일별 섹션(목차) 구조를 반환합니다.

- `<h1>`~`<h4>`, DART 전용 `<SECTION-N>` 태그에서 섹션 추출
- 각 섹션에 `id` 부여 (예: `f0s2` = 파일0의 3번째 섹션)
- `view_disclosure`에서 `section_id`로 사용

### 9. `view_disclosure(rcept_no, section_id="", page=1, page_size=4000)` ✨

공시 원문을 섹션별 또는 페이지 단위로 읽습니다.

- `section_id` 지정 시 해당 섹션만, 미지정 시 전체 문서
- `page_size` 범위: 1,000~8,000자
- 단락 경계에서 분할 (문장 중간 끊김 방지)
- 마지막 페이지가 아니면 다음 페이지 호출 방법 안내

### 10. `get_company_info(company_name)` ✨

기업 개요 정보(대표자·업종·설립일·상장 구분 등)를 조회합니다.

- 내부 흐름: `resolve_corp` → `fetch_company_info`
- 반환: 기업명, 종목코드, 대표자, 법인구분, 업종, 설립일, 결산월, 주소, 홈페이지, IR URL, 전화

### 11. `get_financial_summary(company_name, year="", report_type="annual")` ✨

기업의 주요 재무제표(매출·영업이익·순이익·자산·부채)를 조회합니다.

- 내부 흐름: `resolve_corp` → `fetch_financial_statements`
- `report_type` 허용값: `"annual"`(사업보고서), `"half"`(반기), `"q1"`(1분기), `"q3"`(3분기)
- 반환: 연결/별도 구분, 사업연도, 주요 계정과목별 당기/전기 금액
- `year` 미입력 시 직전 연도

### 12. `compare_financials(company_names, year="")` ✨

여러 기업(2~5개)의 재무제표를 나란히 비교합니다.

- 내부 흐름: `resolve_corp` × N → `fetch_multi_financial` (`/fnlttMultiAcnt.json`)
- 반환: 기업별 매출·영업이익·당기순이익·자산·부채 비교 텍스트
- 기업을 찾지 못해도 2개 이상 성공하면 부분 결과 반환

### 13. `get_shareholder_info(company_name, year="")` ✨

최대주주 및 특수관계인, 5% 이상 대량보유자 현황을 조회합니다.

- 내부 흐름: `resolve_corp` → `fetch_shareholder_status`
- 반환: 최대주주/특수관계인 보유 주식 수·비율, 5% 대량보유보고 목록
- `year` 미입력 시 직전 연도
- DART 공시 기준이므로 최신 변동 사항이 반영되지 않을 수 있음

### 14. `search_market_disclosures(preset, days=7, max_results=50)` ✨

시장 전체 공시를 preset 기반으로 배치 스캔합니다.

- `preset` 허용값: `cb_issue`, `treasury`, `reverse_split`, `3pca`, `shareholder_change`, `exec_change`, `audit_issue`, `asset_transfer`, `going_concern`, `embezzle`, `inquiry`, `all_risk`
- `days` 범위: 1~90일, `max_results` 범위: 1~200건
- 내부 흐름: `fetch_market_disclosures` (corp_code 없이 `/list.json`) → `match_signals` 필터
- 반환: 날짜|기업|공시명|신호|접수번호 한 줄씩

### 15. `check_disclosure_anomaly(company_name, lookback_days=365)` ✨

공시 구조 지표 5개에 해당하는 건수·비율을 나열합니다. **기업 위험도를 정량화하거나 등급을 부여하지 않습니다** (v0.8.5 원칙).

- 지표: ① 정정공시 비율 ② 감사의견 이슈 ③ 공시의무 위반 ④ 자본 스트레스 ⑤ 조회공시 빈도
- 감사의견 구조화 엔드포인트(`fetch_audit_opinion_history`)로 최근 5년 감사인 교체 2회 이상·비감사용역 비중 30% 초과 경고 문구 자동 첨부(점수 가산 없음)
- 새 API 호출 없음 — `fetch_company_disclosures` + `match_signals` + `is_amendment_disclosure` 재사용
- 반환: 포지셔닝 고지 + 지표별 내역(탐지 건수·근거 공시명 최대 3건) + 감사의견 관련 경고(해당 시)

### 16. `get_executive_compensation(company_name, year="", report_type="annual")` ✨

임원 보수 현황을 4섹션으로 조회합니다.

- 내부 흐름: `resolve_corp` → `fetch_executive_compensation`
- 섹션: ① 5억 이상 고액수령자 ② 개인별 보수 ③ 미등기임원 보수 ④ 주총 승인 한도
- `report_type` 허용값: `annual` | `half` | `q1` | `q3`

### 17. `track_insider_trading(company_name, lookback_years=2)` ✨ v0.8.6

최대주주·5% 대량보유자·임원·주요주주의 지분 변동 시계열을 분기 보고 단위로 분석합니다.

- 내부 흐름: `resolve_corp` → `fetch_insider_timeline` (4개 엔드포인트 통합) → `fetch_company_disclosures` + `match_signals` → `detect_insider_pre_disclosure`
- 통합 엔드포인트: `elestock`(5% 대량보유, 전체 이력) + `hyslrSttus`(최대주주 현황) + `hyslrChgSttus`(최대주주 변동현황) + `tesstkAcqsDspsSttus`(임원·주요주주 자기주식). 신규 3개는 4개 분기 reprt_code(11011·11012·11013·11014) × N년 루프.
- v0.8.6 출력 보정: 합산 행("계"/"합계") 스킵, 인접 분기 동일 비율(<0.005%p) dedup, lookback 윈도우 외 데이터 필터, `exec_treasury`(회사 자기주식)는 보고자별 시계열에서 분리.
- 추가 플래그 `INSIDER_PRE_DISCLOSURE` (taxonomy 3.6, base_score 0): 매도 이벤트(Δ<0) ±30일 내 부정 공시(AUDIT/INSOLVENCY/EMBEZZLE/INQUIRY/GOING_CONCERN/DISCLOSURE_VIOL/DEBT_RESTR) 동시 발생 시 사실 표기. 점수 가산 없음(v0.8.5 원칙).
- 보유 비율(Δ) 계산 + 30일 윈도우 매수/매도 클러스터 탐지(0.5%p 임계).
- `lookback_years` 범위: 1~5년.
- 반환: 보고자별 Δ 테이블 + 클러스터 알림 + INSIDER_PRE_DISCLOSURE 패턴 라인 + 공시 지연 고지.
- ※ DART API는 임원 거래일 단위 시계열을 직접 제공하지 않습니다. 본 도구는 **분기 보고 단위** 스냅샷의 차이를 추적합니다.

### 18. `track_fund_usage(company_name, lookback_years=3)` ✨

유상증자·CB 발행 자금의 계획 vs 실제 집행을 대조합니다 (DS002).

- 내부 흐름: `resolve_corp` → `fetch_fund_usage` (공모·사모 2개 엔드포인트 통합)
- 이상 플래그: `FUND_DIVERSION`(용도 변경), `FUND_UNREPORTED`(실제 집행 미보고)
- `lookback_years` 범위: 1~5년
- 반환: 납입일·계획금액·실제집행·차이사유 + 플래그 + 금감원 카탈로그(`zombie_ma`, `fake_new_biz`) 발췌

### 19. `get_major_decision(rcept_no, corp_cls="K", decision_type="")` ✨

타법인주식·영업·자산 양수도, 합병·분할 등 DS005 주요 결정 공시의 상대방·규모·외부평가를 조회합니다.

- 내부 흐름: `resolve_decision_type`(공시명 → decision_type) → `fetch_major_decision` (12개 DS005 엔드포인트 중 자동 선택)
- 이상 플래그: `DECISION_RELATED_PARTY`(특수관계 거래), `DECISION_OVERSIZED`(자산총액 대비 과대), `DECISION_NO_EXTVAL`(외부평가 미시행)
- `corp_cls`: `Y`(유가증권), `K`(코스닥), `N`(코넥스), `E`(기타)
- `decision_type` 자동 결정 가능(공시명 기반). 수동 지정 시 허용값: `stock_acq`/`stock_div`/`merger`/`demerger`/`business_acq`/`business_div`/`tangible_acq`/`tangible_div`/`bond_acq`/`bond_div`/`demerger_merger`/`stock_exchange`

### 20. `track_capital_structure(company_name, lookback_years=3)` ✨ v0.8.7

자본 이벤트(증자·감자·자사주·CB/BW/EB/RCPS 9종 + 자사주 결정 4종)를 시간순으로 집계해 '자본 주무르기' 리듬을 탐지합니다.

- 내부 흐름: `resolve_corp` → `fetch_company_disclosures` → `match_signals` × N + **`fetch_treasury_decisions` 4엔드포인트 머지(v0.8.7)** → `CAPITAL_EVENT_KEYS` 필터 → `detect_capital_churn` + `fetch_debt_balance` × N → `detect_debt_rollover`
- v0.8.7: 키워드 매칭에 더해 자사주 결정 구조화 데이터 4종(`tsstkAqDecsn`·`tsstkDpDecsn`·`tsstkAqTrctrCnsDecsn`·`tsstkAqTrctrCcDecsn`)을 자동 통합. 동일 `rcept_no` 중복 방지. 신규 신호 키 `TREASURY_TRUST`(taxonomy 2.8, 비희석성).
- 판정 규칙:
  - 12개월 슬라이딩 윈도우에서 자본 이벤트 ≥3건 → `CAPITAL_CHURN` 플래그
  - 3년 이상 채무잔액이 거의 변동 없고(YoY ≤ 10%) CB 발행 ≥2건 → `CB_ROLLOVER` 플래그(자본 차환 의존)
- `lookback_years` 범위: 1~5년
- v0.8.0: "최근 3년 채무증권 잔액 추이" 블록을 시계열 위에 출력

### 21. `scan_financial_anomaly(company_name, year="", report_type="annual")` ✨ v0.8.8

재무제표 4개 지표(매출채권·재고자산·현금흐름·자본잠식)를 전년 대비 비교해 이상을 탐지하고, **단일회사 주요 재무지표 7종의 YoY 추세**를 별도 블록으로 표기합니다.

- 내부 흐름: `resolve_corp` → `fetch_financial_statements_all` (CFS→OFS 폴백) → `_fs_response_to_periods` → **`fetch_company_indicators` × 2(당기/전기)** → `detect_financial_anomaly(current, prior, current_indx, prior_indx)`
- 이상 플래그 4종(절대 임계): `AR_SURGE`, `INVENTORY_SURGE`, `CASH_GAP`, `CAPITAL_IMPAIRMENT`
- v0.8.8 추가: `fnlttSinglIndx` 4카테고리(M210000 수익성·M220000 안정성·M230000 성장성·M240000 활동성)에서 핵심 7종(순이익률·자기자본비율·부채비율·유동비율·매출액증가율·매출채권회전율·재고자산회전율)을 `12.30%p → 8.10%p (전년 대비 -34.1%)` 형식으로 표기. 점수 가산 없음, 사실 표기만(v0.8.5 원칙).
- `report_type` 허용값: `annual`·`half`·`q1`·`q3`
- ※ DART API는 업종 평균을 직접 제공하지 않습니다(검증 완료). 본 도구는 **회사 자체 YoY 추세**로 false-positive를 완화합니다.

### 22. `get_audit_opinion_history(company_name, lookback_years=5)` ✨ v0.8.0

최근 5년 감사의견·감사인 재직 이력·비감사용역 비중 경고를 조회합니다.

- 내부 흐름: `resolve_corp` → `fetch_audit_opinion_history` (3개 엔드포인트 × 연도 루프)
- 반환: 연도별 감사의견 + 연속 재직 연수, 감사인 교체 이력, 비감사용역 비중 30% 초과 연도 경고
- `lookback_years` 범위: 1~10년
- DART 감사보수 절대 금액 표시는 단위(천원/백만원) 혼용으로 v0.8.0에서 생략. 비중(%)만 경고 섹션에서 제공

### 23. `track_debt_balance(company_name, year="")` ✨ v0.8.0

채무증권 5종 잔액과 1년 이내 만기 비중을 조회합니다.

- 내부 흐름: `resolve_corp` → `fetch_debt_balance` (5개 엔드포인트 통합)
- 반환: 종류별 잔액(회사채·단기사채·기업어음·신종자본증권·조건부자본증권) + 1년 이내 만기 비중
- 판정 규칙: 1년 이내 만기 비중 ≥30% → 차환 압박 경고
- `year` 미입력 시 직전 연도

---

## 핵심 내부 함수

### `dart_client.py`

| 함수 | 역할 |
|------|------|
| `_retry(method, url, **kwargs)` | 429/5xx 지수 백오프 재시도 (최대 3회) |
| `_load_corp_codes(api_key)` | DART corpCode.xml 다운로드 + 24시간 파일 캐시 |
| `resolve_corp(query, api_key)` | 기업명/종목코드 → (corp_name, {corp_code, stock_code}) |
| `fetch_company_disclosures(corp_code, api_key, lookback_days)` | /list.json 페이지네이션 (최대 500건) |
| `_fetch_document_zip(rcept_no, api_key)` | /document.xml ZIP 다운로드 + 인메모리 LRU 캐시 (5건, 10분 TTL) |
| `fetch_document_text(rcept_no, api_key, max_chars=3000)` | 단순 태그 제거 텍스트 (기존 호환용) |
| `fetch_disclosure_full(rcept_no, api_key, max_chars=8000)` | 가장 큰 파일 선정 + 구조 보존 텍스트 |
| `_html_to_structured_text(html)` | HTML → 마크다운 (헤더·테이블·리스트 보존) |
| `list_document_sections(rcept_no, api_key)` | ZIP 파일별 섹션 목록 반환 |
| `fetch_document_content(rcept_no, api_key, ...)` | 페이지네이션 원문 조회 |
| `fetch_company_info(corp_code, api_key)` | `/company.json` — 기업 개요 (대표자·업종·설립일 등) |
| `fetch_financial_statements(corp_code, api_key, year, report_type)` | `/fnlttSinglAcnt.json` — 단일 기업 재무제표 |
| `fetch_multi_financial(corp_codes, api_key, year, report_type)` | `/fnlttMultiAcnt.json` — 다중 기업 재무 비교 |
| `fetch_shareholder_status(corp_code, api_key, year, report_type)` | 최대주주 현황 + 5% 대량보유 통합 조회 |
| `fetch_market_disclosures(api_key, bgn_de, end_de, pblntf_ty, max_pages)` | corp_code 없이 시장 전체 공시 조회 |
| `fetch_executive_compensation(corp_code, api_key, year, report_type)` | 보수 4개 엔드포인트 통합 조회 |
| `fetch_insider_timeline(corp_code, api_key, lookback_years)` | elestock + hyslrSttus + hyslrChgSttus + tesstkAcqsDspsSttus 4엔드포인트 × 4분기 통합 시계열 (v0.8.6) |
| `detect_insider_pre_disclosure(insider_records, signal_events, window_days=30)` | 매도 ±30일 내 부정 공시 패턴 탐지 (v0.8.6) |
| `fetch_treasury_decisions(corp_code, api_key, lookback_years)` | 자사주 결정 4엔드포인트(취득·처분·신탁체결·신탁해지) 통합. key=TREASURY/TREASURY_TRUST로 정규화 (v0.8.7) |
| `fetch_company_indicators(corp_code, api_key, bsns_year, reprt_code)` | 단일회사 주요 재무지표 4카테고리(수익성·안정성·성장성·활동성) 통합 → {idx_nm: float} flat dict (v0.8.8) |
| `fetch_distress_events(corp_code, api_key, lookback_years)` | 부도·영업정지·회생절차·해산사유 4엔드포인트 통합. key=DISTRESS_EVENT + subtype 라벨 (v0.9.0) |
| `fetch_dividend_history(corp_code, api_key, lookback_years)` | alotMatter을 분기 4코드 × N년 호출. 각 record에 bsns_year/reprt_code 부착 (v0.9.0) |
| `detect_dividend_drain(dividend_records, current_fs)` | 적자 시점 배당 유출(DIVIDEND_DRAIN) 패턴 — 당기순이익 음수 + 현금배당 양수 시 flag (v0.9.0) |
| `fetch_fund_usage(corp_code, api_key, corp_cls, lookback_years)` | 공모·사모 자금사용 2개 엔드포인트 통합 + 이상 플래그 탐지 |
| `fetch_major_decision(rcept_no, corp_cls, decision_type)` | 12개 DS005 주요결정 엔드포인트 중 decision_type에 따라 자동 선택 |
| `resolve_decision_type(report_nm)` | 공시명 → decision_type 키 자동 추론 (`[기재정정]` 등 접두어 제거) |
| `detect_capital_churn(events, lookback_years)` | 12개월 슬라이딩 윈도우로 CAPITAL_CHURN 판정 |
| `detect_financial_anomaly(current, prior)` | 4개 지표 YoY 비교 → 플래그+메트릭 |
| `fetch_audit_opinion_history(corp_code, api_key, lookback_years)` | 감사의견 3개 엔드포인트 × 연도 루프 통합 + 재직 연수·교체·비감사 비중 경고 |
| `fetch_debt_balance(corp_code, api_key, year)` | 채무증권 5개 엔드포인트 통합 + 1년 이내 만기 비중 산출 |
| `detect_debt_rollover(balance_history, capital_events)` | 3년 잔액 변동 ≤10% + CB ≥2건 → CB_ROLLOVER 판정 |

### DART API 엔드포인트

| 엔드포인트 | 용도 |
|-----------|------|
| `GET /api/corpCode.xml` | 전체 기업 코드 ZIP (24시간 캐시) |
| `GET /api/list.json` | 기업별 공시 목록 (corp_code, 날짜 범위) |
| `GET /api/document.xml` | 공시 원문 ZIP (rcept_no) |
| `GET /api/company.json` | 기업 개요 정보 (corp_code) |
| `GET /api/fnlttSinglAcnt.json` | 단일 기업 재무제표 (corp_code, 연도, 보고서 유형) |
| `GET /api/fnlttMultiAcnt.json` | 다중 기업 재무 비교 (corp_codes 목록) |
| `GET /api/majorstock.json` | 최대주주 현황 (corp_code, 연도) |
| `GET /api/elestock.json` | 5% 이상 대량보유 현황 (corp_code, 연도) |
| `GET /api/hyslrSttus.json` | 최대주주 현황 (corp_code, bsns_year, reprt_code) |
| `GET /api/hyslrChgSttus.json` | 최대주주 변동현황 (corp_code, bsns_year, reprt_code) — v0.8.6 |
| `GET /api/tesstkAcqsDspsSttus.json` | 임원·주요주주 자기주식 취득·처분 현황 (corp_code, bsns_year, reprt_code) — v0.8.6 |
| `GET /api/prstInvstmEntrCptalUseDtls.json` | 공모 자금 사용 내역 (corp_code, 연도) |
| `GET /api/otrCptalUseDtls.json` | 사모 자금 사용 내역 (corp_code, 연도) |
| `GET /api/bsnAcqsDecsn.json` / `bsnTrfDecsn.json` | 영업 양수/양도 결정 (rcept_no) |
| `GET /api/tsstkAqDecsn.json` / `tsstkDpDecsn.json` | 자사주 취득/처분 결정 (v0.8.7 통합) |
| `GET /api/tsstkAqTrctrCnsDecsn.json` / `tsstkAqTrctrCcDecsn.json` | 자사주 신탁계약 체결/해지 결정 (v0.8.7 통합) |
| `GET /api/fnlttSinglIndx.json` | 단일회사 주요 재무지표 (corp_code, bsns_year, reprt_code, idx_cl_code) — v0.8.8 통합 |
| `GET /api/dfOcr.json` | 부도발생 (corp_code, bgn_de, end_de) — v0.9.0 통합 |
| `GET /api/bsnSp.json` | 영업정지 (corp_code, bgn_de, end_de) — v0.9.0 통합 |
| `GET /api/ctrcvsBgrq.json` | 회생절차 개시신청 (corp_code, bgn_de, end_de) — v0.9.0 통합 |
| `GET /api/dsRsOcr.json` | 해산사유 발생 (corp_code, bgn_de, end_de) — v0.9.0 통합 |
| `GET /api/alotMatter.json` | 배당에 관한 사항 (corp_code, bsns_year, reprt_code) — v0.9.0 통합 |
| `GET /api/otcprStkInvscrTrfDecsn.json` / `otcprStkInvscrAcqsDecsn.json` | 타법인 주식 양수/양도 |
| `GET /api/bdwtIsDecsn.json` / `cvbdIsDecsn.json` | 채권 인수/발행 결정 |
| `GET /api/cmpMgDecsn.json` / `cmpDvDecsn.json` / `cmpDvmgDecsn.json` | 합병·분할·분할합병 결정 |
| `GET /api/stkExtrDecsn.json` | 주식교환·이전 결정 |
| `GET /api/accnutAdtorNmNdAdtOpinion.json` | 감사인 및 감사의견 (corp_code, bsns_year, reprt_code) |
| `GET /api/adtServcCnclsSttus.json` | 감사용역 계약 체결 현황 (corp_code, bsns_year) |
| `GET /api/accnutAdtorNonAdtServcCnclsSttus.json` | 비감사용역 계약 체결 현황 (corp_code, bsns_year) |
| `GET /api/cprndIsDecsn.json` | 회사채 발행 잔액 (corp_code, bsns_year) |
| `GET /api/stIsDecsn.json` | 단기사채 미상환 잔액 |
| `GET /api/cpIsDecsn.json` | 기업어음 미상환 잔액 |
| `GET /api/newCaptlScrtIsDecsn.json` | 신종자본증권 미상환 잔액 |
| `GET /api/cndlCaptlScrtIsDecsn.json` | 조건부자본증권 미상환 잔액 |

모든 요청에 `crtfc_key` 파라미터로 API 키 전달.

---

## 캐시 구조

| 캐시 | 저장 위치 | TTL |
|------|-----------|-----|
| 기업 코드 목록 | `~/.cache/dart-risk-mcp/corp_codes.json` | 24시간 |
| 공시 원문 ZIP | 메모리 `_zip_cache` (최대 5건) | 10분 |
| 자금사용 내역 | 메모리 `_fund_usage_cache` (최대 20건) | 10분 |
| 주요결정 공시 | 메모리 `_major_decision_cache` (최대 50건) | 10분 |
| 감사의견 이력 | 메모리 `_audit_history_cache` (최대 20건) | 10분 |
| 채무증권 잔액 | 메모리 `_debt_balance_cache` (최대 20건) | 10분 |

---

## 코딩 규칙

- **외부 라이브러리 추가 금지**: `requests`와 `mcp` 외 의존성을 추가하지 않습니다. HTML 파싱도 regex + 문자열 처리로 구현합니다.
- **인코딩 처리**: DART 문서는 utf-8, euc-kr, cp949 순으로 시도합니다 (`_decode_zip_file`).
- **오류 처리**: API 호출 실패 시 빈 값 반환 (예외를 도구 레벨로 전파하지 않음).
- **정정공시 필터**: `is_amendment_disclosure(report_nm)`으로 `[기재정정]` 등을 감지해 내부 랭킹에서 제외합니다.
- **점수·등급 없음 원칙 (v0.8.5)**: 기업 위험도를 정량화하거나 등급("매우위험", "고위험" 등)으로 부여하는 어떤 표기도 사용자 출력에 노출되면 안 됩니다. 내부에서는 `SIGNAL_TYPES[*].score`·`taxonomy.base_score`로 신호 우선순위를 정렬하지만 렌더 경로로 유출되면 안 됩니다. `tests/test_golden_output_hygiene.py`가 점수/등급/이모지 회귀를 기계적으로 막습니다.

---

## 자주 있는 작업

### 새 신호 유형 추가

1. `signals.py` → `SIGNAL_TYPES` 리스트에 항목 추가 (key, label, score, keywords)
2. `signals.py` → `SIGNAL_KEY_TO_TAXONOMY` 딕셔너리에 taxonomy ID 매핑 (예: `"MY_KEY": "5.4"`)
3. `taxonomy.py` → `TAXONOMY` 딕셔너리에 해당 ID 항목 추가 (severity, keywords, indicators 등)
4. (선택) `taxonomy.py` → `CROSS_SIGNAL_PATTERNS`에 관련 조합 패턴 추가

### 새 복합 패턴 추가

`taxonomy.py` → `CROSS_SIGNAL_PATTERNS` 딕셔너리(dict[str, dict] — key=패턴명, value=상세)에 항목 추가:
```python
"패턴명": {
    "name": "패턴명",
    "description": "패턴 설명",
    "signal_sequence": ["taxonomy_id_1", "taxonomy_id_2"],  # 이 신호들이 모두 탐지되면 매칭
    "timeline_months": 12,
    "severity": "CRITICAL",  # CRITICAL / HIGH / MEDIUM / LOW
    "field_evidence": ["실제 사례 근거"],
}
```

등록 패턴 9개 (v0.6.0 기준):
- **기존 4개 (전통 위기 사이클)**: `founder_fade`(창업주 퇴장), `debt_spiral`(부채 악순환), `reverse_split_spiral`(무상감자 나선), `related_party_hollowing`(특수관계자 자산 공동화)
- **v0.4.0 신규 4개 (금감원 사례 기반)**: `zombie_ma`(무자본 M&A), `audit_insider_dump`(감사의견 내부자 덤프), `delisting_evasion`(상폐 회피), `fake_new_biz`(허위 신사업 주가부양)
- **v0.6.0 신규 1개**: `capital_churn_anomaly`(자본 이벤트 과다 반복 + 공시의무 위반)

### 도구 추가

1. `dart_client.py`에 핵심 로직 함수 작성
2. `core/__init__.py`에 import + `__all__` 추가
3. `server.py`에 `@mcp.tool()` 데코레이터로 도구 등록

---

## 테스트 방법

```bash
# 서버 import 검증
python -c "import dart_risk_mcp.server; print('OK')"

# 등록된 도구 목록 확인
python -c "
from dart_risk_mcp.server import mcp
for t in mcp._tool_manager.list_tools():
    print(t.name)
"

# 실제 API 호출 테스트 (API 키 필요)
DART_API_KEY=키값 python -c "
from dart_risk_mcp.core.dart_client import resolve_corp
print(resolve_corp('삼성전자', '키값'))
"
```
