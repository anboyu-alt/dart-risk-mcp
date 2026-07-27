# SE-4c: 화면 가독성 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 지금 화면은 데이터를 다 보여주지만 **읽을 수가 없다.** 필드명이 원본 코드 그대로이고, 1건짜리 49열 레코드를 가로로 펴서 글자가 세로로 쪼개지며, 모든 행이 같은 값인 열이 화면 폭을 낭비한다. 이걸 고쳐서 사람이 읽는 화면으로 만든다.

**Architecture:** SE-4b가 세운 구조(`app.js` 순수 로직 + `ui.js` DOM)를 그대로 쓴다. 판단 로직은 전부 `app.js`의 순수 함수로 넣어 **node 서브프로세스로 pytest에서 검증**한다. 서버 API는 건드리지 않는다.

**Tech Stack:** HTML + 순수 JS(프레임워크·빌드·CDN 없음), 테스트는 `unittest` + `node` 서브프로세스

## Global Constraints

- **외부 CDN·빌드 스텝·프레임워크·npm 의존성 금지.** `package.json` 금지.
- `dart_risk_mcp/` core를 **수정하지 않는다.** `se_server/`의 API 계약도 **바꾸지 않는다** — 소비만 한다. 바꿔야 할 이유를 발견하면 **멈추고 보고한다.**
- **데이터를 조용히 숨기지 않는다.** 라벨이 없으면 원본 키를 그대로 쓴다. 접는 것은 되지만 **없애는 것은 안 된다.**
- **사용자·API 데이터는 `textContent`로만 DOM에 넣는다.** 데이터가 섞인 `innerHTML`·`outerHTML`·`insertAdjacentHTML`·`document.write` 금지.
- **실명에는 `status`와 동명이인 경고가 항상 동반된다.** `showGate()`가 패널을 닫고 화면을 비우는 성질을 깨뜨리지 않는다.
- **한 번 받은 섹션은 다시 받지 않는다.**
- **점수·등급·판정 어휘 금지**(v0.8.5). "위험", "의심", "고위험" 같은 말을 화면 문구로 쓰지 않는다.
- **자산 참조는 루트 기준 절대경로**(`/se/...`). `trailingSlash:false` 때문에 상대경로는 404가 된다.
- 주석·UI 문구는 **한국어**. 테스트는 `unittest.TestCase`, 실제 네트워크 호출 없음.

## 선행 조건

**SE-4b가 머지되어 프로덕션에서 동작 중이다.** `https://dart-risk-mcp.vercel.app/se` 에서 로그인·분석·섹션·패널이 돈다.

---

## 확인된 사실 — 엔켐 실측 필드 목록

**추측이 아니다.** 2026-07-27에 프로덕션에서 엔켐(1년)을 실제로 돌려 수집한 것이다. 47항목 완료·실패 0건.

| 섹션 | 레코드 | 열 | 모든 행이 같은 값인 열 |
|---|---:|---:|---|
| `company_info` | 1 | 19 | — |
| `disclosures` | 145 | 9 | `corp_cls` `corp_code` `corp_name` `stock_code` |
| `fund_usage` | 25 | 11 | `flags` `pay_amount` `dffrnc_resn` |
| `affiliates` | 27 | 20 | `stlm_dt` `corp_cls` `rcept_no` `corp_code` `corp_name` |
| `financials` | 30 | 21 | `currency` `rcept_no` `bsns_year` `corp_code` `frmtrm_nm` `thstrm_nm` `reprt_code` `stock_code` `bfefrmtrm_nm` |
| `indicators` | **1** | **49** | — |
| `shareholders` | 1 | 2 | — (`major_holders`/`bulk_holders` = 리스트를 담은 dict) |
| `insider_timeline` | 68 | **38** | `corp_code` `corp_name` |
| `executive_roster` | 1 | 7 | — (**키가 사람 이름**: 김기범·박시묵·…) |
| `audit_history` | 1 | 3 | — (`opinions`/`auditor_changes`/`independence_warnings`) |
| `debt_balance` | 1 | 5 | — |
| `distress` | 0 | 0 | — (해당 없음 = 정상) |
| `dividends` | 75 | 12 | `corp_cls` `corp_code` `corp_name` |
| `doc:*` | 34건 | — | `text` `files` `main_file` `truncated` `char_count` |

**이 표가 이번 계획의 근거 전부다.** 읽어보면 문제와 해법이 그대로 보인다:

- `indicators`가 **1건 × 49열** — 가로로 펴니 열 하나가 6px가 되어 글자가 세로로 쪼개졌다. **세로로 돌리면 해결된다.**
- `disclosures`는 9열 중 **4열이 상수** — 캡션으로 올리면 5열만 남는다.
- `financials`는 21열 중 **9열이 상수** — 12열로 줄어든다.
- `insider_timeline`은 상수를 빼도 **36열** — 접기가 필요한 유일한 섹션이다.
- `executive_roster`는 **키가 사람 이름**이라 일반 표 렌더가 통하지 않는다.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `docs/tool/se/app.js` | **수정** — 라벨 사전, 값 포맷터, 세로/가로 판단, 상수열 승격, 접기 판단 |
| `docs/tool/se/ui.js` | **수정** — 2단 레이아웃 렌더, 좌측 목차, 테마 토글, 캡션·접기 DOM |
| `docs/tool/se/index.html` | **수정** — 2단 그리드, 목차 자리, 테마 토글 버튼, 라이트 모드 변수 |
| `tests/se/test_se_app_js.py` | node로 순수 함수 검증 |
| `tests/se/test_se_page_assets.py` | 정적 검사 |

