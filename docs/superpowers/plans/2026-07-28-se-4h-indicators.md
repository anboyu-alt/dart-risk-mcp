# SE-4h 주요 재무지표 — 분류·용어·흐름 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 뒤섞인 49개 숫자 목록을 **분류된 · 뜻이 적힌 · 단위가 붙은 · 시간에 따라 움직이는** 화면으로 바꾼다.

**Architecture:** core에 `fetch_indicator_history`를 **새로 추가**해 연도 루프를 돌면서 DART가 주는 분류(`idx_cl_nm`)를 보존한 행 목록을 반환한다. 기존 `fetch_company_indicators`는 손대지 않는다(MCP 도구가 쓴다). 클라이언트는 그 행들을 4블록으로 나눠 렌더하고, 지표명 → 설명 정적 표로 뜻을 붙이며, 연도별 추이를 기존 차트 배선으로 그린다.

**Tech Stack:** Python(core, `requests`만), 순수 ES5 스타일 JS, Chart.js(이미 vendored), pytest + node 서브프로세스.

## Global Constraints

- **판정 금지 (v0.8.5).** "부채비율 130%는 높다/낮다", "양호", "위험", "주의", "악화", "개선" 같은 어휘를 쓰지 않는다. 업종마다 기준이 달라 임계선을 우리가 그으면 판정이 된다. **지표의 뜻을 설명하는 것은 허용**되고, **값을 평가하는 것은 금지**된다.
- **점수·등급·순위 금지.**
- **임계선 금지.** 차트에 "부채비율 200%" 같은 기준선을 긋지 않는다.
- **`dart_risk_mcp/` 변경은 오직 추가만.** 기존 함수·시그니처·반환형을 바꾸지 않는다. MCP 도구 26개의 동작이 한 톨도 달라지면 안 된다. 특히 `fetch_company_indicators`는 `scan_financial_anomaly`가 쓰므로 **그대로 둔다.**
- **외부 의존성 추가 금지.** `requests`/`mcp` 외 파이썬 의존성, CDN 자산 모두 금지.
- **DOM 주입 금지.** 데이터는 `textContent`로만 넣는다.
- **다크·라이트 양쪽 정의.** 새 CSS 변수는 `:root`와 `:root[data-theme="light"]` 양쪽에.
- **로그아웃 잔류 금지.** 새로 만든 DOM·차트가 `showGate()`에서 지워져야 한다.
- **값이 없는 지표를 조용히 숨기지 않는다.** DART가 `null`을 주는 지표가 실제로 있다(엔켐 실측: 세전계속사업이익률·당좌비율·매출채권회전율·매입채무회전율 등). 없으면 없다고 표기한다.

---

## 배경: 실측으로 확인한 것

2026-07-28 엔켐(`corp_code=01011526`, `bsns_year=2025`, `reprt_code=11011`) 실 API로 확인했다.

### `fnlttSinglIndx`는 4분류로 총 66개를 준다 — 지금은 그 분류가 버려진다

| `idx_cl_code` | `idx_cl_nm` | 지표 수 |
|---|---|---:|
| `M210000` | 수익성 | 15 |
| `M220000` | 안정성 | 22 |
| `M230000` | 성장성 | 18 |
| `M240000` | 활동성 | 11 |

`fetch_company_indicators`가 4번의 응답을 **`{idx_nm: float}` 평평한 딕셔너리로 합치면서 `idx_cl_nm`을 버린다.** 그래서 화면에 49개가 뒤섞여 나온다(66개 중 `idx_val`이 `null`인 것이 빠져 49개).

**응답 레코드 필드:** `reprt_code, bsns_year, corp_code, stock_code, stlm_dt, idx_cl_code, idx_cl_nm, idx_code, idx_nm, idx_val`

**⚠️ `idx_val` 키가 아예 없는 레코드가 있다.** 위 필드 목록은 수익성 응답 첫 레코드 기준인데, 그 레코드에는 `idx_val`이 **키 자체로 존재하지 않는다**(세전계속사업이익률). 다른 분류의 레코드에는 있다. `r["idx_val"]`로 접근하면 `KeyError`가 난다 — 반드시 `.get()`을 쓴다.

### 66개 지표 전체 이름 (정적 분류표의 원본 — 그대로 옮겨 쓸 것)

