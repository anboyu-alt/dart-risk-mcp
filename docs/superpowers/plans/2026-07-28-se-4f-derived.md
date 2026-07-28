# SE-4f: 파생 지표와 분류 시각화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공시된 숫자를 옮겨 보여주는 데서 한 걸음 더 나가, **계산해야 보이는 것**과 **분류해야 보이는 것**을 만든다.

**Architecture:** SE-4c·4d가 세운 구조 그대로 — 계산·분류는 `app.js`의 **순수 함수**로 두고 node로 검증, 렌더만 `ui.js`. 서버 API·core는 건드리지 않는다.

**Tech Stack:** HTML + 순수 JS + Chart.js 4.5.1(이미 반입됨), 테스트는 `unittest` + `node` 서브프로세스

## 이 계획이 존재하는 이유

사용자가 실물 화면을 보고 말했다:

> 일반적으로 공시된 숫자 그대로 보여주는 부분도 좋지만 **영업이익률처럼 계산이 필요한 부분을 우리가 해줘서 보여주는 게 정보로서 더 가치가 있음.** 자본잠식률이나 부채비율 같은 거 공시상 숫자로는 잘 안 나오는데 시간에 따라 변화되는 걸 보여주면 좋지.

그리고 공시 목록에 대해:

> 단순 건수로만 집계하면 별 의미가 없다. 공시별 색상구분을 하면서 보여주는 게 좋을 거 같아.

**둘 다 "데이터를 가공해야 정보가 된다"는 같은 이야기다.**

---

## Global Constraints

- **외부 런타임 의존 금지.** 라이브러리는 파일로 반입(Chart.js는 이미 `/se/vendor/`에 있다). CDN·npm·빌드 스텝 금지.
- `dart_risk_mcp/` core를 **수정하지 않는다.** `se_server/` API 계약도 **바꾸지 않는다** — 소비만 한다. 바꿔야 할 이유를 발견하면 **멈추고 보고한다.**
- **표를 없애지 않는다.** 차트·파생값은 표 위에 얹는다.
- **데이터를 조용히 숨기지 않는다.**
- **판정 금지**(v0.8.5). 아래 "판정선" 절이 이 계획의 핵심 제약이다.
- **사용자·API 데이터는 `textContent`로만 DOM에 넣는다.** `innerHTML`·`outerHTML`·`insertAdjacentHTML`·`document.write` 금지.
- **실명 취급 불변식** — `showGate()`가 패널·본문·헤더·바·목차·기업 개요·차트를 비우는 성질을 깨뜨리지 않는다.
- **자산 참조는 루트 기준 절대경로**(`/se/...`).
- 주석·UI 문구는 **한국어**. `unittest.TestCase`, 실제 네트워크 호출 없음.

---

## 판정선 — 파생 지표에서 특히 위험하다

계산은 **사실**이다. 해석은 **판정**이다. 이 계획은 그 선을 넘기 쉬우므로 명시한다.

| 해도 되는 것 (사실) | 하면 안 되는 것 (판정) |
|---|---|
| 영업이익률 −13.8% → −25.1% 를 그린다 | "악화"·"개선"이라고 쓴다 |
| 부채비율 추이를 선으로 잇는다 | 200% 선을 긋고 넘으면 강조한다 |
| 계산식을 화면에 밝힌다 | "적정 수준"·"위험 수준"을 말한다 |
| 공시를 유형별로 색칠한다 | 특정 유형을 "주의 신호"로 표시한다 |
| 배당총액과 순이익을 나란히 놓는다 | "배당 여력 부족"이라고 판단한다 |

**계산식을 반드시 화면에 밝힌다.** 우리가 만든 숫자는 어떻게 나왔는지 사용자가 검증할 수 있어야 한다. 공시 원본 숫자와 우리 계산값이 구분되지 않으면 그것도 일종의 거짓말이다.

---

## 확인된 사실 (실제 API를 호출해 검산했다)

2026-07-28에 엔켐 실데이터로 확인했다.

### 재무제표에 계산 재료가 전부 있다

`fnlttSinglAcnt`(= `financials` 섹션)가 주는 계정과목:

| 재무상태표(BS) | 손익계산서(IS) |
|---|---|
| 유동자산 · 비유동자산 · **자산총계** | **매출액** · **영업이익** |
| 유동부채 · 비유동부채 · **부채총계** | 법인세차감전 순이익 |
| **자본금** · **이익잉여금** · **자본총계** | **당기순이익(손실)** · 총포괄손익 |

