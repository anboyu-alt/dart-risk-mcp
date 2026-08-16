# 금감원 보도자료 카탈로그 파이프라인 이식 — 설계

- 작성일: 2026-08-16
- 상태: 설계 승인됨 (구현 계획 미작성)
- 관련 기존 코드: `dart_risk_mcp/core/catalog.py`, `dart_risk_mcp/knowledge/manipulation_catalog/`
- 이식 원본: `vibecoding/dart-monitor` (scripts/collect_catalog_sources.py 외 3종 + fss_press_release/)

---

## 1. 배경

`dart_risk_mcp/knowledge/manipulation_catalog/` 8개 MD는 금감원·금융위 보도자료 기반 불공정거래 유형 카탈로그이며, `core/catalog.py`의 `load_catalog_excerpt`가 4개 MCP 도구(`analyze_company_risk`, `check_disclosure_risk`, `find_risk_precedents`, `track_fund_usage`)에서 발췌로 사용한다.

문제는 이 MD가 **다른 레포(dart-monitor)에서 1회성으로 생성된 스냅샷**이라는 점이다.

- 이 레포에는 수집·생성 코드가 없다 (`scripts/`에 관련 파일 0개, MD를 write하는 코드는 `catalog.py` 외 없음 — grep 실측)
- 생성 시점 2026-04-20에 고정. 이후 보도자료 미반영
- dart-monitor의 분류 기준(`signal_taxonomy_mapping.TAXONOMY`)과 이 레포의 `core/taxonomy.py`가 **드리프트**

### 1.1 taxonomy 드리프트 (실측)

두 레포의 TAXONOMY를 각각 import해 키를 센 결과:

| 레포 | 키 개수 |
|---|---|
| dart-monitor `signal_taxonomy_mapping.TAXONOMY` | **37** |
| dart-risk-mcp `core/taxonomy.TAXONOMY` | **45** |

dart-risk-mcp에만 존재하는 8개: `2.7`, `2.8`, `3.6`, `3.7`, `5.6`, `5.7`, `5.8`, `8.5`
(= `TREASURY_TRUST`·`INSIDER_PRE_DISCLOSURE`·`STAKE_PLEDGE`·`FUND_OUTFLOW`·`ACQ_REVIEW` 등 v0.8.6~v1.6.1에 추가된 신호군)

즉 **dart-monitor에서 카탈로그를 재생성해도 이 8개 유형의 사례 근거는 영원히 비어 있다.**

---

## 2. 실측 근거

설계 판단의 근거가 된 측정값이다. **직접 측정한 값**과 **표본에서 외삽한 추정값**을 구분해 기록한다.

### 2.1 직접 측정 (2026-08-16)

**본문 확보 경로** — 표본: FSS 보도자료 nttId 131250 / 132502 / 133239 / 133310 / 133522 (카탈로그 MD에 남아 있던 원문 URL에서 추출)

| 경로 | 측정 결과 | 표본 수 |
|---|---|---|
| 첨부 `fileSn=1` 매직바이트 | `D0CF11E0A1B11AE1` = CFBF 구형 HWP(OLE 복합문서) | **5/5** |
| 첨부 `fileSn=2` | `255044462D312E34` = PDF 1.4, FlateDecode 스트림 + `/Font` | 매직 직접 확인 1건(131250) / `.pdf` 첨부 존재 5/5 |
| 게시판 페이지 본문 영역(`bd-view`) 텍스트 | **505 ~ 1,097자** (제목·등록일·조회수·첨부파일명 포함) | 5/5 |
| 문서뷰어 `/fss/etc/docView/view.do?viewType=BODY` | JS 로더 껍데기(3,257 bytes) → 실제 렌더러는 `vod2.fss.or.kr/ctrl/viewer_ssl.aspx?...&type=jpg`. `type=html/text/txt/jpg` 전부 동일한 "Image Viewer" HTML 반환 | 1건 |

**결론: 무의존(표준 라이브러리 + requests)으로 보도자료 전문을 얻을 경로가 없다.**
- 첨부 HWP가 ZIP이 아니라 OLE이므로 `zipfile`+`xml.etree`로 파싱 불가
- PDF는 한글 CID 폰트 + ToUnicode CMap 파싱이 필요해 순수 파이썬 구현이 비현실적
- 문서뷰어는 이미지 변환이라 텍스트가 존재하지 않음

> dart-monitor `fss_press_release/attachment.py`에 `_extract_hwpx`(zipfile 기반)가 있으나, 금감원 첨부는 위 실측대로 구형 HWP다. 이 함수가 유효한 대상은 정책브리핑(금융위) 쪽 첨부로 추정되며 이번 설계는 그것에 의존하지 않는다.