**수익성 (15)**
`세전계속사업이익률 · 순이익률 · 총포괄이익률 · 매출총이익률 · 매출원가율 · ROE · 판관비율 · 총자산영업이익률 · 총자산세전계속사업이익률 · 자기자본영업이익률 · 자기자본세전계속사업이익률 · 자본금영업이익률 · 자본금세전계속사업이익률 · 납입자본이익률 · 영업수익경비율`

**안정성 (22)**
`자기자본비율 · 부채비율 · 유동비율 · 당좌비율 · 유동부채비율 · 비유동부채비율 · 이자보상배율 · 순이자보상배율 · 비유동비율 · 금융비용부담률 · 자본유보율 · 유보액대비율 · 재무레버리지 · 비유동적합률 · 비유동자산구성비율 · 유형자산구성비율 · 유동자산구성비율 · 재고자산구성비율 · 유동자산/비유동자산비율 · 재고자산/유동자산비율 · 매출채권/매입채무비율 · 매입채무/재고자산비율`

**성장성 (18)**
`매출액증가율(YoY) · 매출총이익증가율(YoY) · 영업이익증가율(YoY) · 세전계속사업이익증가율(YoY) · 순이익증가율(YoY) · 총포괄이익증가율(YoY) · 총자산증가율 · 비유동자산증가율 · 유형자산증가율 · 부채총계증가율 · 총차입금증가율 · 자기자본증가율 · 유동자산증가율 · 매출채권증가율 · 재고자산증가율 · 유동부채증가율 · 매입채무증가율 · 비유동부채증가율`

**활동성 (11)**
`총자산회전율 · 매출채권회전율 · 재고자산회전율 · 매출원가/재고자산 · 매입채무회전율 · 비유동자산회전율 · 유형자산회전율 · 타인자본회전율 · 자기자본회전율 · 자본금회전율 · 배당성향(%)`

전체 목록은 `tmp/indicator_categories.json`에도 저장돼 있다.

### 성장성 18개는 이미 "흐름"이다

`매출액증가율(YoY) -14.469`, `영업이익증가율(YoY) 55.52`. 이것들은 전년 대비 변화율이다. 지금은 레벨 지표와 한 표에 섞여 있어 **무엇이 현재 값이고 무엇이 변화인지 구분되지 않는다.** 분류만 나눠도 해결된다.

### 전년도 호출이 된다

`bsns_year=2024` → `status=000`, 15건. 엔켐 순이익률 **2024 `-152.661` → 2025 `-22.56`**. 연도당 4번 호출.

### 단위

DART는 전부 **%**로 준다. `부채비율 130.248` = 130.2%, `ROE -14.612` = −14.6%. 회전율도 %다(`재고자산회전율 454.463` = 454.5%). 화면에 단위가 없어 배수인지 %인지 알 수 없다.

**⚠️ `배당성향(%)`은 이름에 이미 `(%)`가 들어 있다.** 기계적으로 `%`를 붙이면 `배당성향(%) 25.1%`가 된다. 이름에 `(%)`가 있으면 중복해서 붙이지 않는다.

**⚠️ `재무레버리지 230.248`·`이자보상배율`은 이름이 "배"인데 값은 %다.** 우리가 배수로 환산하지 않는다 — DART가 준 값을 그대로 쓰고 단위도 DART 기준(%)으로 표기한다. 환산은 우리가 계산을 얹는 것이고, 잘못 환산하면 틀린 숫자를 자신 있게 보여주게 된다.

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `dart_risk_mcp/core/dart_client.py` | `fetch_indicator_history` **신규 추가**. 기존 함수 무변경 | 추가만 |
| `dart_risk_mcp/core/__init__.py` | 신규 함수 export | 추가만 |
| `se_server/jobs/registry.py` | `indicators` 스펙을 신규 함수로 교체 | 수정 |
| `docs/tool/se/app.js` | `INDICATOR_CATEGORIES`·`INDICATOR_NOTES`·`indicatorBlocks`·`indicatorTrend` | 수정 |
| `docs/tool/se/ui.js` | 4블록 렌더 + 추이 차트 배선 | 수정 |
| `tests/test_dart_client.py` (또는 해당 파일) | core 신규 함수 검증 | 수정 |
| `tests/se/test_se_app_js.py` | 순수 함수 검증 | 수정 |
| `tests/se/test_se_page_assets.py` | 판정 어휘·자산 정적 검사 | 수정 |

---

## Task 1: core `fetch_indicator_history` + 레지스트리 교체

