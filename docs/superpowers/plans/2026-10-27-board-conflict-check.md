# 이사회 이해상충 점검 도구 `check_board_conflict` — 구현 계획

승인된 설계: `C:\Users\anboy\.claude\plans\temporal-dreaming-magpie.md` (2026-10-27). 이 파일은 그 설계를 작업 단위로 쪼갠 것이다. 설계와 이 파일이 어긋나면 설계가 우선한다.

## Global Constraints (모든 Task에 적용)

- 런타임 의존성은 `mcp`·`requests`뿐. `pypdf` 등 import 금지(`tests/test_catalog_packaging.py`).
- 점수·등급·판정 어휘 금지(v0.8.5). 「제척 없음」·「위험」·「심각」·「껍데기」 같은 말을 **우리 문장**에 쓰지 않는다. 의결표의 「-」는 그대로 「-」로 적고 「표는 불참과 제척을 가르지 않습니다」를 붙인다.
- 빈 값이 「없다」로 읽히면 안 된다 — 조회 실패는 `FetchList.fetch_failed`/`_fetch_failed_notice`, 상한 절단은 「전체 N건 중 최근 M건 확인 · K건 미확인」으로 밝힌다.
- 새 fetcher는 정상 응답(status `000`·`013`)만 캐시한다(`tests/test_cache_failure_guard.py`).
- 응답 키는 `tests/fixtures/api/response_keys.json`에 있는 것만 읽는다(`tests/test_no_dead_fields.py`).
- 모든 도구는 **마크다운 문자열** 반환. JSON 반환 금지.
- 버전·`CHANGELOG.md`·`README.md`를 건드리지 않는다(릴리스 정책).
- 커밋 메시지 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- 테스트는 `env -u DART_API_KEY python -m pytest <파일> -q`로 돈다(키 없는 조건). 전체 스위트 중에는 소스를 고치지 않는다.
- 픽스처는 **원문 그대로**(공백·개행 가공 금지). 어림수·추정값을 "실측"이라 적지 않는다.

## 실측 사실 (2026-10-27, 변경 금지 — 테스트 기대값의 출처)

- 종목 357880 = DART corp_name `SKAI`, corp_code `01381984`, 원문 표기 (주)스카이월드와이드, 코스닥.
- 20251219000418 「주요사항보고서(타법인주식및출자증권양수결정)」: 발행회사 (주)스카이인텔리전스 · 대표자 이재철 · 회사와 관계 「최대주주의 특수관계인」 / 거래상대방 주식회사 디렉터스컴퍼니 · 회사와의 관계 「최대주주」 / 양수금액 23,567,700,000원(자기자본대비 77.53%) / 이사회결의일 2025-12-19 / 사외이사 참석 2 / DS005 구조화 데이터 **없음**.
- 20260323001292 사업보고서(2025.12): 섹션 `f0s30` "VI. 이사회 등 회사의 기관에 관한 사항" 안 「(2) 이사회의 주요 의결사항 등」 표. 열 머리 2단 — 상단 `회차 | 개최 일자 | 의안 내용 | 가결 여부 | 사내이사 등의 성명 | 사외이사 등의 성명`, 하단 `신재혁(출석률: 100%) | 이재철(출석률: 100%) | 제갈완(출석률: 100%) | MAO, XUCHAO(출석률: 0%) | 곽노준(출석률: 100%) | 신기동(출석률: 100%) | 홍영훈(출석률: 100%)`. 2025-12-19 행: `35 | 2025년 12월 19일 | 타법인 주식취득 계약의 건 | 가결 | 찬성 | 찬성 | 찬성 | - | - | - | 찬성`.
- 같은 보고서 임원현황(기준 2025.09.30, 출생년월 칸 있음): 신재혁 1981.06 대표이사·사내이사·주요경력에 「現 디렉터스컴퍼니 대표이사」·최대주주와의관계 「특수관계인」 / 이재철 1984.04 부대표·사내이사·「現 디렉터스컴퍼니 COO … 現 스카이인텔리전스 CEO」·「특수관계인」(주석: 2026-01-31 사임) / 제갈완 1989.01 상무·사내이사·「現 디렉터스컴퍼니 CFO」·관계 「-」. `exctvSttus` 응답 키: `birth_ym, chrg_job, corp_cls, corp_code, corp_name, fte_at, hffc_pd, main_career, mxmm_shrholdr_relate, nm, ofcps, rcept_no, rgist_exctv_at, sexdstn, stlm_dt, tenure_end_on` — 겸직 전용 키 **없음**.
- 20261021000417 「주요사항보고서(타법인주식및출자증권양수결정)」: 상대방 주식회사 스카이디렉터스 · 「최대주주」 · 잔금 2027-01-28. 첨부는 주요사항보고서 PDF 1건뿐, "의사록" 파일 없음. 결의일 이후 정기보고서 미접수(2026-10-27 기준).
- taxonomy `4.1`~`4.4` 사용 중, `4.5` 비어 있음. `4.2`는 `related_party_hollowing` 패턴 입력이라 재사용하지 않는다. `docs/DEFERRED-DECISIONS.md` 다음 번호는 **18**.