---

### Task 1: 필드 라벨 사전과 값 포맷터

**Files:**
- Modify: `docs/tool/se/app.js`
- Test: `tests/se/test_se_app_js.py`

**Interfaces:**
- Consumes: 기존 `LABELS`, `label(key)`
- Produces: `LABELS` 대폭 확장, `formatValue(key, value)` → 표시용 문자열

**원칙:** **확신하는 것만 넣는다.** 위 실측 목록에 없는 필드가 와도 원본 키를 그대로 쓴다(기존 동작 유지). 라벨이 틀리면 데이터가 사라지는 것보다 나쁘다 — 사용자가 잘못 읽게 되기 때문이다.

**근거를 코드에서 확인한 필드:** `tm`=회차(`server.py:_fund_round_korean`), `inv_prm`=피출자 법인명(`dart_client.py:2827`), `lwfr`=전전기(`dart_client.py:3482`), `se`=항목 구분(`dart_client.py:3553`), `plan_useprps`/`real_dtls_cn`/`dffrnc_resn`=`_normalize_fund_usage`(`dart_client.py:500~535`).

- [ ] **Step 1: 실패하는 테스트 작성 (`tests/se/test_se_app_js.py`에 추가)**

```python
@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestLabels(unittest.TestCase):
    def test_known_dart_fields_get_korean_labels(self):
        cases = {
            "rm": "비고", "flr_nm": "공시제출인", "report_nm": "공시명",
            "tm": "회차", "inv_prm": "피출자 법인명", "lwfr": "전전기",
            "plan_amount": "계획 금액", "real_dtls_amount": "실제 집행 금액",
        }
        for key, want in cases.items():
            self.assertEqual(run_js(f'label({json.dumps(key)})'), want)

    def test_unknown_field_keeps_raw_key(self):
        """라벨이 없다고 숨기거나 바꾸면 안 된다."""
        self.assertEqual(run_js('label("totally_unknown_xyz")'), "totally_unknown_xyz")

    def test_label_is_not_fooled_by_prototype_keys(self):
        for key in ("toString", "constructor", "__proto__", "hasOwnProperty"):
            self.assertEqual(run_js(f'label({json.dumps(key)})'), key)

    def test_every_label_is_a_nonempty_string(self):
        """빈 라벨이 들어가면 열 제목이 사라진다."""
        labels = run_js("LABELS")
        bad = [k for k, v in labels.items() if not isinstance(v, str) or not v.strip()]
        self.assertEqual(bad, [], f"빈 라벨: {bad}")

    def test_no_label_collides_with_a_different_raw_key(self):
        """서로 다른 필드가 같은 한국어 라벨을 가지면 열을 구분할 수 없다."""
        labels = run_js("LABELS")
        seen = {}
        dup = []
        for k, v in labels.items():
            if v in seen:
                dup.append(f"{seen[v]}·{k} → {v}")
            seen[v] = k
        self.assertEqual(dup, [], "라벨이 겹칩니다:\n  " + "\n  ".join(dup))


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestFormatValue(unittest.TestCase):
    def test_large_amount_becomes_readable_korean_unit(self):
        self.assertEqual(run_js('formatValue("plan_amount", 13082000000)'), "130.8억")

    def test_trillion_scale(self):
        self.assertEqual(run_js('formatValue("plan_amount", 1300000000000)'), "1.3조")

    def test_small_amount_keeps_thousands_separator(self):
        self.assertEqual(run_js('formatValue("plan_amount", 4500)'), "4,500")

    def test_zero_is_zero_not_blank(self):
        """0을 빈칸으로 만들면 잘못된 정보다."""
        self.assertEqual(run_js('formatValue("plan_amount", 0)'), "0")

    def test_yyyymmdd_becomes_dotted_date(self):
        self.assertEqual(run_js('formatValue("rcept_dt", "20260724")'), "2026.07.24")

    def test_rcept_no_is_never_reformatted_as_a_date(self):
        """접수번호는 14자리 숫자다. 날짜로 오인하면 안 된다."""
        self.assertEqual(run_js('formatValue("rcept_no", "20260724000552")'),
                         "20260724000552")

    def test_non_amount_field_with_big_number_is_untouched(self):
        """금액 필드가 아닌데 큰 수라고 억으로 바꾸면 거짓말이 된다."""
        self.assertEqual(run_js('formatValue("corp_code", "01011526")'), "01011526")

    def test_null_becomes_empty_string(self):
        self.assertEqual(run_js('formatValue("plan_amount", null)'), "")

    def test_negative_amount_keeps_sign(self):
        self.assertEqual(run_js('formatValue("plan_amount", -13082000000)'), "-130.8억")
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_se_app_js.py -k "Labels or FormatValue" -v`
Expected: FAIL — `formatValue is not defined`, 라벨 미등록

