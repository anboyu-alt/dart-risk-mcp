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
    ├── signals.py       # 54개 신호 유형 (8개 카테고리) + 키워드 매칭 (v0.4.0 카탈로그 기반 보강, v1.6.1 기준 54종)
    ├── catalog.py       # 금감원·금융위 MD 카탈로그 로더 (load_catalog_excerpt, taxonomy_label_ko)
    ├── cb_extractor.py  # CB/BW 인수자명 추출
    ├── sector_policy.py # 업종별 유의 회계정책 정적 맵 (KSIC 조회, kreports 이식/Apache 2.0)
    ├── notes.py         # 재무제표 주석 카테고리 분류 (제목 키워드 10종, kreports 이식/Apache 2.0)
    ├── watchlist.py     # 인물↔회사군 영속 워치리스트 (순수 파일 I/O)
    ├── known_actors.py  # 공개기록 행위자 레지스트리 로드/조회, 회사명 역방향 조회 포함 (비공개 Notion opt-in)
    ├── qualifiers.py    # 신호 한정층 — 제목 구조 파싱(parse_report_name) + observed/procedural tier 판정(qualify_signals) + 헤드라인 선정(pick_headline). 순수 함수, 네트워크 호출 없음
    └── taxonomy.py      # 44개 신호 분류(v1.6.0 기준) + 위험 점수 + 패턴 10종