---

## Task 1: 실공시 픽스처 수집

**파일**: `tests/fixtures/board/` 신설 — `README.md`, `20251219000418_text.txt`, `20260323001292_board_section.md`, `exctvSttus_01381984_2025_11011.json`, `control_<rcept>_text.txt`.

`DART_API_KEY`가 환경변수에 있어야 한다(없으면 BLOCKED 보고). 수집 스크립트는 스크래치 디렉터리에 두고 레포에 커밋하지 않는다. 레포 루트에서 `PYTHONPATH=.`로 실행한다(scratchpad의 sys.path 함정).

1. `dart_risk_mcp.core.dart_client.fetch_document_text("20251219000418", key, max_chars=6000)` 결과를 **그대로** `20251219000418_text.txt`에 저장(utf-8). 「거래상대방」·「대표자」·「회사와의 관계」·「이사회결의일」이 들어 있는지 확인하고 없으면 `max_chars`를 12000으로 올려 다시 저장하고 README에 값을 적는다.
2. 사업보고서 20260323001292: `dart_client._fetch_document_zip` → 가장 큰 `.xml/.html/.htm` 파일 → `_decode_zip_file` → `_html_to_structured_text`로 마크다운 전문을 얻는다(`fetch_disclosure_full`은 20,000자 캡이라 쓰지 않는다). 「이사회의 주요 의결사항」이 처음 나오는 위치의 **2,000자 앞**부터 그 표가 끝나고 다음 소제목(「(3)」 또는 「이사회 내 위원회」 등)까지를 잘라 `20260323001292_board_section.md`에 저장. 잘라낸 범위(문자 오프셋)를 README에 적는다. 표가 파이프(`|`) 마크다운인지, 2단 헤더가 어떤 행 모양으로 오는지 README에 **원문 2~3줄 인용**으로 적는다.
3. `requests.get(f"{dart_client.DART_BASE}/exctvSttus.json", params={crtfc_key, corp_code:"01381984", bsns_year:"2025", reprt_code:"11011"})` 응답 JSON의 `list`를 **키 하나 빼지 않고** `exctvSttus_01381984_2025_11011.json`에 저장(`ensure_ascii=False, indent=2`). 행 수를 README에.
4. 대조군: `dart_client.fetch_market_disclosures(key, bgn_de=<오늘-45일>, end_de=<오늘>, pblntf_ty="B", max_pages=20)`에서 제목에 「타법인주식및출자증권양수결정」 또는 「타법인주식및출자증권취득결정」이 있고 정정 태그(`[`로 시작) 없는 건을 접수순 최신부터 열어 `fetch_document_text(max_chars=6000)`에 「회사와의 관계」 뒤 값이 「-」·「해당없음」·「해당사항없음」·「없음」 중 하나인 **첫 건**을 `control_<rcept_no>_text.txt`로 저장. 회사명·제목·접수번호·그 관계 원문을 README에 적는다. 45일 안에 없으면 90일로 넓히고 그 사실을 적는다.
5. README에 수집 일시(KST)·명령 요지·각 파일의 출처를 적는다.

**검증**: 네 파일이 비어 있지 않고 README의 인용이 파일 내용과 일치. 커밋 1개: `test(board): SKAI 357880 이사회 이해상충 픽스처 수집`.

---

## Task 2: `core/board.py` 순수 파서 5종 + 단위 테스트

**파일**: `dart_risk_mcp/core/board.py`(신설), `dart_risk_mcp/core/__init__.py`(export), `tests/test_board_parsers.py`(신설). 네트워크 호출 0, `requests` import 금지.

TDD: 테스트를 먼저 쓰고 실패를 본 뒤 구현한다. 픽스처는 Task 1의 네 파일.

### 함수