- [ ] **Step 3: `app.js`의 `LABELS`를 실측 필드로 교체**

```js
// DART 필드명 → 한국어 라벨.
//
// **확신하는 것만 넣는다.** 여기 없는 필드는 원본 키를 그대로 열 이름으로
// 쓴다 — 숨기면 데이터가 조용히 사라지고, 틀린 라벨을 붙이면 사용자가
// 잘못 읽는다. 둘 다 데이터가 없는 것보다 나쁘다.
//
// 아래 항목은 2026-07-27 엔켐 실측 응답에서 수집한 필드이며, 뜻이
// 모호한 것은 core 코드에서 근거를 확인했다(tm·inv_prm·lwfr·se 등).
const LABELS = Object.assign(Object.create(null), {
  // ── 공통 식별자
  rcept_no: "접수번호", rcept_dt: "접수일자", corp_code: "고유번호",
  corp_name: "회사명", corp_cls: "법인구분", stock_code: "종목코드",
  stock_name: "종목명", bsns_year: "사업연도", reprt_code: "보고서코드",
  stlm_dt: "결산일", rm: "비고", nm: "성명",

  // ── 기업 개요
  ceo_nm: "대표자", est_dt: "설립일", adres: "주소", hm_url: "홈페이지",
  ir_url: "IR 주소", phn_no: "전화", fax_no: "팩스", acc_mt: "결산월",
  induty_code: "업종코드", corp_name_eng: "영문 회사명",
  jurir_no: "법인등록번호", bizr_no: "사업자등록번호",

  // ── 공시 목록
  flr_nm: "공시제출인", report_nm: "공시명",

  // ── 자금사용 (dart_client._normalize_fund_usage)
  tm: "회차", kind: "구분", year: "연도", flags: "이상 표시",
  pay_de: "납입일", pay_amount: "납입 금액",
  plan_useprps: "계획 용도", plan_amount: "계획 금액",
  real_dtls_cn: "실제 집행 내역", real_dtls_amount: "실제 집행 금액",
  dffrnc_resn: "차이 발생 사유",

  // ── 타법인 출자
  inv_prm: "피출자 법인명", invstmnt_purps: "출자 목적",
  frst_acqs_de: "최초 취득일", frst_acqs_amount: "최초 취득 금액",
  bsis_blce_qy: "기초 수량", bsis_blce_qota_rt: "기초 지분율",
  bsis_blce_acntbk_amount: "기초 장부가액",
  trmend_blce_qy: "기말 수량", trmend_blce_qota_rt: "기말 지분율",
  trmend_blce_acntbk_amount: "기말 장부가액",
  incrs_dcrs_acqs_dsps_qy: "증감 수량",
  incrs_dcrs_acqs_dsps_amount: "증감 금액",
  incrs_dcrs_evl_lstmn: "증감 평가손익",
  recent_bsns_year_fnnr_sttus_tot_assets: "피투자사 총자산",
  recent_bsns_year_fnnr_sttus_thstrm_ntpf: "피투자사 당기순이익",

  // ── 재무제표
  account_nm: "계정과목", fs_nm: "재무제표", sj_nm: "재무제표 구분",
  fs_div: "연결/별도", sj_div: "구분코드", currency: "통화", ord: "순번",
  thstrm_nm: "당기", thstrm_dt: "당기 기간", thstrm_amount: "당기 금액",
  frmtrm_nm: "전기", frmtrm_dt: "전기 기간", frmtrm_amount: "전기 금액",
  bfefrmtrm_nm: "전전기", bfefrmtrm_dt: "전전기 기간",
  bfefrmtrm_amount: "전전기 금액",

  // ── 내부자 지분
  repror: "보고자", source: "출처", relate: "관계", stock_knd: "주식 종류",
  isu_exctv_ofcps: "직위", isu_exctv_rgist_at: "등기 여부",
  isu_main_shrholdr: "주요주주 구분", mxmm_shrholdr_nm: "최대주주명",
  sp_stock_lmp_cnt: "소유 주식수", sp_stock_lmp_rate: "소유 비율",
  sp_stock_lmp_irds_cnt: "증감 주식수", sp_stock_lmp_irds_rate: "증감 비율",
  bsis_posesn_stock_co: "기초 소유 주식수",
  bsis_posesn_stock_qota_rt: "기초 지분율",
  trmend_posesn_stock_co: "기말 소유 주식수",
  trmend_posesn_stock_qota_rt: "기말 지분율",
  posesn_stock_co: "소유 주식수", qota_rt: "지분율",
  change_on: "변동일", change_cause: "변동 원인",
  change_qy_acqs: "취득 수량", change_qy_dsps: "처분 수량",
  change_qy_incnr: "기타 증감 수량",
  bsis_qy: "기초 수량(자기주식)", trmend_qy: "기말 수량(자기주식)",
  acqs_mth1: "취득방법1", acqs_mth2: "취득방법2", acqs_mth3: "취득방법3",

  // ── 배당 (thstrm/frmtrm/lwfr = 당기/전기/전전기)
  se: "항목", thstrm: "당기 값", frmtrm: "전기 값", lwfr: "전전기 값",

  // ── 채무·감사
  total: "합계", by_kind: "종류별", equity_ratio: "자기자본 대비",
  maturity_1y_share: "1년 내 만기 비중",
  opinions: "감사의견", auditor_changes: "감사인 교체",
  independence_warnings: "독립성 경고",
  major_holders: "최대주주", bulk_holders: "5% 이상 대량보유",

  // ── 공시 원문
  text: "본문", files: "파일 목록", main_file: "주 파일",
  char_count: "글자 수", truncated: "잘림",
});
```