**Files:**
- Modify(추가만): `dart_risk_mcp/core/dart_client.py`, `dart_risk_mcp/core/__init__.py`
- Modify: `se_server/jobs/registry.py`
- Test: core 테스트 파일(기존 `fetch_company_indicators` 테스트가 있는 곳에 나란히), `tests/se/` 레지스트리 테스트

**Interfaces:**
- Consumes: `fetch_company_indicators`의 내부 호출 방식(`_INDX_CL_CODES` 루프, `_retry`, 캐시). **읽고 같은 방식을 따르되 기존 함수는 고치지 않는다.**
- Produces:
  ```python
  def fetch_indicator_history(
      corp_code: str,
      api_key: str,
      lookback_years: int = 1,
      reprt_code: str = "11011",
  ) -> list[dict]:
      """연도별 주요 재무지표를 분류를 보존한 행 목록으로 반환.

      각 행: {"bsns_year": "2025", "category": "수익성",
              "idx_nm": "순이익률", "idx_val": -22.56 | None}
      """
  ```

**요구사항:**
- 조회 연도 수는 `max(3, lookback_years)`를 5로 상한한다. **추이는 최소 2점이 필요하고 재무는 3기간이 관례다** — 사용자가 1년을 골라도 흐름을 보여주려면 3년이 필요하다. 상한 5는 기존 `_MAX_YEARS`와 맞춘다.
- 가장 최근 사업연도부터 과거로 내려간다. 기준 연도는 `fetch_company_indicators`를 부르는 쪽이 쓰는 것과 같은 방식(직전 사업연도)으로 구한다 — `registry.py`의 `_previous_business_year()`를 참고하되, core가 se_server를 import하면 안 되므로 core 안에 이미 같은 계산이 있는지 먼저 찾아 재사용한다. 없으면 core에 최소한으로 둔다.
- `idx_val`은 `.get()`으로 읽고, 빈 문자열·`None`·숫자로 못 바꾸는 값은 `None`으로 둔다. **행 자체는 버리지 않는다** — 지표가 존재한다는 사실은 남긴다.
- `idx_cl_nm`이 응답에 없으면 `idx_cl_code`로 폴백하고, 그것도 없으면 `"기타"`.
- 어떤 연도의 호출이 실패해도 예외를 밖으로 던지지 않는다(프로젝트 규칙: API 실패 시 빈 값). 그 연도만 빠진다.
- 캐시는 기존 지표 캐시 방식을 따른다.

**레지스트리 교체:**

`se_server/jobs/registry.py`의
```python
Stage1Spec("indicators", "재무", "fetch_company_indicators", ("corp_code", "bsns_year")),
```
를
```python
Stage1Spec("indicators", "재무", "fetch_indicator_history",
           ("corp_code", "lookback_years"), oversized=True),
```
로 바꾼다.

**`oversized=True`인 이유:** 호출 수가 연수에 비례한다(3~5년 × 4분류 = 12~20콜). `Stage1Spec` 독스트링이 정의한 기준에 정확히 해당한다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

기존 core 테스트 파일의 컨벤션(HTTP 모킹 방식)을 먼저 읽고 그대로 따른다. 검증할 것:

1. 반환이 행 목록이고 각 행에 `bsns_year`·`category`·`idx_nm`·`idx_val` 네 키가 있다
2. `lookback_years=1`을 줘도 **3개 연도**가 조회된다
3. `lookback_years=5` → 5개 연도, `lookback_years=99` → 5개 연도(상한)
4. `idx_val` 키가 **없는** 레코드가 와도 `KeyError` 없이 `idx_val: None` 행이 나온다 (엔켐 실측 사례)
5. `idx_val`이 `""` 이거나 숫자가 아니면 `None`
6. 분류가 `idx_cl_nm` 값으로 채워진다 (`"수익성"` 등)
7. 한 연도 호출이 예외를 던져도 함수는 예외를 밖으로 내지 않고 나머지 연도 결과를 돌려준다
8. **`fetch_company_indicators`의 반환이 그대로다** — 같은 입력에 대해 이전과 동일한 평평한 딕셔너리. 이 테스트가 MCP 도구 무영향의 증거다

- [ ] **Step 2: 실패 확인**

Run: 해당 테스트 파일의 새 테스트만 `-k`로. Expected: FAIL (`fetch_indicator_history` 없음)

- [ ] **Step 3: 구현**