```python
def parse_decision_parties(text: str) -> dict
```
`fetch_document_text` 평문(공백 구분)에서 읽는다. 반환:
```python
{"counterparty": {"name": str, "rep": str, "relation": str},
 "target":       {"name": str, "rep": str, "relation": str},   # 발행회사(양수 대상). 없으면 name ""
 "resolution_date8": str,          # 「이사회결의일(결정일)」 → YYYYMMDD, 없으면 ""
 "outside_directors_present": str, # 「사외이사 참석」 뒤 숫자 원문, 없으면 ""
 "related_party": bool}            # 아래 규칙
```
- 상대방 블록: 「거래상대방」 뒤 「회사명(성명)」·「대표자」·「회사와의 관계」. 대상회사 블록: 「발행회사」 뒤 「회사명」·「대표자」·「회사와 관계|회사와의 관계」. 라벨 변형(「회사와 관계」/「회사와의 관계」/「회사와의관계」)을 모두 받는다. 값은 다음 라벨(「주소」·「국적」·「대표자」·「회사와」·「자본금」·「주요사업」 등) 앞에서 끊고 strip. 대표자 값은 한글·라틴·쉼표·마침표·공백 2~30자, 뒤에 조사·문장이 붙으면 버린다(기존 `_COUNTERPARTY_LOOKS_DIRTY_RE`와 같은 태도 — 더러운 값은 빈 문자열).
- `related_party`: 상대방 또는 대상회사 relation에 「최대주주」·「특수관계」·「계열」이 있으면 True. 단 `dart_client.classify_outflow_relation(relation) == "external"`(부정 표기)이면 False.
- 정정 원문(`dart_client._is_amended_document(text)`)이면 모두 빈 값 + `related_party False`.

```python
def extract_board_section(markdown: str) -> str
```
「이사회의 주요 의결사항」(공백 변형 허용: `이사회의\s*주요\s*의결사항`)이 처음 나오는 줄부터, 다음 소제목 줄(정규식 `^\s*(\(\d+\)|[가-하]\.|\d+\.|[IVX]+\.)` 또는 `^#{1,4} `)까지. 없으면 `""`.

```python
def parse_board_resolutions(section_md: str) -> dict
```
반환 `{"directors": [{"name": str, "group": "사내"|"사외"|"", "attendance": str}], "rows": [{"no": str, "date8": str, "agenda": str, "result": str, "votes": {name: str}}], "unparsed": int}`.
- 파이프 표만 읽는다. 첫 헤더 행에서 `사내이사 등의 성명`·`사외이사 등의 성명` 열 **위치**를 잡고, 둘째 헤더 행(또는 `|---|` 구분선 다음 첫 행)에서 `이름(출석률: N%)` 셀을 이름·출석률로 가른다. `MAO, XUCHAO`처럼 쉼표가 든 이름을 셀 단위로 보존한다.
- 데이터 행은 `회차 | 개최 일자 | 의안 내용 | 가결 여부 | 이사별 표기…`. 날짜는 「2025년 12월 19일」·「2025.12.19」·「2025-12-19」 모두 YYYYMMDD로. 셀 수가 헤더와 다르면 그 행은 `unparsed`에 세고 버린다(조용히 버리지 않는다).
- 이사별 표기 값은 원문 그대로(「찬성」·「반대」·「기권」·「-」·그 밖의 원문). 변환하지 않는다.
- 실측상 「사내이사 등의 성명」 그룹 열은 상단 헤더가 colspan으로 묶여 올 수 있어 셀 수가 상단과 하단에서 다르다 — Task 1 README의 원문 인용을 보고 실제 모양에 맞춘다.

```python
def find_resolution_rows(parsed: dict, date8: str, agenda_hint: str = "") -> list[dict]
```
`date8` 일치 행 전부. 둘 이상이고 `agenda_hint` 낱말(공백 제거 비교)이 든 행이 있으면 그 행들을 앞에.

```python
def match_director_overlap(roster_rows: list[dict], parties: dict, other_roster_rows: list[dict] | None = None) -> list[dict]
```
`roster_rows`는 `exctvSttus` 행(키 `nm, birth_ym, ofcps, rgist_exctv_at, chrg_job, main_career, mxmm_shrholdr_relate`). `parties`는 `parse_decision_parties` 결과. 반환 행:
```python
{"name": str, "role_at_issuer": str,          # f"{ofcps}/{rgist_exctv_at}" 형태 (예: "대표이사/등기임원")
 "side": "counterparty"|"target", "other_name": str,
 "role_at_other": str,                        # 근거 ①이면 "대표자(공시 기재)", ②면 main_career에서 회사명 앞뒤 ≤20자 인용
 "evidence": list[str],                       # "공시 거래상대방 대표자 일치" / "임원현황 주요경력: 「…」" / "상대방 임원현황 이름 일치"
 "birth_match": True|False|None,              # other_roster_rows에 같은 이름이 있을 때만 True/False, 아니면 None
 "mxmm_shrholdr_relate": str}
```
- 이름 비교: `known_actors.normalize_name` 류가 있으면 재사용, 없으면 공백 제거·대문자 비교 함수를 `board.py` 안에 둔다. 회사명 비교: `dart_client._fold_corp_name`(법인 접미·공백 제거·대문자) — `(주)`·`주식회사`·`㈜` 변형 흡수.
- 근거 ① `nm` == 상대방/대상회사 `rep`. ② `main_career`에 폴딩한 상대방/대상회사 `name`이 등장. ③ `other_roster_rows`에 `nm` 일치(이때 `birth_ym` 비교). 한 사람이 여러 근거면 evidence에 전부 담고 행은 하나. 같은 사람이 counterparty·target 양쪽이면 행 둘.
- `nm`이 「계」·「합계」·빈 값이면 건너뛴다.