**`Object.create(null)`로 만드는 이유:** `LABELS["toString"]`이 `Object.prototype`의 함수를 돌려주면 열 제목이 함수 객체가 된다. SE-4b에서 실제로 잡힌 버그다.

- [ ] **Step 4: `formatValue` 구현**

```js
// 금액으로 읽어야 하는 필드. 여기 없는 필드의 큰 수는 건드리지 않는다 —
// `corp_code`("01011526")를 억으로 바꾸면 거짓말이 된다.
const AMOUNT_FIELDS = new Set([
  "pay_amount", "plan_amount", "real_dtls_amount",
  "frst_acqs_amount", "bsis_blce_acntbk_amount", "trmend_blce_acntbk_amount",
  "incrs_dcrs_acqs_dsps_amount", "incrs_dcrs_evl_lstmn",
  "recent_bsns_year_fnnr_sttus_tot_assets",
  "recent_bsns_year_fnnr_sttus_thstrm_ntpf",
  "thstrm_amount", "frmtrm_amount", "bfefrmtrm_amount", "total",
]);

// 날짜로 읽어야 하는 필드. **접수번호는 14자리라 여기 들어가면 안 된다.**
const DATE_FIELDS = new Set([
  "rcept_dt", "est_dt", "pay_de", "stlm_dt", "frst_acqs_de", "change_on",
]);

/** 금액을 한국식 단위로 줄인다. 0과 음수를 잃지 않는다. */
function formatAmount(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return String(n);
  const sign = v < 0 ? "-" : "";
  const abs = Math.abs(v);
  if (abs >= 1e12) return sign + (abs / 1e12).toFixed(1).replace(/\.0$/, "") + "조";
  if (abs >= 1e8) return sign + (abs / 1e8).toFixed(1).replace(/\.0$/, "") + "억";
  return v.toLocaleString("ko-KR");
}

/** 표시용 문자열. 필드 이름을 봐야 단위를 알 수 있으므로 key를 받는다. */
function formatValue(key, value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  const s = String(value);
  if (AMOUNT_FIELDS.has(key) && /^-?[\d,]*\d$/.test(s)) {
    return formatAmount(s.replace(/,/g, ""));
  }
  if (DATE_FIELDS.has(key) && /^\d{8}$/.test(s)) {
    return s.slice(0, 4) + "." + s.slice(4, 6) + "." + s.slice(6, 8);
  }
  return s;
}
```

`module.exports`에 `formatValue`·`formatAmount`·`AMOUNT_FIELDS`·`DATE_FIELDS`를 추가한다.

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/se/test_se_app_js.py -v`

- [ ] **Step 6: 커밋**

```bash
git add docs/tool/se/app.js tests/se/test_se_app_js.py
git commit -m "feat(se): DART 필드 한국어 라벨 사전과 금액·날짜 포맷터"
```

---

### Task 2: 세로/가로 자동 판단과 상수열 캡션 승격

**Files:**
- Modify: `docs/tool/se/app.js`, `docs/tool/se/ui.js`
- Test: `tests/se/test_se_app_js.py`

**Interfaces:**
- Produces: `tableLayout(records)` → `{orientation: "vertical"|"horizontal", caption: [[라벨, 값]], columns, keys, rows}`

**규칙 (실측 근거):**

| 조건 | 방향 | 근거 |
|---|---|---|
| 레코드 1건 | **세로**(키-값 2열) | `indicators` 1건 49열이 가로라 글자가 쪼개졌다 |
| 레코드 N건 | **가로**(표) | `disclosures` 145건 |

**상수열 승격:** 레코드가 2건 이상이고 **모든 행의 값이 같은 열**은 표에서 빼서 표 위 캡션으로 올린다. `disclosures`의 `corp_code`·`corp_name`·`stock_code`·`corp_cls`가 이 규칙 하나로 사라진다 — 사장님이 지적한 "내가 검색한 회사명이 145줄 반복" 문제가 여기서 해결된다.

**주의:** 캡션으로 올리는 것은 **숨기는 게 아니다.** 값은 표 위에 한 번 표시된다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestTableLayout(unittest.TestCase):
    def test_single_record_is_vertical(self):
        got = run_js('tableLayout([{a:1,b:2,c:3}])')
        self.assertEqual(got["orientation"], "vertical")

    def test_many_records_is_horizontal(self):
        got = run_js('tableLayout([{a:1},{a:2},{a:3}])')
        self.assertEqual(got["orientation"], "horizontal")

    def test_constant_columns_move_to_caption(self):
        got = run_js('tableLayout([{co:"엔켐",n:1},{co:"엔켐",n:2}])')
        self.assertNotIn("co", got["keys"])
        self.assertTrue(any(c[1] == "엔켐" for c in got["caption"]))

    def test_varying_column_stays_in_table(self):
        got = run_js('tableLayout([{co:"엔켐",n:1},{co:"엔켐",n:2}])')
        self.assertIn("n", got["keys"])

    def test_single_record_has_no_caption_promotion(self):
        """1건일 때 모든 열이 '상수'이므로 승격하면 표가 통째로 사라진다."""
        got = run_js('tableLayout([{a:1,b:2}])')
        self.assertEqual(got["caption"], [])
        self.assertEqual(sorted(got["keys"]), ["a", "b"])

    def test_no_data_is_lost_between_caption_and_table(self):
        """어떤 열도 캡션에도 표에도 없으면 데이터가 사라진 것이다."""
        got = run_js('tableLayout([{a:"x",b:1},{a:"x",b:2}])')
        shown = set(got["keys"]) | {c[0] for c in got["caption"]}
        self.assertEqual(shown, {"비고" if False else "a", "b"} - set() | {"a", "b"} - set(),
                         "열이 사라졌습니다")

    def test_vertical_rows_are_label_value_pairs(self):
        got = run_js('tableLayout([{rcept_no:"20260724000552"}])')
        self.assertEqual(got["rows"][0][0], "접수번호")

    def test_values_are_formatted(self):
        got = run_js('tableLayout([{plan_amount:13082000000},{plan_amount:1}])')
        self.assertIn("130.8억", [c for r in got["rows"] for c in r])

    def test_empty_input_is_null(self):
        for expr in ("tableLayout([])", "tableLayout(null)"):
            self.assertIsNone(run_js(expr))
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/se/test_se_app_js.py -k TableLayout -v`
Expected: FAIL — `tableLayout is not defined`