`fetch_company_indicators` 바로 아래에 추가한다. 기존 함수를 재사용해도 되지만 **그러면 분류가 이미 버려진 뒤**라 값을 되살릴 수 없다 — `_INDX_CL_CODES` 루프를 별도로 돌면서 원본 레코드를 보존해야 한다.

- [ ] **Step 4: 통과 확인 + 레지스트리 교체 + 레지스트리 테스트**

레지스트리에는 이미 "`param_names`가 core 함수의 실제 키워드 인자와 일치해야 한다"는 불변식과 그걸 검사하는 테스트가 있을 가능성이 높다. 찾아서 새 스펙이 통과하는지 확인하고, 없으면 이 항목만이라도 검사를 추가한다. **이름이 틀리면 런타임 TypeError가 난다**(독스트링이 직접 경고하는 사고다).

- [ ] **Step 5: 전체 회귀**

Run: `python -m pytest tests/ -q`
Expected: 실패 0. **MCP 도구 관련 테스트가 한 건도 깨지지 않아야 한다.**

- [ ] **Step 6: 커밋**

```bash
git add dart_risk_mcp/core/dart_client.py dart_risk_mcp/core/__init__.py se_server/jobs/registry.py tests/
git commit -m "feat(se): 지표 다년 조회 + 분류 보존 (fetch_indicator_history 신규)"
```

---

## Task 2: 클라이언트 — 4분류 · 용어 · 단위 · 우선순위

**Files:**
- Modify: `docs/tool/se/app.js`, `docs/tool/se/ui.js`
- Test: `tests/se/test_se_app_js.py`

**Interfaces:**
- Consumes: Task 1이 보내는 행 목록 `[{bsns_year, category, idx_nm, idx_val}]`
- Consumes: 기존 `isNoDataMarker`·`MARK_RULES`·`cellMarks`(SE-4g), `tableLayout`, `groupHolder`
- Produces:
  - `INDICATOR_CATEGORY_ORDER` → `["수익성", "안정성", "성장성", "활동성"]`
  - `INDICATOR_NOTES` → `{ [지표명]: "뜻 한 줄" }` (`Object.create(null)`)
  - `INDICATOR_PRIMARY` → `{ [분류]: [지표명, ...] }` — 각 분류에서 먼저 보여줄 지표
  - `formatIndicator(idxNm, idxVal)` → 표시 문자열. `null`이면 `"—"`. 이름에 `(%)`가 이미 있으면 `%`를 덧붙이지 않는다
  - `indicatorBlocks(rows)` → `[{category, latestYear, primary: [{idx_nm, note, cells}], rest: [...]}]`
    - 최신 연도를 기준으로 지표를 나열하고, 각 지표에 연도별 값을 `cells`로 붙인다
    - `INDICATOR_PRIMARY`에 있는 지표가 `primary`, 나머지가 `rest`(접힘)
    - `INDICATOR_CATEGORY_ORDER`에 없는 분류는 **버리지 않고** 맨 뒤에 붙인다

**용어 설명 — 원칙**

**뜻만 쓰고 값을 평가하지 않는다.** 판정 어휘 금지 검사에 걸린다.

- ✅ `부채비율 — 빌린 돈이 자기 돈의 몇 %인가`
- ✅ `유동비율 — 1년 안에 갚을 빚 대비, 1년 안에 현금이 될 자산의 비율`
- ✅ `자본유보율 — 벌어서 쌓아둔 돈이 자본금의 몇 %인가`
- ❌ `부채비율 — 높을수록 위험하다`
- ❌ `유동비율 — 100% 이상이면 안전하다`

**`INDICATOR_PRIMARY` (설명을 다는 대상, 분류당 5~6개):**

| 분류 | 지표 |
|---|---|
| 수익성 | 순이익률 · 매출총이익률 · 매출원가율 · ROE · 판관비율 |
| 안정성 | 부채비율 · 자기자본비율 · 유동비율 · 당좌비율 · 이자보상배율 · 자본유보율 |
| 성장성 | 매출액증가율(YoY) · 영업이익증가율(YoY) · 순이익증가율(YoY) · 총자산증가율 · 자기자본증가율 · 부채총계증가율 |
| 활동성 | 총자산회전율 · 매출채권회전율 · 재고자산회전율 · 매입채무회전율 · 배당성향(%) |

나머지 44개는 `rest`로 접는다. **`납입자본이익률`·`자본금회전율` 같은 지표는 자본금이 작으면 값이 폭발한다**(엔켐 실측: 각각 −657.0, 2912.4). 지우지 않고 뒤로 보낸다.