```python
def summarize_board_conflict(directors: list[dict], overlaps: list[dict], row: dict | None) -> str
```
한 줄. 예: `이사 7인 중 3인이 상대방·대상회사 임원 겸직 · 결의 참여 표기: 찬성 3 · 「-」 3`. `row`가 None이면 `… 겸직 · 의결표 없음`. `directors`가 비면 「이사 수 확인 불가」. 판정 어휘 금지.

### 테스트(최소)

- SKAI: `parse_decision_parties` → counterparty name에 「디렉터스컴퍼니」, rep 「신재혁」(원문에 있을 때 — 없으면 테스트에서 실제 값으로 고정), relation 「최대주주」; target name 「스카이인텔리전스」, rep 「이재철」, relation 「최대주주의 특수관계인」; `resolution_date8 == "20251219"`; `related_party is True`.
- `extract_board_section` + `parse_board_resolutions`: directors 7명 이름 순서 고정(`신재혁, 이재철, 제갈완, MAO, XUCHAO, 곽노준, 신기동, 홍영훈`), 20251219 행의 votes == 위 실측(찬성·찬성·찬성·-·-·-·찬성), result 「가결」, agenda에 「타법인 주식취득」.
- `match_director_overlap`(SKAI 명부 픽스처 × SKAI parties) → 이름 집합 `{신재혁, 이재철, 제갈완}`; 신재혁 evidence에 ①·②, 이재철에 ①(target rep)·②, 제갈완에 ②만; 모두 `birth_match is None`.
- 대조군 픽스처: `related_party is False`, `match_director_overlap(SKAI 명부, 대조군 parties)` → `[]`.
- `summarize_board_conflict` 문자열에 「3인」·「찬성 3」·「「-」 3」이 있고 `위험|제척 없음|심각` 없음.
- 2단 헤더가 아닌 단순 표·빈 문자열·정정 원문에서 예외 없이 빈 결과.

커밋: `feat(board): 이사회 의결표·거래 당사자 파서 (순수 함수)`.

---

## Task 3: 임원 명부 fetcher `fetch_executive_roster_rows`

**파일**: `dart_risk_mcp/core/dart_client.py`, `dart_risk_mcp/core/__init__.py`, `tests/conftest.py`(`STRUCTURED_FETCH_STUBS`에 추가), `tests/test_board_roster_fetch.py`(신설).

```python
def fetch_executive_roster_rows(corp_code: str, api_key: str, bsns_year: str, reprt_code: str = "11011") -> FetchList
```
- `/exctvSttus.json` 1콜. 반환은 `FetchList`(list 상속, `.fetch_failed`). 각 행은 응답 dict에서 `nm, birth_ym, ofcps, rgist_exctv_at, chrg_job, main_career, mxmm_shrholdr_relate, hffc_pd, fte_at` 아홉 키만 담는다(전부 `response_keys.json`의 `exctvSttus`에 있음). 「계」·「합계」 행 제외.
- status `000` → 행, `013` → 빈 FetchList(`fetch_failed False`), 그 밖(020·800·HTTP 오류·예외) → 빈 FetchList(`fetch_failed True`). 캐시는 `_cache_set` 관례로 정상 응답만, 키 `("roster_rows", corp_code, bsns_year, reprt_code)`, 10분.
- `fetch_executive_roster_detail`은 **건드리지 않는다**.
- 정기보고서 제목 → `(bsns_year, reprt_code)` 유도 순수 함수도 같이: `periodic_report_code(report_nm: str) -> tuple[str, str] | None` — `사업보고서 (2025.12)`→`("2025","11011")`, `반기보고서 (2026.06)`→`("2026","11012")`, `분기보고서 (2026.03)`→`("2026","11013")`, `분기보고서 (2026.09)`→`("2026","11014")`. 접두 태그(`[기재정정]` 등)는 `strip_amendment_prefix`로 뗀다. 그 밖은 None.

테스트: `responses`/`monkeypatch`로 `_retry` 또는 `requests.Session.request`를 막아 000·013·020·예외 네 경로와 캐시 미저장(020)을 검사. `periodic_report_code` 6케이스. `tests/test_structured_fetch_honesty.py`·`test_cache_failure_guard.py`·`test_no_dead_fields.py`를 돌려 통과.