- [ ] **Step 3: 구현**

```js
/** 레코드 목록을 화면에 낼 형태로 바꾼다.
 *
 * 1건이면 세로(키-값), 여러 건이면 가로(표)다. 1건짜리 49열(indicators)을
 * 가로로 펴면 열 하나가 몇 픽셀이 되어 글자가 세로로 쪼개진다.
 */
function tableLayout(records) {
  if (!Array.isArray(records)) return null;
  const rows = records.filter(function (r) { return r && typeof r === "object" && !Array.isArray(r); });
  if (rows.length === 0) return null;

  const keys = [];
  const seen = new Set();
  for (const r of rows) {
    for (const k of Object.keys(r)) if (!seen.has(k)) { seen.add(k); keys.push(k); }
  }
  if (keys.length === 0) return null;

  if (rows.length === 1) {
    // 세로 — 승격할 게 없다. 1건에서는 모든 열이 '상수'라 승격하면 표가 빈다.
    return {
      orientation: "vertical",
      caption: [],
      columns: ["항목", "값"],
      keys: keys,
      rows: keys.map(function (k) { return [label(k), formatValue(k, rows[0][k])]; }),
    };
  }

  // 모든 행이 같은 값인 열은 표 위 캡션으로 올린다. 숨기는 게 아니라
  // 145줄 반복 대신 한 번만 보여주는 것이다.
  const constant = keys.filter(function (k) {
    const first = JSON.stringify(rows[0][k]);
    return rows.every(function (r) { return JSON.stringify(r[k]) === first; });
  });
  const constSet = new Set(constant);
  const bodyKeys = keys.filter(function (k) { return !constSet.has(k); });
  // 전부 상수면 표가 비어버리므로 승격하지 않는다.
  const promote = bodyKeys.length > 0 ? constant : [];
  const finalKeys = bodyKeys.length > 0 ? bodyKeys : keys;

  return {
    orientation: "horizontal",
    caption: promote.map(function (k) { return [label(k), formatValue(k, rows[0][k])]; }),
    columns: finalKeys.map(label),
    keys: finalKeys,
    rows: rows.map(function (r) {
      return finalKeys.map(function (k) { return formatValue(k, r[k]); });
    }),
  };
}
```

`module.exports`에 `tableLayout`을 추가한다.

- [ ] **Step 4: `ui.js`가 `tableLayout`을 쓰도록 교체**

`tableEl`이 `caption`을 표 위 `<div class="cap">`로 그리고, `orientation`에 따라 헤더 유무를 바꾼다. `rcept_no` 열 클릭(공시 패널)은 `keys.indexOf("rcept_no")`로 계속 찾는다 — **세로일 때는 값 셀 위치가 다르므로 두 경우를 모두 처리해야 한다.**

- [ ] **Step 5: 통과 확인 후 커밋**

```bash
git add docs/tool/se tests/se/test_se_app_js.py
git commit -m "feat(se): 1건은 세로·N건은 가로, 반복되는 열은 캡션으로"
```

---

### Task 3: 넓은 표 접기

**Files:**
- Modify: `docs/tool/se/app.js`, `docs/tool/se/ui.js`
- Test: `tests/se/test_se_app_js.py`