**FSS 보도자료 게시판 규모** — 목록 페이지 `list.do?menuNo=200218&sdate=&edate=&pageIndex=` 의 페이지네이션을 지수·이분 탐색으로 프로빙(페이지당 10행)

| 연도 | 마지막 페이지 | 마지막 페이지 행수 | 추정 건수 |
|---|---|---|---|
| 2010 | 67 | 8 | 668 |
| 2015 | 83 | 4 | 824 |
| 2020 | 63 | 3 | 623 |
| 2025 | 85 | 2 | 842 |

2010~2025 전 연도에서 데이터 존재를 확인했다(연도 필터가 실제 동작 — 반환 행의 등록일 연도가 요청 연도와 일치).

**dart-monitor 필터 키워드** (코드 실측, `scripts/collect_catalog_sources.py:26`)

```python
KEYWORDS: list[str] = ["불공정거래", "주가조작", "사모CB"]
```

제목 + 요약에 이 중 하나라도 포함되면 통과. 카탈로그 README 기준 수집 실적은 2023-10-23 ~ 2026-04-19 기간에 **84건 수집 / 30건 분류 / 54건 낮은 신뢰도 제외 / 2건 미분류**.

**이 레포의 의존성 현황** (실측)

- `pyproject.toml` / `requirements.txt`: `mcp>=1.0.0`, `requests>=2.28.0` 뿐
- `scripts/*.py`의 서드파티 import: **0개** (Notion API도 requests로 직접 호출)
- `.github/workflows/*.yml`의 pip install: `pip install -e .`, `pip install pytest`, `pip install requests`, `python -m pip install --upgrade build` 뿐

즉 이 레포는 런타임뿐 아니라 배치 스크립트까지 "표준 라이브러리 + requests" 원칙이 일관된다.

### 2.2 추정값 (외삽 — 측정 아님)

| 항목 | 추정 | 근거 |
|---|---|---|
| 2010~2026 FSS 보도자료 원본 총량 | **약 12,000건** | 연도 4개 표본 평균 ≈ 730건 × 17년 |
| 현 키워드 3개 통과율 | **약 4.7%** | 84건 ÷ (2.5년 × 약 730건) |
| 키워드 확장 후 후보 건수 | **1,000 ~ 1,800건** | 통과율 10~15% 가정 — 미검증 |

> 확장 후 통과율은 키워드 목록이 확정되기 전에는 알 수 없다. 구현 시 `--dry-run`으로 실제 통과 건수를 먼저 측정하고 이 수치를 갱신할 것.

---

## 3. 목적

1. **보도자료를 분석해 탐지 유형 자체를 업그레이드** — 기존 45개 유형에 매핑되지 않는 신종 수법을 발굴해 신규 신호 후보로 제시
2. **신규 8개 유형(`2.7`·`2.8`·`3.6`·`3.7`·`5.6`·`5.7`·`5.8`·`8.5`)의 사례 근거 공백 해소**
3. **dart-monitor 의존 제거** — 이 레포만으로 카탈로그를 생성·갱신할 수 있는 자립

---

## 4. 설계

### 4.1 구조

```
scripts/catalog/
├── __init__.py
├── collect.py     # Phase A: 보도자료 목록 수집 + 키워드 필터 → catalog_sources.jsonl
├── extract.py     # Phase B: 본문 확보 (3단 폴백) → catalog_bodies.jsonl
├── classify.py    # Phase C: 2단계 분류 → catalog_classified.jsonl
├── build_md.py    # Phase D: knowledge/manipulation_catalog/*.md 재생성
└── gaps.py        # Phase E: 미매핑 수법 → 신규 유형 후보 리포트
```

중간 산출물은 `data/catalog/*.jsonl`. 각 Phase는 독립 실행 가능하고 `--resume`으로 중단 지점부터 재개한다(12,000건 규모에서 필수).

### 4.2 Phase A — 수집

- 소스: 금감원 FSS 오픈API(`bodoInfo.jsp`) + 금융위 정책브리핑(`apis.data.go.kr`)
- 기간: **2010-01-01 ~ 실행일** (`--start`/`--end`로 조정 가능)
- 청크: FSS 월 단위, 정책브리핑 3일 단위 (dart-monitor 관례 유지 — API 응답 상한 회피)
- **키워드 확장**: 현 3개에서 taxonomy 45개를 겨냥해 확장한다. 초기 목록(구현 시 `--dry-run` 통과 건수로 검증 후 조정):

  ```
  불공정거래, 주가조작, 시세조종, 미공개정보, 부정거래,
  사모CB, 전환사채, 신주인수권, 유상증자, 무상감자,
  최대주주, 무자본, 횡령, 배임, 회계처리기준, 감사의견,
  분식회계, 상장폐지, 증권선물위원회, 조사·제재, 공시위반
  ```