커밋: `feat(dart_client): 임원현황 행 fetcher (주요경력·최대주주관계 포함)`.

---

## Task 4: 도구 `check_board_conflict` + 도구 테스트

**파일**: `dart_risk_mcp/server.py`, `tests/test_board_conflict_tool.py`(신설), `tests/test_arg_validation.py`(`lookback_days` 추가), `tests/test_golden_output_hygiene.py`(`_FIRST_LINE_PATTERNS`에 첫 줄 등록).

시그니처(CLAUDE.md에 그대로 적힐 것):
```python
@mcp.tool()
def check_board_conflict(company_name: str, rcept_no: str = "", lookback_days: int = 180) -> str
```
독스트링 첫 문장: 「주요사항보고서 거래의 상대방이 최대주주·특수관계인일 때, 그 결의에 참여한 이사가 상대방·대상회사 임원을 겸하는지 공시 범위에서 대조합니다.」 한계 문장 포함: 「비상장 상대방 임원은 공시 기재(대표자·발행사 임원 주요경력)로만 확인되므로 등기부로 보완해야 합니다. 이사회의사록 첨부는 읽지 않습니다.」

흐름:
1. `_api_key()` → `_coerce_int(lookback_days, 180, 1, 730)` → `resolve_corp(company_name, key)`; 8자리 숫자면 `dc._corp_cache`에서 corp_code 직접 해석(`get_unlisted_financials` 관례 참고). 못 찾으면 기존 「❌ 기업을 찾을 수 없습니다」 문구.
2. 대상 공시:
   - `rcept_no` 있음: `resolve_disclosure_row_with_status`로 행 복원. `ROW_SCAN_LIMIT`/`ROW_ERROR`는 「신호가 없다는 뜻이 아닙니다」 안내(`check_disclosure_risk`와 같은 문구), `ROW_NOT_FOUND`는 접수번호 확인 안내. 제목이 1차 대상 유형이 아니면 그 사실을 적고 종료.
   - 없음: `fetch_company_disclosures_with_status(corp_code, key, lookback_days=...)` → 1차 대상 유형(`resolve_decision_type`이 `stock_acq|stock_div|business_acq|business_div|tangible_acq|tangible_div`를 주거나, `_is_acquisition_title`, `_is_asset_disposal_title`, 또는 `match_signals` 키에 `FUND_OUTFLOW`/`RELATED_PARTY`) 중 **정정 제외**(`is_amendment_disclosure`) 최신 `_BOARD_MAX_CHECK = 3`건. 머리에 「해당 유형 공시 N건 중 최근 3건 확인 · K건 미확인」. 0건이면 「이 창에는 해당 유형 공시가 없습니다」(조회 실패면 `_fetch_failed_notice`).
3. 건마다 `fetch_document_text(rcept_no, key, max_chars=6000)` → `board.parse_decision_parties`. 금전대여·담보·채무보증·특수관계인 거래 서식은 `parse_outflow_detail`/`parse_related_party_detail`의 counterparty·relation을 `parties["counterparty"]`에 채우고 rep는 `parse_decision_parties`가 읽은 값(없으면 ""). 결의일은 parties가 없으면 접수일로 대체하고 「결의일 미기재 — 접수일 기준」을 적는다.
4. 정기보고서: 공시 목록(2단계에서 받았거나 `rcept_no` 모드면 `fetch_company_disclosures_with_status(lookback_days=400)` 1회)에서 `periodic_report_code`가 None이 아닌 건 중 `rcept_dt >= 결의일`인 것을 접수순 오름차순으로 최대 2건. 없으면 「결의일 이후 정기보고서 미접수 — 의결표 없음」. 각 건은 `dc._fetch_document_zip` → 가장 큰 파일 → `_html_to_structured_text`(캡 없음) → `extract_board_section` → `parse_board_resolutions` → `find_resolution_rows(결의일, agenda_hint=상대방 이름 앞 4자)`. 행이 있으면 멈추고 출처 접수번호를 적는다.
5. 명부: 그 정기보고서의 `(bsns_year, reprt_code)`로 `fetch_executive_roster_rows`. 정기보고서가 없으면 결의일 연도의 `11011`로 1회 시도하고 「명부 기준 보고서: …」를 적는다. 상대방이 `classify_target_listing(name) == "listed"`면 `resolve_corp(name)`으로 corp_code를 얻어 같은 `(bsns_year, reprt_code)` 명부 1회 → `other_roster_rows`.
6. `match_director_overlap` → 렌더. 겹침 ≥1이면 `BOARD_CONFLICT` 라벨 줄(Task 5에서 신호로 등록되기 전까지는 문자열 「이사회 결의 참여 이사의 상대방 겸직」만).