**대상은 하나다.** `insider_timeline`이 상수열을 빼고도 **36열**이다. 나머지 섹션은 Task 2로 12열 이하가 된다.

**규칙:** 열이 **12개를 넘으면** 앞 열부터 12개만 표시하고 나머지는 접는다. 접힌 열은 행을 펼치면 세로로 보인다.

**접는 것이지 없애는 것이 아니다.** 이 구분이 이 계획의 원칙이다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestWideTableFolding(unittest.TestCase):
    _WIDE = "Array.from({length:3},(_,i)=>Object.fromEntries(Array.from({length:20},(_,j)=>['f'+j, i+'-'+j])))"

    def test_visible_columns_are_capped(self):
        got = run_js(f"tableLayout({self._WIDE})")
        self.assertLessEqual(len(got["keys"]), 12)

    def test_folded_columns_are_reported_not_dropped(self):
        got = run_js(f"tableLayout({self._WIDE})")
        self.assertTrue(got["foldedKeys"], "접힌 열 목록이 없습니다")

    def test_every_column_is_either_visible_folded_or_caption(self):
        got = run_js(f"tableLayout({self._WIDE})")
        accounted = set(got["keys"]) | set(got["foldedKeys"]) | {c[0] for c in got["caption"]}
        self.assertEqual(len(accounted), 20, "열이 사라졌습니다")

    def test_narrow_table_folds_nothing(self):
        got = run_js('tableLayout([{a:1,b:2},{a:3,b:4}])')
        self.assertEqual(got["foldedKeys"], [])

    def test_folded_rows_carry_the_hidden_values(self):
        got = run_js(f"tableLayout({self._WIDE})")
        self.assertTrue(got["foldedRows"][0], "접힌 값이 비어 있습니다")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/se/test_se_app_js.py -k WideTable -v`

- [ ] **Step 3: `tableLayout`에 접기 추가**

```js
// 한 화면에서 읽을 수 있는 열 수의 상한. insider_timeline이 상수열을
// 빼고도 36열이라 필요하다. 넘는 열은 **접을 뿐 버리지 않는다.**
const MAX_VISIBLE_COLUMNS = 12;
```

가로 분기에서 `finalKeys`를 `visible`/`folded`로 나누고, `foldedKeys`·`foldedRows`를 결과에 담는다. 세로 분기는 접지 않는다(원래 한 줄에 한 항목이라 넓지 않다).

- [ ] **Step 4: `ui.js`에 펼치기 버튼 추가**

행 끝에 `⋯` 버튼을 두고, 누르면 그 행 아래에 접힌 열이 세로로 펼쳐진다. 버튼 문구는 `"나머지 N개 열"`.

- [ ] **Step 5: 통과 확인 후 커밋**

```bash
git commit -m "feat(se): 12열 넘는 표는 접는다 — 버리지 않고 펼칠 수 있게"
```

---

### Task 4: 특수 형태 섹션 처리

**Files:**
- Modify: `docs/tool/se/app.js`
- Test: `tests/se/test_se_app_js.py`

일반 표 규칙이 통하지 않는 섹션이 실측에서 셋 나왔다.

| 섹션 | 형태 | 처리 |
|---|---|---|
| `executive_roster` | **키가 사람 이름**, 값은 연도 목록 | `[{성명, 재직 연도}]` 레코드 목록으로 변환 |
| `shareholders` | `{major_holders:[], bulk_holders:[]}` | 하위 키마다 소제목 + 표 (기존 `sectionBlocks`가 처리) |
| `audit_history` | `{opinions:[], auditor_changes:[], independence_warnings:[]}` | 동일 |

`executive_roster`만 새 처리가 필요하다. **사람 이름을 열 제목으로 쓰면 임원이 7명일 때 7열짜리 1행 표가 되어 읽을 수 없다.**

- [ ] **Step 1: 실패하는 테스트 작성**

```python
@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestExecutiveRoster(unittest.TestCase):
    _SAMPLE = '{"김기범":["2025","2026"],"박시묵":["2026"]}'

    def test_names_become_rows_not_columns(self):
        got = run_js(f'normalizeRoster({self._SAMPLE})')
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0]["성명"], "김기범")

    def test_years_are_joined_readably(self):
        got = run_js(f'normalizeRoster({self._SAMPLE})')
        self.assertIn("2025", got[0]["재직 연도"])
        self.assertIn("2026", got[0]["재직 연도"])

    def test_year_set_object_form_is_handled(self):
        """연도가 배열이 아니라 객체로 올 수도 있다."""
        got = run_js('normalizeRoster({"김기범":{"2026":true}})')
        self.assertEqual(got[0]["성명"], "김기범")

    def test_non_object_input_is_empty_list(self):
        for expr in ("normalizeRoster(null)", 'normalizeRoster("x")', "normalizeRoster([])"):
            self.assertEqual(run_js(expr), [])

    def test_no_name_is_dropped(self):
        got = run_js('normalizeRoster({"가":[],"나":[],"다":[]})')
        self.assertEqual([r["성명"] for r in got], ["가", "나", "다"])
