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
    ├── sector_policy.py # 업종별 유의 회계정책 정적 맵 (KSIC 조회, kreports 이식/Apache 2.0)
    ├── notes.py         # 재무제표 주석 카테고리 분류 (제목 키워드 10종, kreports 이식/Apache 2.0)
    ├── watchlist.py     # 인물↔회사군 영속 워치리스트 (순수 파일 I/O)
    ├── known_actors.py  # 공개기록 행위자 레지스트리 로드/조회 (비공개 Notion opt-in)
    └── taxonomy.py      # 27개 신호 분류 + 위험 점수 + 패턴
```

> 동봉 데이터: `dart_risk_mcp/data/known_actors.json`(빈 스켈레톤 — v1.5.0부터 인물 데이터 미포함). 레지스트리 원본은 제작자 비공개 Notion DB. DB 셋업: `scripts/setup_known_actors_db.py`(+`setup-known-actors-db.yml`, 1회성).
> 레지스트리 로드: `load_known_actors()` 우선순위 = `DART_KNOWN_ACTORS_PATH`(로컬 JSON) > Notion(`NOTION_TOKEN`+`DB_KNOWN_ACTORS` env, 24h 캐시 `~/.cache/dart-risk-mcp/known_actors_notion.json`) > 동봉(빈 스켈레톤). Notion 미설정 시 네트워크 시도 없이 graceful 비활성화. 자동 갱신: `scripts/refresh_known_actors.py` + `.github/workflows/refresh-known-actors.yml`(매일 cron — 시장 신규 CB/유상증자 인수자를 등재 인물과 표기 정규화 매칭해 `auto_matched` 근거를 Notion에 기록, public 커밋 없음). 운영자 Secrets: `DART_API_KEY`, `NOTION_TOKEN`, `DB_KNOWN_ACTORS`.
> 레지스트리 DB 스키마: 인물명(title)·status(select)·source·evidence·date·rcept_no(rich_text)·url·tags·**관련기업**(multi_select — 등장 회사명 태깅, evidence 텍스트와 분리해 회사별 필터링·추적 가능). `discover_actors.py`는 반복 등장한 문제 회사 전체를, `refresh_known_actors.py`는 해당 근거의 단일 회사를 태깅. 스키마 마이그레이션: `scripts/setup_known_actors_db.py`를 `DB_KNOWN_ACTORS` 설정된 상태로 재실행하면 신규 속성 추가 + 기존 행 소급 백필(추가만, 삭제 없음).
> 자동 발굴: `scripts/discover_actors.py`(같은 cron)는 시장 '문제 회사'(자금조달+불안정 신호 동반)의 인수자를 **sightings로 누적**(12개월 윈도우)하고, 서로 다른 문제 회사 2곳+(N=2)에 반복 등장하는 행위자를 레지스트리(비공개 Notion)에 `auto_matched`(자동 발굴)로 등재 + 제작자 이메일. **노출 경계**: sightings(1회 포함, 미검증)는 **private repo `dart-risk-mcp-sightings`**(제작자만, `SIGHTINGS_REPO_TOKEN` PAT), 레지스트리도 **비공개 Notion**(접근은 opt-in, README 참고) — public 레포에는 어떤 인물 데이터도 커밋하지 않는다. 행위자는 `classify_actor`로 개인/조합/법인 3분류 추적(레지스트리 `구분` select) — 제도권 기관(증권사·은행·연기금 등, 반복 등장이 정상)과 임원은 제외. 베이스 백필: `scripts/backfill_sightings.py`(+`backfill-sightings.yml`). 연결망 시각화: `scripts/build_network_html.py`(+`network_template.html`) — sightings에서 2사+ 추적 행위자↔회사 이분 그래프를 자체 완결형 HTML로 렌더(외부 CDN 없음). **출력 HTML은 실명 포함 → public 레포 커밋 금지**, 스크립트만 레포에 둠.

---

## MCP 도구 26개

### 1. `analyze_company_risk(company_name, lookback_years=1)`

기업명 또는 종목코드로 최근 공시 전체를 스캔해 종합 위험 리포트를 반환합니다.

- 내부 흐름: `resolve_corp` → `fetch_company_disclosures` → `match_signals` × N → `calculate_risk_score` → `find_pattern_match` → `extract_cb_investors`
- 반환: 위험 등급, 탐지 신호 목록, 복합 패턴, CB 인수자, 위기 타임라인
- `lookback_years` 범위 1~5, 기본 1년. 다년(>1년) 조회 시 결과 하단에 예상 출력 규모(문자·토큰 추정) 푸터 표기.

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

### 4. `build_event_timeline(company_name, lookback_years=1)` ✨

기업의 공시 이벤트를 시간순 서사 구조로 구성합니다.

- 진입기(CB_BW, 3PCA, MGMT), 심화기(SHAREHOLDER, EXEC), 탈출기(INQUIRY, AUDIT, EMBEZZLE) 3단계 분류
- `CROSS_SIGNAL_PATTERNS`(taxonomy.py)과 매칭하여 알려진 위기 패턴 식별
- CB 인수자(행위자) 정보도 함께 표시
- 정정공시는 자동 제외
- `lookback_years` 범위 1~5, 기본 1년. 다년(>1년) 조회 시 결과 하단에 예상 출력 규모(문자·토큰 추정) 푸터 표기.

### 5. `find_actor_overlap(company_names, lookback_years=1, watchlist="")` ✨

여러 기업(2~5개)의 CB/BW/EB·유상증자 인수자 + **등기임원 겸직**을 통합 비교해 공통 행위자(세력)를 탐지합니다.

- 기업별 CB/유상증자 공시 인수자(최대 3건/기업) + `fetch_executive_roster`로 임원현황 다년 수집
- 2개 이상 기업에 (돈 댄 사람 **또는** 등기임원으로) 등장 = 공통 행위자. 출처 태그 `[CB]`/`[유상증자]`/`[임원]`
- 핵심: 무자본 M&A 세력은 인수마다 새 SPC/조합을 만들어 조합명이 매번 다르지만, **임원 이름은 고정점** — 다년 합집합으로 겸직 포착
- `lookback_years` 범위 1~5년. 기본 1년이면 출력 안내가 "최근 365일", N년이면 "최근 N년"으로 정직 표기
- DART API 제약: 행위자 이름으로 역검색 불가, 기업 목록을 직접 입력해야 함
- `watchlist` 지정 시 `manage_watchlist`에 저장된 인물의 회사군을 `company_names`와 합집합으로 자동 로드(예: `find_actor_overlap(watchlist="신승수")`)
- 탐지된 인물(인수자·임원)을 공개기록 레지스트리(`lookup_actor`)와 대조해 매칭 시 "📎 공개기록 참고(사실 표기 — 판정 아님)" 섹션 + 면책 표면화
- 라이브 입증: 신승수군(이엠앤아이·제이케이시냅스·CG인바이츠·헬스커넥트·티쓰리) `lookback_years=3` → 신승수 3개사 겸직 + 신용규·이호영 동행 인물 탐지

### 6. `list_disclosures_by_stock(stock_code, lookback_years=1)` ✨

종목코드(6자리)로 최근 공시 목록과 접수번호를 반환합니다.

- `resolve_corp` → `fetch_company_disclosures` 순서로 호출
- 반환: 접수번호·날짜·공시명 한 줄씩 목록
- 하단에 `get_disclosure_document` 연동 안내 자동 포함
- 입력 검증: 6자리 숫자 여부, API키, 기업 존재 여부
- `lookback_years` 범위 1~5, 기본 1년. 다년(>1년) 조회 시 결과 하단에 예상 출력 규모(문자·토큰 추정) 푸터 표기.

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
- **주석 카테고리 감지**(kreports NOTE_KEYWORDS 이식/Apache 2.0): 섹션 제목 태그 `⟨주석: 라벨⟩` + 하단 "🔎 주석 카테고리 감지" 요약. 10카테고리(계속기업·특수관계자·우발부채·종속기업·금융상품·수익인식·리스·충당부채·자산손상·후속사건), 우선순위순 최대 2태그/제목. 섹션에 안 잡히는 주석 헤딩은 `scan_note_titles`(원문 `<TITLE>` 태그 스캔)로 보완 — "파일N '제목' (약 X% 지점)" 형식. 제목 80자 초과는 본문 오인으로 태깅 제외. 사실 라벨만, 판정 없음

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

### 15. `check_disclosure_anomaly(company_name, lookback_years=1)` ✨

공시 구조 지표 5개에 해당하는 건수·비율을 나열합니다. **기업 위험도를 정량화하거나 등급을 부여하지 않습니다** (v0.8.5 원칙).

- 지표: ① 정정공시 비율 ② 감사의견 이슈 ③ 공시의무 위반 ④ 자본 스트레스 ⑤ 조회공시 빈도
- 감사의견 구조화 엔드포인트(`fetch_audit_opinion_history`)로 최근 5년 감사인 교체 2회 이상·비감사용역 비중 30% 초과 경고 문구 자동 첨부(점수 가산 없음)
- 새 API 호출 없음 — `fetch_company_disclosures` + `match_signals` + `is_amendment_disclosure` 재사용
- 반환: 포지셔닝 고지 + 지표별 내역(탐지 건수·근거 공시명 최대 3건) + 감사의견 관련 경고(해당 시)
- `lookback_years` 범위 1~5, 기본 1년. 다년(>1년) 조회 시 결과 하단에 예상 출력 규모(문자·토큰 추정) 푸터 표기.

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
- 이상 플래그 8종: `AR_SURGE`, `INVENTORY_SURGE`, `CASH_GAP`, `CAPITAL_IMPAIRMENT`(절대 임계) + `CFS_OFS_REVERSAL`(별도>연결 당기순이익 역전 — 종속회사 합산 손실, 격차 ≥10%일 때만. 정상 대기업의 연결>별도 괴리는 플래그하지 않음 — 삼성전자 +46% 라이브 검증) + `OPNET_POS_NEG`(영업흑자·순손실 — 영업외 손실)·`OPNET_NEG_POS`(영업적자·순이익 흑자 — 일회성 이익 의심, 상폐 요건 회피 연관) + `RESTATEMENT`(전기 수치 재작성 — 올해 보고서의 전기값 vs 작년 보고서의 당기값을 6계정×fs_div 대조, 0.5% 허용오차. `detect_restatement`, 직전 연도 `fnlttSinglAcnt` 1회 추가 호출)
- 발생액 비율 (순이익−영업현금흐름)/|순이익| 을 당기/전기/Δ로 사실 표기(플래그 없음, kreports accrual_ratio 이식). 연결/별도 비교는 `fnlttSinglAcnt` 1회 추가 호출로 CFS/OFS 당기순이익 쌍 추출(`extract_cfs_ofs_ni`)
- "이익조작 연구 변수" 블록(`compute_beneish_variables`, kreports 이식/Apache 2.0): Beneish 개별 변수 6종(DSRI·GMI·AQI·SGI·SGAI·LVGI)을 전년=1.00 기준 지수로 사실 표기. **M-Score 합산·임계 판정 없음**(v0.8.5 원칙, 안내 문구 자동 첨부). DEPI·TATA는 감가상각비 미노출로 제외(라이브 검증), LVGI는 부채총계/자산총계 기준(명칭에 명시)
- "연구개발비 비중 (사업보고서 기재)" 블록(`extract_rd_ratio_from_report`, kreports business_insights 이식/Apache 2.0): 최근 사업보고서 원문의 "연구개발비/매출액 비율" 표에서 최근 3개 연도 값을 regex 추출해 사실 표기 (annual만, ZIP 다운로드 +1회). % 생략 변형은 인접 소수점 연속 규칙으로 흡수, 산정 기준 상이 안내 자동 첨부. 라이브 검증 5/6사(제이스코는 R&D 표 없음 — 정상 미검출)
- v0.8.8 추가: `fnlttSinglIndx` 4카테고리(M210000 수익성·M220000 안정성·M230000 성장성·M240000 활동성)에서 핵심 7종(순이익률·자기자본비율·부채비율·유동비율·매출액증가율·매출채권회전율·재고자산회전율)을 `12.30%p → 8.10%p (전년 대비 -34.1%)` 형식으로 표기. 점수 가산 없음, 사실 표기만(v0.8.5 원칙).
- `report_type` 허용값: `annual`·`half`·`q1`·`q3`
- 결과 하단 "업종별 유의 회계정책 (참고)" 블록: `fetch_company_info`의 KSIC 업종코드로 `core/sector_policy.py` 정적 맵(kreports 이식, Apache 2.0)을 조회해 해당 업종에서 회계처리 판단 영향이 큰 항목을 [핵심]/[참고] 라벨로 안내. 업종 일반 참고 자료이며 기업 판정·점수 아님(v0.8.5 원칙)
- ※ DART API는 업종 평균을 직접 제공하지 않습니다(검증 완료). 본 도구는 **회사 자체 YoY 추세**로 false-positive를 완화합니다.

### 22. `get_audit_opinion_history(company_name, lookback_years=5)` ✨ v0.8.0

최근 5년 감사의견·감사인 재직 이력·비감사용역 비중 경고를 조회합니다.

- 내부 흐름: `resolve_corp` → `fetch_audit_opinion_history` (3개 엔드포인트 × 연도 루프)
- 반환: 연도별 감사의견 + 연속 재직 연수, 감사인 교체 이력, 비감사용역 비중 30% 초과 연도 경고
- `lookback_years` 범위: 1~10년
- 감사인명은 `_normalize_auditor` 별칭 정규화("삼정KPMG"→"삼정회계법인", 13법인·kreports 이식/Apache 2.0) 후 저장·비교 — 표기 혼재로 인한 교체·재직연수 오탐 방지
- "연속 적자 (참고)" 블록(`fetch_loss_streak`): 연도별 `fnlttSinglAcnt` 루프(최대 5회 추가 호출)로 영업손실·순손실 연속 연수를 최신 연도부터 계산해 2년 이상일 때만 사실 표기. 데이터 없는 연도는 보수적으로 연속 중단. 라이브: 헬릭스미스 5년·제이스코 영업 4년/순손실 5년 연속 매칭
- DART 감사보수 절대 금액 표시는 단위(천원/백만원) 혼용으로 v0.8.0에서 생략. 비중(%)만 경고 섹션에서 제공

### 23. `track_debt_balance(company_name, year="")` ✨ v0.8.0

채무증권 5종 잔액과 1년 이내 만기 비중을 조회합니다.

- 내부 흐름: `resolve_corp` → `fetch_debt_balance` (5개 엔드포인트 통합)
- 반환: 종류별 잔액(회사채·단기사채·기업어음·신종자본증권·조건부자본증권) + 1년 이내 만기 비중
- 판정 규칙: 1년 이내 만기 비중 ≥30% → 차환 압박 경고
- `year` 미입력 시 직전 연도

### 24. `manage_watchlist(action, person="", companies=None, note="")` ✨

감시 대상 인물↔회사군 워치리스트를 관리합니다 (영속 저장).

- `action` 허용값: `list`(등록 인물·회사 수) | `show`(특정 인물 회사군·메모) | `add`(인물 추가/갱신, companies 합집합 병합) | `remove`(인물 삭제)
- 저장 위치: `~/.config/dart-risk-mcp/watchlist.json` (환경변수 `DART_WATCHLIST_PATH`로 오버라이드)
- DART는 인물명 역검색 불가 → 회사군은 사용자가 직접 채움(예: `find_actor_overlap` 임원 겸직 결과를 `add`)
- 저장된 인물은 `find_actor_overlap(watchlist=인물명)`으로 바로 재조회
- **저장 + 수동 조회까지만** — 실시간 알림·자동 스캔은 비범위

### 25. `lookup_known_actor(name)` ✨

인물명으로 **공개기록 행위자 레지스트리**를 조회합니다 (사실 표기 — 판정 아님).

- 출처가 명확한 공개기록(DART 임원현황·CB/유상증자 인수)에 그 인물이 어느 상장사에 등장했는지를 사실로만 반환. **위험 판정·점수·등급 없음**, 동명이인·원본 확인 면책 동반
- 데이터: 비공개 Notion DB(opt-in). `core/known_actors.py`의 `lookup_actor`로 조회(표기 정규화 매칭)
- `find_actor_overlap`도 탐지된 인물을 이 레지스트리와 자동 대조해 "공개기록 참고" 섹션으로 표면화
- **status 3단계:** `verified`(회사 직접 조회 근거) / `maintainer_seed`(제작자 등록, 근거 미확보) / `auto_matched`(**동명이인 미확인** — 두 경로: 등재 인물의 시장 이름 매칭 `refresh_known_actors`, 또는 문제회사 N=2 반복 자동 발굴 `discover_actors`). 자동 매칭은 verified로 자동 승격하지 않으며 강한 동명이인 경고를 동반
- **등재 기준:** 공개 출처가 확인된 경우에만 등재. 근거(회사·연도·출처)는 `scripts/refresh_known_actors.py`·`scripts/discover_actors.py`(매일 자동)가 DART에서 집계해 Notion에 기록(사람은 검토·승격만). 단정 표현 금지. 명단은 제작자가 직접 관리·연락(GitHub 프로필 연락처). 변경 시 제작자 Gmail 통지(`refresh_known_actors.py`의 `send_mail`, 자격증명 `MAIL_USER`/`MAIL_APP_PASSWORD`/`MAIL_TO` Secret)

### 26. `get_affiliate_investments(company_name, year="")` ✨

타법인 출자현황(이 회사가 어떤 법인들에 돈을 넣었는지)을 사실로 나열합니다 (DS002 `otrCprInvstmntSttus`).

- 내부 흐름: `resolve_corp` → `fetch_affiliate_investments` (합계 행 제거)
- 반환: 피출자 법인·출자목적·기말지분율·장부가액·최초취득일·피투자사 최근 순이익 표(장부가액 상위 30건) + 요약 사실(총 건수·지분율 50%+ 건수·피투자사 적자 건수·해당연도 신규 취득 건수)
- 용도: 무자본 M&A 세력의 SPC·자회사망 추적, `related_party_hollowing` 패턴·`find_actor_overlap`·`scan_financial_anomaly`(CFS_OFS_REVERSAL)와 교차 확인
- 금액은 DART 응답 원문 표기 그대로(보고서별 단위 혼용 가능 → 단위 유의 안내 자동 첨부). 점수·등급 없음
- `year` 미입력 시 직전 연도. 표 셀은 개행·파이프 정제(`_cell`) — 원문 개행이 표를 깨지 않음

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
| `fetch_executive_roster(corp_code, api_key, lookback_years)` | 임원현황(exctvSttus) 다년 수집 → {임원명: {연도}} 합집합. 조합명 비고정성 우회용 고정점 (find_actor_overlap 임원 차원) |
| `fetch_insider_timeline(corp_code, api_key, lookback_years)` | elestock + hyslrSttus + hyslrChgSttus + tesstkAcqsDspsSttus 4엔드포인트 × 4분기 통합 시계열 (v0.8.6) |
| `detect_insider_pre_disclosure(insider_records, signal_events, window_days=30)` | 매도 ±30일 내 부정 공시 패턴 탐지 (v0.8.6) |
| `fetch_treasury_decisions(corp_code, api_key, lookback_years)` | 자사주 결정 4엔드포인트(취득·처분·신탁체결·신탁해지) 통합. key=TREASURY/TREASURY_TRUST로 정규화 (v0.8.7) |
| `fetch_company_indicators(corp_code, api_key, bsns_year, reprt_code)` | 단일회사 주요 재무지표 4카테고리(수익성·안정성·성장성·활동성) 통합 → {idx_nm: float} flat dict (v0.8.8) |
| `fetch_distress_events(corp_code, api_key, lookback_years)` | 부도·영업정지·회생절차·해산사유 4엔드포인트 통합. key=DISTRESS_EVENT + subtype 라벨 (v0.9.0) |
| `fetch_dividend_history(corp_code, api_key, lookback_years)` | alotMatter을 분기 4코드 × N년 호출. 각 record에 bsns_year/reprt_code 부착 (v0.9.0) |
| `detect_dividend_drain(dividend_records, current_fs)` | 적자 시점 배당 유출(DIVIDEND_DRAIN) 패턴 — 당기순이익 음수 + 현금배당 양수 시 flag (v0.9.0) |
| `fetch_affiliate_investments(corp_code, api_key, year, report_type)` | 타법인 출자현황(otrCprInvstmntSttus) 조회 + 합계 행 제거 |
| `scan_note_titles(rcept_no, api_key)` | 공시 ZIP 전 파일 `<TITLE>` 태그 스캔 → 주석 카테고리 제목 검출 (섹션 추출 보완 경로) |
| `compute_beneish_variables(current, prior)` | Beneish 개별 변수 6종 YoY 지수 계산 — 합산·판정 없음, 사실 표기 전용 |
| `detect_profit_direction_divergence(current)` | 영업이익↔순이익 부호 괴리 (OPNET_POS_NEG / OPNET_NEG_POS) |
| `detect_restatement(current_rows, prior_rows)` | 전기 수치 재작성 감지 — 연도 간 보고값 대조, 원인 판정 없음 (RESTATEMENT) |
| `extract_rd_ratio_from_report(corp_code, api_key)` | 최근 사업보고서 원문에서 연구개발비/매출액 비율(최근 3개 연도) regex 추출 |
| `fetch_loss_streak(corp_code, api_key, lookback_years)` | 연도별 영업이익·순이익 부호 → 최신 연도부터 연속 적자 연수 |
| `extract_cfs_ofs_ni(fs_rows)` | fnlttSinglAcnt rows에서 (연결, 별도) 당기순이익 쌍 추출 — CFS_OFS_REVERSAL 판정 입력 |
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
| `GET /api/exctvSttus.json` | 임원 현황 (corp_code, bsns_year, reprt_code) — find_actor_overlap 겸직 탐지 |
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
| `GET /api/otrCprInvstmntSttus.json` | 타법인 출자현황 (corp_code, bsns_year, reprt_code) — get_affiliate_investments |
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
| 워치리스트(영속, 캐시 아님) | `~/.config/dart-risk-mcp/watchlist.json` (`DART_WATCHLIST_PATH`로 오버라이드) | 영속(비휘발) |
| 공개기록 원격 캐시 | `~/.cache/dart-risk-mcp/known_actors_remote.json` (GitHub raw fetch) | 24시간 |

> 워치리스트는 캐시가 아니라 사용자 자산이라 `~/.cache`가 아닌 `~/.config`에 영속 저장합니다. `core/watchlist.py`의 `add_person`/`remove_person`/`get_person_companies`/`list_persons`/`load_watchlist`/`save_watchlist`가 관리합니다.

---

## 코딩 규칙

- **외부 라이브러리 추가 금지**: `requests`와 `mcp` 외 의존성을 추가하지 않습니다. HTML 파싱도 regex + 문자열 처리로 구현합니다.
- **인코딩 처리**: DART 문서는 utf-8, euc-kr, cp949 순으로 시도합니다 (`_decode_zip_file`).
- **오류 처리**: API 호출 실패 시 빈 값 반환 (예외를 도구 레벨로 전파하지 않음).
- **정정공시 필터**: `is_amendment_disclosure(report_nm)`으로 `[기재정정]` 등을 감지해 내부 랭킹에서 제외합니다.
- **점수·등급 없음 원칙 (v0.8.5)**: 기업 위험도를 정량화하거나 등급("매우위험", "고위험" 등)으로 부여하는 어떤 표기도 사용자 출력에 노출되면 안 됩니다. 내부에서는 `SIGNAL_TYPES[*].score`·`taxonomy.base_score`로 신호 우선순위를 정렬하지만 렌더 경로로 유출되면 안 됩니다. `tests/test_golden_output_hygiene.py`가 점수/등급/이모지 회귀를 기계적으로 막습니다.

---

## 비범위 (v1.0 GA에서 영구 확정)

PR이나 이슈가 다음 항목 중 하나를 요청한다면 본 도구의 설계 결정과 충돌합니다. README "이 도구가 하지 않는 것" 절과 동일 정책이며, 우회 코드 추가를 금지합니다.

| 비범위 | 사유 / 검증 출처 |
|--------|------------------|
| 점수·등급 부여 | v0.8.5 원칙 — 정량화는 법적 판단·투자 권유로 해석될 수 있음 |
| 실시간 알림·푸시 | 사용자 책임 영역(별도 시스템) |
| 매수/매도 추천·가격 예측 | 본 도구 출력은 투자 판단 근거가 아님 |
| 업종 평균 비교 | DART API 미제공 — `tmp/v1_feasibility/REPORT.md` #6 검증 |
| 해외상장 신호 | 한국 기업 발생 빈도 미미 — v1.0 검증 후 영구 폐기(#8) |
| 비상장사 감사보고서 정량 추출 | 비정형 PDF — v0.7.x Track C 폐기 |
| 시장 전체 일일 자동 스캔 | DART 호출 한도 + 사용자 책임 영역 분리 |
| DS007 증권신고서(bdRs/mgRs) | 5개 대형 회사 3년 윈도우 0건 — v1.0.1 검증 후 영구 폐기 |

신규 도구 추가 시 위 비범위에 해당하지 않는지 먼저 확인하고, 도구 카탈로그 23개의 인플레이션을 회피합니다(흡수 우선 — v0.9.0 `analyze_company_risk` 부실 후속 흡수 사례 참고).

---

## 라이브 검증 매트릭스 (v1.0.3 기준)

각 도구·신호 키가 실 DART API 응답으로 매칭된 적 있는지 정직 표기. ⚠ = 코드와 단위 테스트는 있으나 라이브 매칭 사례 0 → 사례 발견 시 골드 추가하고 ⚠ 제거.

| 항목 | 라이브 검증 | 비고 |
|---|:---:|---|
| 회사명 단순 13개 도구 + 종목/접수번호/재무/감사/채무 도구 | ✅ | 6 회사 매트릭스 골드 (셀트리온·제이스코·두산에너빌리티·삼성전자·헬릭스미스·두산) |
| `search_market_disclosures` 12개 preset | ✅ | v1.0.3에서 8개 추가, 골드 `tests/fixtures/sample_outputs/market_*.txt` 12개 |
| `track_capital_structure` 의 `capital_churn_anomaly` | ✅ | 제이스코홀딩스 라이브 매칭 |
| `scan_financial_anomaly` 의 `CFS_OFS_REVERSAL` | ✅ | 셀트리온 라이브 매칭 (연결 4,189억 < 별도 1조48억, -58.3%), 골드 `셀트리온_scan_fs.txt` |
| `get_affiliate_investments` | ✅ | 6사 골드 `*_affiliates.txt` (삼성전자 137건·제이스코 2건 등 라이브) |
| `scan_financial_anomaly` 의 `RESTATEMENT` | ✅ | 셀트리온(최대 +1.4%)·두산(최대 -15.1%) 라이브 매칭, 골드 `*_scan_fs.txt` |
| `scan_financial_anomaly` 의 `OPNET_POS_NEG`/`OPNET_NEG_POS` | ⚠ | 6사 매트릭스 미발화(모두 부호 동일) — 위험사례 발굴 시 골드 추가 |
| `scan_financial_anomaly` 의 R&D 비중 블록 | ✅ | 5/6사 라이브 추출(삼성 11.3%·헬릭스미스 115.8% 등), 제이스코는 R&D 표 없음(정상) |
| `get_audit_opinion_history` 의 연속 적자 블록 | ✅ | 헬릭스미스 5년·제이스코 영업 4년/순손실 5년 라이브 매칭 |
| `find_actor_overlap` 임원 겸직 매칭 | ✅ | 신승수군 3개사 겸직 라이브 매칭(신용규·이호영 동행 포함), 골드 `tests/fixtures/sample_outputs/actor_overlap.txt` |
| `TREASURY_TRUST` (v0.8.7) | ⚠ | 자사주 신탁 발생 빈도 낮음 |
| `INSIDER_PRE_DISCLOSURE` (v0.8.6) | ⚠ | 매도 ±30일 부정 공시 |
| `DIVIDEND_DRAIN` (v0.9.0) | ⚠ | 적자 시점 배당 동시 사례 |
| `DISTRESS_EVENT` (v0.9.0) | ⚠ | 부도/영업정지/회생/해산 4 endpoint, 헬릭스미스조차 미발화 |
| `get_major_decision` 12개 decision_type | ⚠ | DS005 빈도 낮음, 단위 테스트만, 6 회사 365일 0건 |
| `CROSS_SIGNAL_PATTERNS` 9개 중 8개 (capital_churn_anomaly 제외) | ⚠ | `founder_fade`·`debt_spiral`·`reverse_split_spiral`·`related_party_hollowing`·`zombie_ma`·`audit_insider_dump`·`delisting_evasion`·`fake_new_biz` |

신규 PR이 ⚠ 항목의 라이브 매칭 사례 발굴 시: (1) 사례 회사를 `scripts/regen_goldens.py`의 `COMPANIES`에 추가하거나 (2) `tests/fixtures/sample_outputs/`에 직접 골드 추가. hygiene 검증 9/9 PASS 후 ⚠ 제거.

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

### 골드 출력 재생성 (회귀 검증용)

`scripts/regen_goldens.py`로 6개 회사 × 23개 도구 매트릭스를 한 번에 재생성합니다.
API 키는 `tmp/_apikey.txt` 또는 환경변수 `DART_API_KEY`에서 자동 로드.

```bash
python scripts/regen_goldens.py --dry-run                            # 호출 매트릭스만 확인
python scripts/regen_goldens.py --companies 셀트리온 --tools capital  # 부분 재생성
python scripts/regen_goldens.py                                       # 전체 ≥100개 재생성
```

생성 후 `python -m pytest tests/test_golden_output_hygiene.py -v`로 회귀 검증.

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

# context-mode — MANDATORY routing rules

You have context-mode MCP tools available. These rules are NOT optional — they protect your context window from flooding. A single unrouted command can dump 56 KB into context and waste the entire session.

## BLOCKED commands — do NOT attempt these

### curl / wget — BLOCKED
Any Bash command containing `curl` or `wget` is intercepted and replaced with an error message. Do NOT retry.
Instead use:
- `ctx_fetch_and_index(url, source)` to fetch and index web pages
- `ctx_execute(language: "javascript", code: "const r = await fetch(...)")` to run HTTP calls in sandbox

### Inline HTTP — BLOCKED
Any Bash command containing `fetch('http`, `requests.get(`, `requests.post(`, `http.get(`, or `http.request(` is intercepted and replaced with an error message. Do NOT retry with Bash.
Instead use:
- `ctx_execute(language, code)` to run HTTP calls in sandbox — only stdout enters context

### WebFetch — BLOCKED
WebFetch calls are denied entirely. The URL is extracted and you are told to use `ctx_fetch_and_index` instead.
Instead use:
- `ctx_fetch_and_index(url, source)` then `ctx_search(queries)` to query the indexed content

## REDIRECTED tools — use sandbox equivalents

### Bash (>20 lines output)
Bash is ONLY for: `git`, `mkdir`, `rm`, `mv`, `cd`, `ls`, `npm install`, `pip install`, and other short-output commands.
For everything else, use:
- `ctx_batch_execute(commands, queries)` — run multiple commands + search in ONE call
- `ctx_execute(language: "shell", code: "...")` — run in sandbox, only stdout enters context

### Read (for analysis)
If you are reading a file to **Edit** it → Read is correct (Edit needs content in context).
If you are reading to **analyze, explore, or summarize** → use `ctx_execute_file(path, language, code)` instead. Only your printed summary enters context. The raw file content stays in the sandbox.

### Grep (large results)
Grep results can flood context. Use `ctx_execute(language: "shell", code: "grep ...")` to run searches in sandbox. Only your printed summary enters context.

## Tool selection hierarchy

1. **GATHER**: `ctx_batch_execute(commands, queries)` — Primary tool. Runs all commands, auto-indexes output, returns search results. ONE call replaces 30+ individual calls.
2. **FOLLOW-UP**: `ctx_search(queries: ["q1", "q2", ...])` — Query indexed content. Pass ALL questions as array in ONE call.
3. **PROCESSING**: `ctx_execute(language, code)` | `ctx_execute_file(path, language, code)` — Sandbox execution. Only stdout enters context.
4. **WEB**: `ctx_fetch_and_index(url, source)` then `ctx_search(queries)` — Fetch, chunk, index, query. Raw HTML never enters context.
5. **INDEX**: `ctx_index(content, source)` — Store content in FTS5 knowledge base for later search.

## Subagent routing

When spawning subagents (Agent/Task tool), the routing block is automatically injected into their prompt. Bash-type subagents are upgraded to general-purpose so they have access to MCP tools. You do NOT need to manually instruct subagents about context-mode.

## Output constraints

- Keep responses under 500 words.
- Write artifacts (code, configs, PRDs) to FILES — never return them as inline text. Return only: file path + 1-line description.
- When indexing content, use descriptive source labels so others can `ctx_search(source: "label")` later.

## ctx commands

| Command | Action |
|---------|--------|
| `ctx stats` | Call the `ctx_stats` MCP tool and display the full output verbatim |
| `ctx doctor` | Call the `ctx_doctor` MCP tool, run the returned shell command, display as checklist |
| `ctx upgrade` | Call the `ctx_upgrade` MCP tool, run the returned shell command, display as checklist |