출력(절 순서 고정, 첫 줄 형식 `🪑 {회사명} — 이사회 이해상충 확인 · {접수번호 또는 창}`):
```
🪑 SKAI — 이사회 이해상충 확인 · 20251219000418

━━ 거래 ━━
공시: 2025.12.19 주요사항보고서(타법인주식및출자증권양수결정) (rcept_no=20251219000418)
유형: 타법인 주식 양수 · 이사회결의일 2025.12.19 · 사외이사 참석 2
거래상대방: 주식회사 디렉터스컴퍼니 · 대표자 … · 회사와의 관계 「최대주주」
대상회사: (주)스카이인텔리전스 · 대표자 이재철 · 회사와 관계 「최대주주의 특수관계인」

━━ 이사회 의결 ━━
출처: 사업보고서 (2025.12) 20260323001292 「이사회의 주요 의결사항」
35회차 2025.12.19 「타법인 주식취득 계약의 건」 — 가결
이사별 표기: 신재혁 찬성 · 이재철 찬성 · 제갈완 찬성 · MAO, XUCHAO - · 곽노준 - · 신기동 - · 홍영훈 찬성
(「-」는 표가 불참과 제척을 가르지 않습니다 — 의사록은 공시 첨부에서 확인)

━━ 겸직 대조 ━━
- 신재혁 — 발행사 대표이사/등기임원 · 상대방 디렉터스컴퍼니: 대표자(공시 기재) · 임원현황 주요경력 「現 디렉터스컴퍼니 대표이사」 · 최대주주와의 관계 「특수관계인」 · 결의 표기 찬성 · 생년월 대조 불가
- …

━━ 한계 ━━
- 비상장 상대방 임원은 공시 기재(대표자·발행사 임원 주요경력)로만 확인했습니다 — 등기부 대조를 권합니다.
- 이사회의사록 첨부는 이 도구가 읽지 않습니다.
- CB·BW·유상증자 발행대상자 유형은 이 도구의 1차 범위 밖입니다.

요약: 이사 7인 중 3인이 상대방·대상회사 임원 겸직 · 결의 참여 표기: 찬성 3 · 「-」 3

📎 사실 표기입니다 — 판정·점수·등급이 아닙니다. 동명이인 가능성이 있습니다.
```
`_glossary_block`은 실제로 찍힌 해설 문장이 없으므로 붙이지 않는다(절이 비면 생략하는 관례).

테스트(`no_structured_dart` 픽스처 + `monkeypatch`로 `resolve_corp`·`fetch_company_disclosures_with_status`·`resolve_disclosure_row_with_status`·`fetch_document_text`·`_fetch_document_zip`(또는 마크다운을 주는 헬퍼)·`fetch_executive_roster_rows`를 막고 Task 1 픽스처를 먹인다):
- rcept 모드 SKAI: 출력에 「3인」·「신재혁」·「이재철」·「제갈완」·「20260323001292」·「찬성 3」; 「제척 없음」 없음.
- 정기보고서 미접수 경로: 「정기보고서 미접수」 문구 + 명부 기준 보고서 표기.
- 창 모드: 대상 4건 중 3건만 확인 → 「4건 중 최근 3건 확인 · 1건 미확인」.
- 조회 실패(`fetch_failed`) → `_fetch_failed_notice` 문구, 「없습니다」 아님.
- 키 없음 → 「❌ DART_API_KEY」. `lookback_days="abc"`·None → 예외 없이 기본 180.
- 대조군 rcept → 「겸직 대조」 절에 「해당 없음」 류 사실 문장, 요약에 「0인」.

커밋: `feat(server): check_board_conflict 도구`.

---

## Task 5: `BOARD_CONFLICT` 신호 + taxonomy `4.5` 등록 + export

**파일**: `dart_risk_mcp/core/signals.py`, `dart_risk_mcp/core/taxonomy.py`, `dart_risk_mcp/core/explain.py`, `data/catalog/labels_ko.json`, `dart_risk_mcp/server.py`(`_PHASE_MAP`), `tests/test_golden_output_hygiene.py`(`_INTERNAL_CODES`), `docs/tool/signals-data.json`(재생성), `tests/test_board_signal_registration.py`(신설).