```

- [ ] **Step 2: 실패 확인 → 구현**

```js
/** 임원현황을 {이름: 연도들} 에서 레코드 목록으로 바꾼다.
 *
 * 이름을 열 제목으로 쓰면 임원 7명일 때 7열짜리 1행 표가 되어 읽을 수
 * 없다. 사람이 행이 되어야 한다.
 */
function normalizeRoster(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.keys(value).map(function (name) {
    const raw = value[name];
    const years = Array.isArray(raw) ? raw
                : (raw && typeof raw === "object") ? Object.keys(raw)
                : (raw === null || raw === undefined) ? [] : [String(raw)];
    return { "성명": name, "재직 연도": years.slice().sort().join(", ") };
  });
}
```

`sectionBlocks`가 `executive_roster` 키를 만나면 `normalizeRoster`를 통과시킨 뒤 일반 표 경로로 보낸다.

- [ ] **Step 3: 통과 확인 후 커밋**

```bash
git commit -m "feat(se): 임원현황은 이름을 행으로 — 열 제목이 사람 이름이면 못 읽는다"
```

---

### Task 5: 2단 레이아웃·좌측 목차·테마 토글

**Files:**
- Modify: `docs/tool/se/index.html`, `docs/tool/se/ui.js`
- Test: `tests/se/test_se_page_assets.py`

**골격을 바꾸는 게 아니다.** 설계 결정(§12)은 "롱스크롤 + 우측 슬라이드 패널"이고, 버린 것은 **탭·별도 섹션**(행위자를 격리시키므로)이었다. **목차는 한 흐름을 유지하므로 그 결정에 걸리지 않는다.**

```
┌──────┬────────────────────────────────┬─ 우측 패널(기존)
│ 목차 │  섹션 A        │  섹션 B        │
│      │  섹션 C        │  섹션 D        │
└──────┴────────────────────────────────┴
```

- 좌측 목차: `position: sticky`, 현재 섹션 표시, 클릭 시 이동
- 본문: 2단 그리드. **넓은 표(가로·12열)는 2단 폭 전체를 쓴다**
- 좁은 화면(≤1100px)에서는 1단으로 접고 목차는 상단 가로 목록으로

**테마 토글:** 기본은 현재의 어두운 화면. 토글 시 라이트. 선택은 `localStorage`(`se_theme`)에 기억한다. CSS 변수 22개에 라이트 값을 대응시키고 `<html data-theme="light">`로 전환한다.

- [ ] **Step 1: 실패하는 테스트 작성 (`tests/se/test_se_page_assets.py`에 추가)**

```python
class TestLayoutAndTheme(unittest.TestCase):
    def test_toc_and_two_column_grid_exist(self):
        html = _sources()["index.html"]
        self.assertIn('id="toc"', html)
        self.assertRegex(html, r"grid-template-columns")

    def test_theme_toggle_is_wired_not_dead(self):
        """SE-4b에서 배선 없는 함수가 두 번 나왔다. 같은 일을 막는다."""
        ui = _sources()["ui.js"]
        body = _extract_function_body(ui, "init")
        self.assertIn("theme", body, "init에서 테마 토글을 배선하지 않습니다")

    def test_theme_choice_is_persisted(self):
        self.assertIn("se_theme", _sources()["app.js"] + _sources()["ui.js"])

    def test_light_theme_overrides_every_dark_variable(self):
        """일부 변수만 덮으면 라이트 모드에서 글자가 안 보인다."""
        html = _sources()["index.html"]
        dark = set(re.findall(r"(--[a-z0-9-]+)\s*:", html.split('[data-theme="light"]')[0]))
        light = set(re.findall(r"(--[a-z0-9-]+)\s*:", html.split('[data-theme="light"]')[1]))
        missing = sorted(v for v in dark if v not in light and not v.startswith("--mono"))
        self.assertEqual(missing, [], f"라이트 모드에 없는 변수: {missing}")

    def test_narrow_screen_falls_back_to_one_column(self):
        self.assertRegex(_sources()["index.html"], r"@media[^{]*max-width")