`INDICATOR_NOTES`는 위 22개에 대해 작성한다. 나머지는 설명 없이 이름만 나온다 — **이름만으로 뜻이 서는 것들이다**(유형자산증가율 등).

- [ ] **Step 1: 실패하는 테스트를 쓴다**

픽스처는 **실측 형태 그대로**다. 이 계열에서 픽스처가 실데이터와 달라 결함이 초록으로 통과한 사고가 여섯 번 있었다.

```python
INDICATOR_ROWS = """[
 {"bsns_year":"2025","category":"수익성","idx_nm":"순이익률","idx_val":-22.56},
 {"bsns_year":"2024","category":"수익성","idx_nm":"순이익률","idx_val":-152.661},
 {"bsns_year":"2025","category":"수익성","idx_nm":"세전계속사업이익률","idx_val":null},
 {"bsns_year":"2024","category":"수익성","idx_nm":"세전계속사업이익률","idx_val":null},
 {"bsns_year":"2025","category":"수익성","idx_nm":"납입자본이익률","idx_val":-657.043},
 {"bsns_year":"2025","category":"안정성","idx_nm":"부채비율","idx_val":130.248},
 {"bsns_year":"2024","category":"안정성","idx_nm":"부채비율","idx_val":139.2},
 {"bsns_year":"2025","category":"활동성","idx_nm":"배당성향(%)","idx_val":25.1},
 {"bsns_year":"2025","category":"새분류","idx_nm":"미지의지표","idx_val":1.0}
]"""
```

검증할 것:

1. 블록이 `수익성 → 안정성 → 성장성 → 활동성` 순이고, **모르는 분류(`새분류`)가 버려지지 않고 맨 뒤에** 온다
2. `순이익률`은 `primary`, `납입자본이익률`은 `rest`
3. `INDICATOR_NOTES["부채비율"]`이 존재하고 문자열이다
4. `formatIndicator("부채비율", 130.248)` → `%`가 붙는다
5. `formatIndicator("배당성향(%)", 25.1)` → **`%`가 두 번 붙지 않는다**
6. `formatIndicator("순이익률", null)` → `"—"` (값 없음이 조용히 사라지지 않는다)
7. 같은 지표의 두 연도 값이 한 줄에 나란히 온다(2025, 2024)
8. `indicatorBlocks([])` → `[]`, `indicatorBlocks(null)` → `[]`
9. **`INDICATOR_NOTES` 전체 값에 판정 어휘가 없다** — `높", "낮", "위험", "주의", "안전", "양호", "악화", "개선", "우수", "부실"` 을 검사한다. (`"높"`·`"낮"` 은 "높을수록"·"낮으면" 류를 통째로 막기 위한 것이다.)

- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**

- [ ] **Step 5: `ui.js` 렌더**

`renderSection`의 `indicators` 경로를 4블록으로 바꾼다. 각 블록:

- 제목 = 분류명
- `primary` 표: `지표 | 뜻 | 2025 | 2024 | 2023`
- **뜻 열은 `primary`에만 있다.** `rest` 표에는 뜻 열을 만들지 않는다(빈 칸이 줄줄이 생긴다)
- `rest`는 기존 접기 방식과 같은 패턴으로 접는다
- 블록 아래에 **"DART가 계산해 공시한 값입니다 — 우리가 계산한 값이 아닙니다"** 고지. SE-4f에서 파생 지표에 붙인 고지와 방향이 반대이므로 문구를 구분한다

- [ ] **Step 6: 정적 검사 추가**

`tests/se/test_se_page_assets.py`에 `INDICATOR_NOTES` 판정 어휘 검사를 넣는다(app.js 소스 대상). SE-4g의 `TestMarkVocabulary`가 쓰는 방식을 따르되, **앵커는 `const INDICATOR_NOTES` 선언문으로 좁힌다**(SE-4g에서 앵커가 넓어 터진 적이 있다).

- [ ] **Step 7: 전체 회귀 + 커밋**

```bash
python -m pytest tests/ -q
git add docs/tool/se/app.js docs/tool/se/ui.js tests/se/
git commit -m "feat(se): 재무지표 4분류 + 용어 설명 + 단위 표기"
```

---

## Task 3: 추이 차트 + 실측 검증

**Files:**
- Modify: `docs/tool/se/app.js`, `docs/tool/se/ui.js`
- Test: `tests/se/test_se_app_js.py`