- 출력 레코드: `source`(fss/policy), `id`, `title`, `date`, `summary`, `url`, `attachment_urls`, `matched_keywords`

**주의**: FSS 오픈API가 2010년까지 데이터를 반환하는지는 **키가 없어 미검증**이다(게시판 웹페이지로는 2010년 존재를 확인). API가 과거 데이터를 제한할 경우 게시판 목록 파싱 폴백이 필요하며, 이는 구현 시 첫 확인 항목이다.

### 4.3 Phase B — 본문 확보 (2개 진입점)

Phase C의 2단계 분류가 비용 절감 효과를 내려면, **PDF를 전량 미리 받아서는 안 된다.** 따라서 `extract.py`는 순서가 고정된 단일 폴백이 아니라 **두 개의 진입점**을 제공한다.

**`extract_light(records)` — 전량 대상, 의존성 없음**

1. **게시판 페이지 본문** — `bd-view` 영역 텍스트(실측 505~1,097자). 표준 라이브러리만 사용
2. **제목 + API 요약** — 위가 실패 시

`body_source`를 `page` 또는 `title_only`로 기록한다. Phase C 1차 스크리닝의 입력이 된다.

**`extract_full(record)` — Phase C 1차 통과분만, `pypdf` 필요**

`fileSn=2` 첨부(PDF)를 다운로드해 텍스트를 추출하고 `body_source`를 `pdf`로 **갱신**한다. Phase C 2차가 건별로 호출한다. `pypdf` 미설치 시 이 함수는 `None`을 반환하고, 호출부는 `extract_light` 결과를 그대로 써서 정밀 분류를 진행한다(품질은 낮아지되 중단되지 않음).

각 레코드에 **`body_source`**(`pdf` / `page` / `title_only`)와 `body_chars`를 기록한다. 요약 기반 분류와 전문 기반 분류를 사후에 구분할 수 있어야 카탈로그 품질을 정직하게 서술할 수 있다.

`pypdf` import는 `try/except ImportError`로 감싸고, 없으면 경고 1줄 출력 후 요약 모드로 계속 진행한다(이 레포의 graceful degradation 관례 — `known_actors`의 Notion 미설정 시 조용히 비활성화와 동일).

### 4.4 Phase C — 2단계 분류

키워드를 넓히면 후보가 1,000~1,800건(추정)이 되어 전량 PDF 다운로드 + 정밀 분류는 낭비다.

**1차 스크리닝** (전 후보 대상, 값싼 호출)
- 입력: `extract_light` 결과 (제목 + 페이지 요약). PDF를 받지 않는다
- 판정: 카탈로그 등재 가치 있음/없음 + 대략의 카테고리(1~8)
- 목적: PDF 다운로드 대상을 좁힘

**2차 정밀 분류** (1차 통과분만)
- 입력: 건별로 `extract_full(record)`를 호출해 확보한 PDF 전문. `None`이면(pypdf 미설치·다운로드 실패) `extract_light` 결과로 진행하고 `body_source`를 그대로 둔다
- 출력: `taxonomy_ids`(45개 중 매핑), `적발기법`, `인용법조`, `제재내용`, `confidence`
- 45개 어디에도 매핑되지 않으면 `taxonomy_ids: []` + `unmapped_technique` 서술을 남긴다 → Phase E 입력

**LLM 호출 방식**: `anthropic` SDK 대신 Anthropic API를 `requests`로 직접 호출한다(이 레포가 Notion API를 다루는 방식과 동일). 시스템 프롬프트에 `cache_control: ephemeral`을 걸어 프롬프트 캐싱을 유지한다 — taxonomy 45개 정의가 매 호출 반복되므로 캐싱 효과가 크다.

**분류 기준의 단일 출처**: `dart_risk_mcp.core.taxonomy.TAXONOMY`를 직접 import한다. dart-monitor의 `signal_taxonomy_mapping.py`(1,170줄)는 **이식하지 않는다.** 이로써 37↔45 드리프트가 구조적으로 재발할 수 없고, 향후 taxonomy에 유형이 추가되면 다음 실행부터 자동으로 분류 대상이 된다.

### 4.5 Phase D — MD 생성