- `signals.py`: `SIGNAL_TYPES`에 `{"key": "BOARD_CONFLICT", "label": "이사회 결의 참여 이사의 상대방 겸직", "score": 0, "keywords": []}` — `FUND_UNREPORTED` 항목 바로 뒤. `SIGNAL_KEY_TO_TAXONOMY["BOARD_CONFLICT"] = ["4.5"]`. `NON_TITLE_SIGNALS`·`AMBIGUOUS_SIGNAL_KEYS`·`_PRIORITY_CONTEXT`에 넣지 않는다(기본 watch).
- `taxonomy.py`: `TAXONOMY["4.5"]` — `1.8` 항목을 본떠 `id, name("특수관계자 거래 결의의 이사 겸직"), category 4, severity "MEDIUM", base_score 0, keywords ["이사회 결의", "겸직"], indicators, legal_basis ["상법 제398조(이사 등과 회사 간의 거래)", "상법 제391조 제3항·제368조 제3항(특별이해관계인의 의결권 제한)"], field_evidence []`. 어느 `CROSS_SIGNAL_PATTERNS`에도 넣지 않는다.
- `labels_ko.json`: `"4.5": {"ko": "특수관계자 거래 결의의 이사 겸직", ...}` — 기존 항목 스키마 그대로.
- `explain.py` `FLAG_PROSE["BOARD_CONFLICT"]`: 3문장 구조(①「~라는 사실 표기입니다」 ②「보통 ~를 뜻합니다」 ③「다만 ~ 원문에서 확인하세요」). 첫 문장 안에 `다.` 하나. 판정 어휘 0. 예: 「거래 상대방이 최대주주·특수관계인인 결의에 참여한 이사가 그 상대방이나 대상회사의 임원도 맡고 있다는 사실 표기입니다. 보통 그 이사가 양쪽 이해를 함께 가진 자리에서 표결했다는 뜻입니다. 다만 의결표의 「-」가 불참인지 제척인지는 표가 말하지 않으니 의사록을 확인하세요.」
- `server._PHASE_MAP["BOARD_CONFLICT"] = "심화기"`.
- `python scripts/export_tool_data.py` 재생성 → `docs/tool/signals-data.json` 커밋.
- 테스트: 키가 `SIGNAL_TYPES`·매핑·`TAXONOMY["4.5"]`·`labels_ko`·`FLAG_PROSE`·`_PHASE_MAP`에 전부 있고, `4.5`가 어느 패턴 `signal_sequence`에도 없으며, `find_pattern_overlaps`에 `{"4.5"}`만 넣었을 때 결과가 비는 것. 그리고 `tests/test_export_tool_data.py tests/test_timeline_phase_coverage.py tests/test_observed_reachability.py tests/test_prose_readability.py tests/test_prose_hygiene_static.py tests/test_mapping_evidence_sweep.py tests/test_observation_priority.py tests/test_glossary_footer_wiring.py`가 통과(sweep이 0% 매핑을 신고하면 그 테스트의 허용 목록에 「구조화 파생 신호 — 제목 키워드 없음」 근거로 등록).

커밋: `feat(signals): BOARD_CONFLICT 신호 + taxonomy 4.5 (패턴 미사용)`.

---

## Task 6: 파이프라인 배선 (analyze · timeline · check_disclosure_risk)

**파일**: `dart_risk_mcp/server.py`, `tests/test_board_conflict_wiring.py`(신설).

- Task 4의 흐름 3~6을 내부 함수 `_board_conflict_block(corp_code, corp_name, disclosures, rcept_row, api_key, *, key_budget_note) -> tuple[str, bool]`(블록 마크다운, 겹침 여부)로 떼어 도구와 공유한다(도구는 그 함수를 부른다 — 중복 구현 금지).
- `analyze_company_risk`·`build_event_timeline`: `_confirm_acquisition_targets`·`_confirm_outflow_counterparties` 결과에서 `classification == "affiliated"`(또는 relation에 「최대주주」)인 행이 있을 때만 **최근 1건**에 블록 「🪑 이사회 이해상충 확인」을 붙인다(형제 블록 「🔍 자금유출·양수거래 상대방 확인」 바로 뒤). 지도 모드(`_is_deep_window`)면 생략. 겹침 True면 `signal_events`에 `{"key": "BOARD_CONFLICT", "label": _v5_lookup 라벨, "rcept_dt": 결의일, "rcept_no": …, "report_nm": …}`를 `FUND_UNREPORTED` 추가 자리(server.py 2865 부근) 옆에서 추가 — 한정층 tier는 observed. 블록 생성 중 예외·조회 실패는 블록만 생략하고 「이사회 이해상충 확인: 조회 실패로 확인하지 못했습니다」 한 줄을 남긴다.
- `check_disclosure_risk`: 제목이 1차 대상 유형이고 `parse_decision_parties(...)["related_party"]`면 같은 블록 1회(행 복원 성공 시에만).
- `build_event_timeline`: 해당 결의일 이벤트 줄 끝에 ` · 🪑 {summarize_board_conflict 한 줄}`.
- `find_actor_overlap` 불변.