각 계정마다 **당기 · 전기 · 전전기** 3기간 금액이 온다.

### 실제로 계산한 결과 (엔켐, 연결)

| | 2025(당기) | 2024(전기) |
|---|---:|---:|
| 영업이익률 | **−25.1%** | −13.8% |
| 순이익률 | −22.6% | −152.7% |
| 부채비율 | 130.2% | 139.2% |

**이것이 이 계획의 근거다.** `indicators` 섹션(`fnlttSinglIndx`)이 이미 49개 지표를 주지만 **한 시점 스냅샷뿐**이다. `financials`에서 계산하면 **3기간 추이**가 나온다. 공시가 주는 것은 사진이고, 우리가 만드는 것은 흐름이다.

### ⚠️ 자본잠식률에 함정이 있다

공식 `(자본금 − 자본총계) / 자본금`을 엔켐에 적용하면 **−4302.9%** 가 나온다. 자본총계(4,810억)가 자본금(109억)보다 훨씬 크기 때문이다.

**자본잠식이 없는 회사에 잠식률을 표기하면 안 된다.** 값이 음수이면 "잠식 없음"으로 표기하고 차트에 그리지 않는다. **숫자가 계산된다고 의미가 있는 것은 아니다.**

### 배당은 같은 섹션 안에서 비교된다

`alotMatter`(= `dividends`)의 `se` 실제 값:

```
주당액면가액(원) · (연결)당기순이익(백만원) · (별도)당기순이익(백만원)
(연결)주당순이익(원) · 현금배당금총액(백만원) · 주식배당금총액(백만원)
(연결)현금배당성향(%) · 현금배당수익률(%) · 주당 현금배당금(원) …
```

**`(연결)당기순이익(백만원)`이 배당 섹션 안에 이미 있다.** 사용자가 요청한 "결산총배당 vs 벌어들인 돈" 비교가 **섹션 간 조인 없이** 가능하다.

**단위 주의:** 배당은 **백만원**, `financials`는 **원**이다. 섞으면 안 된다. 잉여금(이익잉여금)은 `financials`에 있으므로 그건 섹션 간 조인이 필요하다.

> 엔켐은 현금배당금총액이 `-`(배당 없음)라 이 비교가 발화하지 않는다. **배당하는 회사로 확인해야 한다.**

### 공시 분류 자산이 이미 있다

`docs/tool/signals-data.json`(23,798 bytes)이 공개 뷰어용으로 존재하며, 같은 배포 루트라 **`/signals-data.json`으로 접근 가능**하다.

```
{ signals: [{key, label, keywords, taxonomies, category, prose}], 
  patterns: [...], categories: {...}, capital_event_keys, amendment_pattern, fs_aliases }
```

공개 뷰어(`docs/tool/index.html`)에 `matchSignal`이 이미 있다(564·620행). **로직을 새로 만들지 말고 읽어서 맞춘다.**

---

## File Structure

| 파일 | 책임 |
|---|---|
| `docs/tool/se/app.js` | **수정** — 파생 지표 계산, 공시 분류, 배당 비교 (전부 순수 함수) |
| `docs/tool/se/ui.js` | **수정** — 파생 지표 블록·계산식 표기·색상 렌더 |
| `docs/tool/se/index.html` | **수정** — `signals-data.json` 로드, 파생 블록 CSS |
| `tests/se/test_se_app_js.py` | node로 순수 함수 검증 |
| `tests/se/test_se_page_assets.py` | 정적 검사 |

---

### Task 1: 재무 파생 지표 — 이 계획의 핵심

**Files:**
- Modify: `docs/tool/se/app.js`
- Test: `tests/se/test_se_app_js.py`

**Interfaces:**
- Produces: `financialRatios(records)` → 레코드 배열. **각 항목의 키는 정확히 이것이다** (테스트가 이 이름으로 조회한다):

```js
{
  구분: "연결" | "별도",   // fs_div — 섞으면 거짓이 되므로 반드시 나뉜다
  기간: "당기" | "전기" | "전전기",
  지표: "영업이익률" | "순이익률" | "부채비율" | "유동비율" | "자본잠식률",
  값: number | null,        // null = 계산 불가 또는 표기 부적절(자본잠식 없음)
  계산식: "영업이익 ÷ 매출액",
  재료: { "영업이익": -78386657935, "매출액": 312794042228 },
  사유: "매출액 없음"        // 값이 null일 때만. 왜 없는지 반드시 말한다
}
```