- 출력: `dart_risk_mcp/knowledge/manipulation_catalog/0{1..8}_*.md` + `README.md`
- 카테고리 파일 매핑은 `core/catalog.py`의 `_CATEGORY_TO_FILE`과 **정확히 일치**해야 한다(불일치 시 발췌가 조용히 비어버림)
- 기존 MD 포맷 유지: `## N.M: 제목`, `### 정의`, `### 탐지 키워드`, `### 위험 신호`, `### 금감원·금융위 적발 사례`, `### 적발 기법 종합`
- `- **Severity**` / `- **Base Score**` / `- **Crisis Timeline**` 3줄은 **MD에 그대로 포함**한다. 런타임에서 `catalog.py`의 `_strip_taxonomy_metadata`가 제거하는 현 구조를 유지 — v0.8.5 점수·등급 미노출 원칙에 영향 없음
- README에 수집 기간·건수·`body_source` 분포를 기록해 카탈로그 품질을 정직하게 표기

### 4.6 Phase E — 신규 유형 후보 리포트

Phase C 2차에서 `taxonomy_ids: []`로 판정된 건을 모아 `docs/catalog/gap-report-YYYY-MM-DD.md`를 생성한다.

- 내용: 미매핑 수법 서술, 출처 보도자료(제목·일자·URL), 유사 기존 유형 후보, 빈도
- **`taxonomy.py`를 자동 수정하지 않는다.** 사람이 리포트를 검토해 CLAUDE.md의 기존 "새 신호 유형 추가" 4단계 절차(`signals.py` → `SIGNAL_KEY_TO_TAXONOMY` → `taxonomy.py` → 선택적 `CROSS_SIGNAL_PATTERNS`)로 반영한다
- 이것이 목적 1("유형을 분석해 툴 업그레이드")의 직접 산출물이다

---

## 5. 의존성 및 환경변수

### 5.1 의존성

`pyproject.toml`에 optional 그룹을 추가한다:

```toml
[project.optional-dependencies]
catalog = ["pypdf>=4.0.0"]
```

- **런타임 패키지 `dart_risk_mcp/`의 의존성은 0 추가** — `mcp` + `requests` 불변
- `pypdf`는 `scripts/catalog/extract.py`에서만, optional import로 사용
- MCP 서버 사용자는 `pypdf`를 설치하지 않으며 설치할 이유도 없다

이는 CLAUDE.md 코딩 규칙("`requests`와 `mcp` 외 의존성을 추가하지 않습니다")에 대한 **배치 전용·optional 예외**다. 규칙 자체는 런타임 패키지에 대해 그대로 유지된다. 구현 시 CLAUDE.md에 이 경계를 명시한다.

### 5.2 환경변수 (전부 신규 — 사용자가 직접 발급해야 함)

| 변수 | 용도 | 발급처 |
|---|---|---|
| `FSS_API_KEY` | 금감원 보도자료 오픈API | fss.or.kr 오픈API |
| `DATA_GO_KR_API_KEY` | 금융위 정책브리핑 | 공공데이터포털 |
| `ANTHROPIC_API_KEY` | Phase C 분류 | console.anthropic.com |

셋 다 이 개발 머신에 없음을 확인했다(User/Machine/Process 스코프 전부 부재, dart-monitor에 `.env`도 없음 — Actions Secrets로만 보유). **이것이 구현 착수의 선행 블로커다.**

---

## 6. 실행·운영

- `.github/workflows/refresh-catalog.yml`
  - `workflow_dispatch` (수동 트리거, 파라미터: `--start`/`--end`/`--phase`)
  - `schedule`: **월 1회** cron
- Secrets: `FSS_API_KEY`, `DATA_GO_KR_API_KEY`, `ANTHROPIC_API_KEY`
- 워크플로우는 `pip install -e ".[catalog]"`로 pypdf 포함 설치
- 2010년 백필은 **수동 트리거 1회**로 수행(장시간·고비용). 이후 월간 cron은 증분만 처리
- 중간 산출물 JSONL은 커밋하지 않는다(`.gitignore`). 커밋 대상은 생성된 MD와 갭 리포트

---

## 7. 노출 경계

- 카탈로그 MD는 **공개 레포에 커밋한다** — 소스가 이미 공개된 금감원·금융위 보도자료이고, 현재도 공개 상태다
- 갭 리포트도 같은 성격이라 공개 커밋 대상
- 이는 `known_actors`(인물 레지스트리, 비공개 Notion)·`sightings`(private repo)와는 **별개 경계**다. 카탈로그 파이프라인은 인물 데이터를 생성하지 않으며, 두 체계를 연결하지 않는다

---