```

- [ ] **Step 2: 실패 확인 → `index.html`·`ui.js` 구현**

Run: `python -m pytest tests/se/test_se_page_assets.py -k LayoutAndTheme -v`

- [ ] **Step 3: 통과 확인 후 커밋**

```bash
git commit -m "feat(se): 2단 레이아웃·좌측 목차·라이트 모드 토글"
```

---

### Task 6: 공시 원문 최소 가공

**Files:**
- Modify: `docs/tool/se/app.js`, `docs/tool/se/ui.js`
- Test: `tests/se/test_se_app_js.py`

지금 우측 패널의 공시 원문은 **한 덩어리 문단**이다. 원본이 `표머리 | 값 | 값` 형태의 파이프 구분 표를 담고 있는데 그대로 이어 붙어서, 사장님 말씀대로 "고민만 생기는 나열"이 된다.

**최소한의 가공만 한다.** 요약하거나 판정하지 않는다 — 구조를 복원할 뿐이다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestDocumentBlocks(unittest.TestCase):
    def test_pipe_rows_become_a_table_block(self):
        got = run_js(r'documentBlocks("머리말\n| 항목 | 값 |\n| 자본금 | 100 |\n꼬리말")')
        kinds = [b["kind"] for b in got]
        self.assertIn("table", kinds)

    def test_prose_around_tables_is_kept(self):
        got = run_js(r'documentBlocks("머리말\n| a | b |\n꼬리말")')
        texts = " ".join(b.get("text", "") for b in got if b["kind"] == "text")
        self.assertIn("머리말", texts)
        self.assertIn("꼬리말", texts)

    def test_nothing_is_lost(self):
        src = "가나다\n| ㄱ | ㄴ |\n라마바"
        got = run_js(f'documentBlocks({json.dumps(src)})')
        joined = "".join(
            b.get("text", "") + " ".join(" ".join(r) for r in b.get("rows", []))
            for b in got
        )
        for token in ("가나다", "ㄱ", "ㄴ", "라마바"):
            self.assertIn(token, joined, f"{token}이 사라졌습니다")

    def test_plain_text_without_pipes_is_one_text_block(self):
        got = run_js('documentBlocks("파이프 없는 본문")')
        self.assertEqual([b["kind"] for b in got], ["text"])

    def test_empty_input_is_empty_list(self):
        for expr in ('documentBlocks("")', "documentBlocks(null)"):
            self.assertEqual(run_js(expr), [])

    def test_separator_only_rows_are_not_data(self):
        """`|---|---|` 는 구분선이지 데이터가 아니다."""
        got = run_js(r'documentBlocks("| a | b |\n|---|---|\n| 1 | 2 |")')
        table = [b for b in got if b["kind"] == "table"][0]
        self.assertNotIn(["---", "---"], table["rows"])
```

- [ ] **Step 2: 실패 확인 → 구현**

```js
/** 공시 원문을 문단과 표 블록으로 나눈다.
 *
 * **가공은 구조 복원까지만 한다.** 요약하거나 중요도를 매기지 않는다 —
 * 그건 판정이고, 이 도구는 사실만 표기한다(v0.8.5).
 */
function documentBlocks(text) {
  if (!text || typeof text !== "string") return [];
  const blocks = [];
  let prose = [];
  let table = [];

  function flushProse() {
    const t = prose.join("\n").trim();
    if (t) blocks.push({ kind: "text", text: t });
    prose = [];
  }
  function flushTable() {
    if (table.length) blocks.push({ kind: "table", rows: table });
    table = [];
  }

  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trim();
    if (line.indexOf("|") >= 0) {
      const cells = line.split("|").map(function (c) { return c.trim(); })
                        .filter(function (c, i, a) { return !(c === "" && (i === 0 || i === a.length - 1)); });
      // `|---|---|` 는 구분선이지 데이터가 아니다.
      if (cells.length && cells.every(function (c) { return /^:?-{2,}:?$/.test(c); })) continue;
      if (cells.length) { flushProse(); table.push(cells); continue; }
    }
    flushTable();
    prose.push(raw);
  }
  flushTable();
  flushProse();
  return blocks;
}
```

- [ ] **Step 3: `ui.js`의 `openDocPanel`이 블록을 그리도록 교체**

`<pre>` 한 덩어리 대신 `text` 블록은 `<p>`, `table` 블록은 `<table>`로 그린다. **값은 전부 `textContent`.**

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/ -q`

- [ ] **Step 5: 커밋**

```bash
git commit -m "feat(se): 공시 원문을 문단·표로 복원 — 요약이 아니라 구조만"
```

---

### Task 7: 프로덕션 확인

- [ ] **Step 1: 배포 후 자산 경로 확인**

```bash
python -m pytest tests/se/test_se_page_assets.py -k AssetPaths -v
```

배포된 실물도 확인한다 — 파일이 맞다고 배포가 도는 것은 아니다(2026-07-27 실측 교훈).

- [ ] **Step 2: 사람이 브라우저에서 확인**

| 확인 | 통과 기준 |
|---|---|
| `indicators` 섹션 | 세로 목록으로 읽힌다. 글자가 세로로 쪼개지지 않는다 |
| `disclosures` 섹션 | 회사명·종목코드·고유번호가 표 위 캡션에 한 번만 나온다 |
| `fund_usage` 섹션 | `plan_amount`가 `130.8억` 형태로 보인다 |
| `insider_timeline` | 12열까지 보이고 `⋯`로 나머지가 펼쳐진다 |
| `executive_roster` | 임원 이름이 **행**으로 나온다 |
| 공시 원문 패널 | 표가 표로 보인다 |
| 테마 토글 | 라이트에서 글자가 읽힌다. 새로고침해도 유지된다 |
| 목차 | 클릭하면 해당 섹션으로 이동한다 |

---

## 이 계획이 하지 않는 것

- **자금 체인·시계열 레인(스펙 ②③)** — SE-4d로 남긴다. 읽을 수 있는 화면이 먼저다
- **행위자 조회 캐시** — 지금 Notion 왕복으로 7초 걸린다. SE-1의 Supabase 캐시를 물리면 되지만 별건이다
- **요약·중요도 판정** — 원문 가공은 구조 복원까지다. 요약은 판정이고, 이 도구는 사실만 표기한다