테스트(mock): affiliated 행이 없으면 `fetch_executive_roster_rows`·ZIP 호출 0회; 있으면 1회; 지도 모드(`lookback_years=3`)면 0회; 겹침 True면 리포트에 `BOARD_CONFLICT` 라벨이 「관찰된 신호」 절에 나타남; 블록 함수 예외 → 리포트는 정상 반환 + 「확인하지 못했습니다」 문구; `check_disclosure_risk` 대조군 → 블록 없음.

커밋: `feat(server): 이사회 이해상충 블록을 analyze·timeline·risk_check에 배선`.

---

## Task 7: 문서 — CLAUDE.md · manifest · DEFERRED-DECISIONS

**파일**: `CLAUDE.md`, `extension/manifest.json`, `tests/test_doc_tool_signatures.py`, `docs/DEFERRED-DECISIONS.md`.

- CLAUDE.md `### 35. \`check_board_conflict(company_name, rcept_no="", lookback_days=180)\` ✨ v1.30.0` 항목을 34번 뒤에 — 내부 흐름·출력 절·한계·설계 결정(의사록 제외 이유·4.5 신설 이유·find_actor_overlap 미통합 이유·1차 유형 한정)·라이브 검증(SKAI 두 접수번호 결과를 Task 8 실측값으로)·테스트 파일명. 「실측 사실」 절의 수치를 그대로 쓴다.
- 「MCP 도구 34개」→35개(CLAUDE.md 24행·77행), `extension/manifest.json` 7행 「34개 도구」→35, `tests/test_doc_tool_signatures.py` 62-63행의 34→35. 디렉토리 구조 표에 `board.py` 한 줄. 라이브 검증 매트릭스에 행 추가. 신호 표(Cat 4 거버넌스)에 `BOARD_CONFLICT` — `tests/test_doc_signal_categories.py`가 대조하므로 그 테스트가 요구하는 자리에.
- `docs/DEFERRED-DECISIONS.md` `## 18. 이사회의사록 첨부 파싱(제398조·제척·날짜 불일치)` — 무엇이 문제인지(첨부는 OpenAPI 밖·비공식 뷰어 파싱·PDF 의존성·SKAI 20261021000417 첨부에 의사록 없음 실측), 선택지 (a) korean-dart 등 외부 도구로 사람이 확인(현재) (b) `dart.fss.or.kr` 비공식 파싱 + optional `pdf` 그룹 (c) 하지 않음. 제작자 판단 대기.
- `python -m pytest tests/test_doc_tool_signatures.py tests/test_claude_md_counts.py tests/test_doc_facts.py tests/test_mcpb_manifest.py tests/test_doc_signal_categories.py tests/test_doc_internal_signatures.py -q` 통과.

커밋: `docs: check_board_conflict 항목·도구 수 35·DEFERRED 18`.

---

## Task 8: 골든 재생성 + 라이브 검증 + 전체 테스트

**파일**: `scripts/regen_goldens.py`, `tests/fixtures/sample_outputs/*_board*.txt`, `tests/test_golden_output_hygiene.py`(필요 시 `_ALLOWED_PAREN_ABBREVS`).

- `regen_goldens.py`: 회사 단일 인자 도구 목록에 단축명 `board` → `check_board_conflict(company)`(180일 모드, 파일 `{회사}_board.txt`). `_TITLED_RCEPT_TOOLS`에 `("board_rcept", "check_board_conflict", 마커 "양수결정")`을 `_resolve_titled_rcept` 관례로 추가(정정 제외). 단축명 충돌 확인(`market` 사례 참고).
- `python scripts/regen_goldens.py --tools board board_rcept` 실행(키 필요) → hygiene 통과. 걸리면 **골든을 손으로 고치지 말고** 원인을 코드·허용 목록에서 고친다.
- 라이브(결과를 `docs/superpowers/plans/2026-10-27-board-conflict-check.md` 끝 「라이브 결과」 절에 **원문 그대로** 붙인다 — CLAUDE.md 라이브 검증 행의 근거): `check_board_conflict("357880", rcept_no="20251219000418")`, `check_board_conflict("357880", rcept_no="20261021000417")`, `check_board_conflict("357880")`, `check_board_conflict("삼성전자")`, `analyze_company_risk("357880")`(블록 1회·`BOARD_CONFLICT` 관찰 절·패턴 카드 수가 배선 전과 같음 — 배선 전 값은 `git stash` 없이 `git worktree`나 이전 커밋 체크아웃으로 잰다).
- 전체: `env -u DART_API_KEY python -m pytest tests/ -q` 와 키 있는 `python -m pytest tests/ -q` 둘 다 0 failed, 두 실행의 passed·skipped 수가 서로 다름을 보고에 적는다.

커밋: `test(golden): check_board_conflict 골든 + 라이브 검증 기록`.