## 8. 테스트 전략

이 레포 관례(외부 호출 없는 순수 함수 단위 테스트 + 골드 회귀)를 따른다.

- `tests/test_catalog_pipeline.py` — 순수 함수 단위: 키워드 매칭, 레코드 정규화, `body_source` 판정, MD 렌더링
- 네트워크·LLM 호출은 fixture JSON으로 대체(라이브 호출 금지 — 기존 `tests/` 정책과 동일)
- **`_CATEGORY_TO_FILE` 정합성 테스트**: Phase D가 생성하는 파일명 집합이 `core/catalog.py`의 매핑과 일치하는지 기계적으로 검증. 불일치는 발췌를 조용히 비우므로 반드시 자동 검증 대상
- **`load_catalog_excerpt` 비어있지 않음 검증**: 재생성된 MD로 발췌를 뽑아 빈 문자열이 아님을 assert. `catalog.py` docstring이 경고하는 "죽은 배선" 회귀 방지
- `tests/test_golden_output_hygiene.py` 9/9 PASS 유지 — MD 변경이 도구 출력의 점수·등급 문구를 유발하지 않는지

---

## 9. 비범위

| 항목 | 사유 |
|---|---|
| 런타임 보도자료 조회 | MCP 도구 실행 중 실시간 검색은 하지 않는다. 카탈로그는 배치 생성된 정적 자료 |
| `taxonomy.py` 자동 수정 | Phase E는 후보 리포트까지. 신호 추가는 사람 검토 후 기존 4단계 절차로 |
| 구형 HWP(OLE) 파서 자체 구현 | PDF가 항상 병행 제공됨을 실측(5/5)했으므로 불필요 |
| 순수 파이썬 PDF 텍스트 추출 | 한글 CID 폰트 + ToUnicode CMap 파싱 필요 — 수백 줄 규모에 취약. `pypdf` optional로 해결 |
| dart-monitor `signal_taxonomy_mapping.py` 이식 | 드리프트 재발 방지를 위해 `core/taxonomy.py` 단일 출처화 |
| 인물·행위자 데이터 추출 | 카탈로그는 유형 지식이지 인물 레지스트리가 아니다. `known_actors` 경계 유지 |

---

## 10. 리스크 및 미해결

| # | 리스크 | 대응 |
|---|---|---|
| 1 | **FSS 오픈API의 과거 데이터 보유 범위 미검증** — 2010년까지 반환하는지 키가 없어 확인 못 함 | 구현 첫 단계에서 확인. 제한 시 게시판 목록 파싱 폴백 |
| 2 | 확장 키워드 통과율이 추정(10~15%)일 뿐 | `--dry-run`으로 실제 건수 측정 후 키워드 조정. 스펙 §2.2 수치 갱신 |
| 3 | LLM 분류 비용이 백필 규모에 비례 | 2단계 분류로 PDF·정밀호출을 좁힘. 1차 스크리닝 결과를 보고 2차 실행 여부를 사람이 결정 |
| 4 | 12,000건 목록 수집의 요청량 | 월 단위 청크 + `--resume` + 요청 간 대기. FSS 서버 부하 배려 |
| 5 | 기존 MD를 재생성하면 현재 카탈로그가 교체됨 | 백필 결과를 기존 MD와 diff로 비교 검토한 뒤 커밋. 품질 하락 시 롤백 |
| 6 | 요약 기반 분류(`body_source: page`)의 정확도가 전문 기반보다 낮음 | `body_source`를 레코드·README에 기록해 품질을 정직하게 표기. 숨기지 않는다 |

---

## 11. 성공 기준

1. `FSS_API_KEY` 등 3개 키가 설정된 환경에서 `scripts/catalog/` 5단계가 종단 실행되고, `knowledge/manipulation_catalog/*.md` 8개가 재생성된다
2. 재생성된 MD로 `load_catalog_excerpt`가 **빈 문자열이 아닌** 발췌를 반환한다(4개 도구 전부)
3. 신규 8개 유형(`2.7`·`2.8`·`3.6`·`3.7`·`5.6`·`5.7`·`5.8`·`8.5`) 중 **최소 1개 이상**에 실제 보도자료 사례가 등재된다
4. `docs/catalog/gap-report-*.md`가 생성되고, 미매핑 수법이 최소 1건 이상 후보로 제시된다
5. `pypdf` 미설치 환경에서도 파이프라인이 요약 모드로 완주한다(예외 없이)
6. `tests/test_golden_output_hygiene.py` 9/9 PASS 유지, 런타임 패키지 의존성 `mcp`+`requests` 불변