**Interfaces:**
- Consumes: `indicatorBlocks`, 기존 `CHART_SPECS`·`renderChart`·`chartData`·`writeChartCell` 충돌 가드
- Produces: 분류별 추이 차트 데이터

**요구사항:**

- 분류마다 차트 하나. x축은 **연도(오름차순)**, 계열은 `primary` 지표들
- **성장성은 이미 증가율이다.** 증가율의 추이를 선으로 그리는 건 맞지만, 다른 분류의 레벨 지표와 같은 차트에 섞으면 안 된다 — 분류별로 나뉘므로 자동 해결된다. 다만 축 라벨이 `%`라는 점만 맞추면 된다
- **임계선을 긋지 않는다**(부채비율 200% 등). Global Constraints 참고
- 값이 `null`인 지표는 계열에서 **제외**한다(선이 0으로 떨어지면 거짓이다). 전 연도가 `null`인 지표는 계열 자체를 만들지 않는다
- 단위가 섞이지 않는지 확인한다 — DART는 전부 %라 한 축이면 된다. **회전율(454%)과 이익률(−22%)이 한 축에 있으면 이익률 선이 납작해진다.** 분류가 다르므로 같은 차트에 오지 않지만, 활동성 분류 안에서는 `재고자산회전율 454`와 `총자산회전율 27.6`이 함께 온다. 이 경우를 어떻게 다룰지 정하고 그 이유를 주석에 남긴다 — 축을 나누거나, 계열을 줄이거나, 그대로 두거나. **"그대로 둔다"도 이유를 적으면 정당한 선택이다**
- `showGate()`가 새 차트를 파괴하는지 확인한다(SE-4d에서 만든 차트 정리 경로에 등록)

- [ ] **Step 1: 실패하는 테스트를 쓴다**

1. 연도가 **오름차순**으로 정렬된다(입력을 내림차순으로 넣어도)
2. `null` 값이 `0`으로 바뀌지 않는다
3. 전 연도가 `null`인 지표는 계열에 없다
4. 분류별로 차트가 나뉜다

- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**

- [ ] **Step 5: 실측 검증 — 반드시 실 API로**

`.env.local`의 `DART_API_KEY`로 엔켐(`01011526`)에 대해 `fetch_indicator_history(lookback_years=1)`를 실행하고 확인한다:

- **3개 연도**가 온다
- 분류가 4개 다 있다
- **순이익률: 2024 `-152.661` → 2025 `-22.56`** (실측 기준값)
- **부채비율 2025 `130.248`**
- `idx_val`이 `None`인 행이 존재하고, 그것 때문에 예외가 나지 않는다

**숫자가 다르면 멈추고 보고한다.** 기대값을 출력에 맞춰 고치지 않는다.

- [ ] **Step 6: 화면 확인**

`docs/tool/`을 로컬 정적 서버로 띄우고 실제 브라우저에서 `renderSection("indicators", rows)`를 실행해 확인한다:

- 4블록이 순서대로 보인다
- 뜻 열이 `primary`에만 있다
- 값에 `%`가 붙고 `배당성향(%)`에 중복되지 않는다
- 차트가 그려지고 x축이 연도다
- 가로 오버플로가 없다
- 라이트/다크 양쪽에서 읽힌다

**정적 검사만으로 성공을 보고하지 않는다.** 이 저장소는 파일이 맞는데 화면이 죽어 있던 사고를 겪었다.

- [ ] **Step 7: 전체 회귀 + 커밋**

---

## Self-Review 결과

- **판정선:** 용어 설명이 이 계획에서 가장 위험한 지점이다. "뜻"과 "평가"의 경계가 흐리기 때문에 Task 2에 어휘 검사를 기계적으로 넣었고, `"높"`·`"낮"` 을 통째로 막아 "높을수록 ~" 류를 원천 차단했다.
- **MCP 무영향:** `fetch_company_indicators`를 손대지 않고 새 함수를 추가하는 방식이라 `scan_financial_anomaly`가 안전하다. Task 1에 그걸 검증하는 테스트를 명시했다.
- **비용:** `oversized=True`로 3~5년 × 4콜. 기본 1년 선택 시에도 3년을 부르므로 12콜이다(기존 4콜). 흐름을 보여주려면 불가피하다.
- **남는 것:** 배수 단위(이자보상배율·재무레버리지)를 DART %값 그대로 두기로 했다. 환산은 우리가 계산을 얹는 것이라 뺐다.