```

> 동봉 데이터: `dart_risk_mcp/data/known_actors.json`(빈 스켈레톤 — v1.5.0부터 인물 데이터 미포함). 레지스트리 원본은 제작자 비공개 Notion DB. DB 셋업: `scripts/setup_known_actors_db.py`(+`setup-known-actors-db.yml`, 1회성).
> 레지스트리 로드: `load_known_actors()` 우선순위 = `DART_KNOWN_ACTORS_PATH`(로컬 JSON) > Notion(`NOTION_TOKEN`+`DB_KNOWN_ACTORS` env, 24h 캐시 `~/.cache/dart-risk-mcp/known_actors_notion.json`) > 동봉(빈 스켈레톤). Notion 미설정 시 네트워크 시도 없이 graceful 비활성화. 자동 갱신: `scripts/refresh_known_actors.py` + `.github/workflows/refresh-known-actors.yml`(매일 cron — 시장 신규 CB/유상증자 인수자를 등재 인물과 표기 정규화 매칭해 `auto_matched` 근거를 Notion에 기록, public 커밋 없음). 운영자 Secrets: `DART_API_KEY`, `NOTION_TOKEN`, `DB_KNOWN_ACTORS`.
> 레지스트리 DB 스키마: 인물명(title)·status(select)·source·evidence·date·rcept_no(rich_text)·url·tags·**관련기업**(multi_select — 등장 회사명 태깅, evidence 텍스트와 분리해 회사별 필터링·추적 가능). `discover_actors.py`는 반복 등장한 문제 회사 전체를, `refresh_known_actors.py`는 해당 근거의 단일 회사를 태깅. 스키마 마이그레이션: `scripts/setup_known_actors_db.py`를 `DB_KNOWN_ACTORS` 설정된 상태로 재실행하면 신규 속성 추가 + 기존 행 소급 백필(추가만, 삭제 없음).
> 자동 발굴: `scripts/discover_actors.py`(같은 cron)는 시장 '문제 회사'(자금조달+불안정 신호 동반)의 행위자를 **sightings로 누적**(보존 창 `WINDOW_MONTHS=140`개월 — 2015년까지의 백필 데이터가 프루닝되지 않도록 넓힘, "12개월"이던 옛 서술은 2026-08-04 감사에서 실코드와 불일치 확인·정정)하고, 서로 다른 문제 회사 2곳+(N=2)에 반복 등장하는 행위자를 레지스트리(비공개 Notion)에 `auto_matched`(자동 발굴)로 등재 + 제작자 이메일. 수집원은 3종(v1.8.0): ① CB/BW·EB·유상증자 **인수자**(`collect_funding_sightings_range`) ② 자금유출성 거래(금전대여·채무보증·담보제공·유형자산양수)의 **유출 상대방**(`collect_outflow_sightings_range` — classify_outflow_relation이 affiliated/external로 판정한 건만, **subsidiary(종속회사·자회사)는 세력 추적 대상이 아니라 제외**) ③ 최대주주변경(정정 제외)의 **신규 최대주주**(`collect_control_change_sightings_range` — "외 N인" 접미 제거 후 저장). 세 수집원 모두 상대방이 공시 회사 자신과 동일 명칭이면 제외한다. sighting 레코드의 출처는 `"src"` 필드(값 `"funding"`/`"outflow"`/`"control"`, 없으면 `"funding"` 기본 취급 — 기존 인수자 레코드와의 하위 호환)로 구분하며, 등재 evidence 문구에 혼합 출처를 "문제 회사 N곳 등장(유출 상대방·신규 최대주주): A사·B사" 형식으로 반영한다(`SRC_LABELS`/`_SRC_ORDER`). 인물 분류 필드 `"kind"`(person/fund/corp — 이미 이 의미로 쓰이던 필드라 출처 구분에는 재사용하지 않고 `"src"`를 신설)는 세 수집원 모두 동일하게 `classify_actor`로 채운다. 후자 두 수집원은 기존 `should_store`(자산운용 등 기타기관 보존)보다 넓게 제외한다 — `classify_tracked_entity`가 은행·증권·캐피탈·저축은행·금고·보험·투자신탁 등 제도권 금융기관(`classify_actor`의 institution 판정)에 더해 단독 표기 "신탁"(institution 패턴에 없음)도 게이트한다(대여·담보·최대주주 자리의 금융기관은 정상적인 대주·수탁 관계일 뿐 추적 대상이 아니라는 설계 결정). **노출 경계**: sightings(1회 포함, 미검증)는 **private repo `dart-risk-mcp-sightings`**(제작자만, `SIGHTINGS_REPO_TOKEN` PAT), 레지스트리도 **비공개 Notion**(접근은 opt-in, README 참고) — public 레포에는 어떤 인물 데이터도 커밋하지 않는다. 행위자는 `classify_actor`로 개인/조합/법인 3분류 추적(레지스트리 `구분` select) — 제도권 기관(증권사·은행·연기금 등, 반복 등장이 정상)과 임원은 제외. 베이스 백필: `scripts/backfill_sightings.py`(+`backfill-sightings.yml`). 개명 소급 병합: 행위자명은 제출 시점 사명으로 동결되므로 `scripts/backfill_renames.py`(+`backfill-renames.yml`)가 '상호변경안내' 공시를 백필해 `corp_renames`({corp_code: 옛 사명})를 sightings에 영속하고, `reconcile_corp_renames`가 옛 사명 행위자 키를 corp_code로 재해석해 별칭 병합한다. 단 '상호변경안내'는 사실상 코스닥 전용이라(610사 중 K 354 vs Y 2 실측) **KOSPI 개명(주총 정관변경, 예: 에이프로젠KIC→에이프로젠 00152385)은 수동 시드**로 소급한다 — private sightings repo의 `manual_renames.json`(스키마는 corp_renames와 동일, **근거 rcept_no 없는 entry는 기계적 거부**)을 `scripts/merge_manual_renames.py`(+`merge-manual-renames.yml`, DART 대조 검증: rcept↔corp_code 연결 치명·원문 옛 사명 표기 경고)가 검증·병합하고, daily cron(discover_actors.main)도 같은 시드를 자동 반영한다(`apply_manual_renames`). 공개 `corp-aliases.json`(주간 corp-map diff)도 `_combined_legacy_index`로 legacy 해석에 합류해 diff 도입 이후 개명은 시장 무관 자동 커버(라이브: 한국조선해양→에이치디한국조선해양 등 KOSPI 3건 소급 병합 실측). 상세: `docs/superpowers/plans/2026-08-03-kospi-rename-manual-seed.md`. 연결망 시각화: `scripts/build_network_html.py`(+`network_template.html`) — sightings에서 2사+ 추적 행위자↔회사 이분 그래프를 자체 완결형 HTML로 렌더(외부 CDN 없음). **출력 HTML은 실명 포함 → public 레포 커밋 금지**, 스크립트만 레포에 둠. 노드 병합 우선순위는 `actor_corp_ids`(reconcile_corp_renames의 명부 해석, v1.11.0) > fold2cc(비모호 fold) > 미병합 — 동명 별개 법인(실측: 에이프로젠 상장 00152385 vs 비상장 00549059)은 병합하지 않고 검색 리스트 시장 배지 + 상세 패널 "동명 별개 법인 N건" 사실 주석으로 구분한다. 유가증권(KOSPI) 상장사의 옛 상호는 '상호변경안내'가 사실상 코스닥 공시라(corp_renames 610사 중 K 354 vs Y 2 실측) 백필로 소급되지 않는 알려진 한계 — 에이프로젠KIC(2020년 KIC→MED 개명, 주총 공시로만 존재) 명의 행위자 키가 그 사례.

> **백필 실적(2026-08-17)**: 수집 3,429건 → 1차 통과 1,242건 → 2차 분류 완료. taxonomy가
> 매핑된 사례 **277건 / 22개 유형**(4.3이 130건으로 최다). 카탈로그 MD는 37종 → **45종**.
> **미매핑 965건은 대부분 의도적 공백**이다 — 일반 시세조종·미공개정보이용·부정거래·
> 선행매매·차명거래·공매도·리딩방·사모펀드는 taxonomy에 항목이 없고 DART 공시로 관측되지도
> 않는다(범위 밖). 금융투자업자 영업 규제 위반, 정책·통계 보도자료, 2010~2013 머리말뿐인
> 자료도 같은 이유로 비워 둔다. 분류·판단 근거: `docs/catalog/gap-triage-2026-08-17.md`.

> 카탈로그 생성 파이프라인: `scripts/catalog/`(collect → classify → build_md → gaps, 4단계).
> `collect`는 금감원 게시판을 웹 파싱으로 목록 수집한다(FSS 오픈API는 일일 30회 한도가
> 실증돼 폐기, API 키 불필요). `classify`는 1차 스크리닝(제목·부서) → 2차 정밀 분류
> 2단계이며, 1차 통과분에 한해 `extract.py`(라이브러리, CLI 없음)를 건별로 호출해 원문을
> 추출한다. `knowledge/manipulation_catalog/*.md`는 이 파이프라인의 산출물이며 손으로
> 고치지 않는다(고치면 다음 실행에서 덮어써진다). 한글 표시 라벨은
> `data/catalog/labels_ko.json`이 단일 출처 — `TAXONOMY`의 `name`은 45개 중 41개가
> 영문이라 사용자 노출용으로 쓸 수 없다(2026-08-16 실측). 라벨을 고치려면 JSON을 고치고
> `build_md.py`를 재실행한다.
> **의존성 경계**: `pypdf`는 `[project.optional-dependencies]`의 `catalog` 그룹 전용이며
> 런타임 패키지 `dart_risk_mcp/`는 여전히 `mcp`+`requests`만 쓴다. 미설치 환경에서는
> `extract_full`이 `None`을 반환해 요약 모드로 degrade한다.
> 자동 갱신: `.github/workflows/refresh-catalog.yml`(매월 1일 UTC 18:00 cron +
> workflow_dispatch — 수집 연도·분류 건수 상한 수동 입력 가능). 필요 Secret은
> `ANTHROPIC_API_KEY` 하나뿐(분류 단계 LLM 호출용). 카탈로그 MD·gap 리포트 생성 후
> `load_catalog_excerpt`가 비어있지 않은지·점수 메타가 노출되지 않는지 검증하고,
> `test_catalog_render.py`/`test_catalog_labels.py`/`test_golden_output_hygiene.py`를
> 통과해야 커밋·푸시한다. 패키징 경계 자체는 `tests/test_catalog_packaging.py`가 고정.
> 설계·실측 근거: `docs/superpowers/specs/2026-08-16-fss-catalog-pipeline-design.md`

---

## MCP 도구 26개

### 1. `analyze_company_risk(company_name, lookback_years=1)`

기업명 또는 종목코드로 최근 공시 전체를 스캔해 종합 위험 리포트를 반환합니다.

- 내부 흐름: `resolve_corp` → `fetch_company_disclosures` → `match_signals` × N → `calculate_risk_score` → `find_pattern_match` → `extract_cb_investors`
- 반환: 위험 등급, 탐지 신호 목록, 복합 패턴, CB 인수자, 위기 타임라인
- `lookback_years` 범위 1~5, 기본 1년. 다년(>1년) 조회 시 결과 하단에 예상 출력 규모(문자·토큰 추정) 푸터 표기.
- 공개기록 레지스트리(opt-in) 설정 시, 이 회사가 등재 행위자의 관련기업으로 태깅돼 있으면 리포트 말미에 "📎 공개기록 참고" 섹션 자동 표면화 (`lookup_actors_by_company` 역방향 조회 — 사실 표기, 판정 없음)
- v1.6.0: `FUND_OUTFLOW`/`ACQ_REVIEW` 신호가 매칭된 공시 중 `resolve_decision_type`이 결정
  유형(유형자산양수/영업양수/타법인주식및출자증권양수)을 판별하는 것만 최근 최대 2건
  `fetch_major_decision`으로 추가 조회해 "🔍 자금유출·양수거래 상대방 확인" 섹션에
  거래상대방·회사와의 관계·외부평가를 사실로 표기(`DECISION_RELATED_PARTY` 있으면 함께
  표면화). 실패해도 이 블록만 조용히 생략 — 기존 리포트 무영향, 점수 가산 없음.
- v1.14.0: 원문 사실 블록 2종 추가 — `_related_party_detail_block`("🤝 특수관계인
  자금거래 확인", `RELATED_PARTY` 관찰 시 최근 3건까지 `fetch_related_party_detail`로
  상대방·관계·금액·**이자율**·자기자본대비 표기)와 `_earnings_shock_block`("📉 손익구조
  급변 내역", `EARNINGS_SHOCK` 관찰 시 최근 2건까지 계정별 증감비율·흑자적자전환여부
  표기). 해당 신호가 관찰되지 않으면 원문을 열지 않는다(호출 예산 0). 추출 실패 시
  블록 자체 생략 — 기존 심화 블록 관례. 점수 가산 없음. 자기자본대비는 원문 표기
  그대로 오므로 숫자일 때만 `%`를 붙인다("자본잠식" 같은 문자 표기 대응).
- v1.7.0: 조회 창 내 최대주주변경(정정·"계약체결/해제"류 예고성 공시 제외) 최근 1건의
  원문을 `fetch_control_change_detail` → `parse_control_change_detail`로 추가 확인해
  "🔁 최대주주 변경 상세" 섹션에 변경전→변경후 명칭·비율, `classify_holder_type`
  명칭 유형 라벨(조합/유한회사/주식회사/기타법인/법인 표기 없음), 인수자금(자기자금/
  차입금, 차입금>0이면 차입처·담보내역까지)을 사실로 표기. 근거: 금감원 무자본 M&A
  합동점검(2019-12-19) — 적발 24사의 신규 최대주주 82%가 비외감법인·투자조합,
  인수자금 대부분이 주식담보대출(단계①, 차입금>0일 때만 인용문 1줄 첨부). 변경후
  명칭(외 N인 접미 제거)을 공개기록 레지스트리와도 대조(`lookup_actor`, 미설정 시
  조용히 생략). 원문 추출 실패 시 블록 자체 생략 — 점수 가산 없음.

### 2. `check_disclosure_risk(rcept_no="", report_name="")`

개별 공시 하나를 분석합니다. 접수번호가 있으면 원문 500자 미리보기도 포함합니다.

- 접수번호 또는 공시 제목 중 하나만 있어도 작동
- 접수번호가 있으면 **제목 동반 여부와 무관하게** `resolve_disclosure_row_from_rcept_no`로 list.json 원본 행을 역해석해 제출인(`flr_nm`)·회사명을 복원하고 한정층 판정 입력(`filing`)으로 쓴다 — 행이 있어야 R1(제출인 ≠ 회사)이 발화하므로, 접수번호+제목을 함께 넘긴 호출과 접수번호만 넘긴 호출이 같은 공시에 같은 판정을 낸다. `report_name`을 넘기면 **표시 제목은 그 값이 우선**하고, `제출인:` 줄은 행 조회에 성공했을 때만 표기한다. 실패 시 자리표시자 제목("접수번호 N")·무신호로 조용히 퇴화(회귀 아님)
- CB/BW 공시면 자동으로 인수자 추출
- DS005 결정 공시(제목으로 `resolve_decision_type` 판별)면 `resolve_corp_code_from_rcept_no`로 rcept_no→corp_code를 역해석해 "📑 주요 결정 공시" 섹션에 상대방·금액·특수관계·외부평가 표기 — DS005는 corp_code가 항상 필수라 역해석 실패 시 헛호출 없이 섹션만 생략
- 한정층(`qualify_signals`) 적용: 매칭 신호마다 `🎯` observed 또는 `⚪ 절차·사후 보고`(강등 사유 동반)로 단일 판정 표시. 단건 공시 도구라 `analyze_company_risk`/`build_event_timeline`의 관찰/절차 두 섹션 레이아웃은 쓰지 않는다. 강등 줄에 덧붙는 문장은 `analyze_company_risk`와 같은 한정 표현("회사가 낸 사건 자체의 공시가 아니거나 이미 끝난 건의 사후 보고입니다")을 쓴다 — R1/R1b만 참인 단정 표현은 R2(결과보고서)·R3(자회사)·R4(해명)·R5(정정)에서 강등 사유와 정면 모순된다. 금감원 카탈로그 발췌(`load_catalog_excerpt`)도 **observed 신호의 taxonomy id만** 입력으로 받는다 — 전부 강등된 공시에서 수 KB 발췌가 출력을 뒤덮어 강등을 시각적으로 되돌리지 않게 하기 위함

### 3. `find_risk_precedents(signal_types, lookback_days=90)`

신호 유형 목록을 받아 각 신호의 의미, 위기 타임라인, 복합 패턴을 반환합니다.

- 실제 과거 공시 검색은 하지 않음 (taxonomy 정적 데이터 조회)
- `SIGNAL_KEY_TO_TAXONOMY`로 신호 키 → taxonomy ID(1.1~8.5) 매핑 후 조회
- 사용 가능한 신호 키 (30개, 8개 카테고리):

  > ⚠ 아래 키 중 15종(`CB_REPAY`·`CB_BUYBACK`·`CB_ROLLOVER`·`TREASURY_EB`·`BUYBACK_NEG`·`MEETING_VIOL`·`ACTIVIST`·`DISTRESS_MA`·`GAMJA_MERGE`·`CAPITAL_RED`·`RIGHTS_UNDER`·`ASSET_SPIRAL`·`CIRCULAR`·`REVENUE_IRREG`·`CONTINGENT`)은 **공시 제목으로 발화하지 않는다**(`core/signals.py`의 `NON_TITLE_SIGNALS`). `find_risk_precedents`로 조회하면 그 사실이 함께 표시된다.

  | 카테고리 | 키 목록 |
  |---------|---------|
  | Cat 1 CB/채권 | `CB_BW`, `CB_REPAY`, `EB`, `RCPS`, `CB_ROLLOVER`, `CB_BUYBACK`, `TREASURY_EB` |
  | Cat 2 자본구조 | `REVERSE_SPLIT`, `GAMJA_MERGE`, `3PCA`, `RIGHTS_UNDER`, `TREASURY` |
  | Cat 3 경영권 | `SHAREHOLDER`, `EXEC`, `MGMT_DISPUTE`, `CIRCULAR`, `STAKE_PLEDGE` |
  | Cat 4 거버넌스 | `RELATED_PARTY`, `AUDIT` |
  | Cat 5 기업활동 | `ASSET_TRANSFER`, `DEMERGER`, `MGMT`, `FUND_OUTFLOW`, `ACQ_REVIEW` |
  | Cat 6 회계/재무 | `REVENUE_IRREG`, `CONTINGENT` |
  | Cat 7 시장조작 | `INQUIRY`, `EMBEZZLE` |
  | Cat 8 위기/부실 | `INSOLVENCY`, `DEBT_RESTR`, `GOING_CONCERN`, `DELISTING_RISK`, `WATCH_ISSUE` |

  v1.6.0 신규: `FUND_OUTFLOW`(금전대여·채무보증·담보제공·유형자산양수 — 참고 강도, taxonomy 5.7)
  · `ACQ_REVIEW`(영업양수·타법인주식및출자증권양수 — 상대방 확인 안내, taxonomy 5.8).
  **v1.12.1 `INQUIRY` 정밀화 (2026-08-21)**: 키워드 8종을 시장 전체 실측
  (2026-05-23~2026-08-21, 90일·고유 공시 49,816건)으로 재검증해 5종을 제거했다 —
  "거래정지"·"매매정지"(304건/45종을 잡았지만 조회공시·풍문 계열은 4건뿐,
  나머지는 주식병합·감자·무상증자 등 기업행위에 따른 정례적 매매정지)와
  "주가이상"·"이상거래"·"거래량급증"(전부 0건, DART 공시 제목에 없는 표현).
  남은 3종은 "조회공시"(142건)·"풍문또는보도"(148건)·"조회공시요구"(139건).
  동시에 `SIGNAL_KEY_TO_TAXONOMY["INQUIRY"]`를 `["4.3","7.1"]` → `["7.1"]`로 좁혔다 —
  조회공시는 공시·보고 의무 위반이 아니고 4.3은 `DISCLOSURE_VIOL`이 맡는다.
  실사고: 한탑(002680)에서 「주권매매거래정지(주식의 병합, 분할 등 전자등록 변경,
  말소)」 **1건**이 조회공시로 오탐되고 이중 매핑을 타고 4.3+7.1을 동시에 켜서,
  부분 겹침 임계(`min_overlap=2`)를 단독 충족해 무자본 M&A·허위 신사업 주가부양·
  상폐 회피 카드 3개를 한꺼번에 띄웠다(수정 후 한탑 관찰 taxonomy에서 4.3·7.1이
  사라지고 패턴 겹침 0건). **알려진 공백**: 「…(상장폐지사유발생)」·
  「…(상장적격성실질심사대상)」·「…(개선기간부여)」류 약 60건(90일 기준)이 이제
  어떤 신호에도 잡히지 않는다 — 실제로 의미 있는 상장폐지 위기 신호지만 7.1이
  아니라 8.x 위기·부실 계열에 속하고 지금 그 자리를 맡는 신호가 없다. 억지로
  붙이면 이번에 고친 오분류를 반대 방향으로 되풀이하는 셈이라 신호 신설은 별도
  판단으로 남겼다.

  v1.6.1 신규: `STAKE_PLEDGE`(최대주주 주식담보제공계약 체결·해제·취소 — 참고 강도, taxonomy 3.7).
  "최대주주변경을수반하는주식담보제공계약체결"류는 최대주주 개인의 주식담보 차입이라
  `FUND_OUTFLOW`에서 분리했다(회사 자금 유출이 아님). `FUND_OUTFLOW` 키워드도 "담보제공"
  단독에서 "담보제공결정"·"특수관계인에대한담보제공"으로 정밀화해 이 오분류를 막았다
  (라이브 시장 스캔에서 4개 회사 동일 제목의 "특수관계인에대한담보제공"이 "담보제공결정"
  단독 키워드로는 누락되는 것을 실측 확인해 별도 키워드로 보강).
  경영권 변경(`SHAREHOLDER`, 3.1) 직후 `FUND_OUTFLOW`가 겹치면 복합 패턴 `capital_backflow`
  ("자금 역류", CRITICAL) 후보가 되지만, v1.6.1부터는 제목 매칭만으로 바로 발화하지
  않는다 — `analyze_company_risk`/`build_event_timeline`이 원문(금전대여·채무보증·
  담보제공)과 DS005 구조화 데이터(유형자산양수)로 거래상대방·관계를 확인해 **계열·
  특수관계(비연결) 관계가 1건이라도 확인될 때만** 패턴을 표시한다(`server.py`의
  `_confirm_outflow_counterparties`/`_capital_backflow_gate`). 종속회사·외부로만
  확인되거나 상대방을 아예 특정하지 못하면 패턴 대신 사실 블록으로 대체된다 —
  아틀라스링크(01309795, 297570)·한농화성(011500) 라이브 매칭, 아래
  "제목 수준 vs 내용 확인 감사표" 참고. v1.9.0: 상대방이 종속회사로 확인된
  건은 타법인 출자현황(`fetch_affiliate_investments`)과 대조해 그 종속회사의
  지분 변동·최근 순이익을 "상대방 확인" 블록 해당 줄에 사실로만 병기한다
  (`match_affiliate_row`/`summarize_affiliate_stake` — 판정·게이트 발화
  조건은 불변, subsidiary는 여전히 패턴 미발화 사유). 아틀라스링크 실측: "주식회사
  한국파일 · 관계: 종속회사 — 최초취득 2023-09 · 지분 46.3→62.4% 확대 · 피출자사
  최근 순이익 -49억원".

### 4. `build_event_timeline(company_name, lookback_years=1)` ✨

기업의 공시 이벤트를 시간순 서사 구조로 구성합니다.

- 진입기(CB_BW, 3PCA, MGMT), 심화기(SHAREHOLDER, EXEC), 탈출기(INQUIRY, AUDIT, EMBEZZLE) 3단계 분류
- `CROSS_SIGNAL_PATTERNS`(taxonomy.py)과 매칭하여 알려진 위기 패턴 식별
- CB 인수자(행위자) 정보도 함께 표시
- 정정공시는 자동 제외
- `lookback_years` 범위 1~5, 기본 1년. 다년(>1년) 조회 시 결과 하단에 예상 출력 규모(문자·토큰 추정) 푸터 표기.
- 공개기록 레지스트리(opt-in) 설정 시, 이 회사가 등재 행위자의 관련기업으로 태깅돼 있으면 리포트 말미에 "📎 공개기록 참고" 섹션 자동 표면화 (`lookup_actors_by_company` 역방향 조회 — 사실 표기, 판정 없음)
- v1.7.0: `analyze_company_risk`와 동일한 "🔁 최대주주 변경 상세" 블록(최대주주변경
  원문에서 신규 최대주주 명칭·유형·자금조달 사실 추출)을 공개기록 참고 섹션 앞에 표시.
- v1.14.0: `analyze_company_risk`와 동일한 "🤝 특수관계인 자금거래 확인"·"📉 손익구조
  급변 내역" 블록을 최대주주 변경 상세 앞에 표시.

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

- `preset` 허용값: `cb_issue`, `treasury`, `reverse_split`, `3pca`, `shareholder_change`, `exec_change`, `audit_issue`, `asset_transfer`, `going_concern`, `delisting`(v1.12.2 신규 — `DELISTING_RISK`+`WATCH_ISSUE`), `embezzle`, `inquiry`, `fund_outflow`(v1.6.0 신규 — `FUND_OUTFLOW`/`ACQ_REVIEW`), `all_risk`
- `days` 범위: 1~90일, `max_results` 범위: 1~200건
- v1.10.2: 시장 스캔을 **2일 청크**로 순회하고, 상한(1,000건) 도달 청크는 **1일 단위 재분할**(상한 1,500건)로 재조회 — 한 호출로 창 전체를 덮으려다 최신 1~2일만 스캔되던 조용한 절단 해소(실사고: asset_transfer 30일이 7/22 유형자산양수를 놓침). 하루가 1,500건을 넘는 극단일만 "스캔 구간 일부 절단"으로 정직 표기
- 내부 흐름: `fetch_market_disclosures` (corp_code 없이 `/list.json`) → `match_signals` → 한정층(`qualify_signals`)으로 관찰/절차 분리 → `_filter_market_rows`가 절차·사후 보고 행을 제외하고 관찰 신호만 preset 필터에 통과
- 반환: 날짜|기업|공시명|신호|접수번호 한 줄씩(관찰 신호만). 헤더에 "전체 N건 중 관찰 신호 M건 (표시 K건) · 절차·사후 보고 P건 제외" 건수 표기

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
- 통합 엔드포인트: `elestock`(임원·주요주주 특정증권 소유보고, 전체 이력 — 등기임원·지배주주 중심이며 5% 대량보유가 아니다. 그건 `fetch_major_holdings`/`majorstock.json`이다) + `hyslrSttus`(최대주주 현황) + `hyslrChgSttus`(최대주주 변동현황) + `tesstkAcqsDspsSttus`(임원·주요주주 자기주식). 신규 3개는 4개 분기 reprt_code(11011·11012·11013·11014) × N년 루프.
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

- 내부 흐름: `resolve_corp` → `fetch_financial_statements_all` (CFS→OFS 폴백) → `_fs_response_to_periods` → **`fetch_company_indicators` × 2(당기/전기)** → `extract_loan_advance(fs_list)`(추가 API 호출 없음) → `detect_financial_anomaly(current, prior, current_indx, prior_indx, loan_advance=...)`
- 이상 플래그 9종: `AR_SURGE`, `INVENTORY_SURGE`, `CASH_GAP`, `CAPITAL_IMPAIRMENT`(절대 임계) + `CFS_OFS_REVERSAL`(별도>연결 당기순이익 역전 — 종속회사 합산 손실, 격차 ≥10%일 때만. 정상 대기업의 연결>별도 괴리는 플래그하지 않음 — 삼성전자 +46% 라이브 검증) + `OPNET_POS_NEG`(영업흑자·순손실 — 영업외 손실)·`OPNET_NEG_POS`(영업적자·순이익 흑자 — 일회성 이익 의심, 상폐 요건 회피 연관) + `RESTATEMENT`(전기 수치 재작성 — 올해 보고서의 전기값 vs 작년 보고서의 당기값을 6계정×fs_div 대조, 0.5% 허용오차. `detect_restatement`, 직전 연도 `fnlttSinglAcnt` 1회 추가 호출) + `LOAN_ADVANCE_SURGE`(v1.6.0, 금감원 2019-12 무자본 M&A 합동점검 유의사항 ③ 도구화 — 재무상태표 대여금+선급금 합계가 전기 대비 2배↑·10억원↑이면 플래그)
- 발생액 비율 (순이익−영업현금흐름)/|순이익| 을 당기/전기/Δ로 사실 표기(플래그 없음, kreports accrual_ratio 이식). 연결/별도 비교는 `fnlttSinglAcnt` 1회 추가 호출로 CFS/OFS 당기순이익 쌍 추출(`extract_cfs_ofs_ni`)
- "대여금·선급금 (계정 노출 시)" 블록(`extract_loan_advance`, v1.6.0): fnlttSinglAcntAll rows에서 "대여금"·"선급금" 포함 계정("선급비용" 제외)을 sj_div로 재무상태표(BS, 잔액)/현금흐름표(CF, 증감) 구분해 당기/전기 사실 표기 + 금감원 합동점검 인용 1줄. 계정 자체가 노출되지 않는 회사가 흔해(셀트리온·삼성전자·제이스코홀딩스·아틀라스링크 0건) 미노출 시 블록 자체 생략(정상). 노출 시에도 BS(잔액) 항목이 있을 때만 표 상단 지표 행 + `LOAN_ADVANCE_SURGE` 판정 대상, CF(흐름) 전용 노출은 사실 표기만 하고 판정하지 않음
- "이익조작 연구 변수" 블록(`compute_beneish_variables`, kreports 이식/Apache 2.0): Beneish 개별 변수 최대 8종(DSRI·GMI·AQI·SGI·SGAI·LVGI + DEPI·TATA)을 전년=1.00 기준 지수로 사실 표기(단, TATA는 당기 비율). **M-Score 합산·임계 판정 없음**(v0.8.5 원칙, 안내 문구 자동 첨부). DEPI·TATA의 감가상각비는 fnlttSinglAcntAll 미노출이라 사업보고서 XBRL 인스턴스에서 좁게 추출(`extract_xbrl_depreciation`, annual만, ZIP +1회, `_is_zip_safe` 가드) — 소형사는 XBRL 재무 태깅이 없어(기업개황 dart-gcd만) 미발화가 정상이며 이때 기존 6종만 표기. TATA는 축약식(ΔCA−Δ현금−ΔCL−감가상각비)/총자산, LVGI는 부채총계/자산총계 기준(명칭에 명시). 라이브 발화: 삼성전자·셀트리온·두산·두산에너빌리티 4/6사
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
| `_load_corp_codes(api_key)` | DART corpCode.xml 다운로드 + 24시간 파일 캐시(포맷 `{"_v": _CORP_CACHE_VERSION, "data": {...}}`, v1.10.1). 동명 법인은 `_merge_corp_entry`로 병합(아래). 캐시 파일에 `_v` 필드가 없거나 버전이 다르면(구버전 캐시) TTL과 무관하게 재다운로드 — 실측 사례: 앤로보틱스(구 협진, 138360)가 이름을 키로 쓰는 옛 dict 로직 때문에 corp-map·resolve_corp 양쪽에서 소실됐던 것을 캐시 무효화로 치유 |
| `_merge_corp_entry(cache, mdates, name, code, stock, mdate)` | 동명 법인 충돌 정책: 상장(`stock_code` 보유) 우선, 동급(둘 다 상장/둘 다 비상장)이면 `modify_date` 최신 우선. corpCode.xml에 같은 `corp_name`의 서로 다른 법인이 존재할 수 있어(실측: 앤로보틱스 — 상장 00808068/138360/구 협진 vs 비상장 01358296/구 나이콤) 이름을 키로 쓰는 dict 구조상 한쪽은 소실되는데, 최소한 사용자가 찾을 가능성이 높은 상장사가 남도록 결정 |
| `_resolve_corp_cache_dir()` | corp_codes.json 캐시 쓰기 가능 디렉터리 반환. `_CACHE_DIR`(`~/.cache/dart-risk-mcp`) mkdir이 OSError면 `tempfile.gettempdir()/dart-risk-mcp`로 폴백(Vercel 등 서버리스는 `$HOME`이 매 호출 새 컨테이너를 가리키거나 쓰기가 막혀 있을 수 있음 — se_server/api/handlers.py의 기존 관찰과 동일 근거). 폴백마저 실패하면 `_CACHE_DIR`을 그대로 반환(예외를 삼킴) |
| `load_corp_aliases()` | 옛 상호(상호변경) → {corp_code, stock_code, current} 별칭 맵 로드. 우선순위 env `DART_CORP_ALIASES_PATH` > 레포 상대 `docs/tool/corp-aliases.json`(개발 체크아웃) > 원격(`DART_CORP_ALIASES_URL`, 기본 vercel 주소) 24시간 파일 캐시 > `{}`(전부 실패 시 graceful) |
| `resolve_corp(query, api_key)` | 기업명/종목코드 → (corp_name, {corp_code, stock_code}). 해석 순서: 정확 일치 → 종목코드 → **별칭 정확 일치(옛 상호, v1.10.0)** → 부분 일치. 별칭으로 해석되면 반환 dict에 `alias_note` 추가(자동 전환 사실 안내). 정확 일치와 별칭이 같은 이름을 두고 충돌하면(예: 동명의 죽은 법인과 상호변경 이력이 같은 이름을 공유) 기존 정확 일치를 그대로 반환하고 `alias_note`에 참고만 병기 — 자동 전환하지 않는다 |
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
| `detect_dividend_drain(dividend_records)` | 적자 시점 배당 유출(DIVIDEND_DRAIN) 패턴 — alotMatter 자체가 bundling한 연도별 (연결)/(별도)당기순이익을 그 연도 현금배당과 짝지어 flag(SE-12, v0.9.0 재설계). 별도 재무제표 조회 불필요. CFS 순이익은 지배기업소유주지분순이익(비지배지분 제외)이라 총 당기순이익과 부호가 다를 수 있음(두산 2023 CFS 실측: alotMatter -3,883억 vs 총 당기순이익 +2,721억) — 출력에 "연결·지배지분 기준" 명시 |
| `fetch_affiliate_investments(corp_code, api_key, year, report_type)` | 타법인 출자현황(otrCprInvstmntSttus) 조회 + 합계 행 제거 |
| `match_affiliate_row(rows, counterparty_name)` | 타법인 출자현황 rows에서 상대방 이름과 일치하는 행을 찾는 순수 함수. 법인 표기(㈜/(주)/주식회사) 차이는 `_fold_corp_name`으로 흡수 (v1.9.0) |
| `summarize_affiliate_stake(row, as_of=None)` | 타법인 출자현황 한 행에서 최초취득일·기초/기말 지분율·증감액·피출자사 최근 순이익을 사실로 요약하는 순수 함수. 콤마·"-"(미기재) 안전 파싱 (v1.9.0) |
| `parse_outflow_detail(text)` | 금전대여·채무보증·담보제공 결정 원문(fetch_document_text 출력)에서 상대방·관계·금액·자기자본대비를 정규식으로 추출하는 순수 파서. "대여 상대"/"성명(법인명)" 두 라벨, "-회사와의 관계"/"(회사와의 관계)" 두 괄호 변형 모두 대응 (v1.6.1) |
| `fetch_outflow_detail(rcept_no, api_key)` | `fetch_document_text(max_chars=4000)` + `parse_outflow_detail` 래퍼. 실패 시 빈 dict (v1.6.1) |
| `classify_outflow_relation(relation)` | 관계 원문 표기 → affiliated(계열·특수관계)/subsidiary(종속회사)/external(타인 등)/unknown(추출 실패) 4범주 분류 — `capital_backflow` 게이트의 입력 (v1.6.1). 부정 표기("특수관계 없음"·"최대주주 아님" 등)는 키워드 검사보다 먼저 external로 분류한다 — 부분 문자열 매칭이 affiliated로 오분류해 CRITICAL 패턴을 오발화시키던 버그 수정(2026-08-04) |
| `parse_control_change_detail(text)` | 최대주주변경 원문(fetch_document_text 출력)에서 변경전/후 최대주주 명칭·비율·변경사유·지분인수목적·자금조달(자기자금/차입금/차입처/담보내역)을 정규식으로 추출하는 순수 파서. "외 N인"(공백 있음)/"외N명"(공백 없음)/"외 N"(단위 생략) 3변형 모두 대응 (v1.7.0) |
| `fetch_control_change_detail(rcept_no, api_key)` | `fetch_document_text(max_chars=4000)` + `parse_control_change_detail` 래퍼. 실패 시 빈 dict (v1.7.0) |
| `classify_holder_type(name)` / `strip_holder_suffix(name)` | 신규 최대주주 명칭 표기 기준 사실 라벨(조합/유한회사/주식회사/기타법인/법인 표기 없음) 5분류 + "외 N인/명" 접미 제거 유틸. 판정 아님 — 명칭 표기만 본다 (v1.7.0) |
| `scan_note_titles(rcept_no, api_key)` | 공시 ZIP 전 파일 `<TITLE>` 태그 스캔 → 주석 카테고리 제목 검출 (섹션 추출 보완 경로) |
| `compute_beneish_variables(current, prior, dep_current, dep_prior)` | Beneish 개별 변수 최대 8종 계산(감가상각비 인자 제공 시 DEPI·TATA 포함) — 합산·판정 없음, 사실 표기 전용 |
| `extract_xbrl_depreciation(corp_code, api_key, fs_div, year)` | 사업보고서 XBRL 인스턴스(fnlttXbrl.xml)에서 감가상각비 당기/전기 좁은 추출 — 연결/별도 축 매칭, 분기·세그먼트 컨텍스트 제외, 10분 캐시 |
| `parse_xbrl_depreciation(instance_xml, fs_div)` | XBRL 인스턴스 텍스트 → 감가상각비 {current, prior, tag} 순수 파서 (extract의 코어) |
| `detect_profit_direction_divergence(current)` | 영업이익↔순이익 부호 괴리 (OPNET_POS_NEG / OPNET_NEG_POS) |
| `detect_restatement(current_rows, prior_rows)` | 전기 수치 재작성 감지 — 연도 간 보고값 대조, 원인 판정 없음 (RESTATEMENT) |
| `extract_rd_ratio_from_report(corp_code, api_key)` | 최근 사업보고서 원문에서 연구개발비/매출액 비율(최근 3개 연도) regex 추출 |
| `fetch_loss_streak(corp_code, api_key, lookback_years)` | 연도별 영업이익·순이익 부호 → 최신 연도부터 연속 적자 연수 |
| `extract_cfs_ofs_ni(fs_rows)` | fnlttSinglAcnt rows에서 (연결, 별도) 당기순이익 쌍 추출 — CFS_OFS_REVERSAL 판정 입력 |
| `extract_loan_advance(rows)` | fnlttSinglAcntAll rows에서 대여금·선급금 계정을 BS(잔액)/CF(증감)로 구분 추출 — LOAN_ADVANCE_SURGE 판정 입력(v1.6.0, 금감원 2019-12 무자본 M&A 합동점검 유의사항 ③) |
| `fetch_fund_usage(corp_code, api_key, corp_cls, lookback_years)` | 공모·사모 자금사용 2개 엔드포인트 통합 + 이상 플래그 탐지 |
| `fetch_major_decision(rcept_no, corp_cls, decision_type)` | 12개 DS005 주요결정 엔드포인트 중 decision_type에 따라 자동 선택 |
| `resolve_corp_code_from_rcept_no(rcept_no, api_key, max_pages=3)` | rcept_no → corp_code 역해석 — 접수일 하루치 주요사항보고(B) 목록 대조, 최대 3페이지·매칭 즉시 종료·10분 캐시. DS005 필수 corp_code를 접수번호만 아는 경로(check_disclosure_risk)에서 복원 |
| `resolve_disclosure_row_from_rcept_no(rcept_no, api_key, max_pages=12)` | rcept_no → list.json 원본 행 전체(제목·제출인 등) 역해석. `pblntf_ty` 필터 없이 조회 — 형제 함수(`resolve_corp_code_from_rcept_no`)는 `pblntf_ty="B"`로 좁혀 지분공시·거래소공시를 못 찾는다. 매칭 즉시 종료·페이지 간 0.25초 대기·10분 캐시(`_rcept_row_cache`, **실패도 센티널로 캐시**해 재조회가 12회를 다시 쓰지 않게 한다. 단 네트워크 오류·비정상 status는 일시적일 수 있어 미캐시). 알려진 한계 ① 접수번호 앞 8자리가 접수일과 다른 공시는 `None`(실측 0.7% — 20260803 전수 610건 중 4건). ② **페이지 상한 `max_pages`(12)×100 = 하루 1,200행**까지만 훑는다 — 20260731 실측 1,159건(12페이지)이 이미 상한의 96%라 이보다 무거운 날은 뒷부분 행이 스캔 범위 밖으로 밀려 `None`이 되고, **이 `None`은 "그 접수번호가 존재하지 않음"과 구분되지 않는다**(호출부는 둘 다 자리표시자 제목·무신호로 퇴화). 상한 상향은 호출 예산 비용 결정이라 미적용 |
| `resolve_decision_type(report_nm)` | 공시명 → decision_type 키 자동 추론 (`[기재정정]` 등 접두어 제거) |
| `detect_capital_churn(events, lookback_years)` | 12개월 슬라이딩 윈도우로 CAPITAL_CHURN 판정 |
| `detect_financial_anomaly(current, prior)` | 4개 지표 YoY 비교 → 플래그+메트릭 |
| `fetch_audit_opinion_history(corp_code, api_key, lookback_years)` | 감사의견 3개 엔드포인트 × 연도 루프 통합 + 재직 연수·교체·비감사 비중 경고 |
| `fetch_debt_balance(corp_code, api_key, year)` | 채무증권 5개 엔드포인트 통합 + 1년 이내 만기 비중 산출 |
| `detect_debt_rollover(balance_history, capital_events)` | 3년 잔액 변동 ≤10% + CB ≥2건 → CB_ROLLOVER 판정 |
| `find_pattern_overlaps(detected_taxonomies, min_overlap=2)` | 패턴별 부분 겹침 조회 — `matched`/`missing`/`n_matched`/`n_total`, 충족률 내림차순 결정적 정렬. `find_pattern_match`(부분집합, 첫 매칭 1건)와 별개이며 그쪽은 그대로 유지 |
| `taxonomy_label_ko(tid)` | taxonomy id → 한글 라벨. **동봉 MD(`dart_risk_mcp/knowledge/`) 1순위** → `data/catalog/labels_ko.json` → 영문 폴백. ⚠ `pyproject`의 `packages=["dart_risk_mcp"]` 때문에 `data/`는 설치 패키지에 없다 — labels_ko만 보면 설치본에서 조용히 영문으로 퇴화한다(2026-08-17 실측) |

### DART API 엔드포인트

| 엔드포인트 | 용도 |
|-----------|------|
| `GET /api/corpCode.xml` | 전체 기업 코드 ZIP (24시간 캐시) |
| `GET /api/list.json` | 기업별 공시 목록 (corp_code, 날짜 범위) |
| `GET /api/document.xml` | 공시 원문 ZIP (rcept_no) |
| `GET /api/company.json` | 기업 개요 정보 (corp_code) |
| `GET /api/fnlttSinglAcnt.json` | 단일 기업 재무제표 (corp_code, 연도, 보고서 유형) |
| `GET /api/fnlttMultiAcnt.json` | 다중 기업 재무 비교 (corp_codes 목록) |
| `GET /api/fnlttXbrl.xml` | 사업보고서 XBRL 원본 ZIP (rcept_no) — 감가상각비 좁은 추출 전용 (v1.6.0) |
| `GET /api/majorstock.json` | 최대주주 현황 (corp_code, 연도) |
| `GET /api/elestock.json` | 임원·주요주주 특정증권 소유보고 현황 (corp_code, 연도) — 등기임원·지배주주 중심, 5% 대량보유가 아니다(그건 `/api/majorstock.json`) |
| `GET /api/hyslrSttus.json` | 최대주주 현황 (corp_code, bsns_year, reprt_code) |
| `GET /api/hyslrChgSttus.json` | 최대주주 변동현황 (corp_code, bsns_year, reprt_code) — v0.8.6 |
| `GET /api/tesstkAcqsDspsSttus.json` | 임원·주요주주 자기주식 취득·처분 현황 (corp_code, bsns_year, reprt_code) — v0.8.6 |
| `GET /api/exctvSttus.json` | 임원 현황 (corp_code, bsns_year, reprt_code) — find_actor_overlap 겸직 탐지 |
| `GET /api/pssrpCptalUseDtls.json` | 공모 자금 사용 내역 (corp_code, 연도) — dart_client.py:447 실측 명칭 |
| `GET /api/prvsrpCptalUseDtls.json` | 사모 자금 사용 내역 (corp_code, 연도) — dart_client.py:448 실측 명칭 |
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
| 기업 코드 목록 | `~/.cache/dart-risk-mcp/corp_codes_v2.json` (v1.10.2 — 포맷이 바뀌면 파일명을 바꾼다. v2 페이로드를 레거시 corp_codes.json에 썼다가 같은 캐시 디렉터리를 쓰는 구버전 설치 MCP가 평면 dict로 읽어 전 도구가 죽은 실사고(2026-08-05, 'int' object has no attribute 'get'). 레거시 파일은 구버전 소유물로 읽지도 쓰지도 않음) | 24시간 |
| 옛 상호(상호변경) 별칭 맵 | `~/.cache/dart-risk-mcp/corp_aliases.json` (env/레포 상대 파일 경로 사용 시 이 캐시는 건너뜀) | 24시간 |
| 공시 원문 ZIP | 메모리 `_zip_cache` (최대 5건) | 10분 |
| 자금사용 내역 | 메모리 `_fund_usage_cache` (최대 20건) | 10분 |
| 주요결정 공시 | 메모리 `_major_decision_cache` (최대 50건) | 10분 |
| rcept_no→corp_code 역해석 | 메모리 `_rcept_corp_cache` (최대 50건) | 10분 |
| rcept_no→list.json 원본 행 역해석 | 메모리 `_rcept_row_cache` (최대 50건, `_rcept_corp_cache`와 별도 — 값 타입·조회 범위가 달라 공유 시 한쪽 미스가 다른 쪽을 오염시킨다) | 10분 |
| 감사의견 이력 | 메모리 `_audit_history_cache` (최대 20건) | 10분 |
| 채무증권 잔액 | 메모리 `_debt_balance_cache` (최대 20건) | 10분 |
| XBRL 감가상각비 | 메모리 `_xbrl_dep_cache` (최대 10건) | 10분 |
| 워치리스트(영속, 캐시 아님) | `~/.config/dart-risk-mcp/watchlist.json` (`DART_WATCHLIST_PATH`로 오버라이드) | 영속(비휘발) |
| 행위자 레지스트리(Notion) | `~/.cache/dart-risk-mcp/known_actors_notion.json` | 24시간 |
| 행위자 레지스트리(주입 캐시) | `known_actors.set_registry_cache()` 시임 — SE가 Supabase를 주입. 미주입이 기본값이라 MCP·CLI는 파일 캐시만 쓴다 | 24시간 |

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
| `search_market_disclosures` 13개 preset | ✅ | v1.0.3에서 8개 추가, v1.6.0에서 `fund_outflow` 추가, 골드 `tests/fixtures/sample_outputs/market_*.txt` 13개 |
| `track_capital_structure` 의 `capital_churn_anomaly` | ✅ | 제이스코홀딩스 라이브 매칭 |
| `scan_financial_anomaly` 의 `CFS_OFS_REVERSAL` | ✅ | 셀트리온 라이브 매칭 (연결 4,189억 < 별도 1조48억, -58.3%), 골드 `셀트리온_scan_fs.txt` |
| `get_affiliate_investments` | ✅ | 6사 골드 `*_affiliates.txt` (삼성전자 137건·제이스코 2건 등 라이브) |
| `scan_financial_anomaly` 의 `RESTATEMENT` | ✅ | 셀트리온(최대 +1.4%)·두산(최대 -15.1%) 라이브 매칭, 골드 `*_scan_fs.txt` |
| `scan_financial_anomaly` 의 `OPNET_POS_NEG` | ✅ | 2026-08-04 ⚠ 재점검 — 두산(000150) 2020(영업이익 +5,301억/순이익 -7,480억)·두산에너빌리티(034020) 2019(영업이익 +9,184억/순이익 -2,236억) 라이브 매칭, 골드 `두산2020_scan_fs.txt` |
| `scan_financial_anomaly` 의 `OPNET_NEG_POS` | ⚠ | 2026-08-04 재점검 — 코드는 정상(`detect_profit_direction_divergence`, `op<0<ni` 대칭 조건 그대로 존재), 이마트 2023·한국전력공사 2022·아시아나항공 2020·KG모빌리티 2022·한진칼 2020·CJ CGV 2021 6개 추가 표집에서도 미발화(전부 영업·순이익 동부호). 일회성 처분이익으로 영업적자를 가리는 사례 자체가 표집 범위에서 드묾 — 사례 발굴 시 골드 추가 |
| `scan_financial_anomaly` 의 R&D 비중 블록 | ✅ | 5/6사 라이브 추출(삼성 11.3%·헬릭스미스 115.8% 등), 제이스코는 R&D 표 없음(정상) |
| `get_audit_opinion_history` 의 연속 적자 블록 | ✅ | 헬릭스미스 5년·제이스코 영업 4년/순손실 5년 라이브 매칭 |
| `find_actor_overlap` 임원 겸직 매칭 | ✅ | 신승수군 3개사 겸직 라이브 매칭(신용규·이호영 동행 포함), 골드 `tests/fixtures/sample_outputs/actor_overlap.txt` |
| `TREASURY_TRUST` (v0.8.7) | ✅ | 2026-08-04 ⚠ 재점검 — 나이스정보통신(00264945) 20260602000537(자기주식취득신탁계약체결결정) 라이브 매칭, `fetch_treasury_decisions`→`track_capital_structure` 종단 확인. 골드 `나이스정보통신_capital.txt` |
| `INSIDER_PRE_DISCLOSURE` (v0.8.6) | ⚠ | 2026-08-04 재점검 — 코드 정상(매도 ±30일 창·`_NEGATIVE_DISCLOSURE_KEYS` 7종 전부 signals.py에 실존, server.py 필드 연결 확인). STX·롯데카드 등 최근 부실·제재 공시 기업에서 Δ 산출 가능한 시계열이 없어(스냅샷 1건뿐) 미발화, `audit_issue`/`embezzle` market preset도 최근 90일 0건이라 후보 자체가 희소 — 사례 미발굴(2026-08-04 재점검) |
| `DIVIDEND_DRAIN` (v0.9.0) | ✅ | 두산(00117212) 2022 CFS·2023 CFS·2023 OFS·2024 CFS 라이브 발화(SE-12). 6사 매트릭스(SG·두산에너빌리티·삼성전자·셀트리온·제이스코·헬릭스미스)는 여전히 0건 — 미발화가 결함이었던 게 아니라 두산류(비지배지분 큰 회사) 사례가 이 6사엔 없었을 뿐 |
| `DISTRESS_EVENT` (v0.9.0) | ✅ | 2026-08-04 ⚠ 재점검 — 롯데카드(00219051) 20260731000817(영업정지, business_susp)·STX(00138297) 20260403003189(회생절차개시신청, rehabilitation) 라이브 매칭, 골드 `STX_analyze.txt`/`STX_timeline.txt`. 이 과정에서 `_distress_summary`의 rehabilitation 서브타입 필드명 버그(실존하지 않는 "rs"/"ctrcvs_rs" 사용 — 실제 신청사유 필드는 `rq_rs`) 발견·수정. default(부도)·dissolution(해산)은 이번 라운드 미재확인(6개월 표집에 부도 사례 없음, 해산 후보 1건은 상장리츠 특수케이스로 미발화) |
| `get_major_decision` 12개 decision_type | ✅(12/12) | 2026-08-04 재점검 — `tangible_acq`(SE-14/v1.6.0, 아틀라스링크 20260722000373)에 이어 나머지 11개 중 10개를 corp_code 기반 조회로 실측: `business_acq`(오리엔트정공 20260212001424, DECISION_RELATED_PARTY 발화 확인) · `tangible_div`(대산F&B 20260303003033) · `merger`(다산디엠씨 20250827000490, counterparty·related_party="자회사" 정상) · `stock_acq`(엔솔바이오사이언스 20260305001625) 등. 이 과정에서 `stock_exchange`(주식교환·이전결정)의 상대방·관계 필드가 `_normalize_decision` 폴백 체인에 아예 없어 counterparty/relation_text가 항상 공란이었던 필드명 버그 발견·수정(`extr_tgcmp_cmpnm`/`extr_tgcmp_rl_cmpn` 추가) — **stock_exchange ⚠ 해소(2026-08-04 심야 재점검)**: "최근 365일 사례 0건"은 실측 오류였다 — `resolve_decision_type`이 DART 실제 제목 표기의 한글 가운뎃점 "ㆍ"(U+318D)를 제거하지 않아 "주식교환ㆍ이전결정"이 영원히 리졸브 실패했고, 같은 문자로 재검색하니 최근 360일 시장에서 **77건**(이마트·우리금융지주·코오롱인더 등) 존재. "ㆍ" 제거 추가 후 코오롱인더 20260507000581로 종단 라이브 검증 — counterparty "코오롱글로텍 주식회사(KOLON GLOTECH, INC.)"·특수관계 예·외부평가 예 정상 추출(`extr_tgcmp_cmpnm` 필드 수정도 이때 라이브 확인). 부수 수정: 이 필드는 원문 개행이 섞여 와 `_normalize_decision`이 counterparty 공백을 한 줄로 정규화. `demerger_merger`도 상장사 1년 표집 0건(unlisted 1건만 발견, DS005 미노출)이라 미검증 유지. **부가 발견**: 12종 모두 DART 스펙상 corp_code가 항상 필수인데 `check_disclosure_risk`는 corp_code="" 로 `fetch_major_decision`을 호출해(rcept_no 단독 폴백은 DS005에서 구조적으로 항상 실패) "📑 주요 결정 공시에서 읽히는 거래 구조" 섹션이 사실상 항상 공백 — **해소됨(2026-08-02 후속)**: `resolve_corp_code_from_rcept_no`(dart_client)가 접수일(rcept_no 앞 8자리) 하루치 주요사항보고(pblntf_ty=B) 목록을 최대 3페이지 스캔해 rcept_no→corp_code를 역해석(10분 캐시 `_rcept_corp_cache`, 매칭 즉시 조기 종료·비정상 status 즉시 중단으로 호출 예산 상한 3회)하고, 역해석 실패 시 `fetch_major_decision` 헛호출 없이 섹션만 생략하도록 `check_disclosure_risk`에 배선. 아틀라스링크 20260722000373 라이브 재확인 — 섹션이 실제 발화(로아앤코홀딩스·174억·자산대비 15.47%·DECISION_RELATED_PARTY). 단위 테스트 `tests/test_resolve_corp_from_rcept.py`(역해석 성공/캐시/조기종료/페이지상한/실패 시 섹션 생략 8건). **부가 발견 2**: 결정공시가 [기재정정]류 정정 공시면 DS005 corp_code+날짜 조회가 "최초접수일" 기준이라 정정 rcept_no의 날짜로는 항상 013(no data) — 이 자체는 DART 스펙(요청 인자 설명에 "시작일(최초접수일)" 명시)이지 코드 버그 아님, 정정 아닌 원본 rcept_no를 쓰면 정상 조회됨(다산디엠씨 사례로 확인) |
| `capital_backflow`(v1.6.0)/`FUND_OUTFLOW` | ✅ | 아틀라스링크(01309795, 297570) 라이브 매칭 — 최대주주변경(20260709) 후 유형자산양수(20260722)·채무보증(20260729)·금전대여(20260120, 20251015) 연쇄로 패턴 발화, `analyze_company_risk`·`build_event_timeline` 양쪽 골드 확인. v1.6.1 게이트 도입 후에도 계속 발화(유형자산양수 상대 로아앤코홀딩스가 계열회사로 확인돼 affiliated 조건 충족) — 게이트가 발화를 막지 않았음을 확인. 한농화성(011500)도 별도로 게이트 통과 라이브 확인(금전대여 20260728800659 → 바스프한농화성솔루션스, 계열회사) |
| `capital_backflow` 게이트(v1.6.1) — 원문 상대방 관계 실질 판정 | ✅ | `parse_outflow_detail`이 아틀라스링크 금전대여결정(20260120900216/20251015900139)에서 "성명(법인명)"·"(회사와의 관계)" 괄호형이라는 세 번째 실측 서식 변형을 발견 — 최초 구현은 이 변형에서 상대방을 못 찾아 "unknown"으로 놓쳤다가 정규식 보강 후 "주식회사 한국파일/종속회사"로 정확히 추출. subsidiary만 확인되면(계열·특수관계 없음) 패턴이 아니라 사실 블록만 표기하는 경로는 이 실사례로 간접 검증(종속회사 건 3개 중 유형자산양수 1건만 계열회사라 affiliated 통과) |
| `fund_diversion_chain`(금감원 2019-12 무자본 M&A 합동점검 반영) | ✅ | **2026-08-22 정정 — 아래 「후보 0곳」 기록은 스캔 절단의 산물이었다.** 그 판정의 근거였던 `market_items.json`은 3,384건뿐이었는데, 같은 365일 창을 새로 전수 수집하니 **201,361건**이었다(전체의 1.7%만 훑고 '시장에 없다'고 결론냈다 — v1.10.2가 고친 청크 절단 문제와 같은 뿌리). 새 코퍼스로 재집계하니 한정층 통과 기준 CB_BW 1,884건/577개사 · ACQ_REVIEW 132건/109개사이고 **교집합이 50개사**다(0이 아니다). 라이브 종단 확인: **KR모터스(000040)** `analyze_company_risk` 1년 — 20251001 「주요사항보고서(타법인주식및출자증권양수결정)」 + 20260312·20260324 「주요사항보고서(전환사채권발행결정)」로 **2/2 발화**. 덧붙여 `ACQ_REVIEW`의 재현율 갭(86%)을 같은 감사에서 수정했으므로(아래 행) 교집합은 142개사로 늘어난다 — 이 패턴은 요구 신호가 2개뿐이라 특이도가 낮다는 점(겹침 2개 = 곧 전부 일치)을 함께 읽어야 한다. 내용 확인 게이트(`capital_backflow` 방식) 도입은 별도 판단. 근거: `docs/superpowers/specs/2026-08-22-signal-keyword-audit.md` |
| ~~`fund_diversion_chain` 후보 0곳(2026-08-03 기록)~~ | ❌ 폐기 | 2026-08-04 재점검 — `find_pattern_match`는 signal_sequence의 단순 부분집합 판정(순서·타임라인 미강제)이라 11개 패턴 중 요구 신호 개수가 2개(1.1+5.8)로 가장 낮아 원리적으로 가장 발화하기 쉬운 조합이다. 다만 90일 표집 후보(오리엔트정공·엔솔바이오사이언스 등 stock_acq/business_acq 발화 기업)에 CB_BW가 동반 관측되지 않아 이번 라운드도 라이브 매칭 사례 미발굴. 2026-08-03 재점검(365일 시장 전체 스캔, `market_items.json` 3,384건/1,058개 법인 — Task 1 스캔 재사용, 90일이 아닌 1년 전체 창으로 확장) — CB_BW 발행결정(제목 "전환사채권발행결정"·"신주인수권부사채권발행결정")과 ACQ_REVIEW(제목 "타법인주식및출자증권양수결정"·"영업양수결정")를 corp_code 기준 교차한 결과 **후보 0곳**. **산정 방법(기재정정 제외, 브리프 기준)**: CB_BW 6건/5개 법인(HLB·본느·유티아이·피아이이·효성화학), ACQ_REVIEW 1건/1개 법인(두산), 교집합 0 — `tmp/fund_misuse_probe/find_chain_candidates.py` 재실행 + `tmp/fund_misuse_probe/chain_candidates.txt`에 법인명 전체 목록 기록·재현 확인(스크립트 전문·실행 결과는 `docs/superpowers/plans/2026-08-02-fund-misuse-detection-verification.md` 부록 C에도 보존, 참고: 기재정정 포함 시 CB_BW 18건/15개 법인·ACQ_REVIEW 5건/5개 법인이나 이는 브리프 산정 기준이 아님). 90일 표집보다 넓은 1년 창에서도 두 신호가 겹치는 법인이 시장에 없다는 것을 재확인 — `find_pattern_match` 자체의 결함이 아니라 실세계에서 CB/BW 조달사와 타법인출자·영업양수 실행사가 겹치는 사례 자체가 희소함을 시사(zombie_ma·delisting_evasion처럼 요구 신호 수가 많은 패턴보다 이론상 쉬운 조합인데도 후보가 안 잡히는 것은 표본 부재이지 게이트 로직 문제가 아님). 후보 0건이라 `analyze_company_risk` 종단 실행은 생략 |
| `STAKE_PLEDGE`(v1.6.1, 최대주주 주식담보제공계약) | ✅ | 시장 전체 스캔 라이브 매칭(2026-07-31) — 아진산업(주식담보제공계약해제ㆍ취소등)·인카금융서비스(주식담보제공계약체결) 2건, 골드 `market_shareholder_change.txt`/`market_all_risk.txt`. `FUND_OUTFLOW`에서 분리되기 전에는 이 2건이 [최대주주변경, 자금유출성거래]로 오분류됐던 것도 같은 골드 diff로 확인 |
| `LOAN_ADVANCE_SURGE`(대여금·선급금 급증, 금감원 2019-12 무자본 M&A 합동점검 반영) | ⚠ | "대여금·선급금 (계정 노출 시)" 사실 표기 블록 자체는 두산에너빌리티(BS 3계정 노출, 2024 전년 대비 감소)·헬릭스미스·두산(CF 전용 노출) 라이브 확인. 단 플래그 임계(2배↑·10억↑)를 충족하는 실사례는 6사+아틀라스링크 매트릭스에서 아직 미발굴 — 셀트리온·삼성전자·제이스코홀딩스·아틀라스링크는 계정 자체가 노출되지 않음(정상). 2026-08-04 재점검: `extract_loan_advance`/판정식(`la_cur>=10억 and la_cur>=la_pri*2`) 필드명·0-분모 처리 모두 정상, 라이브 헌팅은 예산상 재수행하지 않음(코드 감사만) |
| `CROSS_SIGNAL_PATTERNS` 부분 겹침 표기(2026-08-17) | ✅ | 전부 일치는 회사당 0.2개(10개사 실측, 그마저 전부 2신호 패턴)라 5~6신호 패턴은 발화한 적이 없다. `find_pattern_overlaps`로 "6개 중 3개 관찰 + 안 보임 + 확인해볼 것"을 표기하도록 전환 — 부분 일치는 회사당 1.3개이고 **대조군(셀트리온·삼성전자·두산에너빌리티)은 0**이라 변별력 확인. `capital_backflow`의 v1.6.1 내용 확인 게이트는 그대로 유지(실패 시 겹침 목록에서 제외) |
| 패턴의 **순서** 축(`signal_sequence` 순서) | ❌ 도입 안 함 | 12개사×3년 실측 — 순서 일치율 **64%**(무작위 50%). 제약으로 쓰면 진짜 사례를 떨어뜨린다. 원인은 이 도구가 사건 발생 순서가 아니라 **공시 접수일**을 보기 때문. 근거: `docs/superpowers/specs/2026-08-21-pattern-sequence-measurement.md` |
| 패턴의 **간격** 축(`timeline_months`) | ✅ 도입(재보정 후) | 선행 측정(12개사×3년)은 "적중 49%라 쓸 수 없다"로 결론냈고, 후속 재측정(**250개사×5년·관측 363건** — 선행 측정이 스스로 지목한 "수백 개 회사가 필요" 한계를 메운 표본)이 그 경고를 재확인했다: 옛 설정값으로 게이트를 걸면 관측의 **31.4%**가 영향(20.9% 탈락 + 10.5% 축소). 결론은 "쓰지 말자"가 아니라 **"값이 틀렸다"** — 패턴별 필요 개월 p90으로 재보정(zombie_ma 12→30, fake_new_biz 6→30, audit_insider_dump 6→33, delisting_evasion 9→27, debt_spiral·fund_diversion_chain 12→21, related_party_hollowing 15→18)하니 영향이 **8.0%**로 하락. `capital_backflow`(12)는 "최대주주변경 후 12개월 내"가 정의 자체라 유지(v1.6.1 내용 게이트 별도 보유), `founder_fade`·`reverse_split_spiral`(18)은 이미 p90보다 넉넉해 유지. ⚠ 재보정값은 **in-sample calibration이지 validation이 아니다**(p90은 정의상 그 표본의 90%를 담는다) — 좁히려면 out-of-sample 재측정 필요. 근거: `docs/superpowers/specs/2026-08-21-pattern-window-recalibration.md` |
| `DELISTING_RISK`(상장폐지 절차, v1.12.2) | ✅ | 2026-08-22 `search_market_disclosures("going_concern", 14)` 라이브 — 알에프세미·파라택시스코리아(정리매매 개시)·삼부토건·범양건영(개선기간 종료)·STX(이의신청서 제출)·듀오백·캐리(실질심사 대상결정 기한)·이오플로우·다원시스·코이즈 등 발화. 키워드 4종은 90일 시장 전체 실측(고유 공시 48,646건)에서 합집합 **177건/68개사**이고 전부 기존 신호 미포착이었다(단독 기여: 상장폐지 50·실질심사 57·개선기간 21·정리매매 11). 오탐은 「…절차 미진행」류 약 2~3건(1.7%)으로 측정 — 전부 퇴출 절차 맥락 안의 공시다. 근거: `docs/superpowers/specs/2026-08-22-delisting-risk-signal.md` |
| 한정층 R2 국면 상승 예외(`ESCALATION_SUBTITLES`, v1.12.2) | ✅ | 「주권매매거래정지해제(상장폐지에 따른 정리매매 개시)」는 어미가 '해제'라 R2가 "체결이 아니라 해제입니다"로 강등했다 — 매매정지가 풀린 게 아니라 **상장폐지가 확정돼 정리매매가 시작**된다는 뜻이라 의미가 뒤집힌다. 90일 실측에서 R2가 강등한 23건을 전수 확인해 21건(정리매매 개시 20·재개 1)은 오강등, 2건(「상장폐지사유 미해당」·「실질심사 대상 제외 결정」)은 정당한 강등임을 확인하고 **괄호 부제**로 갈랐다. 라이브: 알에프세미 20260821900899·파라택시스코리아 20260819900696이 observed로 표면화 |
| `WATCH_ISSUE`(관리종목 지정요건, v1.12.3) | ✅ | 90일 시장 전체 실측(고유 공시 48,646건) — "관리종목" 115건/99개사(시가총액 200억 미달 49·주가 1,000원 미달 43 등)와 "매출액미달" 5건/5개사(「반기 또는 분기 매출액 미달 사실발생」)가 **전부 무신호**였던 공백을 메운다. 오탐 0건. ⚠ `"미달"` 단독은 쓸 수 없다 — 집합투자증권 펀드명의 "미달러"(미(美) 달러)가 걸린다(실측 6건). taxonomy는 `DELISTING_RISK`와 같은 8.5를 공유(패턴 미사용·무점수) |
| 방향 안내(`DIRECTION_NOTES`) 커버율 (v1.12.3) | ✅ | `CB_BW` observed 473건 중 **196건(41%)**이 발행이 아니라 만기전취득·소각인데 "CB/BW**발행**입니다"로 표시됐다(`EB`는 18건 중 14건). 기존 마커 2종은 되사기·소각 208건 중 122건(59%)만 잡았다 — 대표 누락은 「주요사항보고서(자기전환사채만기전취득결정)」 61건('사채취득'이 아니라 '만기전취득' 표기). 마커 확장 + `EB`·`RCPS` 항목 신설로 **59%→100%**(207/208). ⚠ `RCPS`에 `"상환"` 금지(상품명이 상환전환우선주) |
| `DEMERGER` 키워드 정밀화 (v1.12.3) | ✅ | `"분할결정"`이 「**주식**분할결정」(액면분할)을 삼켜 `DEMERGER` observed 11건 중 3건(27%)이 회사분할이 아니었다. `"회사분할결정"`으로 좁혔고 빠지는 것은 정확히 그 3건뿐 |
| 한정층 R2b(포장 제목 부제) (v1.12.3) | ✅ | 「기타주요경영사항(제3자배정유상증자결정**철회**)」의 tail은 본체에서 뽑혀 `PHASE_TAILS`에 안 걸려, 증자를 철회한 건이 관찰 신호로 표시됐다. 단독 제목이면 강등되는데 포장지가 씌워지면 안 되는 비일관. `WRAPPER_BODIES`일 때만 부제 어미를 본다. 「소송등의제기ㆍ신청(…)(주주총회결의취소)」는 body가 행위라 제외(실측 확인) |
| `ACQ_REVIEW` 재현율 수정 (v1.12.3) | ✅ | DART는 같은 행위에 두 표기를 쓴다 — DS005 법정 「주요사항보고서(타법인주식및출자증권**양수**결정)」과 자율공시 「타법인주식및출자증권**취득**결정」(4배 흔함). '양수'만 잡아 90일 실측 220건 중 **189건(86%)이 무신호**였다. 이 신호의 목적이 "상대방을 원문에서 확인하라"는 사실 안내(5.8, OBSERVATION·무점수)인데 안내가 필요한 건의 대부분에 안 붙고 있었다. 1년 기준 132건/109개사 → 600건/438개사. 「처분·양도」는 자금이 들어오는 반대 방향이라 미포함 |
| `INSOLVENCY` 재현율 수정 (v1.12.3) | ✅ | 「사채원리금미지급발생」 16건/13개사 + 「대출원리금연체사실발생」 18건/7개사(1년)가 무신호였다 — 사채 원리금 채무불이행인데 제목에 '부도'가 없어 샜다. 실측에서 두 표현 모두 다른 맥락 표기가 0건이라 오탐 여지 없음(국보·다원시스·올리패스·한국유니온제약 등). 반면 「회계처리기준위반…증선위 검찰고발」(12건)·「파생상품거래손실발생」(72건)은 갭이 확인됐지만 **맞는 taxonomy가 없어 넣지 않았다** — 의미가 어긋나는 자리에 밀어 넣는 것이 INQUIRY 실사고의 원인이었다. `tests/test_default_recall.py::TestNotForceMapped`가 '아직 안 잡힌다'를 고정해, 나중에 매핑하면 근거를 남기도록 강제한다 |
| 제목으로 발화 불가한 신호 17종 → 분류·1차 정리 (v1.13.3) | ✅(9종) / ⚠(8종) | 1년 코퍼스(고유 공시 201,361건)에서 모든 키워드가 0건인 신호 17종을 **네 부류로 갈랐다**(처방이 다르다): **A 중복**(`CB_REPAY`·`BUYBACK_NEG`·`TREASURY_EB`·`CB_BUYBACK` — 같은 공시를 `CB_BW`·`TREASURY`·`EB`가 이미 잡는다) + **구조화 전용**(`CB_ROLLOVER` ← `detect_debt_rollover`) · **B 키워드 오류**(`CAPITAL_RED`←「주식소각결정」472 · `ASSET_SPIRAL`←「비유동자산처분결정」83 · `RIGHTS_UNDER`←「실권주일반공모」9 · `CIRCULAR`←개념 재정의 필요) · **C 내용 확인 필요**(`RELATED_PARTY` 5,521건 · `REVENUE_IRREG` 1,970건 · `CONTINGENT` 521건 — 제목만으로 정상/이상 구분 불가) · **D 개념 부재**(`MEETING_VIOL`·`ACTIVIST`·`DISTRESS_MA`·`GAMJA_MERGE` — 무신호 건수가 전부 「주주총회소집공고」·「의결권대리행사권유참고서류」 같은 **정상 절차 공시**다. 조합·시계열로만 성립하므로 신호가 아니라 패턴·`detect_*`의 영역). **1차로 A·D 9종을 정리**했다 — 키워드 제거(동작 불변, 1년 0건) + `NON_TITLE_SIGNALS`로 발화 경로 명시(structured/covered/absent) + preset 정리(`cb_issue` 7→3종, `reverse_split` 3→2종) + `find_risk_precedents`가 조회 시 "제목 스캔에서는 나타나지 않습니다"를 사실로 안내. B·C 8종은 2차 대상. 근거: `docs/superpowers/specs/2026-08-22-dead-signal-triage.md` |
| [정정] 5~6신호 패턴이 발화하지 않는 이유 (v1.13.3) | ✅ | 기존 기록은 "엄격함 자체는 설계상 의도(오탐 방지)"로 읽었으나, 실제로는 **요구 taxonomy를 담당하는 유일한 신호가 관찰 불가**여서다. 정확히 **2개** 패턴이 해당한다 — `zombie_ma`(1.2←`CB_REPAY`뿐) · `founder_fade`(4.1←`MEETING_VIOL`뿐). 1년 실측 겹침 195곳·284곳인데 **전부일치 0곳**. 반면 `debt_spiral`(1.5)·`fake_new_biz`(5.4)는 `CB_BW`·`MGMT`가 같은 taxonomy를 켜므로 **막혀 있지 않다**(작업 중 "넷"이라 적었다가 테스트가 잡아 정정). `tests/test_non_title_signals.py::TestPatternImpact`가 이 구분을 기계적으로 지킨다 |
| `audit_insider_dump`(감사의견 내부자 덤프) | ✅ | **2026-08-22 ⚠ 해소** — 1년 시장 전수(고유 공시 201,361건) 재집계에서 전부일치 1곳을 찾아 라이브 종단 확인했다: **진원생명과학(011000)** 1년 조회 — 4.4 「반기검토의견 부적정, 의견거절 또는 완전자본잠식 사실발생」(20260814) + 7.1 「조회공시요구(풍문또는보도)」(20260617·0618·0715) + 3.1 「최대주주변경」(20260317)로 **3/3 발화**(관찰 구간 20260317~20260814). 같은 회사에서 `fund_diversion_chain` 2/2도 함께 발화 |
| 패턴별 발화 규모 (1년 전수 실측, v1.12.3) | ✅ | 신호가 관찰된 회사 2,735곳 기준 겹침/전부일치: 창업주 퇴장 284/0 · 부채 악순환 231/0 · 무자본 M&A 195/0 · **조달-유용 체인 142/142** · 상폐 회피 106/0 · **자금 역류 62/62** · 허위 신사업 43/0 · 감사의견 내부자 덤프 24/1 · 특수관계 자산 공동화 23/0 · 감자 나선 0/0 · 자본 이벤트 과다 반복 0/0(2.7이 합성 신호라 코퍼스 기반 집계에는 안 잡히는 것이 정상). 요구 신호 2개짜리 패턴(조달-유용 체인·자금 역류)만 전부일치가 나온다 — 5~6신호 패턴이 구조적으로 발화하지 않는다는 기존 기록과 일치 |
| 관찰 윈도우 표기 (v1.12.3 수정) | ✅ | `_best_window`가 창의 **이론적 경계**(start ~ start+timeline_months)를 돌려줘, 관찰이 2026.03~08인 건에 "창 2026.03.17~**2028.12.17**"처럼 아직 오지 않은 날짜가 찍혔다(진원생명과학 실측). 게이트 판정은 경계로 하되 표기는 **실제 관찰된 날짜 범위**로 좁혔다. 뷰어 `bestWindow`도 동일 이식 |
| `fund_diversion_chain` 내용 확인 게이트 (v1.13.0) | ✅ | 게이트 조건을 실측으로 골랐다(25개사·32건 원문 전수) — ① **비상장 대상 여부**: 금감원 근거("조달자금 유용의 최대 경로가 비상장주식 취득 55%")에 가장 충실하지만 대상사 이름을 corpCode에서 못 찾는 건이 **23/32(72%)**라 판정 불가, 기각 ② **자기자본 대비 과대**: 중앙 13.8%·최대 52.1%로 100% 초과 0건이라 임계를 어디 둬도 무의미, 기각 ③ **관계 표기**: 계열회사 7·최대주주/주요주주/관계회사 3·종속회사 2·무관계 19·미확인 1 — 확인율과 판별력이 있어 채택. 회사 단위 통과율 25곳 중 8곳(32%)으로 142개사 → 약 45개사로 좁혀진다. 라이브: **진원생명과학** 발화(계열 확인) / **코아스**(해성옵틱스·이트론·이화전기 전부 무관계)·**KR모터스**(다이나맥 무관계) 차단 |
| 게이트 차단 시 사실 블록 노출 (v1.13.0 수정) | ✅ | 옛 렌더는 `elif`라 겹치는 패턴이 하나라도 있으면 확인된 사실 블록을 통째로 숨겼다 — 코아스에서 「이화전기공업 · 자기자본 대비 **447.3%**」가 가려지는 것을 실측하고 `if`로 바꿨다. 여기 담기는 것은 패턴 주장이 아니라 원문에서 확인한 사실이라 감출 이유가 없다. 두 게이트의 블록은 각자 헤더를 달아 섞이지 않는다(「자금유출 상대방 확인」/「타법인 취득 대상 확인」) |
| `parse_acquisition_detail` 서식 버그 수정 (v1.13.1) | ✅ | 70건 실측에서 **issuer 60%·relation 19%가 실패**하고 있었다. 서식이 두 가지인데(「발행회사 **회사명(국적)** <이름> 대표이사」 37건 vs 「회사명 <이름> **국적** <국적> 대표자」 32건) 하나만 봐서, 전자에서 issuer가 `(` 한 글자로 잘렸다. 관계도 「회사와**의**관계」 변형(3건)을 놓쳤다 — 이건 **게이트의 판정 필드**라 19%가 보수적 차단으로 새고 있었다. 수정 후 둘 다 실패 7%(남은 7%는 발행회사 블록이 없는 「영업양수」 서식, 정상) |
| 취득 대상 비상장 판정률 (v1.13.1) | ✅ | **28% → 93%**(70건: listed 6·unlisted 59·unknown 5). corpCode.xml은 상장·비상장을 모두 담은 공시대상 법인 명부(11만여 건)라 **거기서 못 찾는 것은 판정 불가가 아니라 국내 상장사가 아니라는 근거**다 — 옛 코드는 이를 unknown으로 버렸다. `classify_target_listing`은 ① 이름 없으면 unknown ② 국적이 해외면 unlisted ③ 명부 원문·폴딩·옛 상호 조회 ④ 미발견은 unlisted 순으로 판정한다. ⚠ **게이트 통과 조건이 아니라 사실 표기 전용** — 정상적인 비상장 자회사 편입도 대부분 비상장이라 조건으로 쓰면 거의 전부 통과한다 |
| 괄호 값이 늘 국적은 아니다 (v1.13.2 수정) | ✅ | 취득 원문의 이름 뒤 괄호가 국적이 아닌 경우가 70건 중 **6건**이었다(「JIANGSU … CO.,LTD.」 영문명·「Dunamu Inc.」·「Laftel」·「가칭」·「예정」). 국적으로 취급하면 `classify_target_listing`이 "국내가 아님 → 비상장" 지름길을 잘못 타 **영문 병기가 붙은 상장사가 비상장으로 뒤집힌다**. 이 표본에선 6건 모두 실제로 비상장이라 실피해가 없었지만 논리적 위험이라 `_looks_like_nation`(국가·지역 토큰 목록)으로 가렸다 |
| `ASSET_TRANSFER` 부활 (v1.13.4, 2차 정리) | ✅ | 옛 키워드 5종("자산매각"·"사옥매각"·"자회사매각"·"사업양도"·"저가매각")은 1년 0건 — 개념어였고 DART 제목 표기가 아니었다. 실제 표기로 교체: 특수관계인에대한자산양도 50 · 비유동자산처분결정 48 · 유형자산처분결정 47 · 유형자산양도결정 38 · 영업양도결정 20(자산 처분 계열 **883건이 100% 무신호**였다). ⚠ `"자산양도"` 단독 금지 — 「자산양도등의등록신청서」663건(자산유동화법상 유동화자산 양도 등록)이 걸린다. score 4→1(참고 강도) + `AMBIGUOUS_SIGNAL_KEYS` 편입으로 헤드라인 승격 차단 |
| 자산 처분 원문 확인 계층 (v1.13.4) | ✅ | taxonomy 5.3("특수관계인에게 **공정가 미만** 이전")은 제목만으로 판정 불가 — 정상적 자산 교체가 대다수. `parse_asset_disposal_detail`이 5개 서식을 읽는다(유형자산 처분결정 자율/비유동자산 처분결정 공정위/유형자산 양도 결정 법정/특수관계인에대한자산양도/영업양도결정). 18건 표본 **상대방 100%·금액 89%·관계 56%**(「유형자산 처분결정」서식엔 관계 필드가 없다). 「특수관계인에대한자산양도」는 **단위가 백만원**이라 별도 환산. 기존 `_confirm_outflow_counterparties`에 합류해 `classify_outflow_relation`·렌더링 재사용. 라이브: **효성투자개발** 「비유동자산처분결정」 → 계열회사(에이치에스효성첨단소재) **2,643억원 · 자산총액 대비 455.63%** |
| [수정] 상대방 확인 블록이 안 나오던 경로 (v1.13.4) | ✅ | 확인 결과는 `capital_backflow` 게이트가 막혔을 때만 렌더됐다. 3.1(경영권 변경)이 없어 패턴 자체가 성립하지 않는 회사는 게이트가 호출되지 않아 "누구에게 팔았나"가 통째로 사라졌다(흥아해운·효성투자개발 실측). 확인된 상대방은 패턴 주장이 아니라 사실이라 겹침 유무와 무관하게 낸다. 블록 헤더도 「자금유출·자산이전 상대방 확인」으로 정정 |
| [정정] 1차 B 분류가 성급했다 (v1.13.4) | ✅ | 1차에서 "B 4종은 키워드 교체로 살아난다"고 적었으나 원문을 떠 보니 **셋은 taxonomy 조건과 뜻이 정반대**였다 — `CAPITAL_RED`←「주식소각결정」479건은 원문이 *"자본금의 감소는 없습니다 · 목적: 주주가치 제고"*(상법 343①)라 감자가 아니라 **주주환원**, `RIGHTS_UNDER`←「주주배정후 실권주 일반공모」는 실권주가 **일반투자자**에게 넘어간 건(2.5는 "특수관계인이 인수"), `ASSET_SPIRAL`(연쇄·헐값)·`CIRCULAR`(연쇄 이전)은 단건 제목으로 판정 불가. 넷 다 `NON_TITLE_SIGNALS`(absent) 편입 + preset 제거(`3pca`·`reverse_split`·`asset_transfer`). **교훈: taxonomy가 요구하는 조건(비율·주체·연쇄·가격)을 원문과 대조해야 매핑 가능 여부를 안다** |
| `RELATED_PARTY` 부활 — 들어오는 방향만 (v1.13.5, 3차) | ✅ | 특수관계인 계열 6,575건 중 무신호 5,462건(83%). **나가는 방향은 이미 커버**(자금대여 602·담보제공 185→`FUND_OUTFLOW`, 자산양도 50→`ASSET_TRANSFER`, 유상증자 참여 237→`3PCA`)라 **들어오는 방향**만 잡아 대칭을 맞췄다 — 자금차입 1,320/391개사 · 받은담보 212 · 출자 197 = **1,732건**(회사당 3~4건). ⚠ 「동일인등출자계열회사와의 상품ㆍ용역거래」 **2,330건/579개사**는 대기업집단 일상 영업이라 제외. 원문 `parse_related_party_detail`이 상대방·관계·금액(**단위 백만원**)과 차입 서식의 **이자율(%)**을 읽는다(10건 표본 상대방 100%, 실측 이자율 4.6~8.95%). score 1 + `AMBIGUOUS` 편입 |
| `EARNINGS_SHOCK` 신설 (v1.13.5, 3차) | ✅ | 「매출액 또는 손익구조 30%(대규모법인 15%) 이상 변동/변경」 **1,958건/년**(회사당 0.7건)이 무신호였다. **6.1이 아니라 8.5에 매핑** — 6.1은 "수익 **인식 정책** 변경"이고 이 공시는 결산 결과 통보다(6.1의 위험신호 '매출채권/매출 급등'은 이미 `AR_SURGE`가 재무제표로 본다). 8.5는 OBSERVATION·무점수·패턴 미사용이라 새 taxonomy 없이 붙는다. 원문 `parse_earnings_shock_detail`이 계정별 **증감비율**·**흑자적자전환여부**를 읽는다(10건 표본 100%, 적자전환 1·흑자전환 2). score 0 + `AMBIGUOUS` 편입 |
| [정정] C 3종 중 매핑이 맞는 건 하나뿐 (v1.13.5) | ✅ | 2차와 같은 함정을 다시 확인했다 — `REVENUE_IRREG`(6.1 "수익 인식 **정책** 변경")·`CONTINGENT`(6.2 "우발채무 **누락**")는 후보 제목과 뜻이 어긋난다. 「소송등의판결」은 **공시된** 건이라 '누락'을 판정할 수 없고, 6.2의 "특수관계인 보증"은 이미 `FUND_OUTFLOW`가 869건 잡는다. 둘은 `NON_TITLE_SIGNALS`에 유지 |
| `parse_control_change_detail`/"🔁 최대주주 변경 상세" 블록(v1.7.0) | ✅ | 4건 라이브 매칭 — 아틀라스링크 20260709900615("외 1인" 공백형)·졸스 20260728900445("외N명" 붙임형)·제이케이시냅스 20260728900521("외 N" 접미 없음, (주) 접미)·선광 20260727900769(개인명, "외 22" 단위 생략형). 골드 `아틀라스링크_analyze.txt`/`아틀라스링크_timeline.txt` 갱신. 차입금>0(주식담보대출) 경로는 6사+아틀라스링크 매트릭스에서 미발굴 — 자기자금만 있는 사례만 라이브 확인 |
| `_related_party_detail_block`/"🤝 특수관계인 자금거래 확인"(v1.14.0) | ✅ | 2026-08-22 라이브 3건 — 포승그린파워 20260812000839(자금차입 · (주)엘엑스인터내셔널 · 계열회사 · 1200억원 · **이자율 4.6%** · 자기자본 대비 187.72%)·20260812000842(받은담보 449억원)·푸른파트너스자산운용 20260812000725(출자 · 푸른 유아이엘 신기술조합 제1호 · 출자조합 · 12억원). 이자율·자기자본대비는 제목에 없던 값 |
| `_earnings_shock_block`/"📉 손익구조 급변 내역"(v1.14.0) | ✅ | 2026-08-22 라이브 — 포시에스 20260820900300(매출액 +8.0% · 영업이익 +32.1% · 당기순이익 +57.3%). **적자전환 경로는 파서 단위 테스트만** — 2026-08-10~20 시장 표집에서 손익구조 공시 자체가 1건뿐이었고 그 1건이 흑자 증가라 라이브 전환 사례 미발굴 |
| `match_affiliate_row`/`summarize_affiliate_stake` — 종속회사 유출 사실 병기(v1.9.0) | ✅ | 아틀라스링크 실측 3건(20260729/20260120/20251015 — 상대방 전부 "주식회사 한국파일") 전부 타법인 출자현황과 매칭돼 "최초취득 2023-09 · 지분 46.3→62.4% 확대 · 피출자사 최근 순이익 -49억원" 병기 확인. 골드 `아틀라스링크_analyze.txt`/`아틀라스링크_timeline.txt` 갱신 |
| `track_fund_usage`의 `FUND_UNREPORTED`(실제 집행 미보고) | ✅ | 2026-08-03 — 오르비텍(00297989, 046120) `track_fund_usage(lookback_years=3)` MCP 종단 실행 라이브 매칭: 2025·2026 사모 제8~11회차(각 연도 4건, 총 8건) 전부 "받은 돈이 어디에 쓰였는지 보고되지 않고 있습니다" 발화 확인, 점수·등급 문구 없음(hygiene 9/9 PASS). 골드 `오르비텍_fund_usage.txt` 신규(`scripts/regen_goldens.py` COMPANIES에 오르비텍 추가). **오탐 모드 병기(코퍼스 실측, 15개 조달건·48레코드 표본)**: FUND_UNREPORTED의 주된 오탐 원인은 recency(신규 조달 유예 부족)가 아니라 **"다년 보고 스냅샷 미정산"**이다 — 48건 중 31건(64.6%, 8개 조달건)은 같은 조달건의 더 최신 연도 보고서에서 이미 `real_dtls_amount>0`·`real_dtls_cn` 기재로 갱신돼 도구가 더 이상 플래그하지 않는 옛 스냅샷 잔재였다(예: 48건 중 최다 기여였던 유티아이 25건이 4개 조달건 전부 100% 완전소진으로 해소). 도구의 실제 판정 로직(`_detect_fund_anomaly`, 최신연도 라인아이템 기준)으로도 여전히 발화하는 실질 미해소는 17건(7개 조달건, 4개 회사 — 링크드·HLB·오르비텍·피아이이)뿐이며, 오르비텍 4개 조달건(사모 제8~11회차)이 2026년 보고서에서도 real=0을 유지하는 가장 뚜렷한 실측 사례다. 개선 후보(코드 미변경, 기록만): 같은 조달건의 최신 연도 보고서 기준 재정산 로직 부재가 오탐의 구조적 원인 — 상세는 `docs/superpowers/plans/2026-08-02-fund-misuse-detection-verification.md` 부록 B |
| `track_fund_usage`의 `FUND_DIVERSION`(용도 변경) | ⚠ | 2026-08-03 재점검 — 15개 회사·문장형 차이사유(`dffrnc_resn`) 429건 전수 표본에서 현재 14종 키워드 발화 0건(코퍼스 실측). 코드 버그가 아니라 **리콜 갭이 실측으로 확정**됐다 — 키워드가 "목적변경/사업취소/운영자금 전용" 같은 정형 법정 문구 재진술만 잡고, "계획-실집행 카테고리 자체의 이탈"은 구조적으로 못 잡는다. `plan_useprps`↔`real_dtls_cn` 카테고리가 실제로 disjoint한 의미상 목적 외 사용 진짜 사례는 6건 존재(회사×카테고리 전환 단위): 본느(운전자금→타사지분취득, 문구 내재형)·링크드 3종(운영자금→타법인증권취득/채무상환/시설자금)·형지엘리트(신규사업투자→CB상환)·비에스제이홀딩스(채무상환→자산취득) — 전부 현재 키워드 14종에 미포착 확인. 발화 0건이라 재현 가능한 라이브 골드를 만들 수 없어 골드 미추가 — 키워드 보강 후보로 남기며, 표본·사례 원문은 `docs/superpowers/plans/2026-08-02-fund-misuse-detection-verification.md` 부록 A 참고 |

신규 PR이 ⚠ 항목의 라이브 매칭 사례 발굴 시: (1) 사례 회사를 `scripts/regen_goldens.py`의 `COMPANIES`에 추가하거나 (2) `tests/fixtures/sample_outputs/`에 직접 골드 추가. hygiene 검증 9/9 PASS 후 ⚠ 제거.

---

## 제목 수준 vs 내용 확인 감사표

대부분의 신호는 공시 **제목** 키워드 매칭만으로 충분하다(`match_signals`). 하지만 일부
신호는 제목만으로 발화하면 정상적인 일상 거래(계열사 자금 지원, 정상 M&A 등)까지
전부 걸려 신호 대 잡음비가 무너진다. 이 표는 어떤 신호에 원문·구조화 데이터 확인
계층이 있고 어떤 신호는 제목만으로 충분한지 정직하게 정리한다 — v1.6.1에서
`FUND_OUTFLOW`/`capital_backflow`에 확인 계층을 추가하며 이 구분이 명시적으로 필요해졌다.

| 신호/패턴 | 판정 근거 | 확인 계층 | 근거 |
|---|---|---|---|
| `FUND_OUTFLOW` (개별 신호 표기) | 제목만 | 없음 | 대기업의 일상적 계열 지원과 구분 불가 — 참고 강도(base_score 2)로 사실 표기만 하고 판정하지 않는다 |
| `capital_backflow` (복합 패턴 발화) | **원문/DS005 확인** | `parse_outflow_detail`(금전대여·채무보증·담보제공, 원문 정규식) + `fetch_major_decision`(유형자산양수, DS005 구조화) → `classify_outflow_relation` → `_capital_backflow_gate` | 제목만으로 발화하면 아틀라스링크류(실제 계열 유출)와 일상적 종속회사 자금 지원(예: 담보 상대가 종속회사뿐인 경우)을 구분할 수 없다. affiliated(비연결 계열·특수관계) 확인 1건 이상일 때만 패턴을 표시. v1.9.0: subsidiary로 확인된 상대는 발화 조건에 관여하지 않지만, "상대방 확인" 사실 블록에 타법인 출자현황(`match_affiliate_row`/`summarize_affiliate_stake`) 대조 사실을 병기해 그 종속회사의 지분·자금 실체를 읽을 수 있게 한다(판정 아님) |
| `ACQ_REVIEW` | 제목만 | 없음(단, `get_major_decision` 안내는 별도로 표시) | 정상 M&A가 대다수라 사실 안내 수준. 상대방 확인은 사용자가 `get_major_decision` 호출로 직접 수행하도록 안내만 한다 — capital_backflow처럼 자동 게이트는 아님 |
| `fund_diversion_chain` (복합 패턴 발화) | **원문 확인** | `fetch_acquisition_detail`(`parse_acquisition_detail`) → `classify_outflow_relation` → `_fund_diversion_gate` | 요구 신호가 1.1+5.8 둘뿐이라 겹침 2개면 곧 전부 일치다 — `ACQ_REVIEW` 재현율 수정 후 1년 기준 **142개사**에서 발화해 제목만으로는 정상 사업확장 M&A와 구분되지 않는다. 취득 대상이 **계열·특수관계이면서 비상장으로 확인될 때만** 패턴을 표시하고(v1.13.2 강화 — 금감원 근거가 "유용 최대 경로는 비상장주식 취득 55%"라 두 축이 함께 서야 한다), 그 외에는 확인된 사실(대상 실명·상장 여부·관계·금액·자기자본 대비)만 블록으로 남긴다. 70건 실측에서 계열 확인 10건 중 8건이 비상장이었고 빠지는 2건은 **지주회사가 상장 계열사 지분을 취득한 건**이었다(녹십자홀딩스→녹십자웰빙, 사토시홀딩스→한국첨단소재 — 정상적인 그룹 내 거래). 상장 여부 `unknown`은 통과시키지 않는다. 종속회사는 통과시키지 않는다(모회사의 자회사 지분 확대는 정상적 지배구조 정리 — `capital_backflow`와 같은 판단). **DS005를 쓰지 않는다**: 「타법인주식및출자증권취득결정」(자율공시, 4배 흔함)은 `resolve_decision_type`이 빈 값이고, 법정 「…양수결정」조차 DS005가 '구조화 데이터 없음'을 반환하는 사례가 실측됐다(KR모터스 20251001·코아스 20250904). 원문은 두 서식 모두 구조가 일정해 25개사 32건 표본에서 **32/32(100%)** 파싱 성공 |
| `STAKE_PLEDGE` | 제목만 | 없음 | 오너의 정상적인 주식담보대출(주담대)이 흔해 이 신호 하나만으로는 판단 근거가 되지 않는다(MEDIUM 참고 강도). 담보설정비율·인수 직후 시점 여부는 사용자가 원문에서 직접 확인 |
| `CB_BW` 인수자 추출 | 제목 매칭 + **인수자 실명 확인** | `extract_cb_investors`(구조화 엔드포인트 우선, HTML 폴백) | 신호 자체는 제목으로 충분하지만, "누가 받아갔는지"는 원문 확인 없이는 알 수 없어 별도 추출기를 둔다 |
| `DECISION_RELATED_PARTY`/`DECISION_OVERSIZED`/`DECISION_NO_EXTVAL` | **DS005 구조화 확인** | `fetch_major_decision` → `_normalize_decision`(관계·금액·자산비율) → `_detect_decision_anomaly` | 특수관계 여부·자산 대비 규모·외부평가 실시 여부는 제목에 드러나지 않는다 |
| `SHAREHOLDER`(최대주주변경 상세, v1.7.0으로 격상) | 제목 매칭 + **원문 확인** | `fetch_control_change_detail` → `parse_control_change_detail`(변경전/후 명칭·비율·자금조달) → `classify_holder_type`(명칭 표기 5분류) + 공개기록 레지스트리 대조 | 신호 자체는 제목으로 충분하지만 "새 최대주주가 누구이고 인수자금을 어떻게 조달했는지"는 원문 확인 없이는 알 수 없다. 근거: 금감원 무자본 M&A 합동점검(2019-12-19) — 적발 24사의 신규 최대주주 82%가 비외감법인·투자조합, 인수자금 대부분이 주식담보대출(단계①) |
| `RELATED_PARTY`(v1.14.0) | 제목 매칭 + **원문 확인** | `fetch_related_party_detail` → `parse_related_party_detail`(상대방·관계·금액·이자율·자기자본대비) | taxonomy 4.2가 요구하는 "가격 괴리"는 제목에 없다. 원문에는 이자율이 있어 조건을 눈으로 볼 수 있다 — 실측 편차가 크다(4.6%~8.95%). 신호 자체는 참고 강도(무판정)이며 블록도 사실 표기만 한다 |
| `EARNINGS_SHOCK`(v1.14.0) | 제목 매칭 + **원문 확인** | `fetch_earnings_shock_detail` → `parse_earnings_shock_detail`(계정별 증감비율·흑자적자전환여부) | 제목("매출액또는손익구조30%이상변동")만으로는 **증가인지 감소인지 알 수 없다**. 원문 표의 증감비율·전환여부로 방향을 사실 표기한다. score 0 — 방향을 모르는 채로 가산하지 않는다는 뜻 |
| **원문이 정정신고인 공시**(v1.14.0, 전 파서 공통) | 원문 머리 판정 | `_is_amended_document` → 세 파서 모두 빈 결과 | 제목에 정정 표시가 없는데 원문이 정정신고인 공시가 있다(포커스에이아이 20260821900279 실측 — 제목 「유형자산처분결정(자율공시)」은 `is_amendment_disclosure`를 통과한다). 정정 원문은 「정정전 정정후」가 나란히 오고 정정사유가 서술문이라 표 서식 정규식이 문장을 삼키고, 금액도 **정정전** 값을 잡는다. 어느 값이 현재인지 파서가 판단할 수 없어 읽지 않는다 |
| 그 외 대다수 신호(CB/BW 발행, 감자, 3자배정 등) | 제목만 | 없음 | 공시 제목 자체가 이벤트 유형을 특정하며, 상대방·금액 확인이 신호의 의미를 바꾸지 않는다 |
| **한정층(`core/qualifiers.py`, 전체 신호 공통, 2026-08-14 신규)** | 제목 **구조** 파싱(태그·본체·괄호·어미) | `parse_report_name` → `qualify_signals` — R1(제출인이 회사와 다름) · R1b(대량보유상황보고 등 지분 보유·변동 신고서 3종) · R2(결과보고서·해제·취소·철회·해지·중단 — 이미 끝난 국면) · R3(자회사·종속회사·관계회사·특수관계인 사안) · R4(해명·미확정) · R5(기재정정 등 정정·후속 태그) | `match_signals`는 제목에 키워드가 있는지만 보고 부정·방향·주체·수식어를 구분할 수단이 없어 정상 공시가 신호로 오탐된다(실측: 삼성전자 연간 발화 8건 전부, 셀트리온 32건 중 22건, 두산 10건 중 9건). 한정층은 신호를 지우지 않고 `observed`/`procedural` tier만 붙인다 — `procedural`은 집계·헤드라인·`capital_backflow` 게이트·`CROSS_SIGNAL_PATTERNS` 매칭에서 제외되고, 사유(한국어 문장)와 함께 리포트 말미에 접힌 목록으로 남는다. R1은 `flr_nm` 필드로 판정하며 R1b는 `flr_nm`이 회사 자신이어도(최대주주등소유주식변동신고서 등) 지분 보고 3종이면 무조건 강등한다(2026-08-14 라이브 실측으로 발견한 계획 결함 수정) |
| `3PCA` 라벨 보정(한정층의 라벨 보정, tier는 불변) | 제목에 "제3자배정" 마커 **부재** | `LABEL_OVERRIDES["3PCA"]` — 표시 라벨을 "유상증자(배정방식 미상)"로 보정 | `3PCA` 키워드에 "유상증자"가 통째로 포함돼 일반공모·소액공모·주주배정까지 전부 "제3자배정"으로 표기되던 오탐(셀트리온 헤드라인 오탐의 직접 원인)을 막는다. 신호를 강등하지 않고 라벨만 보정한다 — 실제 배정 방식은 제목만으로 확정할 수 없기 때문. 뷰어(`docs/tool/index.html`)는 라벨이 보정된 행에 한해 "원문 확인" 버튼을 렌더해, 클릭 시에만 원문을 열어 `confirm_markers`(제3자배정·주주배정·일반공모·주주우선공모)를 사후 확인한다(Task 10, 좁은 원문 확인 — 스캔 시점에는 호출하지 않음) |

**설계 원칙**: 확인 계층을 추가할지는 "제목만으로 정상 거래와 이상 거래를 구분할 수
있는가"로 판단한다. 구분 불가하면(FUND_OUTFLOW처럼) 신호 자체는 참고 강도로 유지하고,
그 신호가 **복합 패턴으로 격상**될 때만 원문 확인을 추가한다(개별 신호 표기 자체에
호출을 추가하면 `analyze_company_risk` 1회 실행에 API 호출이 과다해진다). 한정층은 이
원칙과 다른 층위다 — 구조화 API 호출이 아니라 **이미 갖고 있는 제목 문자열의 구조**만
다시 읽어 표시 방식을 정하므로 추가 호출이 없다.

`check_disclosure_risk`와 `search_market_disclosures`도 한정층 적용 대상이다(2026-08-16
후속 배선). 전자는 접수번호만 아는 경로에서 `resolve_disclosure_row_from_rcept_no`로
실제 제목·제출인을 복원한 뒤 단건 판정을 표시하고, 후자는 `_filter_market_rows`가
절차·사후 보고 행을 시장 스캔 목록에서 제외하고 건수만 헤더에 남긴다.

**한정층과 리포트 출력**: `analyze_company_risk`·`build_event_timeline` 둘 다 매칭된
신호를 `qualify_signals`로 나눈 뒤 "━━ 관찰된 신호 (N건) ━━"(observed, 집계·헤드라인·
패턴 매칭의 입력)와 "━━ 절차·사후 보고 (N건) ━━"(procedural, 강등 사유를 사실 문장으로
동반)로 절을 분리해 출력한다. observed가 0건이면 "이 기간 공시에서는 관찰 신호가
없습니다" 안내로 대체하고, 헤드라인 후보는 `AMBIGUOUS_SIGNAL_KEYS`(`TREASURY`·
`TREASURY_TRUST`·`FUND_OUTFLOW`·`ACQ_REVIEW` — 양면적이라 헤드라인 단독 승격 부적절)를
제외한 observed 신호 중에서 `pick_headline`이 고른다. 점수·등급 가산은 여전히 없다
(v0.8.5 원칙 불변 — 한정층은 표시 계층만 바꾼다).

---

## 관찰 윈도우 게이트 (2026-08-21 신규)

`CROSS_SIGNAL_PATTERNS`의 `timeline_months`는 원래 카드 문구로만 쓰이고 매칭에는
관여하지 않았다. 그래서 5년 스캔에서 2~3년 떨어진 신호가 한 패턴으로 묶이면서
카드에 "관찰 윈도우 12개월"이라 적히는 **거짓 표기**가 나왔다(한탑 002680 실측 —
근거 공시가 2024.01~2026.08에 흩어져 있었다).

`find_pattern_overlaps(detected_taxonomies, min_overlap, taxonomy_dates=None)`에
선택 인자 `taxonomy_dates`({taxonomy id: [YYYYMMDD, ...]})를 추가했다. 주면 각 관찰일을
창 시작 후보로 훑어 `[d, d+timeline_months]` 안에 함께 들어온 신호만 `matched`로 인정하고
창 밖은 `missing`으로 보낸다(`_best_window`/`_window_end`). 담기는 개수가 같으면 **늦은
창**을 택한다 — 관측 도구라 최근 겹침이 더 유용하고, 후보를 오름차순으로 훑어 마지막
최대값을 남기므로 결과는 결정적이다. 결과에 `window_start`/`window_end`/`timeline_months`가
실려 렌더러가 실제 창을 표기한다. **미전달(None)이면 기존 동작과 동일**하다(하위 호환).

배선: `server.py`의 `_taxonomy_dates()`가 observed 이벤트를 접어 만들고
`_render_pattern_watch_block(..., taxonomy_dates=)`로 넘긴다(`analyze_company_risk`·
`build_event_timeline` 양쪽). 날짜 없는 합성 이벤트(CAPITAL_CHURN·재무 YoY 플래그)는
조회 창의 최신 공시일에 둔다 — 제목 없이 스캔 창 전체를 근거로 만들어지는 신호라
최신일 배치가 의미에 맞다. 뷰어(`docs/tool/index.html`)는 `windowEnd`/`bestWindow`/
`findPatternOverlaps(…, taxDates)`로 동일 로직을 이식했고, 카드 문구(`patternWindowLabel`)와
근거 목록(`patternEvidenceHTML`)도 실제 창 안으로 제한한다.

`timeline_months` 값 자체는 250개사×5년·관측 363건 실측으로 재보정했다 — 옛 값으로
게이트를 걸면 관측의 31.4%가 영향받아 진짜 사례를 떨어뜨렸을 것이다(선행 측정 #182의
경고가 옳았다). 재보정 후 8.0%. 상세·한계는 위 라이브 검증 매트릭스의 「패턴의 간격 축」
행과 `docs/superpowers/specs/2026-08-21-pattern-window-recalibration.md` 참고.

라이브 효과(5년 스캔, 재보정값 기준): 한탑 겹침 0건(카드 3개 소멸 — INQUIRY 수정 효과),
아틀라스링크 `자금 역류` 2/2 발화 유지, 삼성전자 0건.

## 신호 키워드 감사 (2026-08-22)

INQUIRY의 `"거래정지"` 오탐은 우연히 발견됐다. 같은 종류의 결함이 다른 신호에
남아 있는지를 **코퍼스 전수로 기계적으로** 찾은 결과 3건을 수정했다(방향 안내
커버율 59%→100%, `DEMERGER` 액면분할 오탐, 한정층 R2b). 상세·한계는
`docs/superpowers/specs/2026-08-22-signal-keyword-audit.md`.

**회귀 자산**: `tests/fixtures/corpus/signal_titles_90d.json`에 신호가 붙는 고유
제목 404종을 빈도와 함께 고정했다(전체 48,646건은 11MB라 미커밋). 갱신은
`tmp/delisting_signal/measure.py` 재수집 후 재추출. `tests/test_corpus_invariants.py`가
이 위에 불변식을 건다 — 고정 제목의 신호 유지 · taxonomy 매핑 존재 · 키워드 포함
관계 허용 목록 · 강등/observed 사유 정합 · 되사기 방향 안내 전수 · 과거 실사고 3종
재발 방지.

**키워드를 고치기 전에 반드시 잴 것**: ① 그 표현이 DART 제목에 실제로 나오는가
② 몇 건/몇 개사인가 ③ 그 키워드가 **혼자** 켜는 건수(제거 시 실제 손실)
④ 다른 신호 키워드를 부분 문자열로 포함하는가 ⑤ 제거로 무신호가 되는 제목은 무엇인가.
90일 창은 계절 표현(감사의견·결산)을 못 본다 — 그 판단에는 1년 코퍼스가 필요하다.

## 자주 있는 작업

### 새 신호 유형 추가

0. **(선행) 그 키워드가 DART 공시 제목에 실제로 등장하는지 시장 스캔으로 먼저 잰다.**
   `fetch_market_disclosures`로 30일 이상, 살아 있는 대조군 키워드와 함께 재고 "N건 중 M건"으로
   표기한다. 0건이면 taxonomy가 아니라 **카탈로그 사례·갭 리포트로만** 남긴다 — 조사·제재의
   결과(시세조종·미공개정보이용·선행매매 등)는 회사 공시에 나타나지 않는다. 실측 근거:
   30일 15,555건에서 `시세조종`·`주가조작`·`미공개정보이용`·`선행매매`·`차명` **전부 0건**
   (대조군 `불성실공시` 19·`조회공시` 26·`소송` 71). 이 절차 없이 들어간 `EMBEZZLE`의
   키워드 7개는 발화 실적 0으로 2026-08-17에 제거됐다.
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

> `CROSS_SIGNAL_PATTERNS`(`name`/`description`/`signal_sequence`/`timeline_months`/`field_evidence`)를
> 바꾼 뒤에는 `python scripts/export_tool_data.py`로 `docs/tool/signals-data.json`을 **수동
> 재생성**해야 합니다(CI 자동 실행 없음, SE-13 Task 2 확인). `severity`는 export 대상이 아니므로
> 재생성이 필요 없지만 나머지 필드는 두 뷰어(`docs/tool/index.html`, `docs/tool/se/`)가 그대로
> 읽으므로 잊으면 드리프트가 생깁니다. 재생성 후 `python -m pytest tests/test_export_tool_data.py -v`로
> 검증하세요.

등록 패턴 11개 (v1.6.1 기준):
- **기존 4개 (전통 위기 사이클)**: `founder_fade`(창업주 퇴장), `debt_spiral`(부채 악순환), `reverse_split_spiral`(무상감자 나선), `related_party_hollowing`(특수관계자 자산 공동화)
- **v0.4.0 신규 4개 (금감원 사례 기반)**: `zombie_ma`(무자본 M&A), `audit_insider_dump`(감사의견 내부자 덤프), `delisting_evasion`(상폐 회피), `fake_new_biz`(허위 신사업 주가부양)
- **v0.6.0 신규 1개**: `capital_churn_anomaly`(자본 이벤트 과다 반복 + 공시의무 위반)
- **v1.6.0 신규 2개**: `capital_backflow`(자금 역류 — 최대주주변경 후 12개월 내 금전대여·채무보증·담보제공·자산 양수로 인수자 측에 자원 이전. **v1.6.1부터 내용 조건부 발화**: 제목 매칭만으로는 표시하지 않고, 원문·DS005로 확인한 상대방 관계가 계열·특수관계(비연결)로 1건 이상 나올 때만 패턴을 표시한다 — `server.py`의 `_capital_backflow_gate` 참고), `fund_diversion_chain`(조달-유용 체인 — CB/BW 등 사모 조달 후 비상장주식·타법인 출자로 자금 이동, 금감원 2019-12 무자본 M&A 합동점검에서 조달자금 유용의 최대 경로(비상장주식 취득 55%)로 집계)

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

## 공개 리스크 뷰어 인프라 (docs/tool/)

- **정적 단일 파일**: `docs/tool/index.html` (외부 JS 의존 0, 빌드 없음). 데이터는 `signals-data.json`(scripts/export_tool_data.py로 수동 재생성) + `corp-map.json` + `corp-aliases.json`.
- **릴레이**: JS 릴레이 `api/[endpoint].js`(Vercel icn1)·`relay/worker.js`(Cloudflare 미러)·`scripts/dev_relay.py`(로컬) 3곳이 **동일 화이트리스트 10종**을 복제 유지 — list, company, fnlttSinglAcnt, accnutAdtorNmNdAdtOpinion, exctvSttus, elestock, alotMatter, pssrpCptalUseDtls, prvsrpCptalUseDtls, otrCprInvstmntSttus(v1.9.0 — 종속회사 유출 사실 병기). 하나 추가하면 3곳 모두 갱신.
- **원문 추출**: `api/doc.py`(껍데기) + `tool_server/doc.py`(몸통, 단위 테스트 `tests/test_tool_server_doc.py`) — `GET /api/doc?rcept_no=&max_chars=` + `X-DART-Key` 헤더. `fetch_disclosure_full` 재사용, 200 응답만 CDN 캐시(s-maxage=86400, 키가 URL에 없어 캐시 키 안전). se_server와 분리 이유: SE는 Supabase 인가제라 신뢰 모델이 다름. `.vercelignore`에 `!tool_server` 필수.
- **caution 파생 필드**: export_tool_data.py가 신호별 taxonomy severity를 2단계로 접어 `caution: bool`(CRITICAL/HIGH=true)만 내보낸다. severity·score 원값은 계속 미노출. 뷰어는 이를 '주의/참고' 관찰 우선순위 배지로 렌더(면책 동반) — **뷰어 한정 예외**이며 MCP 도구 출력·SE의 무판정 원칙은 그대로다. 패턴에는 caution을 넣지 않는다(9종 전원 CRITICAL/HIGH → 상수).
- **금감원 적발 사례 배선(2026-08-17)**: `signals-data.json`의 `catalog` 키(13.6KB — `total_cases`·`tax_labels` 45종·`by_taxonomy{n, tech 5, laws 3, recent 3}`)를 export하고, ① SIGNAL COMMENTARY의 각 신호에 "이 유형으로 적발된 금감원 사례 N건" 접힘(사례 0건이면 미렌더) ② PATTERN MATCH에 **구성 신호별** 사례를 붙인다. ⚠ 패턴 전체를 담은 보도자료는 **0건**(사례당 taxonomy id가 1개인 게 87%)이라 "이 패턴의 사례"로 표기하면 거짓 — 한정 문구를 반드시 동반한다. `severity`·`base_score`·`confidence`는 export 금지.
- **버전 표기**: `signals-data.json`의 `meta.version`(단일 출처 `dart_risk_mcp/__init__.py`의 `__version__`, pyproject와 동일)을 면책 문구 끝에 `· v1.12.0 · 금감원 사례 277건 수록`으로 표기. **타임스탬프는 넣지 않는다**(재생성마다 diff 발생). `tests/test_export_tool_data.py`가 세 곳의 버전 일치를 고정한다.
- **기업 검색(상호변경 대응)**: `scripts/build_corp_map.py`가 corp-map.json 재생성 + corp_code 기준 diff로 옛 상호를 `corp-aliases.json`에 append-only 누적. `scripts/backfill_corp_aliases.py`는 시장 전체 "상호변경안내" 공시 원문에서 변경전/후 상호를 추출해 별칭 시드 백필. `.github/workflows/refresh-corp-map.yml` 주간 cron이 둘을 실행해 커밋. 배경: DART corpCode.xml은 상호변경 시 옛 이름을 지운다(실례: 297570 알로이스→아틀라스링크, 2026-06-12) + 동명 죽은 법인 충돌 사례(알로이스 01194892). `build_corp_map.py`는 core `dc._load_corp_codes`/`dc._corp_cache`를 그대로 쓰므로 아래 동명 법인 충돌 정책(`_merge_corp_entry`)이 자동 적용된다.
- **동명 법인 충돌(v1.10.1 실측·수정)**: 앤로보틱스(구 협진, 138360)가 이름·종목코드 어느 쪽으로도 뷰어에서 검색 불가했던 근본 원인 — corpCode.xml에 같은 이름 "앤로보틱스"의 상장(00808068/138360/구 협진)·비상장(01358296/구 나이콤) 법인이 동시에 존재했고, 옛 `_load_corp_codes`가 이름을 키로 쓰는 dict를 XML 등장 순서대로 덮어써 상장 쪽이 우연히 소실됐다(corp-map.json·resolve_corp 양쪽 영향). `_merge_corp_entry`(상장 우선, 동급이면 modify_date 최신 우선)로 수정 + 캐시 파일 포맷 버전(`_v`) 도입으로 이미 오염된 채 굳어 있던 `~/.cache/dart-risk-mcp/corp_codes.json`도 재다운로드로 치유. 협진→앤로보틱스 상호변경(rcept 20260115900145, 2026-01-15)은 `backfill_corp_aliases.py --from 20251201 --to 20260228`로 별칭 백필 완료.
- **기업 검색 서버측 폴백**: `api/corp.py`(껍데기) + `tool_server/corp.py`(몸통, 단위 테스트 `tests/test_tool_server_corp.py`) — `GET /api/corp?q=<2자+>` + `X-DART-Key` 헤더. 뷰어의 로컬 목록(corp-map.json, 상장만·1회성 스냅샷)이 동명 충돌·상호변경 등으로 자동완성을 놓쳤을 때, 서버가 `dc._corp_cache`(corpCode.xml 전체, 비상장 포함) + `load_corp_aliases()`에서 정확 일치(이름/종목코드) → 별칭 정확 일치(현재명 해석) → 부분 일치(짧은 이름순) 순으로 최대 8건을 반환한다. 200 응답 캐시는 `s-maxage=3600`(명부는 공시 원문보다 자주 바뀔 수 있어 doc.py의 86400보다 짧게). `scripts/dev_relay.py`에도 `/api/corp` 분기 추가.
- **뷰어 검색 버튼 상시 활성(v1.10.1)**: `docs/tool/index.html`의 SCAN INPUT에 "검색 ▸" 버튼(`#scanBtn`)을 추가해 자동완성이 빗나가도(로컬 후보 0건) 검색을 시도할 수 있게 했다 — 기존에는 Enter가 로컬 후보 배열의 첫 항목만 선택해, 후보가 아예 없으면 아무 반응이 없었다. `submitScan()`: 로컬 `suggestions()`에 후보가 있으면 그대로 스캔(네트워크 호출 없음), 없으면 `/api/corp` 폴백을 1회 호출해 후보를 `.suggest` 박스에 렌더(상장은 종목코드, 비상장은 "비상장(기타법인) — 공시 이력 기준 조회" dim 표기, 별칭이면 "옛상호 → 현재상호"). 폴백도 0건이면 "DART 명부에서 찾지 못했습니다…" 안내(6자리 숫자 질의면 상장폐지 말소 가능성 문구 추가). 폴백 결과는 `sessionStorage` 10분 캐시(`dart_corp_fb_<q>`). `attachAutocomplete`에 `onEmptyEnter` 콜백 파라미터를 추가해 `#q`(스캔 입력)에서만 로컬 후보 0건 Enter를 `submitScan`으로 연결 — `#cq`(겸직 비교 입력)는 기존 동작 그대로(폴백 대상 아님). 폴백으로 스캔한 회사(corp-map에 없을 수 있음)도 최근 기록·즐겨찾기에서 재스캔 가능하도록 `pushRecent`/`toggleFav`에 `corpCode`를 함께 저장하고, 재클릭 시 `CORPS[name]`이 없으면 `{corpCode, stockCode}` override로 `analyze()`한다(기존 `rescanCurrentLink`가 쓰던 것과 동일 패턴).
- **최근 스캔 6→20건**: `LS_RECENT` 보관 개수를 `RECENT_MAX = 20`으로 확대(기존 6). `#recentRows`에 `max-height: 460px; overflow-y: auto`를 추가해 20건이어도 페이지가 과하게 길어지지 않게 스크롤 처리.
- **종속회사 유출 사실 병기(v1.9.0)**: `capital_backflow` 게이트에서 상대방이 subsidiary(종속회사)로 확인되면, `otrCprInvstmntSttus.json`(타법인 출자현황)을 subsidiary 존재 시에만 조회(최대 2회)해 `matchAffiliateRow`/`summarizeAffiliateStake`(core `match_affiliate_row`/`summarize_affiliate_stake` 이식)로 대조한 사실을 카드에 병기한다. 뷰어는 기존 `fmtKRW`(반올림) 관례를 그대로 써 억원 표기가 core `_format_amount`(절삭)와 값이 다를 수 있다(-4,969,000,000원 → 뷰어 -50억원 vs core -49억원, 각 레이어가 기존 유틸을 재사용한 의도된 차이).
- **원문 확인 계층 이식(v1.14.0)**: core의 `parse_related_party_detail`·`parse_earnings_shock_detail`·`parse_asset_disposal_detail`을 뷰어 JS로 옮기고(`parseRelatedPartyDetail`/`parseEarningsShockDetail`/`parseAssetDisposalDetail`) 세 블록을 렌더한다 — 「RELATED PARTY」·「EARNINGS SHOCK」·「ASSET TRANSFER」. 해당 신호가 관찰되지 않으면 컨테이너 자체를 만들지 않아 원문 조회가 0회(core 블록과 같은 태도). 자산 처분은 core v1.13.4의 판단을 따라 **`capital_backflow` 게이트와 무관하게** 낸다 — 확인된 상대방은 패턴 주장이 아니라 사실이고, 경영권 변경이 없는 회사에서 "누구에게 팔았나"가 통째로 사라지던 문제를 뷰어에서도 해소했다. 라이브 8건 대조로 core와 값 일치 확인, `tests/test_viewer_detail_parser_parity.py`가 고정.
- **`classifyOutflowRelation` 드리프트 수정(v1.14.0)**: 뷰어에 core의 2026-08-04 수정(부정 표기 우선 검사)이 빠져 있어 "특수관계 없음"·"최대주주 아님"을 부분 문자열 매칭이 **계열로 읽었다** — CRITICAL 패턴 오발화 경로. 관계 미추출을 external로 떨어뜨리던 것도 unknown으로 정정했다. 이식 시 로직을 각자 옮기는 구조라 이런 드리프트가 조용히 남는다는 것이 이번 라운드의 교훈.
- **관찰 우선순위 축 분리(v1.15.0)**: v1.14.0은 배지 뒤집힘을 예외 목록으로 우회했는데, 원인은 **severity가 두 질문에 겸직**하고 있던 것이었다 — "점수를 매기나?"(OBSERVATION = base_score 0)와 "먼저 봐야 하나?". 그래서 두 방향으로 깨졌다: ① 무점수 신호가 낮은 우선순위로 내려앉음(「상장폐지 결정」이 '참고') ② severity가 HIGH라는 이유만으로 양면적 신호에 배지가 붙음(`RELATED_PARTY`·`ASSET_TRANSFER`는 `AMBIGUOUS_SIGNAL_KEYS`라 헤드라인 승격이 막혀 있는데 배지는 '주의' — 자기모순). `core/signals.py`에 `observation_priority(key)` → `first`/`watch`/`context` 축을 신설해 severity와 분리했다. 기준은 **"그 공시 한 건만 보고 무엇을 알 수 있는가"** — `first`는 회사의 존속·상장 자격·회계 신뢰성이 걸린 사실(공시 한 건으로 의미 확정), `watch`는 지배구조·자본·자금 흐름의 사건(조합·시계열로 의미가 커짐), `context`는 제목만으로 정상/이상이 갈리지 않아 원문 확인이 필요한 것. 실측: severity 파생 배지는 90일 관찰 공시의 **56.3%**에 붙어 변별력이 없었고(절반을 넘으면 배지가 아니라 기본값), 새 축의 `first`는 **13.0%**다. `signals-data.json`의 `caution` 불리언은 `priority` 문자열로 **대체**됐다(뷰어가 유일한 소비처였다). 뷰어 배지도 3종으로 — 「먼저」(amber 외곽선) · 「참고」(회색, 관찰 신호가 전부 context일 때만) · watch는 기존 `● 신호` 유지. **점수는 여전히 매기지 않는다**(v0.8.5 불변) — 이 값으로 집계·정렬·가산하지 않으며 severity·base_score 원값 미노출도 그대로다. `AMBIGUOUS_SIGNAL_KEYS`(헤드라인 차단)와는 **합치지 않았다** — 겹치지만 같은 개념이 아니라 합치면 헤드라인 정책이 조용히 바뀐다(7종 → 17종). 대신 `AMBIGUOUS ⊆ context` 포함 관계만 불변식으로 두고 `tests/test_observation_priority.py`가 지킨다.
- **알려진 한계 해소(v1.10.0)**: MCP `resolve_corp`가 corpCode.xml 현재명만 검색해 옛 상호 검색이 실패하던 한계를 core `load_corp_aliases()`로 해소했다. 뷰어와 별도 데이터를 새로 만들지 않고 동일 `corp-aliases.json`을 core도 참조한다(우선순위: env `DART_CORP_ALIASES_PATH` > 레포 상대 `docs/tool/corp-aliases.json`(개발 체크아웃) > 원격 vercel 주소 24시간 파일 캐시 > `{}`). `resolve_corp` 해석 순서는 정확 일치 → 종목코드 → 별칭 정확 일치(신규) → 부분 일치이며, 알로이스형 동명 충돌(동명의 죽은 법인과 상호변경 이력이 같은 이름을 공유)은 자동 전환하지 않고 기존 정확 일치 결과에 참고 안내만 병기한다. `analyze_company_risk`·`build_event_timeline`·`list_disclosures_by_stock`·`get_company_info` 4개 도구가 해석 결과에 `alias_note`가 있으면 리포트 상단에 안내 1줄을 표기한다.

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