**값이 `null`이어도 항목 자체는 돌려준다.** 조용히 빼면 사용자는 그 지표가 존재하는 줄도 모른다.

**계산할 지표** (전부 `financials`의 계정과목만으로 가능):

| 지표 | 식 | 단위 |
|---|---|---|
| 영업이익률 | 영업이익 ÷ 매출액 | % |
| 순이익률 | 당기순이익 ÷ 매출액 | % |
| 부채비율 | 부채총계 ÷ 자본총계 | % |
| 유동비율 | 유동자산 ÷ 유동부채 | % |
| 자본잠식률 | (자본금 − 자본총계) ÷ 자본금 | % — **음수면 "잠식 없음"** |

**반드시 지킬 것:**

- **연결(CFS)과 별도(OFS)를 섞지 마라.** `financials`는 둘이 한 목록에 있다(SE-4d에서 차트를 뺀 이유가 이것이다). `fs_div`로 갈라 각각 계산하고 어느 쪽인지 밝혀라.
- **분모가 0이거나 없으면 계산하지 마라.** `null`을 돌려주고 화면에서 빼되, **왜 없는지 표시**하라. 매출액 0인 회사가 실제로 있다.
- **계산식과 재료 값을 함께 돌려줘라.** 화면이 "영업이익률 −25.1% (영업이익 −783.9억 ÷ 매출액 3,127.9억)"처럼 보여줄 수 있어야 한다.
- **자본잠식률은 양수일 때만 값으로 표기**한다. 음수면 "잠식 없음"이다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestFinancialRatios(unittest.TestCase):
    # 엔켐 2025 사업보고서 연결 실측값
    _CFS = """[
      {fs_div:"CFS", sj_div:"IS", account_nm:"매출액",
       thstrm_amount:"312,794,042,228", frmtrm_amount:"365,708,579,550"},
      {fs_div:"CFS", sj_div:"IS", account_nm:"영업이익",
       thstrm_amount:"-78,386,657,935", frmtrm_amount:"-50,403,019,697"},
      {fs_div:"CFS", sj_div:"BS", account_nm:"부채총계",
       thstrm_amount:"626,524,126,732", frmtrm_amount:"675,004,911,778"},
      {fs_div:"CFS", sj_div:"BS", account_nm:"자본총계",
       thstrm_amount:"481,025,051,729", frmtrm_amount:"484,842,224,968"},
      {fs_div:"CFS", sj_div:"BS", account_nm:"자본금",
       thstrm_amount:"10,925,068,000", frmtrm_amount:"10,555,112,500"}
    ]"""

    def test_operating_margin_matches_hand_calculation(self):
        got = run_js(f"financialRatios({self._CFS})")
        cur = [r for r in got if r["지표"] == "영업이익률" and r["기간"] == "당기"][0]
        self.assertAlmostEqual(cur["값"], -25.1, places=1)

    def test_debt_ratio_matches_hand_calculation(self):
        got = run_js(f"financialRatios({self._CFS})")
        cur = [r for r in got if r["지표"] == "부채비율" and r["기간"] == "당기"][0]
        self.assertAlmostEqual(cur["값"], 130.2, places=1)

    def test_prior_period_is_computed_too(self):
        """한 시점만 계산하면 추이가 안 나온다 — 그게 이 태스크의 존재 이유다."""
        got = run_js(f"financialRatios({self._CFS})")
        periods = {r["기간"] for r in got}
        self.assertIn("전기", periods)

    def test_formula_and_inputs_are_returned(self):
        """우리가 만든 숫자는 검증 가능해야 한다."""
        got = run_js(f"financialRatios({self._CFS})")
        r = [x for x in got if x["지표"] == "영업이익률"][0]
        self.assertTrue(r["계산식"])
        self.assertTrue(r["재료"])

    def test_capital_impairment_is_not_reported_when_there_is_none(self):
        """자본총계가 자본금보다 크면 잠식이 아니다.
        공식을 그대로 쓰면 -4302.9% 가 나오는데 그건 정보가 아니다."""
        got = run_js(f"financialRatios({self._CFS})")
        imp = [r for r in got if r["지표"] == "자본잠식률"]
        for r in imp:
            self.assertIsNone(r["값"], f"잠식이 없는데 값을 표기합니다: {r}")

    def test_capital_impairment_is_reported_when_it_exists(self):
        got = run_js('''financialRatios([
          {fs_div:"CFS", sj_div:"BS", account_nm:"자본금", thstrm_amount:"1000"},
          {fs_div:"CFS", sj_div:"BS", account_nm:"자본총계", thstrm_amount:"400"}
        ])''')
        imp = [r for r in got if r["지표"] == "자본잠식률" and r["기간"] == "당기"][0]
        self.assertAlmostEqual(imp["값"], 60.0, places=1)

    def test_consolidated_and_separate_are_not_mixed(self):
        """연결과 별도를 한 계산에 섞으면 거짓이 된다."""
        got = run_js('''financialRatios([
          {fs_div:"CFS", sj_div:"IS", account_nm:"매출액", thstrm_amount:"1000"},
          {fs_div:"CFS", sj_div:"IS", account_nm:"영업이익", thstrm_amount:"100"},
          {fs_div:"OFS", sj_div:"IS", account_nm:"매출액", thstrm_amount:"500"},
          {fs_div:"OFS", sj_div:"IS", account_nm:"영업이익", thstrm_amount:"250"}
        ])''')
        by = {(r["구분"], r["지표"]): r["값"] for r in got if r["지표"] == "영업이익률"}
        self.assertAlmostEqual(by[("연결", "영업이익률")], 10.0, places=1)
        self.assertAlmostEqual(by[("별도", "영업이익률")], 50.0, places=1)

    def test_zero_denominator_yields_null_not_infinity(self):
        got = run_js('''financialRatios([
          {fs_div:"CFS", sj_div:"IS", account_nm:"매출액", thstrm_amount:"0"},
          {fs_div:"CFS", sj_div:"IS", account_nm:"영업이익", thstrm_amount:"100"}
        ])''')
        r = [x for x in got if x["지표"] == "영업이익률"][0]
        self.assertIsNone(r["값"])

    def test_missing_account_yields_null_with_a_reason(self):
        """계정이 없으면 왜 없는지 말해야 한다 — 조용히 빼면 안 된다."""
        got = run_js('''financialRatios([
          {fs_div:"CFS", sj_div:"IS", account_nm:"매출액", thstrm_amount:"1000"}
        ])''')
        r = [x for x in got if x["지표"] == "영업이익률"][0]
        self.assertIsNone(r["값"])
        self.assertTrue(r.get("사유"))

    def test_no_verdict_words_anywhere_in_output(self):
        """계산은 사실, 해석은 판정이다(v0.8.5)."""
        import json as _json
        got = _json.dumps(run_js(f"financialRatios({self._CFS})"), ensure_ascii=False)
        for word in ("악화", "개선", "위험", "주의", "양호", "부실"):
            self.assertNotIn(word, got, f"판정 어휘 '{word}'")
```

- [ ] **Step 2: 실패 확인 → 구현 → 통과 확인 → 커밋**

Run: `python -m pytest tests/se/test_se_app_js.py -k FinancialRatios -v`

`module.exports`에 `financialRatios`를 추가한다. **`CHART_SPECS`에 파생 지표 차트도 추가**해 3기간 추이를 선으로 그린다(SE-4d의 렌더 경로가 자동 처리한다).

---

### Task 2: 파생 지표 렌더 — 계산값임을 밝힌다

**Files:**
- Modify: `docs/tool/se/ui.js`, `docs/tool/se/index.html`
- Test: `tests/se/test_se_page_assets.py`

**공시 원본 숫자와 우리 계산값이 구분되지 않으면 그것도 거짓말이다.** 파생 블록에 다음이 보여야 한다:

- 지표명·기간·값
- **계산식과 재료 값** (예: `영업이익 −783.9억 ÷ 매출액 3,127.9억`)
- **"DART 공시 수치로 계산한 값"이라는 고지**
- 연결/별도 구분

**값이 없는 지표는 사유와 함께 표기**한다(예: `매출액 없음`). 조용히 빼지 않는다.

- [ ] **Step 1~4: 테스트 먼저 → 구현 → 통과 확인 → 커밋**

---

### Task 3: 공시 유형별 색상 분류

**Files:**
- Modify: `docs/tool/se/app.js`, `docs/tool/se/ui.js`, `docs/tool/se/index.html`
- Test: `tests/se/test_se_app_js.py`

**로직을 새로 만들지 마라.** `docs/tool/index.html`에 `matchSignal`이 이미 있고(564·620행), `docs/tool/signals-data.json`이 분류 데이터다. **읽어서 맞춘다.**

`signals-data.json`은 같은 배포 루트에 있으므로 `/signals-data.json`으로 로드한다(루트 기준 절대경로 — `trailingSlash:false` 때문에 상대경로는 404다).

**⚠️ 기존 자산 경로 검사가 이걸 못 잡는다.** `TestAssetPathsSurviveTrailingSlashRedirect`는 `<script src>`·`<link href>` **태그만** 본다. `fetch()`로 부르는 경로는 검사 밖이라, 상대경로로 써도 테스트는 초록인 채 프로덕션에서만 404가 난다 — **이 저장소에서 실제로 겪은 사고와 똑같은 부류다.**

`fetch()` 대상 경로도 루트 절대경로인지 검사하는 테스트를 함께 넣어라.

**월별 건수 막대를 유형별로 쌓아 올린다.** 지금은 단색 막대라 "몇 건"만 보이는데, 유형이 나뉘면 **어떤 성격의 공시가 언제 몰렸는지**가 보인다.

**판정선:** 색은 **유형 구분**이다. 특정 유형에 빨간색을 주거나 "주의"라고 쓰면 판정이다.

**분류되지 않는 공시**는 "기타"로 남긴다 — 빼지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성** — 실제 공시명(`"[기재정정]주요사항보고서(자기전환사채매도결정)"`·`"타법인주식및출자증권취득결정"` 등 엔켐 실측)으로 분류가 되는지, 미분류가 "기타"로 남는지, `signals-data.json`의 키와 우리 분류가 어긋나지 않는지.

- [ ] **Step 2~5: 실패 확인 → 구현 → 통과 확인 → 커밋**

---

### Task 4: 배당 vs 벌어들인 돈

**Files:**
- Modify: `docs/tool/se/app.js`, `docs/tool/se/ui.js`
- Test: `tests/se/test_se_app_js.py`

`dividends` 섹션의 `se` 안에 **`현금배당금총액(백만원)`과 `(연결)당기순이익(백만원)`이 함께** 있다. 같은 단위(백만원)라 **섹션 간 조인 없이** 나란히 놓을 수 있다.

**이익잉여금은 `financials`에 있고 단위가 원**이다. 섹션 간 조인 + 단위 환산이 필요하므로 **이번에는 하지 않는다** — 배당총액 대 순이익 비교만 한다. 근거: 단위 혼동은 이 프로젝트에서 이미 `financials` 차트를 뺀 사유다.

**주의:** 엔켐은 배당이 없어(`-`) 이 비교가 발화하지 않는다. **배당하는 회사로 확인해야 한다.** 확인용 회사를 고르는 것도 이 태스크의 일이다.

**판정선:** 배당총액과 순이익을 나란히 놓는 것은 사실이다. "배당 여력 부족"이라고 쓰면 판정이다.

- [ ] **Step 1~5: 테스트 먼저 → 구현 → 통과 확인 → 커밋**

---

### Task 5: 타법인 출자 — 피투자사와 규모 변화

**Files:**
- Modify: `docs/tool/se/app.js`, `docs/tool/se/ui.js`
- Test: `tests/se/test_se_app_js.py`

사용자 요청:

> 피투자사에 대한 정보를 처음부터 보여줄 필요도 있음. 그리고 이것도 시간의 순서에 따라 투자 규모 변화를 보여주는 시각적 표현을 고민해보자.

`affiliates`(27건)의 실측 필드에 `frst_acqs_de`(최초 취득일)·`bsis_blce_acntbk_amount`(기초 장부가액)·`trmend_blce_acntbk_amount`(기말 장부가액)·`recent_bsns_year_fnnr_sttus_thstrm_ntpf`(피투자사 당기순이익)가 있다.

**먼저 확인하라:** `affiliates`는 **한 사업연도 스냅샷**이다. "시간에 따른 변화"를 어디까지 만들 수 있는지 실제 데이터로 판단하라. 기초→기말 변화는 있지만 여러 해에 걸친 추이는 한 번의 응답에 없다.

**없는 것을 있는 것처럼 만들지 마라.** 만들 수 있는 것만 만들고, 못 하는 것은 계획에 남긴다.

- [ ] **Step 1~5: 실제 데이터 확인 → 테스트 먼저 → 구현 → 통과 확인 → 커밋**

---

### Task 6: 최대주주 변동현황·임원 자기주식 — 데이터부터 확인

**Files:**
- Modify: `docs/tool/se/app.js`(필요시), `docs/tool/se/ui.js`
- Test: `tests/se/test_se_app_js.py`

사용자 지적:

> 최대주주 변동 현황 부분도 이렇게 나오면 무슨 의미가 있는 정보일지 알 수가 없어.
> 임원 주요주주 자기주식 부분은 구현 자체가 덜 된 듯.

**엔켐 화면에서 두 섹션이 거의 빈 행이었다.** 원인이 셋 중 무엇인지 **먼저 확인하라**:

1. DART가 실제로 빈 값을 준다(회사에 해당 사항 없음) → **"해당 없음"으로 표기**하는 게 정답
2. 우리가 필드를 잘못 읽는다 → 고친다
3. 렌더가 의미 있는 열을 빠뜨린다 → 고친다

**`.env.local`에 `DART_API_KEY`가 있으니 실제 API를 호출해 확인하라.** `hyslrChgSttus`·`tesstkAcqsDspsSttus`를 엔켐과 **다른 회사 몇 곳**으로 조회해 비교하면 1번인지 2·3번인지 갈린다.

**임원 현황은 행위자 연결망과 이어진다**(사용자 지적). 다만 그 연결은 별건이므로 이번에는 **"임원 목록이 읽히게" 까지만** 한다.

- [ ] **Step 1: 실제 API로 원인 규명 → 보고**
- [ ] **Step 2~5: 원인에 맞는 처리 → 테스트 → 커밋**

---

### Task 7: 자금 계획 변경 추적

**Files:**
- Modify: `docs/tool/se/app.js`, `docs/tool/se/ui.js`
- Test: `tests/se/test_se_app_js.py`

**SE-4e 조사 중 발견한 것이다.** 엔켐 2022년 자금 사용 보고에서:

| 보고 시점 | 운영자금 **계획** 금액 |
|---|---|
| 2022 1분기 | **342.91억** |
| 2022 반기·3분기·사업보고서 | **352.91억** |

**계획 금액이 중간에 바뀌었다.** 지금 화면으로는 알 수 없다.

같은 조달 건(같은 `pay_de`·`plan_useprps`)에서 **계획 금액이 보고 시점마다 다르면 그 사실을 표기**한다. 자금 용도 변경은 이 도구가 보려는 것의 한복판에 있다.

**판정선:** 변경이 있었다는 **사실**을 표기한다. "용도 변경 의심"이라고 쓰면 판정이다. (참고: core의 `_detect_fund_anomaly`가 이미 `FUND_DIVERSION` 플래그를 만들지만, 그건 계획 대비 실제 차이이지 **계획 자체의 변경**이 아니다.)

- [ ] **Step 1~5: 테스트 먼저 → 구현 → 통과 확인 → 커밋**

---

### Task 8: 프로덕션 확인

- [ ] **Step 1: 배포 후 자산 경로 확인**

`/signals-data.json`이 실제로 200을 주는지 확인한다. **파일이 맞다고 배포가 도는 것은 아니다**(2026-07-27 실측 교훈).

- [ ] **Step 2: 사람이 브라우저에서 확인**

| 확인 | 통과 기준 |
|---|---|
| 재무 파생 지표 | 영업이익률·부채비율이 3기간 추이로 보이고 **계산식이 함께** 뜬다 |
| 자본잠식률 | 엔켐에서 "잠식 없음"으로 나온다(−4302.9% 같은 값이 아니라) |
| 연결/별도 | 섞이지 않고 구분돼 보인다 |
| 공시 목록 | 월별 막대가 **유형별로 색이 나뉜다**. 미분류는 "기타" |
| 배당 | 배당하는 회사에서 배당총액과 순이익이 나란히 보인다 |
| 자금 계획 변경 | 엔켐 2022 운영자금에서 342.91억 → 352.91억 변경이 드러난다 |
| 판정선 | **"악화"·"위험"·임계선·값에 따른 빨간색이 없다** |

---

## 이 계획이 하지 않는 것

- **이익잉여금·자산매각 규모와의 비교** — 섹션 간 조인 + 단위 환산(백만원↔원)이 필요하다. 단위 혼동은 이 프로젝트에서 이미 차트를 하나 빼게 만든 사유라 신중히 간다
- **행위자 연결망과 임원 현황의 연결** — 별건
- **스펙 ②자금 체인**(조달→집행→도착지 흐름도) — 섹션 간 조인이 본격적으로 필요하다
- **행위자 조회 캐시(7초)** — 별건
- **추세선·예측·임계 판정** — 판정이다(v0.8.5)
