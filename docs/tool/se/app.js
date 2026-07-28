"use strict";

// 브라우저에만 남는 값들. 서버에 저장하지 않는다.
const LS_DART_KEY = "se_dart_key";
const LS_SESSION = "se_session";
const LS_JOB = "se_job"; // 진행 중인 분석 작업의 job_id — 상태 자체는
                          // 서버(Postgres)에 있고 브라우저는 이 id만 든다.
const LS_THEME = "se_theme"; // 다크/라이트 선택. 기본은 다크(값이 없거나
                              // "dark")이고, 저장된 값이 "light"일 때만
                              // 라이트로 그린다(ui.js의 applyTheme 참고).

// 이어받기 유효 시간. 이보다 오래된 작업은 새로 시작한다 —
// 며칠 전 작업을 조용히 재개하면 사용자는 새 분석을 받았다고 오해한다.
const RESUME_WINDOW_MS = 12 * 3600 * 1000;

/** 저장된 job_id를 지금 이어받아도 되는지 판정한다.
 *
 * 작업 상태는 Postgres에 있으므로 job_id만 있으면 이어받을 수 있지만,
 * 오래된 job_id를 무한정 이어받으면 사용자는 새 분석을 받았다고 오해한다
 * (며칠 전 결과를 방금 실행한 것처럼 보게 된다). saved가 없거나
 * job_id·saved_at 형태가 예상과 다르면(예: localStorage가 손상되었거나
 * 옛 스키마) 이어받지 않는다 — 모르면 새로 시작하는 쪽이 안전하다.
 */
function resumeTarget(saved, now) {
  const s = saved || {};
  if (typeof s.job_id !== "string" || !s.job_id) return null;
  if (typeof s.saved_at !== "number") return null;
  return (now - s.saved_at) <= RESUME_WINDOW_MS ? s.job_id : null;
}

// registry.STAGE1_SPECS[*].section 과 같은 그룹이다. 서버가 이미 화면
// 그룹을 알고 있으므로 여기서 새로 정하지 않고 그대로 따른다.
//
// "공시 원문 열람"(doc_list)만 예외다 — 이 키는 STAGE1_SPECS에 없다(2단
// `doc:<접수번호>` 섹션들을 addDocListEntry가 한 목록으로 모은 합성 키,
// DOC_LIST_KEY 참고). 여기 없으면 groupTitleFor가 catch-all "기타"로
// 떨어뜨려 본문 맨 끝(다른 어떤 정식 그룹보다도 뒤)으로 밀려난다 —
// design 문서(2026-07-26-risk-viewer-se-design.md §7.1)는 본문 섹션
// 순서에서 "⑦ 공시 원문 열람"을 마지막 정식 섹션으로 정의하므로, 그
// 자리를 그대로 준다(감사·부실 뒤, 아직 "기타"는 아님).
const SECTION_GROUPS = [
  { title: "자금", keys: ["fund_usage", "affiliates", "disclosures"] },
  { title: "재무", keys: ["financials", "indicators"] },
  { title: "지배구조", keys: ["shareholders", "insider_timeline", "executive_roster"] },
  { title: "감사·부실", keys: ["audit_history", "debt_balance", "distress", "dividends"] },
  { title: "공시 원문 열람", keys: ["doc_list"] },
];

function formatCount(n) {
  return Number(n || 0).toLocaleString("ko-KR");
}

// DART 필드명 → 한국어 라벨.
//
// **확신하는 것만 넣는다.** 여기 없는 필드는 원본 키를 그대로 열 이름으로
// 쓴다 — 숨기면 데이터가 조용히 사라지고, 틀린 라벨을 붙이면 사용자가
// 잘못 읽는다. 둘 다 데이터가 없는 것보다 나쁘다.
//
// 아래 항목은 2026-07-27 엔켐 실측 응답에서 수집한 필드이며, 뜻이
// 모호한 것은 core 코드에서 근거를 확인했다(tm·inv_prm·lwfr·se 등).
//
// Object.create(null)로 프로토타입 없는 객체를 만든다 — 일반 객체 리터럴이면
// 키가 "toString"·"constructor"일 때 LABELS[k]가 Object.prototype의 메서드로
// 새어나가 헤더가 함수가 된다(실제로 확인됨). 프로토타입이 없으면 그런 키는
// 그냥 undefined라 아래 label()의 `|| k` 폴백이 정상 동작한다.
const LABELS = Object.assign(Object.create(null), {
  // ── 공통 식별자
  rcept_no: "접수번호", rcept_dt: "접수일자", corp_code: "고유번호",
  corp_name: "회사명", corp_cls: "법인구분", stock_code: "종목코드",
  stock_name: "종목명", bsns_year: "사업연도", reprt_code: "보고서 구분",
  stlm_dt: "결산일", rm: "비고", nm: "성명",

  // ── 기업 개요
  ceo_nm: "대표자", est_dt: "설립일", adres: "주소", hm_url: "홈페이지",
  ir_url: "IR 주소", phn_no: "전화", fax_no: "팩스", acc_mt: "결산월",
  induty_code: "업종코드", corp_name_eng: "영문 회사명",
  jurir_no: "법인등록번호", bizr_no: "사업자등록번호",
  // DART 응답 봉투 필드. 기업 정보는 아니지만 숨기지 않는다 — 응답이
  // 정상이었는지를 사용자가 확인할 수 있어야 한다.
  status: "API 응답 코드", message: "API 응답 메시지",

  // ── 공시 목록
  flr_nm: "공시제출인", report_nm: "공시명",

  // ── 자금사용 (dart_client._normalize_fund_usage)
  // year는 fetch_debt_balance(채무증권 잔액의 기준연도)도 같은 키를 쓴다
  // (dart_client.fetch_debt_balance 반환: {"year": int, ...}) — 두 곳
  // 모두 "이 값을 어느 사업연도로 보고/조회했는지"라는 같은 뜻이라 라벨을
  // 나누지 않는다. fund_usage 쪽 의미(bsns_year × reprt_code 루프의
  // "보고 연도"이지 자금이 실제로 들어오거나 쓰인 시점이 아니다)는
  // ui.js renderSection의 fund_usage 안내문이 별도로 설명한다 — pay_de
  // (아래)와 헷갈리지 않도록 그쪽 라벨을 명확히 하는 쪽을 택했다.
  tm: "회차", kind: "구분", year: "연도", flags: "이상 표시",
  // pay_de는 자금이 "들어온" 날짜(납입일)다 — 계획 대비 실제 집행(plan_
  // amount·real_dtls_amount)이 언제 이뤄졌는지는 이 필드로 알 수 없다.
  // "납입일"만 쓰면 집행일로 오해하기 쉽다(실제 사용자 지적: pay_de
  // 2021.10.26을 보고 "이 날짜에 집행됐다"로 읽었다) — "자금"을 붙여
  // 무엇의 납입인지 명확히 한다. _normalize_fund_usage는 reprt_code(어느
  // 분기 보고인지)를 남기지 않는다(core 수정 불가, 위 브리프 ② 참고) —
  // 있는 필드로 할 수 있는 만큼만 명확히 한다.
  pay_de: "자금 납입일", pay_amount: "납입 금액",
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
  // fs_nm은 섹션 제목 "재무제표"(financials)와 겹치지 않게 구분한다 —
  // 실제 값도 "재무제표"/"연결재무제표" 문자열이라 fs_div(연결/별도)와
  // 의미가 겹치는 필드다.
  account_nm: "계정과목", fs_nm: "재무제표명(개별/연결)", sj_nm: "재무제표 구분",
  fs_div: "연결/별도", sj_div: "구분코드", currency: "통화", ord: "순번",
  thstrm_nm: "당기명", thstrm_dt: "당기 기간", thstrm_amount: "당기 금액",
  frmtrm_nm: "전기명", frmtrm_dt: "전기 기간", frmtrm_amount: "전기 금액",
  // "전전기"는 배당(lwfr)이 이미 쓴다 — 여기는 기수명(예: "제 26 기")이라
  // 뜻이 다르므로 접미어로 구분한다(라벨 충돌 방지).
  bfefrmtrm_nm: "전전기명", bfefrmtrm_dt: "전전기 기간",
  bfefrmtrm_amount: "전전기 금액",

  // ── 내부자 지분 (source 필드의 값 자체 — sourceGroupedBlocks의 표
  // 제목으로 쓴다. dart_client.fetch_insider_timeline이 4개 엔드포인트를
  // 합치며 붙이는 값이라 필드명이 아니라 필드 "값"을 키로 쓴다 — label()이
  // 필드명과 값을 구분하지 않고 같은 사전에서 찾으므로 여기 등록해도 된다.
  //
  // elestock을 "5% 대량보유 이력"이라 부르던 이전 라벨은 틀렸다.
  // dart_client.fetch_bulk_holdings의 docstring이 직접 말한다: elestock은
  // "임원·주요주주 특정증권 소유보고"이고 "등기임원·지배주주 중심"이며,
  // "외부 5% 투자자 진입/이탈은 fetch_major_holdings 사용"이라고 명시한다.
  // 실제 5% 대량보유는 /majorstock.json(fetch_major_holdings)이고, 그
  // 결과는 이 화면에서 shareholders 섹션의 bulk_holders로 따로 들어간다.
  // 필드도 근거다 — isu_exctv_ofcps(임원 직위)·isu_exctv_rgist_at(등기
  // 임원 여부)·isu_main_shrholdr(주요주주 구분)는 5% 대량보유 신고서가
  // 아니라 임원현황 신고서 전용 필드다. 틀린 라벨 탓에 사용자가 지분율
  // 0.00%인 임원(150주·100주 보유)을 보고 "5% 보유자가 지분을 다
  // 팔았나"로 오해했다 — 애초에 5% 보유자가 아니었다.
  //
  // bulk_holders의 "5% 대량보유"와는 뜻 자체가 다르므로 같은 말을 쓰면
  // 안 되고(라벨 충돌 검사 test_no_label_collides_with_a_different_raw_key
  // 도 같은 문자열을 막는다), elestock이 전체 이력을 반환한다는 사실
  // (fetch_insider_timeline 주석)은 "이력"으로 남긴다.
  elestock: "임원·주요주주 소유보고 이력", hyslr: "최대주주 현황",
  hyslr_chg: "최대주주 변동현황", exec_treasury: "임원·주요주주 자기주식",

  // ── 내부자 지분
  repror: "보고자", source: "출처", relate: "관계", stock_knd: "주식 종류",
  isu_exctv_ofcps: "직위", isu_exctv_rgist_at: "등기 여부",
  isu_main_shrholdr: "주요주주 구분", mxmm_shrholdr_nm: "최대주주명",
  // 출자(affiliates)의 "기초/기말 지분율"과 이름이 겹치지 않게 접두어를
  // 붙인다. 같은 라벨이 두 필드에 걸리면 열을 구분할 수 없다.
  sp_stock_lmp_cnt: "특정증권 소유 주식수", sp_stock_lmp_rate: "특정증권 소유 비율",
  sp_stock_lmp_irds_cnt: "특정증권 증감 주식수",
  sp_stock_lmp_irds_rate: "특정증권 증감 비율",
  bsis_posesn_stock_co: "기초 소유 주식수",
  bsis_posesn_stock_qota_rt: "기초 소유 지분율",
  trmend_posesn_stock_co: "기말 소유 주식수",
  trmend_posesn_stock_qota_rt: "기말 소유 지분율",
  posesn_stock_co: "소유 주식수", qota_rt: "지분율",
  change_on: "변동일", change_cause: "변동 원인",
  change_qy_acqs: "취득 수량", change_qy_dsps: "처분 수량",
  change_qy_incnr: "기타 증감 수량",
  bsis_qy: "기초 수량(자기주식)", trmend_qy: "기말 수량(자기주식)",
  acqs_mth1: "취득방법1", acqs_mth2: "취득방법2", acqs_mth3: "취득방법3",

  // ── 배당 (thstrm/frmtrm/lwfr = 당기/전기/전전기)
  se: "항목", thstrm: "당기 값", frmtrm: "전기 값", lwfr: "전전기",

  // ── 채무·감사
  total: "합계", by_kind: "종류별 잔액", equity_ratio: "자기자본 대비",
  maturity_1y_share: "1년 내 만기 비중",
  // by_kind[종류] = {total, maturity_under_1y} (dart_client.fetch_debt_balance).
  // maturity_1y_share(비중, %)와는 다른 필드다 — 이쪽은 금액.
  maturity_under_1y: "1년 이내 만기 금액",
  // normalizeDebtByKind가 by_kind(dict)를 레코드로 뒤집을 때 쓰는 열
  // 이름이다. "종류"만 쓰면 흔해서 다른 필드가 나중에 같은 라벨을 쓸 때
  // 충돌하기 쉽다("주식 종류"·"종류별 잔액"과 겹치지 않게 접두어를 둔다).
  debt_kind: "채무 종류",
  opinions: "감사의견", auditor_changes: "감사인 교체",
  independence_warnings: "감사인 독립성 경고",
  major_holders: "최대주주", bulk_holders: "5% 대량보유",

  // ── 공시 원문
  text: "본문", files: "파일 목록", main_file: "주 파일",
  char_count: "글자 수", truncated: "잘림",

  // ── 종류별 잔액(채무증권) dict-of-lists 하위 키
  corporate_bond: "회사채", short_term_bond: "단기사채",
  commercial_paper: "기업어음", new_capital: "신종자본증권",
  cnd_capital: "조건부자본증권",

  // ── SECTION_GROUPS/registry.STAGE1_SPECS의 1단 섹션 키. ui.js의
  // sectionHolder()가 h2 제목에 label()을 쓴다 — 여기 없으면 원본 키
  // (예: "fund_usage")가 그대로 제목이 된다(숨기지 않는다, 위 label()
  // 계약과 동일).
  company_info: "기업 개요",
  disclosures: "공시 목록",
  fund_usage: "자금 사용 내역",
  affiliates: "타법인 출자현황",
  financials: "재무제표",
  indicators: "주요 재무지표",
  shareholders: "주주 현황",
  insider_timeline: "내부자 지분 변동",
  executive_roster: "임원 현황",
  audit_history: "감사의견 이력",
  debt_balance: "채무증권 잔액",
  distress: "부실 징후",
  dividends: "배당",

  // ── doc: 섹션을 본문에서 모으는 목록(Task 2). DOC_LIST_KEY와 같은 값.
  doc_list: "공시 원문 목록",
});

/** 키 → 한국어 라벨. 없으면 원본 키 그대로(숨기지 않는다). */
function label(k) {
  return LABELS[k] || k;
}

// 금액으로 읽어야 하는 필드. 여기 없는 필드의 큰 수는 건드리지 않는다 —
// `corp_code`("01011526")를 억으로 바꾸면 거짓말이 된다.
const AMOUNT_FIELDS = new Set([
  "pay_amount", "plan_amount", "real_dtls_amount",
  "frst_acqs_amount", "bsis_blce_acntbk_amount", "trmend_blce_acntbk_amount",
  "incrs_dcrs_acqs_dsps_amount", "incrs_dcrs_evl_lstmn",
  "recent_bsns_year_fnnr_sttus_tot_assets",
  "recent_bsns_year_fnnr_sttus_thstrm_ntpf",
  "thstrm_amount", "frmtrm_amount", "bfefrmtrm_amount", "total",
  "maturity_under_1y",
]);

// 날짜로 읽어야 하는 필드. **접수번호는 14자리라 여기 들어가면 안 된다.**
const DATE_FIELDS = new Set([
  "rcept_dt", "est_dt", "pay_de", "stlm_dt", "frst_acqs_de", "change_on",
]);

// 보고서 코드 → 사람이 읽는 한국어. dart_client.py의 _REPORT_CODES 주석과
// 같은 값이다("보고서 코드: 11011=사업보고서, 11012=반기, 11013=1분기,
// 11014=3분기"). reprt_code는 이 서비스를 만드는 사람에게나 익숙한 내부
// 코드일 뿐 값 자체가 사용자에게 의미가 없다(사용자 지적: "보고서코드
// 같은건 이걸 만드는 우리는 쓰지만 이용자에게는 필요없는 정보야") —
// 다만 **정보 자체(어느 시점 보고인지)는 지우지 않는다**(fund_usage가
// 바로 이 정보가 없어서 반복 행을 설명하지 못하는 사례다, 위 LABELS의
// year·pay_de 주석 참고) — 같은 정보를 사람이 읽을 말로만 바꾼다. 여기
// 없는 코드(예상 밖 값)는 formatValue가 원본 그대로 보여준다(label()과
// 같은 "모르면 숨기지 않는다" 계약).
const REPRT_CODE_LABELS = Object.assign(Object.create(null), {
  "11011": "사업보고서", "11012": "반기보고서",
  "11013": "1분기보고서", "11014": "3분기보고서",
});

/** 금액을 한국식 단위로 줄인다. 0과 음수를 잃지 않는다. */
function formatAmount(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return String(n);
  const sign = v < 0 ? "-" : "";
  const abs = Math.abs(v);
  if (abs >= 1e12) return sign + (abs / 1e12).toFixed(1).replace(/\.0$/, "") + "조";
  if (abs >= 1e8) {
    const eok = (abs / 1e8).toFixed(1).replace(/\.0$/, "");
    // 반올림 결과가 "10000"(억)이면 1조 문턱을 넘은 것이다. 999999999999처럼
    // 1e12 바로 아래 값은 억 단위로는 반올림 후 "10000억"이 되는데, 거짓은
    // 아니지만 "1조"가 자연스럽다 — 단위를 다시 계산해 갈아탄다.
    if (eok === "10000") {
      return sign + (abs / 1e12).toFixed(1).replace(/\.0$/, "") + "조";
    }
    return sign + eok + "억";
  }
  return v.toLocaleString("ko-KR");
}

/** 표시용 문자열. 필드 이름을 봐야 단위를 알 수 있으므로 key를 받는다. */
function formatValue(key, value) {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) {
    // 빈 배열을 JSON.stringify로 "[]"라고 그대로 보여주면 무슨 뜻인지
    // 알 수 없다(예: fund_usage의 flags: []가 캡션에 "이상 표시: []"로
    // 뜨던 문제) — 숨기지 않고 "없음"으로 명확히 말한다. 원소가 있으면
    // JSON 배열 표기 대신 쉼표로 이어 사람이 읽기 쉽게 한다(원소가
    // 객체면 그 원소만 JSON으로 남긴다 — 배열 자체를 통째로 뭉개지 않는다).
    if (value.length === 0) return "없음";
    return value.map(function (v) {
      return (v && typeof v === "object") ? JSON.stringify(v) : String(v);
    }).join(", ");
  }
  if (typeof value === "object") return JSON.stringify(value);
  const s = String(value);
  // reprt_code 값 자체를 사람이 읽는 말로 바꾼다(위 REPRT_CODE_LABELS
  // 주석 참고) — corp_code·corp_cls(아래 HIDDEN_ID_KEYS)처럼 지우는 게
  // 아니라, 이 필드는 값을 그대로 두면 오히려 뜻이 없는 내부 코드라서
  // 바꾼다.
  if (key === "reprt_code" && Object.prototype.hasOwnProperty.call(REPRT_CODE_LABELS, s)) {
    return REPRT_CODE_LABELS[s];
  }
  if (AMOUNT_FIELDS.has(key) && /^-?[\d,]*\d$/.test(s)) {
    return formatAmount(s.replace(/,/g, ""));
  }
  if (DATE_FIELDS.has(key)) {
    if (/^\d{8}$/.test(s)) {
      return s.slice(0, 4) + "." + s.slice(4, 6) + "." + s.slice(6, 8);
    }
    // insider_timeline의 rcept_dt 실측(field-inventory)은 "2026-04-15"처럼
    // 하이픈이 있는 10자 문자열이다. 이전에는 8자리 숫자 분기만 있어 이
    // 형태가 그대로(하이픈인 채) 표에 남았는데, 같은 값을 축 라벨로 쓰는
    // 차트(axisLabel)는 하이픈도 "."으로 바꾸므로 표와 차트가 같은 값을
    // 두 가지 표기로 보여줬다(리뷰 지적 ③). axisLabel과 같은 정규식·같은
    // 변환으로 맞춘다 — 표기를 하나로 통일하는 것이지 새 규칙을 만드는
    // 것이 아니다.
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
      return s.replace(/-/g, ".");
    }
  }
  return s;
}

function cell(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** 값을 레코드 배열로 정규화한다. 배열이면 그대로(비객체 항목은 "값" 한
 *  칸에 감싸서 보존), 객체면 1건짜리 배열로, 스칼라면 1건짜리 배열로
 *  감싼다. 표로 만들 것 자체가 없으면(빈 배열·빈 객체·null·undefined)
 *  null을 돌려준다.
 *
 *  sectionBlocks가 tableLayout에 넘기기 전에 쓰는 정규화 로직이다(비객체
 *  항목 보존은 tableLayout 자체도 계약으로 갖고 있다 — 아래 tableLayout
 *  주석 참고, 방어가 호출부에만 있으면 새 호출부가 다시 놓친다). 이전에는
 *  리스트 안 비객체 항목을 조용히 걸러냈고(흔적 없이 사라짐), 스칼라
 *  값 자체는 무조건 null이라 화면이 "표시할 데이터가 없습니다"로
 *  잘못 말했다 — 데이터가 있는데 없다고 하는 것과, 표로 만들 수 없어서
 *  없다고 하는 것은 다르다. */
function toRecords(value) {
  if (value === null || value === undefined) return null;

  let records;
  if (Array.isArray(value)) records = value;
  else if (typeof value === "object") records = [value];
  else records = [value]; // 문자열·숫자 등 스칼라 자체 — 아래서 레코드로 감싼다

  records = records.map(function (r) {
    return (r && typeof r === "object" && !Array.isArray(r)) ? r : { "값": r };
  });
  return records.length === 0 ? null : records;
}

/** 레코드 목록을 화면에 낼 형태로 바꾼다.
 *
 * 1건이면 세로(키-값), 여러 건이면 가로(표)다. 1건짜리 레코드가 필드
 * 수십 개면 가로로 펴는 순간 열 하나가 몇 픽셀이 되어 글자가 세로로
 * 쪼개진다 — 예전에는 indicators(주요 재무지표, 1건 49열)가 이 경로로
 * 왔지만, SE-4h부터 분류(수익성·안정성·성장성·활동성)를 보존한 행
 * 목록으로 바뀌어 이 경로 자체를 타지 않는다(ui.js의 renderSection이
 * key === "indicators"를 sectionBlocks보다 먼저 가로채 indicatorBlocks로
 * 직접 그린다 — 아래 flatKeys 분기 주석도 같은 이유로 갱신했다).
 *
 * 비객체 항목(문자열 등)을 조용히 버리지 않는 것은 호출부의 책임이 아니라
 * 이 함수의 계약이다 — sectionBlocks는 이미 toRecords로 감싸서 넘기지만,
 * 그 방어가 호출부에만 있으면 새 호출부가 다시 놓친다(전에 실제로 그랬다:
 * 리스트 안 문자열 항목이 필터로 걸러져 흔적 없이 사라졌다). toRecords와
 * 같은 감싸기 규칙을 여기서도 한 번 더 적용해, tableLayout 하나만 불러도
 * 안전하다.
 */
function tableLayout(records, markedKeys) {
  if (!Array.isArray(records)) return null;
  const rows = records.map(function (r) {
    return (r && typeof r === "object" && !Array.isArray(r)) ? r : { "값": r };
  });
  if (rows.length === 0) return null;

  const keys = [];
  const seen = new Set();
  for (const r of rows) {
    for (const k of Object.keys(r)) if (!seen.has(k)) { seen.add(k); keys.push(k); }
  }
  if (keys.length === 0) return null;

  if (rows.length === 1) {
    // 세로 — 승격할 게 없다. 1건에서는 모든 열이 '상수'라 승격하면 표가 빈다.
    // columns(["항목","값"])는 일부러 안 넣는다 — ui.js가 세로 표에는
    // 헤더 행을 그리지 않는다(각 행이 이미 [라벨, 값]이라 "항목/값" 헤더는
    // 열 제목과 데이터 사이에 낀 군더더기일 뿐이다). 안 쓰는 필드를
    // 반환값에 남기면 "계산은 했는데 어디서도 그리지 않는" 죽은 출력이 된다.
    return {
      orientation: "vertical",
      caption: [],
      keys: keys,
      rows: keys.map(function (k) { return [label(k), formatValue(k, rows[0][k])]; }),
      // 재무 금액처럼 억·조 단위로 줄인 값은 원 단위 정확한 값을 잃는다 —
      // ui.js가 AMOUNT_FIELDS 열에서 이 원본 값을 title(마우스 오버)로
      // 보여줄 수 있도록 표시용 값과 나란히 남긴다.
      raw: keys.map(function (k) { return cell(rows[0][k]); }),
      // 세로는 원래 한 줄에 한 항목이라 넓지 않다 — 접지 않는다. 가로와
      // 반환 모양을 맞추기 위해 빈 배열로 채운다(ui.js가 undefined 분기를
      // 따로 두지 않아도 되게).
      foldedKeys: [],
      foldedRows: [],
    };
    // 세로에서는 rows[i][0]이 라벨, rows[i][1]이 값이다. 가로와 구조가
    // 다르므로 ui.js의 rcept_no 클릭 배선이 두 경우를 모두 처리해야 한다.
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

  // insider_timeline(상수열 제외 36열)처럼 MAX_VISIBLE_COLUMNS를 넘으면
  // 뒤쪽 열을 접는다 — 버리는 게 아니라 ui.js가 행마다 펼칠 수 있게
  // foldedKeys·foldedRows로 함께 돌려준다(splitVisibleFolded 주석 참고).
  const split = splitVisibleFolded(finalKeys, markedKeys);
  const visibleKeys = split.visible;
  const foldedKeys = split.folded;

  return {
    orientation: "horizontal",
    // rcept_no가 모든 행에서 같으면(affiliates·financials 실측 — 27줄·
    // 30줄 전부 같은 접수번호) 이 열도 여기(캡션)로 승격돼 finalKeys(표
    // 본문 열)에서 빠진다 — ui.js가 캡션의 key로도 rcept_no를 찾아 공시
    // 원문 패널을 열 수 있어야 한다(그러지 않으면 이 섹션들에서는 패널이
    // 도달 불가능해진다). key를 라벨·값과 나란히 남기는 이유는 toTable이
    // 남기던 것과 같다 — ui.js가 "이 항목이 rcept_no인가"를 한국어
    // 라벨로 추측하지 않고 원본 키로 정확히 찾게 하기 위해서다.
    caption: promote.map(function (k) {
      return { key: k, label: label(k), value: formatValue(k, rows[0][k]) };
    }),
    columns: visibleKeys.map(label),
    keys: visibleKeys,
    rows: rows.map(function (r) {
      return visibleKeys.map(function (k) { return formatValue(k, r[k]); });
    }),
    // 세로와 같은 이유(위 raw 주석 참고) — 가로는 셀마다 있으므로 rows와
    // 같은 모양([행][열])의 원본 값 행렬이다.
    raw: rows.map(function (r) {
      return visibleKeys.map(function (k) { return cell(r[k]); });
    }),
    // 접힌 열의 원본 키 목록 — 개수 표시("나머지 N개 열")와 "열이
    // 사라지지 않았다"를 확인하는 용도(keys∪foldedKeys∪caption이
    // finalKeys 전체를 덮어야 한다).
    foldedKeys: foldedKeys,
    // 행마다 접힌 열을 [라벨, 값] 쌍의 배열로 미리 만들어 둔다 — ui.js가
    // 펼치기 버튼을 누르면 이 배열을 세로로 그린다(세로 표의 rows와
    // 같은 [라벨, 값] 모양이라 별도 렌더 분기를 새로 만들지 않아도 된다).
    foldedRows: rows.map(function (r) {
      return foldedKeys.map(function (k) { return [label(k), formatValue(k, r[k])]; });
    }),
  };
}

// 한 화면에서 읽을 수 있는 열 수의 상한. insider_timeline이 상수열을
// 빼고도 36열이라 필요하다. 넘는 열은 **접을 뿐 버리지 않는다** — ui.js가
// 행마다 "나머지 N개 열" 버튼으로 펼칠 수 있게 한다.
const MAX_VISIBLE_COLUMNS = 12;

// 접기로 밀려나면 안 되는 열. ui.js의 tableEl()은 오직
// table.keys.indexOf("rcept_no")로만 공시 원문 패널을 여는 셀을 찾는다
// (앞서 상수열 캡션 승격이 이 열을 빼버려 affiliates·financials에서
// 패널이 통째로 죽었던 사고와 같은 부류) — 앞에서부터 단순히 12개만
// 자르면 insider_timeline처럼 rcept_no가 13번째 이후에 나타나는 실측
// 순서에서 똑같은 사고가 반복된다.
const ALWAYS_VISIBLE_KEYS = ["rcept_no"];

/** finalKeys(캡션 승격 이후 남은 열)를 visible/folded로 나눈다.
 *
 * MAX_VISIBLE_COLUMNS 이하면 전부 visible이다(접을 필요가 없다). 넘으면
 * ALWAYS_VISIBLE_KEYS에 있는 열을 우선 확보하고, 남은 자리를 원래 순서
 * 그대로 앞에서부터 채운다 — essential 열이 뒤로 밀려 있었어도 제자리
 * (원래 열 순서)에서 보이도록 순서 자체는 다시 섞지 않는다.
 *
 * `markedKeys`(선택 인자, markedColumnKeys()가 만든 키 목록/Set)에 있는
 * 열도 ALWAYS_VISIBLE_KEYS와 같은 자격으로 확보한다. **강조는 "눈에 띄게"
 * 하려고 붙이는 것인데, 그 열이 접히면 행마다 버튼을 눌러야 보인다** —
 * 실측(엔켐 affiliates 20열)에서 59개 강조 중 56개가 접힌 열에 있었고,
 * 범례만 세 규칙을 말하고 화면에는 강조가 3개뿐이었다(범례와 화면이
 * 어긋나는 것 자체가 사실 왜곡이다). rcept_no가 접혀 공시 원문 패널이
 * 통째로 죽었던 사고(위 ALWAYS_VISIBLE_KEYS 주석)와 같은 부류다.
 *
 * 열 예산(MAX_VISIBLE_COLUMNS)은 그대로다 — 확보한 열만큼 나머지 자리가
 * 줄어들 뿐 표가 무한정 넓어지지 않는다. */
function splitVisibleFolded(finalKeys, markedKeys) {
  if (finalKeys.length <= MAX_VISIBLE_COLUMNS) {
    return { visible: finalKeys, folded: [] };
  }
  const keep = markedKeys instanceof Set
    ? markedKeys
    : new Set(Array.isArray(markedKeys) ? markedKeys : []);
  const essential = finalKeys.filter(function (k) {
    return ALWAYS_VISIBLE_KEYS.indexOf(k) !== -1 || keep.has(k);
  });
  const essentialSet = new Set(essential);
  const budget = Math.max(MAX_VISIBLE_COLUMNS - essential.length, 0);
  const rest = finalKeys
    .filter(function (k) { return !essentialSet.has(k); })
    .slice(0, budget);
  const restSet = new Set(rest);
  const visible = finalKeys.filter(function (k) {
    return restSet.has(k) || essentialSet.has(k);
  });
  const visibleSet = new Set(visible);
  const folded = finalKeys.filter(function (k) { return !visibleSet.has(k); });
  return { visible: visible, folded: folded };
}

function isPlainObject(v) {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

/** DART가 "이 칸에 보고할 실데이터가 없다"는 뜻으로 관행적으로 쓰는 표기.
 *
 *  실측(task-6, 2026-07-28 — 엔켐·삼성전자 hyslrChgSttus·tesstkAcqsDspsSttus를
 *  bsns_year=2025·reprt_code=11011로 직접 호출해 대조): 두 회사 모두 API는
 *  status "000"(정상)을 주지만, 그 분기에 보고할 변동·거래가 없으면
 *  실데이터 필드 값이 null도 빈 문자열도 아니라 **문자열 "-"** 그 자체로
 *  채워져 온다(엔켐 hyslrChgSttus 1건 — change_on·change_cause·qota_rt 등
 *  6개 필드 전부 "-". 삼성전자도 같은 엔드포인트에서 같은 모양이 나왔다 —
 *  DART 쪽 관행이지 우리 필드 파싱 오류가 아니다). formatValue는 이 값을
 *  그대로 "-"로 보여줘 옛 dropAllEmptyColumns(빈 문자열 기준)가 걸러내지
 *  못했고, 그 결과 "전부 -"인 행이 실데이터가 있는 것처럼 표에 남아
 *  사용자가 "무슨 의미인지 알 수 없다"고 지적한 원인이 됐다. null·빈
 *  문자열도 같은 뜻이므로 하나의 판정 기준으로 합친다.
 */
function isNoDataMarker(v) {
  if (v === null || v === undefined) return true;
  if (typeof v !== "string") return false;
  const t = v.trim();
  return t === "" || t === "-";
}

/** records(같은 source 그룹) 안에서, 모든 행이 isNoDataMarker인 열을
 *  제거한다. 0과 false는 잃지 않는다 — isNoDataMarker(0)·isNoDataMarker(false)는
 *  둘 다 false다(문자열이 아니므로, 값이 있는 데이터를 조용히 숨기지
 *  않는다는 이 화면의 원칙과 같다). 값이 하나라도 있는 열은 반드시 남는다.
 *
 *  insider_timeline이 대표 사례다(dart_client.fetch_insider_timeline —
 *  elestock·hyslr·hyslr_chg·exec_treasury 4개 엔드포인트를 합친 결과라
 *  레코드마다 자기 엔드포인트 필드만 채우고 나머지는 전부 null이다).
 *  source별로 나눈(sourceGroupedBlocks) 뒤에도 그 그룹 안에서마저 전부
 *  비는 열(분기·연도별 응답 형태 차이, 또는 위 isNoDataMarker의 "-" 등)이
 *  남을 수 있어 한 번 더 걷어낸다.
 */
function dropAllEmptyColumns(records) {
  if (!Array.isArray(records) || records.length === 0) return records;
  const keys = [];
  const seen = new Set();
  for (const r of records) {
    for (const k of Object.keys(r)) if (!seen.has(k)) { seen.add(k); keys.push(k); }
  }
  const emptyKeys = keys.filter(function (k) {
    return records.every(function (r) { return isNoDataMarker(r[k]); });
  });
  if (emptyKeys.length === 0) return records;
  const emptySet = new Set(emptyKeys);
  return records.map(function (r) {
    const out = {};
    for (const k of Object.keys(r)) if (!emptySet.has(k)) out[k] = r[k];
    return out;
  });
}

// 레코드의 정체(어느 회사·어느 접수번호·어느 결산일·어느 보고서인지)를
// 밝힐 뿐, "무슨 일이 있었는지"는 말하지 않는 필드. 값이 있어도 정보가
// 아니다 — task-6 실측(엔켐 hyslrChgSttus 1건)이 정확히 이 모양이었다:
// rcept_no·corp_cls·corp_code·corp_name·stlm_dt·bsns_year·reprt_code만
// 채워지고 나머지는 전부 isNoDataMarker였다. **판단 근거**: 이 목록은
// 브리프가 제시한 후보를 그대로 확정한 것이 아니라, 위 실측 응답과
// field-inventory(docs/superpowers/plans/2026-07-27-se-4c-field-inventory.json)
// 를 직접 대조해 "섹션마다 반복되지만 그 자체로는 사건을 서술하지 않는"
// 필드만 추린 결과다 — 예를 들어 rcept_dt(접수일자)는 여기 넣지 않았다
// (elestock 등 다른 source에서는 "언제 일어난 일인지"를 실제로 서술하는
// 값이라 hyslr_chg·exec_treasury에는 애초에 나타나지도 않는다).
//
// corp_code·corp_cls는 sectionBlocks의 depth-0 omitHiddenIds가 이 함수가
// 불리기 전에 이미 걷어내므로 이 시점엔 보통 안 남아 있지만, 방어적으로
// 함께 둔다(재귀 경로·향후 호출부 변경에도 이 판정이 깨지지 않도록).
const META_ONLY_KEYS = new Set([
  "rcept_no", "corp_cls", "corp_code", "corp_name",
  "stlm_dt", "bsns_year", "reprt_code",
]);

/** records(표 하나로 그려질 레코드 목록, source 필드는 이미 뺀 상태)에
 *  META_ONLY_KEYS 밖의 키가 있고, 그 키들의 값이 모든 레코드에서 전부
 *  isNoDataMarker면 true — "레코드에 식별자·메타 필드만 있고 실데이터가
 *  하나도 없다"는 뜻이다.
 *
 *  "값이 하나라도 있으면 표를 그대로 보여준다" 원칙의 반대쪽을 정확히
 *  판정한다 — 메타 키 밖의 값이 단 하나라도 실데이터면(예: 2026 1분기
 *  최대주주 변동현황의 17.40%·변동사유) false를 돌려줘 표를 그대로
 *  두게 한다. 메타 아닌 키가 아예 없는 레코드(모든 키가 META_ONLY_KEYS)도
 *  "보고할 내용이 없다"와 같은 뜻이라 true다.
 *
 *  특정 섹션 키를 검사하지 않는다 — 값의 모양만 보므로 hyslr_chg·
 *  exec_treasury뿐 아니라 같은 모양(식별자만 채워진 레코드)이 나오는 어떤
 *  source 그룹에도 그대로 동작한다.
 */
function isMetaOnlyRecords(records) {
  if (!Array.isArray(records) || records.length === 0) return false;
  for (const r of records) {
    if (!isPlainObject(r)) return false;
    for (const k of Object.keys(r)) {
      if (META_ONLY_KEYS.has(k)) continue;
      if (!isNoDataMarker(r[k])) return false;
    }
  }
  return true;
}

/** 레코드 전부가 비어 있지 않은 문자열 source 필드를 가지면 true다.
 *
 *  이 조건으로만 sourceGroupedBlocks를 태운다 — "source가 없는 데이터
 *  (다른 섹션)에는 이 분리가 적용되면 안 된다"는 요구사항을 지키는
 *  유일한 문(gate)이다. 일부 레코드만 source를 가지면(예상 밖 응답)
 *  false를 돌려줘 안전하게 단일 표로 폴백한다 — 어중간하게 갈라 데이터를
 *  잃는 쪽보다 낫다.
 */
function recordsHaveSourceField(records) {
  return records.length > 0 && records.every(function (r) {
    return isPlainObject(r) && typeof r.source === "string" && r.source !== "";
  });
}

/** source별로 레코드를 나눠 작은 표 여러 개(제목 + 표)로 만든다.
 *
 *  insider_timeline 실측(field-inventory): 접힌 26개 항목 중 값이 있는
 *  열이 0개인 행이 나왔다 — 4개 엔드포인트를 합친 레코드를 한 표로
 *  그리면 레코드마다 자기 엔드포인트 필드만 채우고 나머지 30여 열은
 *  전부 비어 있기 때문이다. source별로 나누면 각 표가 자기 엔드포인트
 *  필드만 갖게 되어 열 수가 줄고 빈칸이 사라진다(dropAllEmptyColumns가
 *  그 안에서마저 전부 비는 열을 한 번 더 걷어낸다).
 *
 *  그룹 순서는 레코드가 등장하는 순서(첫 등장 기준) 그대로 둔다 — 임의로
 *  재정렬하면 실측 정렬(rcept_dt·bsns_year 내림차순, fetch_insider_timeline
 *  주석 참고)이 흐트러진다.
 */
function sourceGroupedBlocks(records) {
  const order = [];
  const groups = new Map();
  for (const r of records) {
    const s = r.source;
    if (!groups.has(s)) { groups.set(s, []); order.push(s); }
    groups.get(s).push(r);
  }
  const blocks = [];
  for (const s of order) {
    // 그룹 안에서는 source 필드 자체를 뺀다. 값이 그룹 전체에서 같은
    // 한 값(s)뿐이라 tableLayout이 그대로 두면 상수 열로 캡션에 올라가
    // "출처: elestock" 식으로 뜨는데, 표 제목(title = label(s), 예: "5%
    // 대량보유 이력")이 이미 같은 정보를 한국어로 말하고 있다 — 같은
    // 것을 원본 키 값과 한국어 라벨 두 가지로 부르는 표기 불일치였다.
    // 숨기는 게 아니다: 값 자체는 title에 여전히 그대로 남는다.
    const withoutSource = groups.get(s).map(function (r) {
      const copy = Object.assign({}, r);
      delete copy.source;
      return copy;
    });
    const cleaned = dropAllEmptyColumns(withoutSource);
    const t = tableLayout(cleaned);
    // records는 표가 실제로 그린 것과 같은 레코드(source 제거·빈 열 제거
    // 반영 후)를 그대로 싣는다 — 다음 태스크(차트)가 이 레코드로 그리므로
    // 표와 다른 값을 보여주면 안 된다.
    if (t) {
      const block = { title: label(s), table: t, records: cleaned };
      // task-6: 표는 지우지 않는다(접수번호로 원문을 직접 열어 확인할 수
      // 있어야 한다 — 우리 판단이 틀렸을 때의 검증 경로이기도 하다). 다만
      // 남은 열이 식별자·메타뿐이면(isMetaOnlyRecords) 그 사실 자체를
      // 문구로 알린다 — "이상 없음"·"정상" 같은 판정 어휘가 아니라
      // "보고된 내역이 없다"는 사실만 말한다(v0.8.5 원칙).
      if (isMetaOnlyRecords(cleaned)) {
        block.note = "해당 기간에 보고된 내역이 없습니다.";
      }
      blocks.push(block);
    }
  }
  return blocks;
}

// 표 셀 하나(max-width:280px)에 욱여넣기엔 너무 긴 문자열의 기준. 공시
// 원문(`doc:` 섹션의 text, 최대 8000자)이 대표 사례 — 다음 태스크가 이런
// 값을 우측 패널로 옮길 예정이니, 여기서는 표에 밀어넣지만 않으면 된다.
const LONG_TEXT_THRESHOLD = 200;

function isLongText(v) {
  return typeof v === "string" && v.length > LONG_TEXT_THRESHOLD;
}

// sectionBlocks의 재귀 깊이 상한. 값은 서버 응답의 JSON.parse 산물이라
// JSON 자체엔 순환 참조가 없지만, 병적으로 깊은 중첩(또는 예상 밖 응답
// 형태)이 오면 재귀가 스택을 태우고, 그러면 analyze()의 폴링 루프가
// (b)와 같은 경로로 예외를 삼키며 조용히 멈춘다. 실제 DART 응답 중첩
// 깊이(2~3단)보다 넉넉히 크게 잡는다.
const MAX_SECTION_DEPTH = 20;

/** 임원현황을 {이름: 연도들} 에서 레코드 목록으로 바꾼다.
 *
 * fetch_executive_roster(dart_client.py)는 {임원명: {연도}}(set)를 돌려주고,
 * se_server의 _jsonable이 set을 정렬된 list로 낮춰 JSON화한다 — 그 결과
 * 화면에 오는 값은 {"김기범": ["2025","2026"], ...} 형태다. 이름을 열
 * 제목으로 쓰면 임원 7명일 때 7열짜리 1행 표가 되어 읽을 수 없다(실측
 * docs/superpowers/plans/2026-07-27-se-4c-field-inventory.json). 사람이
 * 행이 되어야 한다.
 *
 * 연도 쪽은 배열이 정상 형태지만, 방어적으로 객체(키가 연도인 형태)와
 * 스칼라/null도 흡수한다 — 어느 쪽이 와도 이름 자체는 잃지 않는다.
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

/** debt_balance.by_kind({회사채: {total, maturity_under_1y}, ...})를
 *  레코드 목록으로 바꾼다.
 *
 * dart_client.fetch_debt_balance가 종류를 키로 쓰는 dict를 주므로(레코드
 * 리스트가 아니다) — 일반 재귀 경로(sectionBlocks)에 그대로 맡기면 종류마다
 * 별도 1행 표로 쪼개져 종류를 나란히 비교할 수 없고, chartData가 읽을 x축
 * 필드(종류 이름)도 레코드 안에 없다(정규화 전에는 "종류"가 레코드의 값이
 * 아니라 title로만 존재한다). normalizeRoster와 같은 이유로 종류를 열
 * (debt_kind)로 뒤집어 표 하나 + 차트용 레코드로 만든다.
 *
 * 종류 이름(예: "corporate_bond")은 label()로 미리 한국어로 바꿔 저장한다 —
 * formatValue/tableLayout은 열 **이름**(key)만 label()로 바꾸고 셀 **값**은
 * 그대로 두므로, 표·차트 x축에 실제로 찍히는 문자열(값 자체)을 여기서
 * 바꿔둬야 "corporate_bond"가 그대로 노출되지 않는다.
 */
function normalizeDebtByKind(value) {
  if (!isPlainObject(value)) return [];
  return Object.keys(value).map(function (k) {
    const v = isPlainObject(value[k]) ? value[k] : {};
    return { debt_kind: label(k), total: v.total, maturity_under_1y: v.maturity_under_1y };
  });
}

// 반복되는 "내부용" 회사 식별자. 화면 맨 위 고정 박스(company_info,
// renderCompanyInfo)에 이미 한 번 떠 있다 — 회사명·종목코드와 달리
// corp_code(고유번호)·corp_cls(법인구분)는 "사용자가 지금 검색한 회사
// 자체"를 가리키는 값이라 섹션마다 달라지지 않는다(사용자 지적: "보고서
// 코드 같은건 이걸 만드는 우리는 쓰지만 이용자에게는 필요없는 정보야" —
// 같은 부류로 지목됨).
//
// **판단 근거(이 화면의 "데이터를 숨기지 않는다" 원칙과 충돌하지 않는
// 이유):** 이 두 필드만 예외로 다룬다 — 값이 섹션마다 달라지는 다른
// 어떤 필드도 여기 추가하지 않는다. 회사 식별자는 이미 한 곳(company_
// info)에 정확히 남아 있으므로 다른 모든 섹션에서 매번 반복하는 것은
// 새 정보가 아니라 소음이다(재무제표 30줄, 출자현황 27줄이 전부 같은
// corp_code를 반복해 캡션으로 승격되는 실측이 그 소음의 크기다). "숨기지
// 않는다" 원칙은 **관측 데이터**(신호·금액·이름·날짜처럼 섹션마다 값이
// 달라질 수 있는 사실)를 보호하기 위한 것이지, 조회 대상 자체를 가리키는
// 고정 상수를 모든 표에서 반복하라는 뜻이 아니다.
const HIDDEN_ID_KEYS = new Set(["corp_code", "corp_cls"]);

/** value(어떤 모양이든) 트리 전체에서 HIDDEN_ID_KEYS의 키를 재귀적으로
 *  걷어낸다. 원본은 건드리지 않고 새 값을 돌려준다(원본을 참조로 공유하는
 *  다른 호출부가 있을 수 있어 mutate하지 않는다).
 *
 *  company_info 섹션 자신에는 이 함수를 부르지 않는다(sectionBlocks의
 *  호출부가 게이트한다) — 이 값들이 사용자 눈에 보이는 유일한 자리이기
 *  때문이다. */
function omitHiddenIds(value) {
  if (Array.isArray(value)) {
    return value.map(function (v) { return omitHiddenIds(v); });
  }
  if (isPlainObject(value)) {
    const out = {};
    for (const k of Object.keys(value)) {
      if (HIDDEN_ID_KEYS.has(k)) continue;
      out[k] = omitHiddenIds(value[k]);
    }
    return out;
  }
  return value;
}

// 최대주주 현황(major_holders)에 섞여 오는 합계 행의 이름 값. dart_client.
// fetch_affiliate_investments가 같은 이유로 같은 값 집합을 걸러내는 선례가
// 있다("합계 행('계'/'합계')은 제거하고 반환" — docstring). 그쪽은 core라
// 아예 제거해 반환하지만, major_holders는 core(fetch_shareholder_status)가
// 원본 그대로(합계 행 포함) 주므로 **여기서는 지우지 않는다** — 사람 목록
// 사이에 뒤섞여 읽기 힘든 게 문제이지 합계 자체가 문제가 아니다(브리프
// 원칙: "합계를 없애라는 게 아니다"). splitAggregateRows가 같은 표 안에서
// 사람 행과 합계 행을 분리해 각자 제자리(사람 목록 / 합계 소계)에 둔다.
const AGGREGATE_ROW_NAMES = new Set(["계", "합계", "총계"]);

/** 이 레코드가 합계 행("계"·"합계"·"총계")인가. nm이 아예 없거나 문자열이
 *  아니면(예상 밖 응답) 사람 행으로 본다 — 판정을 못 하면 지우지도, 다르게
 *  다루지도 않는 쪽이 안전하다.
 *
 *  비교 전에 모든 공백(앞뒤·내부)을 제거한다 — DART가 "합 계"처럼 내부에
 *  공백을 넣어 보내는 경우가 있어 trim()만으로는 사람 목록에 남는다.
 *  다만 공백 "제거"이지 부분/접두 일치가 아니다 — "계상혁"처럼 실제
 *  인물명은 공백이 없어 원래 글자 그대로 남고, AGGREGATE_ROW_NAMES의
 *  어떤 항목과도 같아지지 않는다(동명이인 원칙과 같은 이유로 정확히
 *  일치할 때만 합계로 분류한다).
 *
 *  splitAggregateRows(표를 사람/합계로 나누기)와 shareholders 강조 규칙
 *  (합계 행에는 강조를 붙이지 않기, 이 파일 아래쪽) 두 곳이 이 하나의
 *  판정을 공유한다 — 같은 질문을 두 군데서 각자 답하면 "계상혁 함정"도
 *  두 군데서 각자 재발한다. */
function isAggregateRow(r) {
  const nm = isPlainObject(r) ? r.nm : undefined;
  return typeof nm === "string" && AGGREGATE_ROW_NAMES.has(nm.replace(/\s+/g, ""));
}

/** records(major_holders 등, nm 필드로 사람을 식별하는 레코드 목록)를
 *  {people, totals}로 나눈다(판정은 isAggregateRow 하나에 맡긴다). */
function splitAggregateRows(records) {
  const people = [];
  const totals = [];
  for (const r of records) {
    if (isAggregateRow(r)) totals.push(r);
    else people.push(r);
  }
  return { people: people, totals: totals };
}

/** 섹션 값을 화면에 그릴 블록 목록 [{title, table}] 또는 [{title, text}]로
 *  바꾼다. title은 없을 수 있다(null). table/text 둘 다 없으면(표로 만들
 *  근거 자체가 없는 하위 키) 그 사실도 블록으로 남긴다 — 하위 항목이
 *  조용히 빠지는 것을 막기 위해서다.
 *
 *  shareholders({major_holders:[...], bulk_holders:[...]})처럼 dict 값
 *  안에 리스트/객체가 섞여 있으면("dict-of-lists") 한 표에 JSON 뭉치로
 *  욱여넣지 않고 하위 키마다 재귀적으로 소제목 + 개별 표로 펼친다.
 *  하위 키에 라벨이 없으면 원본 키를 그대로 쓴다.
 *
 *  executive_roster는 일반 표 규칙이 통하지 않는 특수 형태다(키 자체가
 *  사람 이름) — 최상위 호출(depth 0)에서 key로 이 섹션임을 알아보면
 *  dict-of-lists 펼치기 대신 normalizeRoster로 사람을 행으로 뒤집은 뒤
 *  일반 표 경로(tableLayout)로 보낸다. depth 0에서만 검사하는 이유는
 *  key가 재귀 호출에는 전달되지 않기 때문이다(하위 어딘가에 우연히
 *  "executive_roster"라는 이름의 키가 있어도 이 특수 경로를 타지 않는다).
 *
 *  depth는 내부 재귀 카운터다(호출자는 생략한다 — 기본 0). 상한을
 *  넘으면 재귀를 멈추되, 그 하위 데이터를 조용히 빠뜨리지 않고 상한에
 *  걸렸다는 사실 자체를 텍스트 블록으로 남긴다 — 이 화면의 원칙은
 *  "데이터를 조용히 숨기지 않는다"이다. */
function sectionBlocks(value, depth, key) {
  const d = depth || 0;
  if (value === null || value === undefined) return [];

  // corp_code·corp_cls는 company_info(헤더, 화면 맨 위 고정 박스)에서만
  // 보여준다 — 다른 모든 섹션에서는 반복 소음이라 걷어낸다(위 HIDDEN_ID_
  // KEYS 주석 참고). depth 0에서만 게이트하는 이유는 executive_roster·
  // debt_balance.by_kind와 같다 — 재귀 호출에는 key가 전달되지 않으므로
  // 하위 어딘가에 우연히 "company_info"라는 이름의 중첩 키가 있어도 이
  // 예외가 잘못 적용되지 않는다.
  if (d === 0 && key !== "company_info") value = omitHiddenIds(value);

  if (d > MAX_SECTION_DEPTH) {
    return [{
      title: null,
      text: "중첩이 너무 깊어(깊이 " + d + ") 더 펼치지 않습니다. 원본 데이터는 있습니다.",
    }];
  }

  if (d === 0 && key === "executive_roster") {
    const records = normalizeRoster(value);
    const t = tableLayout(records);
    // records: 차트(다음 태스크)가 표와 같은 데이터를 그리도록, 표가
    // 실제로 쓴 레코드를 그대로 함께 싣는다 — table.rows는 이미
    // formatValue를 거친 문자열이라 차트에는 쓸 수 없다.
    return t ? [{ title: null, table: t, records: records }] : [];
  }

  if (Array.isArray(value)) {
    // tableLayout은 레코드(객체) 배열만 받는다 — toRecords로 비객체
    // 항목(문자열 등)을 "값" 한 칸에 감싸서 보존한 뒤 넘긴다. 그러지
    // 않으면 tableLayout이 비객체 항목을 조용히 걸러내(rows 필터), 예를
    // 들어 independence_warnings(문자열 리스트)가 흔적 없이 사라진다.
    const records = toRecords(value) || [];
    // insider_timeline처럼 레코드 전부가 source 필드를 가지면(4개
    // 엔드포인트를 합친 결과) source별로 작은 표 여러 개로 나눈다 —
    // source가 없는 다른 섹션은 이 분기를 타지 않는다(recordsHaveSourceField
    // 계약). 이 경로는 sourceGroupedBlocks가 블록별로 자기 레코드를
    // 따로 싣는다(source가 레코드에서 빠지므로 섹션 전체 레코드를
    // 넘기는 방식은 여기서 성립하지 않는다).
    if (recordsHaveSourceField(records)) return sourceGroupedBlocks(records);
    const t = tableLayout(records);
    return t ? [{ title: null, table: t, records: records }] : [];
  }

  if (!isPlainObject(value)) {
    if (isLongText(value)) return [{ title: null, text: value }];
    const records = toRecords(value) || [];
    const t = tableLayout(records);
    return t ? [{ title: null, table: t, records: records }] : [];
  }

  const keys = Object.keys(value);
  const nestedKeys = keys.filter(function (k) {
    return isPlainObject(value[k]) || Array.isArray(value[k]);
  });
  const longTextKeys = keys.filter(function (k) {
    return nestedKeys.indexOf(k) === -1 && isLongText(value[k]);
  });
  const flatKeys = keys.filter(function (k) {
    return nestedKeys.indexOf(k) === -1 && longTextKeys.indexOf(k) === -1;
  });

  const blocks = [];
  if (flatKeys.length > 0) {
    // Object.create(null)로 프로토타입 없는 객체를 만든다 — 일반 객체
    // 리터럴이면 키가 "__proto__"일 때 대입이 실제 프로퍼티가 아니라
    // 프로토타입 setter를 타서 그 키가 조용히 사라진다(LABELS와 같은
    // 부류의 버그, 위 LABELS 주석 참고).
    const flat = Object.create(null);
    for (const k of flatKeys) flat[k] = value[k];
    // flat은 항상 단일 평면 객체다 — 레코드 1건짜리 배열로 감싸 넘긴다.
    // (예전에는 이 경로가 indicators(1건 49열)를 세로로 바꾸는 핵심
    // 지점이었다. SE-4h부터 indicators는 행 목록으로 오고 ui.js가
    // key === "indicators"에서 sectionBlocks 자체를 부르지 않으므로 이
    // flatKeys 경로는 이제 이 섹션과 무관하다 — 위 tableLayout 주석 참고.)
    const records = [flat];
    const t = tableLayout(records);
    if (t) blocks.push({ title: null, table: t, records: records });
  }
  for (const k of longTextKeys) {
    blocks.push({ title: label(k), text: value[k] });
  }
  for (const k of nestedKeys) {
    // debt_balance.by_kind만 특수 처리한다(depth 0 + 부모 key로 게이트 —
    // executive_roster와 같은 방식). 다른 섹션에 우연히 "by_kind"라는
    // 이름의 하위 키가 있어도 이 경로를 타지 않는다(key가 재귀 호출에는
    // 전달되지 않으므로 하위 호출에서는 이 조건이 항상 거짓이다).
    if (d === 0 && key === "debt_balance" && k === "by_kind") {
      const records = normalizeDebtByKind(value[k]);
      const t = tableLayout(records);
      blocks.push(t
        ? { title: label(k), table: t, records: records }
        : { title: label(k), table: null, records: null });
      continue;
    }
    // shareholders.major_holders만 특수 처리한다(같은 게이트 방식 — depth
    // 0 + 부모 key). 최대주주 현황에는 합계 행("계")이 사람 이름 자리에
    // 섞여 온다(dart_client.fetch_shareholder_status가 /hyslrSttus.json
    // 원본을 그대로 준다 — fetch_affiliate_investments처럼 core에서 걸러
    // 반환하지 않는다). 합계를 지우라는 게 아니라(브리프 원칙: "합계를
    // 없애라는 게 아닙니다") 사람 목록 사이에 뒤섞여 읽기 힘든 게 문제라,
    // 같은 표 데이터를 사람 표 + 합계 표(제자리에 소계로) 두 블록으로
    // 나눈다 — splitAggregateRows가 판정 못 하면(nm 없음 등) 안전하게
    // 사람 쪽에 남긴다.
    if (d === 0 && key === "shareholders" && k === "major_holders") {
      const arr = Array.isArray(value[k]) ? value[k] : [];
      const split = splitAggregateRows(arr);
      const peopleRecords = toRecords(split.people) || [];
      const pt = tableLayout(peopleRecords);
      if (pt) blocks.push({ title: label(k), table: pt, records: peopleRecords });
      if (split.totals.length > 0) {
        const totalRecords = toRecords(split.totals) || [];
        const tt = tableLayout(totalRecords);
        if (tt) blocks.push({ title: label(k) + " · 합계", table: tt, records: totalRecords });
      }
      if (!pt && split.totals.length === 0) {
        blocks.push({ title: label(k), table: null, records: null });
      }
      continue;
    }
    const sub = sectionBlocks(value[k], d + 1);
    if (sub.length === 0) {
      blocks.push({ title: label(k), table: null, records: null });
      continue;
    }
    for (const sb of sub) {
      const title = sb.title ? (label(k) + " · " + sb.title) : label(k);
      blocks.push(Object.assign({}, sb, { title: title }));
    }
  }
  return blocks;
}

/** 섹션 키가 속한 그룹 제목. SECTION_GROUPS에 없는 키(2단 `doc:` 키 등)는
 *  "기타"로 묶는다 — 그룹이 안 잡힌다고 화면에서 사라지면 안 된다. */
function groupTitleFor(key) {
  for (const g of SECTION_GROUPS) {
    if (g.keys.indexOf(key) !== -1) return g.title;
  }
  return "기타";
}

/** 그룹 제목의 정렬 순서. SECTION_GROUPS 정의 순서를 따르고, 목록에 없는
 *  제목("기타" 포함)은 맨 뒤로 보낸다. */
function groupOrderIndex(title) {
  const idx = SECTION_GROUPS.findIndex(function (g) { return g.title === title; });
  return idx === -1 ? SECTION_GROUPS.length : idx;
}

/** 아직 받지 않은 섹션 키만 돌려준다.
 *
 * 진행률 폴링은 매번 완료된 키 **전체**를 준다. 그대로 다시 받으면
 * SE-4a가 없앤 737KB 문제가 그대로 돌아온다.
 */
function nextKeysToFetch(sectionKeys, fetched) {
  const seen = new Set(fetched || []);
  return (sectionKeys || []).filter(function (k) { return !seen.has(k); });
}

/** step 응답을 보고 폴링을 계속할지 정한다.
 *
 * 예상 밖 응답에서 계속 도는 것이 가장 나쁘다 — 사용자의 DART 호출
 * 한도를 조용히 태우기 때문이다. 모르면 멈춘다.
 */
function pollDecision(body) {
  const b = body || {};
  if (b.done === true) return { shouldStop: true, reason: "" };
  if (b.stalled === true) {
    return { shouldStop: true,
             reason: "진행이 멈췄습니다. 잠시 후 다시 시도해 주세요." };
  }
  if (typeof b.error === "string" && b.error) {
    // 서버가 이미 사용자에게 보여줘도 되는 문구로 다듬어 보낸다
    // (se_server/api/types.py Response.error — "X-DART-Key 헤더가
    // 필요합니다" 같은, 사용자가 스스로 고칠 수 있는 오류). 여기서
    // "서버 응답을 이해하지 못했습니다"로 뭉개면 그 안내가 사라진다.
    return { shouldStop: true, reason: b.error };
  }
  if (typeof b.done !== "boolean") {
    return { shouldStop: true,
             reason: "서버 응답을 이해하지 못했습니다." };
  }
  return { shouldStop: false, reason: "" };
}

// 근거 강도 3단계. 서버(`se_server/api/handlers.py`)와 같은 값이며,
// 모르는 값은 가장 약한 쪽으로 떨어뜨린다 — 확인 안 된 정보를 확인된
// 것처럼 보여주는 방향의 오차는 허용되지 않는다.
const ACTOR_STATUS = {
  // 어느 단계든 동명이인 경고를 갖는다. 레지스트리 대조는 **표기 일치**이지
  // 신원 확인이 아니기 때문이다. 단계 차이는 label이 나타낸다.
  verified: {
    label: "확인된 공개기록",
    warn: "공개기록의 표기가 일치함을 확인한 것이며 신원 확인은 아닙니다. 동명이인일 수 있습니다.",
  },
  maintainer_seed: {
    label: "제작자 등록 (근거 미확보)",
    warn: "근거가 확보되지 않았습니다. 동명이인일 수 있습니다.",
  },
  auto_matched: {
    label: "자동 매칭 (동명이인 미확인)",
    warn: "자동으로 매칭된 이름입니다. 동명이인일 수 있으며 확인되지 않았습니다.",
  },
};

/** 행위자 한 명을 화면에 낼 형태로 바꾼다.
 *
 * 이름·라벨·경고를 한 함수가 함께 만든다. 나눠 두면 한쪽만 그리는
 * 경로가 생기고, 그 경로로 실명이 경고 없이 나간다.
 */
function actorLine(actor) {
  const a = actor || {};
  const raw = a.status;
  const known = typeof raw === "string" && Object.prototype.hasOwnProperty.call(ACTOR_STATUS, raw);
  const meta = known ? ACTOR_STATUS[raw] : ACTOR_STATUS.auto_matched;
  return {
    name: typeof a.name === "string" ? a.name : "",
    statusLabel: meta.label,
    warn: meta.warn,
    companies: Array.isArray(a.companies) ? a.companies : [],
  };
}

/** 공시 원문을 문단과 표 블록으로 나눈다.
 *
 * **가공은 구조 복원까지만 한다.** 요약하거나 중요한 부분을 골라내거나
 * 순서를 바꾸지 않는다 — 그건 판정이고, 이 도구는 사실만 표기한다
 * (v0.8.5 원칙). dart_client.py의 `_html_to_structured_text`가 실제로
 * 표를 파이프(|) 구분 마크다운으로, 행마다 줄바꿈을 넣어 만든다
 * (`_table_to_markdown`이 각 행을 "\n"으로 join) — 그래서 여기서는
 * "|"가 있는 줄만 표 행으로 보고, 그 외는 원문 그대로 문단으로 보존한다.
 * `|---|---|` 같은 마크다운 표 구분선은 데이터가 아니므로 행으로 만들지
 * 않는다(셀 전부가 `-`만으로 이뤄진 줄만 걸러낸다 — 실제 데이터 줄에
 * "-"가 섞여 있어도 다른 셀이 남아 있으면 걸러지지 않는다).
 */
// dart_client.py의 _html_to_structured_text가 <h1>~<h6>를 "#" * level + " "
// 마크다운 헤더로 바꾼다(구조 보존용 중간 표현) — 이 화면은 마크다운을
// 렌더링하지 않고 문단을 <p>에 textContent로 그대로 보여주므로, 이 표시를
// 그대로 두면 "### 회사합병 결정"처럼 원문 화면(HTML)에는 없던 기호가
// 사용자에게 노출된다. 제목 내용(텍스트)은 그대로 두고 마크다운 문법
// 기호만 벗긴다 — 요약·판정이 아니라 표시 방식의 변환일 뿐이다(v0.8.5
// 원칙과 무관: 구조를 재구성하지 않는다, 줄 자체는 그대로 한 문단이다).
function stripMarkdownHeadingHash(line) {
  return line.replace(/^(\s*)#{1,6}(?=\s|$)\s*/, "$1");
}

// 본문에서 doc:<접수번호> 섹션을 모으는 목록 섹션의 키. LABELS의
// doc_list 항목과 짝을 이룬다. ui.js가 이 값으로 renderSection을 호출해
// 표를 (누적이 아니라) 매번 통째로 다시 그린다(renderSection 계약).
const DOC_LIST_KEY = "doc_list";

/** "doc:<접수번호>" 형태의 섹션 키에서 접수번호만 뽑는다. 아니면 null.
 *  registry.py의 expand_stage2가 `f"doc:{rcept_no}"`로 만드는 키와 짝이다. */
function docKeyRceptNo(key) {
  return (typeof key === "string" && key.indexOf("doc:") === 0) ? key.slice(4) : null;
}

/** doc:<접수번호> 섹션 값을 본문 목록의 행 하나로 줄인다.
 *
 * **원문(text, 최대 20,000자)은 목록에 넣지 않는다.** 본문에 그대로
 * 내보내면 엔켐 실측 기준 34건 × 약 13만 자가 쏟아진다(field-inventory) —
 * 원문은 rcept_no를 클릭해 우측 패널(openDocPanel)에서 본다. 여기서는
 * "어떤 공시를 가져왔는지"만 사실대로 남긴다: 접수번호(rcept_no 키를
 * 그대로 써야 ui.js의 기존 클릭 배선 — table.keys.indexOf("rcept_no") —
 * 이 그대로 작동한다), 주 파일·파일 목록, 글자 수, 잘렸는지 여부.
 *
 * main_file·files는 이전에는 본문 표의 열이었다(공시 원문을 doc: 원문
 * 그대로 내보내던 시절). text를 목록으로 바꾸며 이 둘도 함께 빠졌는데,
 * se_server/api/handlers.py의 우측 패널 응답(`_disclosure`)은
 * rcept_no·text·char_count·truncated만 주고 files·main_file은 주지
 * 않는다 — 그 결과 이 두 필드는 화면 어디에서도 도달 불가능해졌다.
 * 값이 있는 데이터를 조용히 숨기지 않는다는 이 화면의 원칙(위 LABELS
 * 주석과 동일)에 따라 목록에 되살린다. 실측(field-inventory) 기준
 * main_file은 34건 중 33건에 실제 파일명(예: "20260715900769.xml")이
 * 있고, files도 함께 채워져 있다(파일이 여러 개인 공시도 있어 배열
 * 그대로 둔다 — formatValue가 원소를 쉼표로 이어 보여준다).
 *
 * files가 빈 배열([])이면(ZIP을 아예 못 받은 경우 — handlers.py의
 * `_disclosure` 주석: "files=[]인 완전한 빈 dict") formatValue(app.js)가
 * 그 사실 그대로 "없음"으로 보여준다 — 목록 단계에서부터 이 공시는 클릭해도
 * 원문이 없다는 것을 미리 알 수 있다(판정 어휘 없이 사실만, v0.8.5 원칙).
 *
 * **rcept_no는 여기서도 한 번 더 정규화한다.** 지금 유일한 호출부인
 * ui.js의 addDocListEntry는 docKeyRceptNo로 "doc:" 접두어를 미리 벗기고
 * 넘기지만, 그 계약을 이 함수 자신도 지켜야 한다 — 그래야 나중에 다른
 * 호출부가 섹션 키(`doc:<접수번호>`)를 그대로 넘기는 실수를 해도(실제로
 * 있었던 사고: rcept_no 열이 접두어를 단 채 우측 패널 openDocPanel로
 * 넘어가 `/api/se/disclosure/doc%3A...`를 요청 — router.py의 rcept_no
 * 패턴 `[0-9]{8,20}`과 매칭되지 않아 404) 목록 행의 rcept_no는 항상
 * 서버가 받는 형태(숫자만)로 남는다. docKeyRceptNo가 null이면(이미
 * 접두어가 없는 값) 원래 값을 그대로 쓴다.
 */
function docListRow(rceptNo, value) {
  const v = value || {};
  const stripped = docKeyRceptNo(rceptNo);
  return {
    rcept_no: stripped !== null ? stripped : rceptNo,
    main_file: v.main_file,
    files: Array.isArray(v.files) ? v.files : [],
    char_count: v.char_count,
    truncated: v.truncated,
  };
}

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

  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (line.indexOf("|") >= 0) {
      const cells = line.split("|").map(function (c) { return c.trim(); })
        .filter(function (c, i, a) { return !(c === "" && (i === 0 || i === a.length - 1)); });
      if (cells.length && cells.every(function (c) { return /^:?-{2,}:?$/.test(c); })) continue;
      if (cells.length) { flushProse(); table.push(cells); continue; }
    }
    flushTable();
    prose.push(stripMarkdownHeadingHash(raw));
  }
  flushTable();
  flushProse();
  return blocks;
}

// fs_div("CFS"/"OFS") → 화면 표기. financials 원본 레코드가 이 두 값만
// 갖는다(field-inventory 실측) — 그 외 값은 아래서 통째로 건너뛴다.
const FS_DIV_LABELS = Object.create(null);
FS_DIV_LABELS.CFS = "연결";
FS_DIV_LABELS.OFS = "별도";

// financialRatios가 만드는 기간 3종과, 각 기간이 financials 레코드의 어느
// 금액 열에서 오는지의 대응표. **당기를 마지막에 둔다** — 이 배열 순서가
// 곧 출력 레코드의 순서이고(전전기→전기→당기), 그 순서가 그대로 두 곳에서
// 쓰인다: ① 아래 CHART_SPECS.financial_ratios의 x축("기간")은 숫자가
// 없는 순수 범주형이라 chartData가 정렬하지 않고 등장 순서를 그대로
// 쓴다(위 chartData 주석 ③) — 당기가 마지막이어야 그래프가 왼쪽(과거)에서
// 오른쪽(현재)으로 흐른다. ② 같은 (구분, 지표) 조합이 기간마다 반복
// 나오므로, 이 조합만으로 마지막 값을 찾는 코드(예: dict 컴프리헨션)는
// 자연히 당기 값을 얻는다 — 순서를 바꾸면 이런 코드가 조용히 옛 기간
// 값을 돌려주게 된다.
const RATIO_PERIODS = [
  { period: "전전기", field: "bfefrmtrm_amount" },
  { period: "전기", field: "frmtrm_amount" },
  { period: "당기", field: "thstrm_amount" },
];

// 계산 가능한 지표 4종(자본잠식률은 표기 조건이 달라 별도 처리한다,
// financialRatios·computeCapitalImpairment 참고). num/den은 계정
// "개념"의 대표 이름이다 — 실제 financials.account_nm은 DART 제출
// 기업마다 표기가 갈린다(엔켐 실측: 당기순이익이 "당기순이익(손실)"로
// 옴). 대표 이름 그대로는 accounts.get()이 못 찾으므로 ACCOUNT_ALIASES·
// pickAccount(아래)를 거쳐 조회한다 — 사유 문구는 그래도 이 대표
// 이름을 써서 "당기순이익 없음"처럼 어떤 개념이 빠졌는지를 말한다
// (실제 만난 표기가 아니라 찾던 개념 기준 — 표기가 열 종류든 사용자가
// 찾을 대상은 하나다).
const RATIO_DEFS = [
  { name: "영업이익률", num: "영업이익", den: "매출액", formula: "영업이익 ÷ 매출액" },
  { name: "순이익률", num: "당기순이익", den: "매출액", formula: "당기순이익 ÷ 매출액" },
  { name: "부채비율", num: "부채총계", den: "자본총계", formula: "부채총계 ÷ 자본총계" },
  { name: "유동비율", num: "유동자산", den: "유동부채", formula: "유동자산 ÷ 유동부채" },
];

// 대표 계정명 → DART 실제 표기 별칭 목록(우선순위순, 대표 이름이 항상
// 1순위). dart_risk_mcp/core/dart_client.py의 _FS_ALIASES·
// docs/tool/signals-data.json의 fs_aliases와 같은 문제(표기 분산)를
// 겨냥하지만 이 파일은 순수 함수 유지가 우선이라(브리프 제약 1) 독립
// 상수로 별도 유지한다 — signals-data.json은 비동기 로드라 얽으면
// financialRatios가 더 이상 순수 함수가 아니게 된다. 여기 있는 6개
// 대표명만 필요하므로 그 부분집합을 그대로 옮겨 적었다(전체 표는 위
// 두 파일이 원본).
//
// **별칭을 무한정 넓히지 않는다** — "법인세차감전 순이익"처럼 다른
// 계정과 이름이 겹치는 표기는 넣지 않는다. 넣으면 값이 없는 것보다
// 나쁜, 틀린 계정을 자신 있게 보여주는 결과가 된다(브리프 경고).
const ACCOUNT_ALIASES = Object.create(null);
ACCOUNT_ALIASES["매출액"] = [
  "매출액", "영업수익", "수익(매출액)", "영업수익(매출액)", "매출",
  "순매출액", "수입금액", "매출수익", "영업수입", "영업매출액", "수익",
];
ACCOUNT_ALIASES["영업이익"] = ["영업이익", "영업이익(손실)", "영업손익", "영업이익(영업손실)"];
ACCOUNT_ALIASES["당기순이익"] = [
  "당기순이익", "당기순이익(손실)", "당기순이익(당기순손실)",
  "당기순손익", "분기순이익", "반기순이익", "연결당기순이익",
];
ACCOUNT_ALIASES["부채총계"] = ["부채총계", "부채 총계"];
ACCOUNT_ALIASES["자본총계"] = ["자본총계", "자본 총계", "자본합계"];
ACCOUNT_ALIASES["유동자산"] = ["유동자산"];
ACCOUNT_ALIASES["유동부채"] = ["유동부채", "유동부채 합계"];
ACCOUNT_ALIASES["자본금"] = ["자본금"];

/** account_nm → 그 계정의 raw financials 행(연결 또는 별도 한 그룹 안).
 *  같은 계정명이 한 그룹 안에 두 번 나오면(정상적인 DART 응답에서는
 *  없어야 하지만) 먼저 만난 행을 신뢰값으로 삼는다 — 뒤 행이 조용히
 *  덮어쓰면 어느 쪽이 실제 계산에 쓰였는지 알 수 없게 된다. */
function indexAccountsByDiv(records) {
  const byDiv = new Map();
  for (const r of records) {
    if (!r || typeof r !== "object") continue;
    const div = r.fs_div;
    if (div !== "CFS" && div !== "OFS") continue; // 실측 밖 값은 계산하지 않는다
    if (!byDiv.has(div)) byDiv.set(div, new Map());
    const accounts = byDiv.get(div);
    if (!accounts.has(r.account_nm)) accounts.set(r.account_nm, r);
  }
  return byDiv;
}

/** 대표 계정명(예: "당기순이익")으로 accounts 맵을 조회한다. ACCOUNT_ALIASES에
 *  등록된 별칭을 우선순위대로 시도하고(대표 이름 자신이 항상 1순위),
 *  등록되지 않은 이름은 그 이름 그대로 한 번만 시도한다(RATIO_DEFS가
 *  모르는 새 계정을 요구해도 조용히 죽지 않는다). */
function pickAccount(accounts, canonicalName) {
  const aliases = ACCOUNT_ALIASES[canonicalName] || [canonicalName];
  for (const alias of aliases) {
    const row = accounts.get(alias);
    if (row) return row;
  }
  return undefined;
}

/** 지표 하나(예: 영업이익률)를 한 기간에 대해 계산한다. 분자·분모 계정 중
 *  하나라도 없거나(계정 자체가 안 잡힘) 분모가 0이면 값은 null이고
 *  **왜 없는지 사유로 남긴다** — 조용히 항목을 빼지 않는다(브리프 원칙).
 *  재료는 항상 두 계정 이름을 키로 갖는 객체를 돌려준다(값이 null이어도
 *  키 자체는 있다) — 검증 가능성(계산식+재료)이 값의 유무와 무관하게
 *  항상 보장돼야 하기 때문이다. */
function computeRatio(구분, 기간, def, accounts, field) {
  const numRow = pickAccount(accounts, def.num);
  const denRow = pickAccount(accounts, def.den);
  const numVal = numRow ? numeric(numRow[field]) : null;
  const denVal = denRow ? numeric(denRow[field]) : null;
  const 재료 = Object.create(null);
  재료[def.num] = numVal;
  재료[def.den] = denVal;

  let 값 = null;
  let 사유 = null;
  if (numVal === null && denVal === null) {
    사유 = def.num + "·" + def.den + " 없음";
  } else if (numVal === null) {
    사유 = def.num + " 없음";
  } else if (denVal === null) {
    사유 = def.den + " 없음";
  } else if (denVal === 0) {
    // 0으로 나누면 Infinity/NaN이 나온다 — "매출액 0인 회사가 실제로
    // 있다"(브리프) 그 경우를 계산 불가로 명시한다.
    사유 = def.den + " 0";
  } else {
    값 = (numVal / denVal) * 100;
  }

  const out = { 구분: 구분, 기간: 기간, 지표: def.name, 값: 값, 계산식: def.formula, 재료: 재료 };
  if (값 === null) out.사유 = 사유;
  return out;
}

/** 자본잠식률은 다른 4개와 표기 조건이 다르다 — 공식(자본금−자본총계)÷
 *  자본금을 그대로 계산하면 잠식이 없는 정상 회사도 큰 음수가 나온다
 *  (브리프 예시: 엔켐 −4302.9%, 자본총계가 자본금보다 훨씬 크기 때문).
 *  그 값은 계산은 맞지만 정보가 아니다 — **양수(자본금이 자본총계보다
 *  커서 실제로 까먹은 경우)일 때만** 값으로 남기고, 0 이하는 "잠식
 *  없음"으로 null 처리한다(브리프 판정선: 계산은 사실, 해석은 판정이지만
 *  "표기하지 않는다"는 판정이 아니라 이 지표의 정의 자체다 — 잠식률은
 *  잠식이 있을 때만 존재하는 개념이다). */
function computeCapitalImpairment(구분, 기간, accounts, field) {
  const capRow = pickAccount(accounts, "자본금");
  const totalRow = pickAccount(accounts, "자본총계");
  const capVal = capRow ? numeric(capRow[field]) : null;
  const totalVal = totalRow ? numeric(totalRow[field]) : null;
  const 재료 = Object.create(null);
  재료["자본금"] = capVal;
  재료["자본총계"] = totalVal;

  let 값 = null;
  let 사유 = null;
  if (capVal === null && totalVal === null) {
    사유 = "자본금·자본총계 없음";
  } else if (capVal === null) {
    사유 = "자본금 없음";
  } else if (totalVal === null) {
    사유 = "자본총계 없음";
  } else if (capVal === 0) {
    사유 = "자본금 0";
  } else {
    const ratio = ((capVal - totalVal) / capVal) * 100;
    if (ratio > 0) {
      값 = ratio;
    } else {
      사유 = "잠식 없음";
    }
  }

  const out = {
    구분: 구분, 기간: 기간, 지표: "자본잠식률",
    값: 값, 계산식: "(자본금 − 자본총계) ÷ 자본금", 재료: 재료,
  };
  if (값 === null) out.사유 = 사유;
  return out;
}

/** financials(원본 재무제표 레코드 배열)에서 파생 지표 5종을 연결/별도 ×
 *  3기간(전전기/전기/당기)으로 계산한다. DART가 주는 건 한 시점 스냅샷
 *  (indicators)이지만, financials의 thstrm_amount·frmtrm_amount·
 *  bfefrmtrm_amount 세 열이 이미 같은 계정의 세 시점 값을 담고 있으므로
 *  그대로 추이를 만들 수 있다 — "공시가 주는 건 사진, 우리가 만드는 건
 *  흐름"(브리프).
 *
 *  **연결과 별도를 절대 같은 계산에 섞지 않는다.** fs_div별로 완전히
 *  독립된 계정 조회 테이블(indexAccountsByDiv)을 만들어 계산하고, 결과
 *  행마다 "구분"을 그대로 남긴다 — SE-4d에서 financials 원본 차트를 뺀
 *  이유가 바로 이 혼입이었다(위 CHART_SPECS 주석 참고). */
function financialRatios(records) {
  if (!Array.isArray(records)) return [];
  const byDiv = indexAccountsByDiv(records);

  const out = [];
  for (const [div, accounts] of byDiv) {
    const 구분 = FS_DIV_LABELS[div] || div;
    for (const p of RATIO_PERIODS) {
      for (const def of RATIO_DEFS) {
        out.push(computeRatio(구분, p.period, def, accounts, p.field));
      }
      out.push(computeCapitalImpairment(구분, p.period, accounts, p.field));
    }
  }
  return out;
}

/** dividends(alotMatter)의 se(항목) 중 이 태스크가 비교하는 5종.
 *  현금배당금총액·(연결/별도)당기순이익·주식배당금총액·현금배당성향이
 *  이미 같은 "백만원"(또는 "%") 단위로 한 응답 안에 나란히 있다(2026-07-28
 *  삼성전자 실측, corp_code=00126380, rcept_no=20250311001085) — 섹션 간
 *  조인이나 단위 환산 없이 그대로 나란히 놓을 수 있다(SE-4f Task 4,
 *  task-4-brief.md). 이익잉여금(financials, 원 단위)은 이번 범위가
 *  아니다 — 단위 혼동(백만원↔원)은 이 프로젝트에서 이미 financials 원본
 *  차트를 통째로 뺀 사유였다(위 CHART_SPECS 주석 참고), 섹션 간 조인 +
 *  단위 환산은 별건이다(브리프). */
const DIVIDEND_SE_FIELDS = [
  "현금배당금총액(백만원)",
  "(연결)당기순이익(백만원)",
  "(별도)당기순이익(백만원)",
  "주식배당금총액(백만원)",
  "(연결)현금배당성향(%)",
];

/** dividends 레코드에서 "배당총액 vs 벌어들인 돈"을 사업연도·보고서구분
 *  (bsns_year × reprt_code)별로 나란히 뽑는다.
 *
 *  현금배당금총액이 없거나("-", DART의 무값 표기) 읽을 수 없는 보고는
 *  아예 행을 만들지 않는다 — 배당이 없는 회사(예: 엔켐, 브리프 경고
 *  "엔켐은 배당이 없습니다")에서 이 비교가 조용히 발화하지 않는 것이
 *  맞는 동작이다: 감추는 게 아니라 비교할 배당액 자체가 없는 것이다.
 *
 *  dividends는 fund_usage와 달리 정규화 과정에서 reprt_code가 탈락하지
 *  않는다(위 CHART_SPECS.dividends 주석 참고) — 같은 사업연도라도 분기
 *  보고서마다 다른 보고이므로 (bsns_year, reprt_code) 쌍으로 묶어 값이
 *  조용히 덮이지 않게 한다. */
function dividendVsIncome(records) {
  if (!Array.isArray(records)) return [];
  const groups = new Map();
  const order = [];
  for (const r of records) {
    if (!r || typeof r !== "object") continue;
    const year = r.bsns_year !== undefined && r.bsns_year !== null ? String(r.bsns_year) : "";
    const reprt = r.reprt_code !== undefined && r.reprt_code !== null ? String(r.reprt_code) : "";
    const key = year + " " + reprt;
    if (!groups.has(key)) {
      groups.set(key, { bsns_year: year, reprt_code: reprt, se: Object.create(null) });
      order.push(key);
    }
    const se = r.se;
    if (typeof se === "string" && DIVIDEND_SE_FIELDS.indexOf(se) !== -1) {
      groups.get(key).se[se] = r.thstrm;
    }
  }

  const out = [];
  for (const key of order) {
    const g = groups.get(key);
    const dividend = numeric(g.se["현금배당금총액(백만원)"]);
    if (dividend === null) continue; // 배당 기록 자체가 없다 — 비교가 발화하지 않는다
    const row = { bsns_year: g.bsns_year, reprt_code: g.reprt_code };
    for (const se of DIVIDEND_SE_FIELDS) {
      row[se] = numeric(g.se[se]);
    }
    out.push(row);
  }
  return out;
}

/** fund_usage 레코드에서 같은 조달 건(같은 pay_de·같은 plan_useprps)의
 *  계획 금액(plan_amount)이 보고 시점마다 다르게 보고된 사실을 뽑는다
 *  (SE-4f Task 7, task-7-brief.md).
 *
 *  fetch_fund_usage(dart_client.py)는 reprt_code(어느 분기 보고인지)를
 *  정규화 과정에서 버린다(core 수정 불가, 위 CHART_SPECS.fund_usage 주석
 *  참고) — 그래서 "1분기엔 342.91억, 반기부터는 352.91억"처럼 **어느
 *  시점에 바뀌었는지**는 여기서 말할 수 없다. 대신 "이 조달 건에 보고된
 *  계획 금액이 서로 다른 값으로 존재한다"는 사실(등장한 서로 다른 값의
 *  집합, 최초 등장 순서)만 표기한다 — 없는 순서 정보를 지어내지 않는다.
 *
 *  2026-07-28 엔켐 실측(corp_code=01011526, bsns_year=2022,
 *  pssrpCptalUseDtls.json)으로 확인: pay_de="2021.10.26"·
 *  plan_useprps="운영자금" 조합에서 plan_amount가 34,291,000,000(1분기
 *  보고)과 35,291,000,000(반기·3분기·사업보고서) 두 값으로 갈린다.
 *  같은 사업보고서(11011) 안에서도 항목이 두 번 중복 수집되지만 값
 *  자체는 같다(pay_de·plan_useprps·plan_amount 모두 동일) — 값이 같으면
 *  "변경"이 아니다(indexOf로 중복 값은 한 번만 센다). */
function fundPlanChanges(records) {
  if (!Array.isArray(records)) return [];
  const groups = new Map();
  const order = [];
  for (const r of records) {
    if (!r || typeof r !== "object") continue;
    const payDe = r.pay_de !== undefined && r.pay_de !== null ? String(r.pay_de) : "";
    const purpose = r.plan_useprps !== undefined && r.plan_useprps !== null ? String(r.plan_useprps) : "";
    if (!payDe || !purpose) continue; // 조달 건을 특정할 식별자가 없으면 묶지 않는다
    const key = payDe + " " + purpose;
    if (!groups.has(key)) {
      groups.set(key, { pay_de: payDe, plan_useprps: purpose, kind: r.kind, amounts: [] });
      order.push(key);
    }
    const amt = numeric(r.plan_amount);
    if (amt === null) continue;
    const g = groups.get(key);
    if (g.amounts.indexOf(amt) === -1) g.amounts.push(amt);
  }

  const out = [];
  for (const key of order) {
    const g = groups.get(key);
    if (g.amounts.length > 1) out.push(g);
  }
  return out;
}

/** affiliates(타법인 출자현황) 레코드를 최초취득일(frst_acqs_de) 오름차순으로
 *  다시 배열한다(SE-4f Task 5, task-5-brief.md: "피투자사에 대한 정보를
 *  처음부터 보여줄 필요도 있음", "시간의 순서에 따라 투자 규모 변화").
 *
 *  **한 사업연도 스냅샷이다.** affiliates는 최근 사업보고서 한 번의 응답이라
 *  여러 해에 걸친 추이는 이 데이터만으로 만들 수 없다(브리프: "없는 것을
 *  있는 것처럼 만들지 마라") — 만들 수 있는 것은 이 스냅샷 안에서 ①언제부터
 *  투자했는지(frst_acqs_de) 순서, ②이번 사업연도 안에서 기초→기말 장부가액이
 *  어떻게 바뀌었는지 둘뿐이다. 이 함수는 ①의 순서만 만든다 — 값을 다시
 *  계산하지 않고 원본 레코드를 그대로, 순서만 바꿔 돌려준다(buildAffiliate
 *  OverviewBlock·CHART_SPECS.affiliate_timeline이 그 순서를 표·차트에 그대로
 *  쓴다).
 *
 *  최초취득일이 없거나 읽을 수 없는 레코드(예상 밖 응답)는 정렬 기준이
 *  없으므로 맨 뒤로 보낸다(없는 순서를 지어내 앞뒤 어딘가에 끼워 넣지
 *  않는다) — 그런 레코드끼리는 원래 등장 순서를 그대로 유지한다(비교 함수가
 *  a.idx-b.idx로 그 순서를 명시한다. Array.prototype.sort 자체가 안정 정렬인
 *  현대 엔진에 기대지 않는다).
 *
 *  같은 날짜(동률)인 레코드도 등장 순서를 유지한다 — 실측(엔켐)에 "골든밸류
 *  제3호"·"제4호" 신기술조합이 둘 다 frst_acqs_de=2025.09.25로 같다. 어느 쪽이
 *  "먼저"인지 원본에 없는 정보이므로 지어내지 않는다.
 *
 *  inv_prm(피출자 법인명)이 없는 레코드는 애초에 어느 법인인지 알 수 없어
 *  뺀다 — core(fetch_affiliate_investments)가 이미 "계"/"합계" 등 요약행을
 *  걸러내지만, 이 함수는 그 계약에 기대지 않고 방어적으로 한 번 더 본다.
 *
 *  **정렬 키는 numeric()이 아니라 axisSortKey()로 뽑는다(최종 리뷰 지적 ①,
 *  다섯 번째 픽스처발 결함).** frst_acqs_de의 실측 형태는 "2018.05.07"처럼
 *  점으로 구분된 문자열인데, numeric()은 "이 값 자체가 순수 숫자다"를
 *  요구해(위 numeric() 주석) 점이 섞이면 무조건 null을 돌려준다 — 즉
 *  실데이터에서는 매 레코드가 null이 되어 이 함수가 사실상 아무 일도
 *  하지 않고 원래 순서를 그대로 돌려주는데, 화면은 여전히 "최초취득일
 *  순"이라 단언한다(입력이 우연히 날짜순이면 눈으로는 맞아 보여 들키지
 *  않는다). axisSortKey()는 문자열에서 숫자만 이어붙이므로
 *  "2018.05.07" → 20180507, "-"(날짜 없음) → 빈 문자열 → null로 자연히
 *  뒤로 간다 — numeric()은 고치지 않는다(금액·비율 파싱에 쓰여 파급이
 *  크다), 여기서만 날짜 전용으로 axisSortKey()를 쓴다. */
function affiliateOverview(records) {
  if (!Array.isArray(records)) return [];
  const rows = records.filter(function (r) {
    return r && typeof r === "object" && typeof r.inv_prm === "string" && r.inv_prm.trim() !== "";
  });
  const withKey = rows.map(function (r, idx) {
    return { r: r, key: axisSortKey(r.frst_acqs_de), idx: idx };
  });
  withKey.sort(function (a, b) {
    if (a.key === null && b.key === null) return a.idx - b.idx;
    if (a.key === null) return 1;
    if (b.key === null) return -1;
    if (a.key !== b.key) return a.key - b.key;
    return a.idx - b.idx; // 동률(같은 날짜)은 등장 순서를 유지한다
  });
  return withKey.map(function (w) { return w.r; });
}

// 섹션별 차트 정의. 여기 없는 섹션은 차트 없이 표만 나온다.
//
// **`time` 축을 쓰지 않는다.** Chart.js의 time scale은 별도 날짜 어댑터를
// 요구해 의존성이 하나 더 늘어난다. 날짜를 "2026.04.15" 문자열로 만들어
// category 축에 넣으면 어댑터 없이 같은 그림이 나온다 — 우리 데이터는
// 보고 시점이 띄엄띄엄한 이산 값이라 오히려 이쪽이 맞다.
// financials는 여기 없다 — 실측(field-inventory)에서 fs_div(CFS/OFS)·
// sj_div(BS/IS)가 상수열이 아니라 30건 안에 연결·별도, 재무상태표·손익계산서가
// 공존한다. 같은 account_nm("유동자산")이 연결 행과 별도 행 양쪽에 나타나는데,
// x축(account_nm) 하나에 값 하나만 담는 chartData 구조로는 뒤 레코드가 앞을
// 조용히 덮어(연결 100이 사라지고 별도 11만 남는 식) 어느 쪽 값인지 표시할
// 방법이 없다(리뷰 지적 ②). 연결과 별도를 한 그림에 섞느니 차트를 빼고
// 표(financials 섹션은 fs_div·sj_div·fs_nm·sj_nm 열을 그대로 보여준다)만
// 남긴다 — 표는 행마다 그 값이 어느 재무제표인지 정확히 말하지만, 차트는
// 그 구분을 표현할 자리가 없다.
const CHART_SPECS = Object.assign(Object.create(null), {
  insider_timeline: {
    kind: "line", title: "보고자별 지분율 추이",
    x: "rcept_dt", y: "sp_stock_lmp_rate", groupBy: "repror", yLabel: "지분율 (%)",
    // Chart.js의 time 축은 별도 날짜 어댑터를 요구한다 — 위 CHART_SPECS
    // 주석의 결정을 실제로 지키는지 테스트가 확인할 수 있도록 명시한다
    // (test_no_spec_uses_a_time_scale). renderChart(ui.js)가 이 값을
    // scales.x.type으로 그대로 쓴다.
    xScale: "category",
  },
  // fetch_fund_usage(dart_client.py)는 연도(bsns_year) × 보고서코드 4종
  // (11011 사업·11012 반기·11013 1분기·11014 3분기)을 루프 돌며 모으므로
  // **같은 회차(tm)가 보고 시점마다 반복 수집된다** — 정규화된 레코드에는
  // reprt_code가 남지 않지만 year(그 루프의 bsns_year)·kind(공모/사모)는
  // 남는다. x를 tm 하나로만 잡으면 같은 회차의 서로 다른 연도 보고(예:
  // 2024년 보고 50억 vs 2025년 보고 130.8억, 실제 회귀 사례)가 한 x축
  // 점에서 뒤 레코드가 앞을 조용히 덮어 표(같은 회차 두 행을 그대로
  // 보여준다)와 다른 값을 말하게 된다(리뷰 지적 ①). compositeXFields로
  // x를 "회차 (연도, 구분)" 형태로 쪼개면 서로 다른 보고가 서로 다른
  // x축 점이 되어 값이 사라지지 않는다 — year·kind가 없는 레코드(예:
  // 테스트 픽스처)는 compositeXValue가 있는 필드만으로 자연히 폴백한다.
  //
  // **kind를 더해도 여전히 다 갈라지지 않는다(라이브 재리뷰 Critical).**
  // 공모(kind="public") 건은 tm 실측값이 "-"(회차 없음)인 경우가 있고,
  // 같은 연도·같은 kind 안에서도 보고서(reprt_code — 정규화 과정
  // (_normalize_fund_usage)에서 탈락해 여기서는 되살릴 수 없다)마다
  // 계획금액이 다른 레코드가 3건까지 나온다(실측: 130.82억/352.91억/
  // 476.57억). reprt_code 없이는 이 세 값을 서로 다른 x축 점으로 가를
  // 방법이 없다 — 이런 진짜 충돌은 chartData 하단의 범용 충돌 감지
  // (writeChartCell)가 그 x축 점을 null로 만든다(표는 여전히 3행 모두
  // 보여준다 — 값을 지어내지 않을 뿐 숨기지도 않는다). reprt_code를
  // 되살리려면 dart_client.py를 고쳐야 하는데 이 브랜치는 core를
  // 읽기만 한다 — 여기서 할 수 있는 최선은 "쪼갤 수 있는 만큼 쪼개고,
  // 남는 충돌은 숨기지 않는다"이다.
  fund_usage: {
    kind: "bar", title: "자금 사용 — 계획 대비 실제 (회차·보고연도·구분별)",
    x: "tm", compositeXFields: ["tm", "year", "kind"], yLabel: "금액", xScale: "category",
    series: [
      { key: "plan_amount", label: "계획 금액" },
      { key: "real_dtls_amount", label: "실제 집행 금액" },
    ],
  },
  // dividends의 se(항목)에는 "주당 현금배당금(원)"처럼 원(₩) 단위와
  // "현금배당수익률(%)"처럼 비율(%) 단위가 한 목록에 섞여 있다(alotMatter
  // 실측). 같은 y축에 그리면 financials의 CFS/OFS를 섞었던 사고와 같은
  // 부류의 거짓말이 된다 — 값 자체는 정확해도 단위가 다른 두 계열을 같은
  // 눈금으로 비교하게 만들기 때문이다. groupFilterSuffix("(원)")로 순수
  // 원화 단위 항목만 계열로 만든다(끝이 정확히 "(원)"인 항목만 — "(백만원)"
  // 은 마지막 3글자가 "만원)"이라 걸리지 않는다, chartData 주석 참고).
  // 제외된 항목(%·백만원·주)은 차트에서만 빠질 뿐 표에는 그대로 남는다.
  //
  // **fetch_dividend_history(dart_client.py)도 4개 reprt_code(11011·
  // 11012·11013·11014) × N년 루프다(fund_usage와 같은 부류의 반복
  // 수집) — 그런데 x는 bsns_year 하나뿐이었다(라이브 재리뷰 Critical,
  // fund_usage와 달리 이 섹션은 손도 안 댄 채였다). 같은 연도·같은
  // 항목(se)에 보고서마다 다른 값이 조용히 하나로 덮이고, 부호까지
  // 뒤집힌다(실측 2025년 (연결)주당순이익(원): -3,154/1,817/2,750/121 —
  // 첫 보고는 적자인데 마지막 값(121)만 남아 흑자로 보였다). dividend
  // 레코드는 fund_usage와 달리 reprt_code가 정규화 과정에서 탈락하지
  // 않고 그대로 남는다(fetch_dividend_history 주석) — compositeXFields로
  // x를 "연도 (보고서코드)"로 쪼개 네 보고를 각자 다른 x축 점으로 남긴다.
  //
  // stock_knd(보통주/우선주)도 groupBy(se) 하나에 안 담기면 같은 항목의
  // 우선주 배당이 보통주 값과 한 계열에서 충돌한다 — compositeGroupFields로
  // 계열 이름도 "항목 (주식종류)"로 쪼갠다. groupFilterSuffix 판정은
  // 계열 이름이 아니라 원래 필드(se)를 그대로 보므로("(원)"으로 끝나는지)
  // 계열을 쪼개도 원 단위 필터링은 그대로 동작한다(chartData의
  // groupFilterField 처리 참고). reprt_code·stock_knd가 없는 레코드
  // (기존 픽스처 등)는 compositeXValue가 있는 필드만으로 자연히 폴백해
  // 이전 동작과 같다.
  dividends: {
    kind: "line", title: "배당 지표 추이 (원 단위 항목만, 연도·보고서코드별)",
    x: "bsns_year", compositeXFields: ["bsns_year", "reprt_code"],
    y: "thstrm", groupBy: "se", compositeGroupFields: ["se", "stock_knd"],
    yLabel: "금액 (원)", xScale: "category", groupFilterSuffix: "(원)",
  },
  // debt_balance.by_kind는 dict라 레코드 리스트가 아니다 — sectionBlocks의
  // 특수 경로(normalizeDebtByKind)가 종류를 debt_kind 열로 뒤집은 레코드를
  // 만들어야 이 스펙이 그릴 수 있다(위 sectionBlocks 주석 참고).
  debt_balance: {
    kind: "bar", title: "채무증권 종류별 잔액", xScale: "category",
    x: "debt_kind", yLabel: "금액",
    series: [
      { key: "total", label: "합계" },
      { key: "maturity_under_1y", label: "1년 이내 만기 금액" },
    ],
  },
  // disclosures는 145건(엔켐 실측)의 개별 공시다 — 월별로 몇 건이었는지는
  // 사실이지만("건수를 세는 것은 사실이다"), "이 달에 몰렸다"고 강조하면
  // 판정이 된다(v0.8.5). monthlyCountOf는 chartData 안에서 건수만 세고
  // 멈춘다 — 순위·강조 없이 막대 높이로만 보여준다. 표는 원본 145행을
  // 그대로 유지한다(집계는 차트 전용 파생값, block.records는 손대지 않는다).
  //
  // **SE-4f Task 3: 단색 막대는 "몇 건"만 보여줄 뿐 "어떤 성격의 공시가
  // 언제 몰렸는지"는 감춘다** — 사용자 요청("공시별 색상 구분"). classifyField
  // (report_nm)가 있고 chartData 호출자가 signalsData(3번째 인자,
  // docs/tool/signals-data.json 로드 결과)를 함께 주면, monthlyCountOf
  // 처리(아래 chartData)가 월별 집계를 카테고리별로 더 잘게 쪼개
  // stacked bar(누적 막대)로 그린다 — 로직은 새로 만들지 않는다.
  // classifyDisclosureCategory·monthlyCountsByCategory가 docs/tool/
  // index.html의 matchSignals·AMEND_RE를 그대로 재현한다(브리프).
  // signalsData가 없거나(로드 실패) 형태가 예상과 다르면 chartData가
  // 자동으로 이전 단색-단일 계열 집계로 물러난다 — 화면이 죽지 않는다.
  // stacked:true는 renderChart(ui.js)가 Chart.js scales.x/y.stacked로
  // 그대로 옮긴다. 색은 카테고리(유형) 구분 전용이다 — 특정 유형에
  // 판정 색(--red)을 주거나 "위험"류 문구를 덧붙이지 않는다(v0.8.5).
  disclosures: {
    kind: "bar", title: "월별 공시 건수 (유형별)", xScale: "category", stacked: true,
    monthlyCountOf: "rcept_dt", classifyField: "report_nm", yLabel: "건수",
  },
  // financialRatios(위)가 만든 파생 레코드(구분·기간·지표·값)를 그린다.
  // financials 원본과 달리 이 레코드는 이미 fs_div를 "구분"(연결/별도)
  // 문자열로 정규화했고, 같은 계정명이 두 재무제표에 겹쳐 나오는 문제
  // 자체가 없다(계산 시점에 이미 갈랐다) — 그래도 "지표"만으로 계열을
  // 나누면 연결 영업이익률과 별도 영업이익률이 같은 계열(같은 이름)에서
  // 충돌한다. compositeGroupFields로 "지표 (구분)"를 계열 이름으로 쪼갠다
  // (dividends의 se×stock_knd와 같은 방식, 위 CHART_SPECS.dividends 주석
  // 참고). x는 "기간"("전전기"/"전기"/"당기" — 숫자가 없는 순수 범주형이라
  // chartData가 정렬하지 않고 등장 순서를 그대로 쓴다, chartData 주석 ③) —
  // financialRatios가 전전기→전기→당기 순으로 내보내므로 그 등장 순서가
  // 곧 시간순이다(위 RATIO_PERIODS 주석 참고). 다섯 지표 모두 단위가 %로
  // 같으므로(dividends처럼 원/%가 섞이는 문제가 없다) 한 y축에 같이 그려도
  // 스케일이 왜곡되지 않는다.
  financial_ratios: {
    kind: "line", title: "재무 파생 지표 추이 (%, 연결·별도 구분)",
    x: "기간", groupBy: "지표", compositeGroupFields: ["지표", "구분"],
    y: "값", yLabel: "%", xScale: "category",
  },
  // affiliateOverview(위)가 최초취득일(frst_acqs_de) 순으로 재배열한
  // 레코드를 그린다(SE-4f Task 5). x는 원본 필드 inv_prm(피출자 법인명)을
  // 그대로 쓴다 — chartData의 x축 정렬 규칙(위 xs.sort 주석 ①~③) 상, x값
  // 전부가 숫자를 포함해야만(allHaveDigits) 정렬이 다시 일어나는데, 실측
  // (엔켐 27건)처럼 회사명 중 하나라도 숫자가 전혀 없으면(예: "중앙첨단소재")
  // 정렬 자체가 스킵되고 affiliateOverview가 만든 순서(등장 순서)가 그대로
  // 보존된다 — 그래서 새 합성 필드를 만들지 않고 inv_prm을 그대로 x로 쓴다.
  //
  // **주의(문서화된 한계)**: 만약 어느 회사의 피출자 법인명 전부가 우연히
  // 숫자를 포함하면(예: 전부 "2025 ○○투자조합" 식) chartData가 그 숫자
  // 기준으로 다시 정렬해 최초취득일 순서와 달라질 수 있다 — 실제 회사·조합명
  // 목록에서는 매우 드문 경우라 별도 방어(합성 라벨 등)를 두지 않았다.
  // compositeXFields로 날짜를 x에 섞어 이 위험을 없애는 방법도 검토했지만,
  // "2022 대신-SBI 코넥스 스케일업 펀드"처럼 회사명 자체에 4자리 연도가
  // 박힌 실측 사례(엔켐)가 axisSortKey(문자열 전체의 숫자를 모두 이어붙임)를
  // 오염시켜 오히려 더 나쁜 순서를 만든다는 것을 확인했다 — 그래서 합성하지
  // 않는 쪽을 택했다.
  //
  // series는 기초→기말 장부가액 두 계열이다 — "이번 사업연도 안에서 규모가
  // 늘었나 줄었나"(브리프 판정선: 허용)만 보여줄 뿐, "집중 투자 시기" 같은
  // 해석은 붙이지 않는다(v0.8.5). 여러 해에 걸친 추이는 이 데이터(한 사업연도
  // 스냅샷)로 만들 수 없다 — buildAffiliateOverviewBlock(ui.js)의 안내문이
  // 그 한계를 그대로 말한다.
  affiliate_timeline: {
    kind: "bar", title: "출자 규모 — 최초취득일 순 (기초→기말 장부가액)",
    x: "inv_prm", xScale: "category", yLabel: "장부가액",
    series: [
      { key: "bsis_blce_acntbk_amount", label: "기초 장부가액" },
      { key: "trmend_blce_acntbk_amount", label: "기말 장부가액" },
    ],
  },
  // SE-4h Task 3 — 재무지표 분류별 추이. indicatorChartRecords(아래,
  // indicatorBlocks 다음에 정의)가 그 분류의 primary 지표 중 값이 하나라도
  // 있는 행만 걸러 넘기므로, 여기 스펙 자체는 financial_ratios와 같은 모양
  // (x=연도, groupBy=지표, y=값)이면 충분하다. bsns_year 값("2025" 등)은
  // 순수 숫자 문자열이라 chartData의 allNumeric 분기(위 xs.sort 주석 ①)에
  // 걸려 항상 오름차순(과거→최근)으로 정렬된다 — fetch_indicator_history가
  // 최근 연도부터 내려오는 순서로 행을 줘도(dart_client.py) 여기서 뒤집을
  // 필요가 없다.
  //
  // **활동성 단위(크기) 혼입 결정 — 그대로 둔다(브리프 요구사항: 이유를
  // 남긴다).** 활동성 primary 5개(총자산회전율·매출채권회전율·
  // 재고자산회전율·매입채무회전율·배당성향(%))는 전부 DART 원본이 %라
  // *단위*는 섞이지 않는다(dividends의 원/%처럼 서로 다른 단위가 섞이는
  // 문제가 아니다) — 다만 *자릿수*가 갈린다(엔켐 실측: 재고자산회전율
  // 454.463 대 총자산회전율 27.6, 약 16배 차이). 검토한 대안과 기각 이유:
  // ① **두 번째 y축(yAxisID)** — renderChart(ui.js)는 이 화면의 다른 8개
  //   스펙 전부가 y축 하나만 쓴다는 전제로 색·범례·툴팁 배선이 돼 있다.
  //   이 스펙 하나만 예외로 두 번째 스케일을 추가하면 그 공용 배선을 다시
  //   검증해야 하는데(다른 스펙에 영향이 없는지), 위험 대비 이득이 작다.
  //   또한 어느 지표를 "주 축"에 두고 어느 지표를 "보조 축"에 둘지 우리가
  //   고르는 순간 그 배치 자체가 이미 판단("이 지표가 더 중요하다")이라
  //   v0.8.5 판정 금지 원칙과 결이 어긋난다.
  // ② **계열 줄이기(예: 재고자산회전율만 차트에서 제외)** — 결국 "이 지표는
  //   차트에 넣을 만큼 안 중요하다"는 값매김과 같은 부류의 선택이다.
  // 그래서 **그대로 한 축에 둔다**: 계열이 눌려 보이는 것은 표현의 한계일
  // 뿐 정보 손실이 아니다 — 정확한 숫자는 이 차트 바로 아래 primary
  // 표(indicatorTableEl)와 툴팁(renderChart의 formatValue 콜백)이 항상
  // 그대로 보여준다(브리프: "차트는 표를 대체하지 않는다", renderChart 주석
  // 과 같은 원칙).
  // tooltipFormat: "indicator" — 툴팁 값을 formatIndicator로 포맷하라는
  // 표시다(renderChart, ui.js). 없으면 표는 "130.248%"인데 툴팁은
  // "130.248"이라 같은 값을 둘이 다르게 말한다(리뷰 지적 ④).
  indicators_수익성: {
    kind: "line", title: "수익성 추이 (%)",
    x: "bsns_year", groupBy: "idx_nm", y: "idx_val", yLabel: "%", xScale: "category",
    tooltipFormat: "indicator",
  },
  indicators_안정성: {
    kind: "line", title: "안정성 추이 (%)",
    x: "bsns_year", groupBy: "idx_nm", y: "idx_val", yLabel: "%", xScale: "category",
    tooltipFormat: "indicator",
  },
  // 성장성 18개는 이미 전년 대비 증가율(YoY)이다(indicatorBlocks 주석 참고)
  // — 그 증가율의 연도별 추이를 선으로 그린다. 레벨 지표(다른 분류)와 한
  // 차트에 섞이는 문제는 분류별로 스펙이 나뉘어 자동으로 해결된다(브리프)
  // — 여기서는 축 라벨만 "%"로 맞춘다.
  indicators_성장성: {
    kind: "line", title: "성장성(증가율) 추이 (%)",
    x: "bsns_year", groupBy: "idx_nm", y: "idx_val", yLabel: "%", xScale: "category",
    tooltipFormat: "indicator",
  },
  indicators_활동성: {
    kind: "line", title: "활동성 추이 (%)",
    x: "bsns_year", groupBy: "idx_nm", y: "idx_val", yLabel: "%", xScale: "category",
    tooltipFormat: "indicator",
  },
});

/** "20260415" → "2026.04.15", "2026-04-15" → "2026.04.15". 날짜가 아니면
 *  원본을 그대로 쓴다.
 *
 *  실측(field-inventory)에서 insider_timeline.rcept_dt는 "2026-04-15"처럼
 *  하이픈이 있는 10자 문자열이다 — 브리프가 예시로 준 8자리 숫자
 *  ("20260415")와 다르다. 8자리 숫자 분기만 있으면 이 실측 형태가 어느
 *  분기에도 걸리지 않아 하이픈이 그대로 노출된다(리뷰 지적 ④). 두 형태
 *  모두 "."로 통일해 화면 표기가 일관되게 한다. */
function axisLabel(v) {
  const s = v === null || v === undefined ? "" : String(v);
  if (/^\d{8}$/.test(s)) return s.slice(0, 4) + "." + s.slice(4, 6) + "." + s.slice(6, 8);
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s.replace(/-/g, ".");
  // disclosures 월별 집계(monthlyCounts)가 만드는 "YYYYMM"(6자리) 라벨.
  // 8자리 분기보다 뒤에 둬야 한다 — 정규식 자체는 서로 겹치지 않지만
  // (자릿수가 다르다) 읽는 순서를 날짜 특이 형태 → 일반형 순으로 유지한다.
  if (/^\d{6}$/.test(s)) return s.slice(0, 4) + "." + s.slice(4, 6);
  return s;
}

/** 숫자로 읽는다. 읽을 수 없으면 null — **0으로 채우지 않는다.**
 *  0으로 채우면 "그 시점에 0이었다"는 거짓말이 된다.
 *
 *  배열·객체는 애초에 숫자가 아니다 — 걸러내지 않으면 String([5])가 "5"로
 *  우연히 읽혀 배열이 숫자인 척한다(리뷰 지적 ⑦).
 *
 *  쉼표는 "13,082,000,000"처럼 천 단위를 3자리씩 묶을 때만 벗긴다.
 *  "1,2,3"처럼 자릿수가 안 맞는 문자열까지 쉼표를 무조건 지우면
 *  "123"이라는 없는 숫자를 만들어낸다(리뷰 지적 ⑦) — 쉼표가 있는데
 *  이 형태에 안 맞으면 애초에 숫자로 보지 않는다. */
function numeric(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === "object") return null;
  const raw = String(v).trim();
  if (raw === "") return null;
  if (raw.indexOf(",") !== -1 && !/^-?\d{1,3}(,\d{3})*(\.\d+)?$/.test(raw)) return null;
  const s = raw.replace(/,/g, "");
  if (!/^-?\d*\.?\d+$/.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** x축 정렬용 보조키: 문자열에 있는 숫자만 이어붙여 정수로 읽는다. 숫자가
 *  전혀 없으면(예: "유동자산") null이다.
 *
 *  numeric()과 다른 함수다 — numeric()은 "이 값 자체가 숫자다"를 요구하고
 *  (예: "제14회"는 실패), 이 함수는 "이 값 안에 정렬 기준이 될 숫자가
 *  있다"만 본다("제14회" → 14). fund_usage.tm의 실측 형태가 "제14회"처럼
 *  숫자가 아닌 문자로 감싸여 있어(리뷰 지적 ①) numeric()만으로는
 *  회차 정렬이 항상 실패한다 — 문자열 정렬(사전식)로 빠지면 "제10회"가
 *  "제9회"보다 앞에 와 그래프가 거짓말을 한다.
 *
 *  "20260415"·"2026-04-15"처럼 형식이 섞인 날짜도 숫자만 이으면 같은
 *  값(20260415)이 되어 시간순이 그대로 유지된다 — 날짜 축은 이 함수
 *  하나로 8자리·하이픈 두 형태를 모두 옳게 정렬한다. */
function axisSortKey(v) {
  const s = v === null || v === undefined ? "" : String(v);
  const digits = s.replace(/[^0-9]/g, "");
  if (digits === "") return null;
  const n = Number(digits);
  return Number.isFinite(n) ? n : null;
}

/** field(예: rcept_dt) 값을 월(YYYYMM, 6자리)로 묶어 건수만 센다.
 *
 * **집계는 여기서 끝난다.** 어떤 달이 많았는지 강조하거나 순위를 매기지
 * 않는다 — 그건 판정이다(v0.8.5, disclosures 브리프의 "막대만 그리고
 * 강조하지 않는다"). axisSortKey와 같은 방식으로 문자열에서 숫자만 뽑아
 * 앞 6자리를 쓰므로 "20260415"·"2026-04-15" 두 형태 모두 같은 월
 * (202604)로 묶인다. 등장 순서를 그대로 보존해 반환한다 — chartData가
 * 이어서 xs를 숫자로(모두 6자리 숫자이므로) 시간순 정렬한다. */
function monthlyCounts(rows, field) {
  const counts = new Map();
  const order = [];
  for (const r of rows) {
    const raw = r[field];
    if (raw === null || raw === undefined || raw === "") continue;
    const digits = String(raw).replace(/[^0-9]/g, "");
    if (digits.length < 6) continue; // 월을 특정할 수 없다 — 건너뛴다(0으로 세지 않는다)
    const month = digits.slice(0, 6);
    if (!counts.has(month)) { counts.set(month, 0); order.push(month); }
    counts.set(month, counts.get(month) + 1);
  }
  return order.map(function (m) { return { month: m, count: counts.get(m) }; });
}

/** reportNm 하나를 signalsData(docs/tool/signals-data.json 로드 결과) 기준
 *  으로 분류해 카테고리 번호(0~8, 0="기타")를 돌려준다. docs/tool/
 *  index.html의 matchSignals(564행)·AMEND_RE와 같은 로직이다(브리프:
 *  "로직을 새로 만들지 마라 — 읽어서 맞춘다. 같은 공시를 공개 뷰어와
 *  SE가 다르게 분류하면 그 자체가 결함") — 정정공시([기재정정] 등,
 *  signalsData.amendment_pattern)는 공개 뷰어와 마찬가지로 신호를 매기지
 *  않고 그대로 "기타"(0)로 남긴다.
 *
 *  **공시 하나는 정확히 한 카테고리에만 속한다.** matchSignals(공개
 *  뷰어)는 여러 신호가 동시에 걸리면 배열 전부를 돌려주지만, 여기서는
 *  signals 배열 순서상 첫 매칭만 쓴다 — 월별 스택 막대에서 한 공시를
 *  두 카테고리에 겹쳐 세면 막대 합이 원본 건수를 넘어서는 거짓말이
 *  된다(브리프: "월별 합계가 원본 건수와 일치해야 합니다").
 *
 *  signalsData가 없거나 signals 배열을 갖추지 못한 예상 밖 형태면(로드
 *  실패·형태 변경) null을 돌려준다 — 호출자가 분류를 포기하고 기존
 *  단색 집계로 물러나는 신호다(브리프: "로드 실패에 대비하세요"). */
function classifyDisclosureCategory(reportNm, signalsData) {
  if (!signalsData || !Array.isArray(signalsData.signals)) return null;
  const nm = typeof reportNm === "string" ? reportNm : "";
  if (typeof signalsData.amendment_pattern === "string") {
    try {
      if (new RegExp(signalsData.amendment_pattern).test(nm)) return 0;
    } catch (e) {
      // 정규식 자체가 깨졌으면(예상 밖 데이터) 정정 판정만 건너뛰고
      // 아래 키워드 매칭으로 이어간다 — 분류를 통째로 포기하지 않는다.
    }
  }
  for (const s of signalsData.signals) {
    const keywords = Array.isArray(s.keywords) ? s.keywords : [];
    for (const kw of keywords) {
      if (kw && nm.indexOf(kw) !== -1) {
        return typeof s.category === "number" ? s.category : 0;
      }
    }
  }
  return 0;
}

/** rows(disclosures 원본 레코드)를 월(YYYYMM)×카테고리 라벨별 건수로
 *  묶는다. monthlyCounts와 같은 원칙 — **집계는 여기서 끝난다.** 어떤
 *  유형이 많았는지 순위를 매기거나 강조하지 않는다(v0.8.5).
 *
 *  카테고리 라벨은 signalsData.categories(예: {"0":"기타","1":"CB/채권",
 *  ...})를 그대로 쓴다 — 우리가 문구를 새로 짓거나 덧붙이지 않는다
 *  (브리프: "signals-data.json의 label에 판정처럼 읽히는 것이 있으면
 *  그대로 쓰되 우리가 덧붙이지는 마세요"). 못 찾으면(예상 밖 카테고리
 *  번호) "기타"로 남긴다 — 조용히 빠뜨리지 않는다.
 *
 *  반환은 [{month, category, count}] — chartData가 이 모양을 그대로
 *  groupBy(y="count", groupBy="category") 경로로 넘겨 재사용한다(새
 *  렌더 분기를 만들지 않는다, monthlyCountOf의 기존 재사용 방식과
 *  같다). 월별 합계가 원본 건수와 일치한다 — 공시 하나는
 *  classifyDisclosureCategory로 정확히 한 카테고리에만 잡힌다. */
function monthlyCountsByCategory(rows, dateField, textField, signalsData) {
  const monthOrder = [];
  const byMonth = new Map(); // month -> Map(label -> count)
  for (const r of rows) {
    const raw = r[dateField];
    if (raw === null || raw === undefined || raw === "") continue;
    const digits = String(raw).replace(/[^0-9]/g, "");
    if (digits.length < 6) continue; // 월을 특정할 수 없다 — 건너뛴다(0으로 세지 않는다)
    const month = digits.slice(0, 6);
    const cat = classifyDisclosureCategory(r[textField], signalsData);
    const catKey = cat === null ? 0 : cat;
    const label = (signalsData.categories && signalsData.categories[String(catKey)]) || "기타";
    if (!byMonth.has(month)) { byMonth.set(month, new Map()); monthOrder.push(month); }
    const perLabel = byMonth.get(month);
    perLabel.set(label, (perLabel.get(label) || 0) + 1);
  }
  const out = [];
  for (const month of monthOrder) {
    for (const [label, count] of byMonth.get(month)) {
      out.push({ month: month, category: label, count: count });
    }
  }
  return out;
}

/** row에서 fields의 값들을 이어 x축 표시용 문자열 하나로 합친다.
 *
 *  fund_usage처럼 한 필드(tm=회차)만으로는 서로 다른 레코드를 구분하지
 *  못할 때 쓴다(위 CHART_SPECS.fund_usage 주석 참고, 리뷰 지적 ①). 비어
 *  있는 필드는 건너뛴다 — year가 없는 레코드(테스트 픽스처 등)에서는
 *  자연히 tm 하나만 남아 이전 동작과 같아진다. 값이 하나도 없으면(모든
 *  필드가 비어 있으면) null — chartData의 기존 "축 값 없으면 건너뛴다"
 *  처리에 그대로 흡수된다.
 *
 *  "제14회 (2025)" 형태로 만든다 — axisSortKey는 문자가 아니라 문자열에
 *  포함된 숫자만 이어붙여 정렬 기준을 삼으므로("제14회 (2025)" →
 *  "142025"), year가 언제나 4자리인 한(달력 연도라 사실상 항상 그렇다)
 *  이 값은 정확히 "회차*10000+연도"와 같아 회차가 먼저, 같은 회차 안에서는
 *  연도가 나중 기준으로 정렬된다 — 별도 비교 함수를 새로 만들 필요가 없다.
 */
function compositeXValue(row, fields) {
  const parts = fields
    .map(function (f) { return row[f]; })
    .filter(function (v) { return v !== null && v !== undefined && v !== ""; })
    .map(String);
  if (parts.length === 0) return null;
  if (parts.length === 1) return parts[0];
  return parts[0] + " (" + parts.slice(1).join(", ") + ")";
}

/** data[i]에 값을 채운다. 아직 비어 있으면 그대로 채우고, 이미 다른
 *  non-null 값이 있는데 새 값이 다르면(진짜 충돌) 그 자리를 null로
 *  되돌리고 다시는 채우지 않는다.
 *
 *  **왜 필요한가.** fund_usage(같은 회차가 보고 시점마다 반복 수집)와
 *  dividends(같은 항목이 분기 보고서마다 반복 수집)에서 실제로 났던
 *  사고가 같은 뿌리다 — 같은 x축 점(같은 회차, 같은 연도)에 서로 다른
 *  값(계획금액 130.82억 vs 352.91억 vs 476.57억, 또는 주당순이익
 *  -3,154원 vs 121원처럼 부호까지 다른 값)이 들어오면, 이전에는 뒤
 *  레코드가 앞을 조용히 덮어 마지막 값 하나만 살아남았다 — 표는 그
 *  값들을 전부 보여주는데 차트는 그중 하나가 "the" 값인 것처럼 그렸다.
 *  compositeXFields·compositeGroupFields로 x/계열 키를 넓혀 우선 최대한
 *  갈라내지만(위 CHART_SPECS.fund_usage·dividends 주석), 정규화 과정에서
 *  탈락한 필드(예: fund_usage의 reprt_code)가 있으면 키를 아무리 넓혀도
 *  가끔 여전히 충돌한다 — 이 함수는 그 **남는** 충돌을 잡는 마지막 방어선
 *  이다. 어느 쪽이 맞는지 차트가 판정해 하나를 고르면 안 된다(v0.8.5,
 *  이 화면의 "조용히 하나만 남기지 않는다" 원칙) — 그래서 고르지 않고
 *  null로 만든다. 표(block.records)는 이 함수를 거치지 않으므로 값이
 *  사라지지 않는다.
 *
 *  같은 값이 반복되는 것은 충돌이 아니다(data[i] !== v로 실제 값 차이만
 *  본다) — 같은 레코드가 우연히 두 번 들어와도 차트가 사라지면 안 된다.
 *
 *  conflicted는 xs와 같은 길이의 boolean 배열이다. 한 번 충돌한 자리는
 *  잠가서, 세 번째 레코드가 먼저 두 값 중 하나와 우연히 같아도(예: v1,
 *  v2, v1 순서) 충돌 사실이 사라지고 값이 되살아나는 일이 없게 한다. */
function writeChartCell(data, conflicted, i, v) {
  if (conflicted[i]) return;
  if (data[i] === null) {
    data[i] = v;
  } else if (data[i] !== v) {
    data[i] = null;
    conflicted[i] = true;
  }
}

/** 레코드 목록을 Chart.js가 받는 형태로 바꾼다. 그릴 게 없으면 null.
 *
 *  signalsData(3번째 인자, 선택)는 disclosures(classifyField가 있는
 *  스펙)에서만 쓰인다 — docs/tool/signals-data.json 로드 결과를 그대로
 *  넘긴다. **순수 함수 계약을 지킨다**(브리프: "순수 함수는 분류 데이터를
 *  인자로 받아 순수하게 유지"): 이 함수 스스로 fetch하거나 전역을 읽지
 *  않는다 — 같은 세 인자에는 항상 같은 결과다. */
function chartData(records, spec, signalsData) {
  if (!Array.isArray(records) || records.length === 0 || !spec) return null;
  let rows = records.filter(function (r) { return r && typeof r === "object"; });
  if (rows.length === 0) return null;

  if (spec.monthlyCountOf) {
    // disclosures처럼 개별 레코드가 아니라 "월별 건수"를 그려야 하는
    // 경우다. 표(block.records)는 원본 개별 레코드를 그대로 유지하고,
    // 이 집계는 차트 전용 파생값이다.
    //
    // **SE-4f Task 3**: classifyField(spec)와 유효한 signalsData가 함께
    // 있으면 월별 건수를 카테고리별로 더 잘게 쪼갠다(monthlyCountsByCategory)
    // — 아래로는 x="month", groupBy="category", y="count"인 기존 groupBy
    // 렌더 경로를 그대로 재사용한다(새 렌더 분기를 만들지 않는다). 그
    // 조건이 아니면(호출자가 signalsData를 안 줬거나 — 기존 2-인자
    // 호출부와 그대로 호환 — 로드에 실패해 형태가 깨졌으면) 이전과 똑같이
    // x="month", series=[{key:"count"}] 단일 계열로 물러난다(브리프:
    // "로드 실패에 대비하세요" — 차트가 죽지 않고 기존 단색 막대가 된다).
    const canClassify = !!spec.classifyField && !!signalsData
      && Array.isArray(signalsData.signals)
      && signalsData.categories && typeof signalsData.categories === "object";
    if (canClassify) {
      rows = monthlyCountsByCategory(rows, spec.monthlyCountOf, spec.classifyField, signalsData);
      if (rows.length === 0) return null;
      spec = Object.assign({}, spec, { x: "month", groupBy: "category", y: "count" });
    } else {
      rows = monthlyCounts(rows, spec.monthlyCountOf);
      if (rows.length === 0) return null;
      spec = Object.assign({}, spec, {
        x: "month",
        series: [{ key: "count", label: spec.yLabel || "건수" }],
      });
    }
  }

  if (spec.compositeXFields) {
    // fund_usage(리뷰 지적 ①) — x 하나(tm)만으로는 같은 회차의 서로 다른
    // 보고 시점을 구분하지 못해 뒤 레코드가 앞을 덮는다. __composite_x를
    // 만들어 spec.x를 그쪽으로 돌린다 — 아래 xs 구성·series/groupBy 분기는
    // 손대지 않고 그대로 재사용한다(새 렌더 분기를 만들지 않는다, 다른
    // monthlyCountOf 처리와 같은 방식).
    const fields = spec.compositeXFields;
    rows = rows.map(function (r) {
      const copy = Object.assign({}, r);
      copy.__composite_x = compositeXValue(r, fields);
      return copy;
    });
    spec = Object.assign({}, spec, { x: "__composite_x" });
  }

  if (spec.compositeGroupFields) {
    // dividends(라이브 재리뷰 Critical ②) — stock_knd(보통주/우선주)가
    // groupBy(se) 하나에 안 담기면 같은 항목의 우선주 배당이 보통주 값과
    // 한 계열에서 충돌한다. __composite_group을 만들어 spec.groupBy를
    // 그쪽으로 돌린다 — compositeXFields와 같은 방식(새 렌더 분기를
    // 만들지 않는다)이지만, groupFilterSuffix 판정(예: "(원)"으로
    // 끝나는지)은 계열 이름이 아니라 **원래** 필드(예: se)를 봐야 하므로
    // groupFilterField에 원래 groupBy를 남겨 둔다 — 아래 groupBy 분기가
    // 이 필드로 필터링하고, 계열 이름 자체는 합성 필드를 쓴다.
    const gfields = spec.compositeGroupFields;
    const filterField = spec.groupFilterField || spec.groupBy;
    rows = rows.map(function (r) {
      const copy = Object.assign({}, r);
      copy.__composite_group = compositeXValue(r, gfields);
      return copy;
    });
    spec = Object.assign({}, spec, { groupBy: "__composite_group", groupFilterField: filterField });
  }

  const xs = [];
  const seen = new Set();
  for (const r of rows) {
    const raw = r[spec.x];
    if (raw === null || raw === undefined || raw === "") continue;
    const key = String(raw);
    if (!seen.has(key)) { seen.add(key); xs.push(key); }
  }
  if (xs.length === 0) return null;
  // 정렬 기준 3단계(리뷰 지적 ①⑤):
  // 1) 값 전부가 순수 숫자면(예: "9","10") 숫자로 정렬한다.
  // 2) 아니지만 전부 숫자를 품고 있으면(예: "제14회", "2026-04-15")
  //    그 숫자로 정렬한다 — axisSortKey가 문자를 벗기고 숫자만 비교하므로
  //    "제9회"가 "제14회"보다 앞에 온다(회차 정렬이 실제로 통한다).
  // 3) 숫자가 전혀 없는 순수 범주형(예: "유동자산")은 정렬하지 않고
  //    원본 등장 순서를 그대로 둔다. **`xs.sort(undefined)`를 여기 쓰면
  //    안 된다** — comparator 없는 Array.prototype.sort는 기본값이 아니라
  //    문자열 사전식 비교라 계정과목이 가나다순으로 뒤바뀐다(실제로 났던
  //    사고, 리뷰 지적 ⑤). 정렬하지 않으려면 sort 자체를 호출하지 않아야
  //    한다.
  const allNumeric = xs.every(function (v) { return numeric(v) !== null; });
  if (allNumeric) {
    xs.sort(function (a, b) { return numeric(a) - numeric(b); });
  } else {
    const allHaveDigits = xs.every(function (v) { return axisSortKey(v) !== null; });
    if (allHaveDigits) {
      xs.sort(function (a, b) { return axisSortKey(a) - axisSortKey(b); });
    }
  }
  const labels = xs.map(axisLabel);
  const at = new Map(xs.map(function (v, i) { return [v, i]; }));

  const datasets = [];
  if (spec.series) {
    // 같은 x에 여러 계열(계획 vs 실제 등)
    for (const s of spec.series) {
      const data = xs.map(function () { return null; });
      // 충돌 감지(writeChartCell)는 x축 점 단위(conflicted[i])로 잠긴다 —
      // 계열(series)마다 별도 배열이어야 한다. 같은 x에서 "계획 금액"이
      // 충돌해도 "실제 집행 금액"까지 덩달아 null이 되면 안 된다.
      const conflicted = xs.map(function () { return false; });
      for (const r of rows) {
        const i = at.get(String(r[spec.x]));
        if (i === undefined) continue;
        const v = numeric(r[s.key]);
        // 같은 x(예: 같은 tm)에 레코드가 둘 이상 있을 수 있다(실측: kind가
        // 상수열이 아니라 회차가 겹친다) — 값이 없는 레코드(v === null)는
        // 건너뛴다(0으로 채우는 것과 같은 부류의 거짓말이 되므로). 값이
        // 있는데 이미 채운 값과 다르면(진짜 충돌) writeChartCell이 그
        // 자리를 null로 되돌린다 — 조용히 마지막 값만 남기지 않는다(위
        // writeChartCell 주석 참고, 실제 사례: fund_usage 리뷰 지적 ①).
        if (v !== null) writeChartCell(data, conflicted, i, v);
      }
      datasets.push({ label: s.label, data: data });
    }
  } else {
    // groupBy로 계열을 나눈다(보고자별 등)
    const groups = new Map();
    const groupConflicts = new Map();
    for (const r of rows) {
      const g = r[spec.groupBy];
      if (g === null || g === undefined || g === "") continue;
      const name = String(g);
      // dividends의 se(항목)처럼 그룹 이름에 단위가 다른 값(원/%/백만원/주)이
      // 섞여 있으면 한 축에 그리는 순간 스케일을 왜곡해 보여준다(위
      // CHART_SPECS.dividends 주석 참고) — groupFilterSuffix가 있으면 그
      // 접미어로 끝나는 이름만 계열로 만든다. 판정은 groupFilterField(없으면
      // groupBy 자신)로 한다 — compositeGroupFields로 groupBy가 합성
      // 필드(__composite_group)로 바뀐 경우에도, 필터는 항상 원래 필드
      // (예: se)의 값을 봐야 "(원)"으로 끝나는지를 정확히 판단한다(합성된
      // "항목 (주식종류)"는 "(원)"으로 끝나지 않으니 계열 이름으로 판정하면
      // 전부 걸러진다). 제외된 항목은 차트에서만 빠질 뿐 표(block.records)
      // 에는 그대로 남는다.
      if (spec.groupFilterSuffix) {
        const filterField = spec.groupFilterField || spec.groupBy;
        const fv = r[filterField];
        const filterName = (fv === null || fv === undefined) ? "" : String(fv);
        if (filterName.slice(-spec.groupFilterSuffix.length) !== spec.groupFilterSuffix) {
          continue;
        }
      }
      if (!groups.has(name)) {
        groups.set(name, xs.map(function () { return null; }));
        groupConflicts.set(name, xs.map(function () { return false; }));
      }
      const i = at.get(String(r[spec.x]));
      if (i === undefined) continue;
      const v = numeric(r[spec.y]);
      // 위 series 분기와 같은 이유·같은 함수(writeChartCell) — 값 없는
      // 레코드는 건너뛰고, 값이 있는데 다른 값과 충돌하면 null로 되돌린다.
      if (v !== null) writeChartCell(groups.get(name), groupConflicts.get(name), i, v);
    }
    for (const [name, data] of groups) datasets.push({ label: name, data: data });
  }

  // 값이 하나도 없으면 빈 그림이 된다 — 차트를 만들지 않는다.
  const any = datasets.some(function (d) {
    return d.data.some(function (v) { return v !== null; });
  });
  if (!any) return null;

  return { labels: labels, datasets: datasets };
}

// ── 재무지표 4분류 · 용어 · 단위 (SE-4h Task 2) ───────────────────────────
// fnlttSinglIndx(주요 재무지표)는 4분류(수익성·안정성·성장성·활동성)
// 66개를 idx_cl_nm과 함께 준다(dart_client.fetch_indicator_history, SE-4h
// Task 1). 여기서는 그 분류를 보존해 4블록으로 묶고, 22개 핵심 지표에만
// 뜻을 달아 나머지 44개는 접는다(indicatorBlocks). ui.js가 이 함수들을
// renderSection에서 직접 불러 그린다 — indicators는 더 이상
// sectionBlocks/tableLayout 경로를 타지 않는다(위 tableLayout·flatKeys
// 분기 주석 참고).

// DART 응답의 idx_cl_nm 값 그대로다 — 원본 카탈로그 순서를 우리가 다시
// 정하지 않는다. 이 목록에 없는 분류가 오면(응답이 바뀌는 경우) 버리지
// 않고 맨 뒤에 붙인다(indicatorBlocks 참고).
const INDICATOR_CATEGORY_ORDER = ["수익성", "안정성", "성장성", "활동성"];

// **SE-4h Task 3 라이브 검증에서 발견한 사실**: fnlttSinglIndx의 idx_cl_nm
// 실측값은 "수익성지표"·"안정성지표"·"성장성지표"·"활동성지표"다(2026-07-28
// 엔켐 corp_code=01011526 raw API 재확인 — idx_cl_code=M210000 응답의
// idx_cl_nm이 정확히 "수익성지표"). 계획 문서 "배경" 절이 근거로 삼은
// tmp/indicator_categories.json은 접미어 없는 "수익성" 등으로 적혀 있었는데
// (그 자료가 실제 API와 달랐다), Task 2가 그 값을 그대로 옮겨 위
// INDICATOR_CATEGORY_ORDER·아래 INDICATOR_PRIMARY·INDICATOR_NOTES를 전부
// "지표" 없는 키로 만들었다 — 실 데이터로는 이 키들이 단 하나도 매칭되지
// 않아 `INDICATOR_PRIMARY[category]`가 항상 빈 배열이 되고, primary·뜻·
// (Task 3의) 추이 차트가 전부 죽은 코드였다(indicatorBlocks(rows).primary
// 가 실 데이터에서 언제나 []). 화면 문구("수익성" 등, "지표"를 빼는 쪽이
// 더 자연스럽다)는 그대로 유지하면서, 여기서 DART 원본 접미어만 표준
// 4개 이름으로 정규화해 그 아래 모든 조회(INDICATOR_CATEGORY_ORDER·
// INDICATOR_PRIMARY·INDICATOR_NOTES·indicatorChartRecords)가 실제로
// 동작하게 한다. **알려진 4개 접미어 형태만** 명시적으로 대응하고, 그 외
// (예: "기타", 미래에 DART가 줄 수 있는 다른 분류)는 원본을 그대로
// 통과시킨다 — "지표"로 끝나면 기계적으로 벗기는 규칙을 쓰면, 언젠가 DART가
// 실제로 "OO지표"라는 별개 분류를 새로 주면 의도치 않게 다른 이름과
// 충돌할 수 있다.
const INDICATOR_CATEGORY_ALIASES = Object.assign(Object.create(null), {
  "수익성지표": "수익성",
  "안정성지표": "안정성",
  "성장성지표": "성장성",
  "활동성지표": "활동성",
});

/** DART가 준 분류 원문(idx_cl_nm, 예: "수익성지표")을 화면·조회에 쓰는
 *  표준 이름("수익성")으로 정규화한다. 빈 값은 "기타", 매핑에 없는 값은
 *  원본을 그대로 돌려준다(모르는 분류를 조용히 삼키지 않는다는 이 파일의
 *  원칙과 같다 — indicatorBlocks의 unknown 처리 참고). */
function normalizeIndicatorCategory(raw) {
  const s = (raw === null || raw === undefined || raw === "") ? "기타" : String(raw);
  return INDICATOR_CATEGORY_ALIASES[s] || s;
}

// 분류당 5~6개, 총 22개(브리프: "나머지 44개는 rest로 접는다"). 여기 없는
// 지표(예: 납입자본이익률·자본금회전율 — 자본금이 작으면 값이 폭발한다,
// 엔켐 실측 각각 -657.0·2912.4)는 지우지 않고 indicatorBlocks의 rest로
// 보낸다 — "이름만으로 뜻이 서는 것들"이라 설명 없이 이름만 보여준다.
const INDICATOR_PRIMARY = Object.assign(Object.create(null), {
  "수익성": ["순이익률", "매출총이익률", "매출원가율", "ROE", "판관비율"],
  "안정성": ["부채비율", "자기자본비율", "유동비율", "당좌비율", "이자보상배율", "자본유보율"],
  "성장성": [
    "매출액증가율(YoY)", "영업이익증가율(YoY)", "순이익증가율(YoY)",
    "총자산증가율", "자기자본증가율", "부채총계증가율",
  ],
  "활동성": ["총자산회전율", "매출채권회전율", "재고자산회전율", "매입채무회전율", "배당성향(%)"],
});

// 뜻만 쓰고 값을 평가하지 않는다(v0.8.5 판정선) — 아래 선언문에는
// "높을수록 ~"·"낮으면 ~"·"위험"·"안전" 같은 문장을 쓰지 않는다.
// tests/se/test_se_page_assets.py::TestIndicatorNotesVocabulary가 이
// 선언문(다음 "});"까지)에 판정 어휘가 없는지 기계적으로 검사한다.
const INDICATOR_NOTES = Object.assign(Object.create(null), {
  "순이익률": "매출액 대비 당기순이익의 비율",
  "매출총이익률": "매출액에서 매출원가를 뺀 매출총이익이 매출액의 몇 %인가",
  "매출원가율": "매출액 대비 매출원가의 비율",
  "ROE": "자기자본 대비 당기순이익의 비율",
  "판관비율": "매출액 대비 판매비와관리비의 비율",
  "부채비율": "자기자본 대비 부채총계의 비율 — 빌린 돈이 자기 돈의 몇 %인가",
  "자기자본비율": "총자산 대비 자기자본의 비율",
  "유동비율": "1년 안에 갚을 유동부채 대비, 1년 안에 현금화할 수 있는 유동자산의 비율",
  "당좌비율": "유동자산에서 재고자산을 뺀 당좌자산이 유동부채의 몇 %인가",
  "이자보상배율": "영업이익이 이자비용의 몇 배인가 — 값은 DART가 준 그대로 %로 표시된다",
  // 자본유보율 = (자본잉여금+이익잉여금)/자본금 — 자본잉여금(주식발행초과금
  // 등 납입된 돈)까지 포함한다. "벌어서 쌓아둔 돈"(이익잉여금만)이라고만
  // 쓰면 절반(자본잉여금)을 빼먹은 설명이 된다(리뷰 지적, SE-4h Task 2).
  "자본유보율": "자본잉여금과 이익잉여금을 더한 유보액이 자본금의 몇 %인가",
  "매출액증가율(YoY)": "전년 매출액 대비 이번 사업연도 매출액의 변화율",
  "영업이익증가율(YoY)": "전년 영업이익 대비 이번 사업연도 영업이익의 변화율",
  "순이익증가율(YoY)": "전년 당기순이익 대비 이번 사업연도 당기순이익의 변화율",
  "총자산증가율": "전년 총자산 대비 이번 사업연도 총자산의 변화율",
  "자기자본증가율": "전년 자기자본 대비 이번 사업연도 자기자본의 변화율",
  "부채총계증가율": "전년 부채총계 대비 이번 사업연도 부채총계의 변화율",
  "총자산회전율": "총자산 대비 매출액의 비율",
  "매출채권회전율": "매출채권 대비 매출액의 비율",
  // 재고자산회전율 자체는 매출액 ÷ 재고자산이다("매출원가 ÷ 재고자산"이
  // 아니다 — 그건 DART가 별도로 제공하는 다른 지표다). 엔켐 실측으로
  // 산술 검증: 재고자산회전율 454.463 ÷ (매출원가/재고자산) 456.673 =
  // 0.99516, 매출액÷매출원가(=1/매출원가율)도 0.99516로 일치한다(리뷰
  // 지적, SE-4h Task 2 — 이전 노트가 그 별도 지표의 정의를 옮겨 붙인
  // 오류였다).
  "재고자산회전율": "재고자산 대비 매출액의 비율",
  // 매입채무회전율은 실측 값이 null이라 위 재고자산회전율처럼 산술로 직접
  // 검증하지 못했다(엔켐·삼성전자·셀트리온·두산에너빌리티 4사 모두 DART가
  // null을 준다) — 총자산·매출채권·재고자산·자기자본·자본금회전율이 모두
  // 매출액 기준인 같은 계열이라는 관행에 따라 맞춘 것이다. 주석에만 "추정"
  // 이라 적고 화면에는 단정형으로 내보내면, 우리가 아는 것보다 화면이 더
  // 확신하는 셈이 된다 — **뜻 문구 자체에 추정임을 적는다**(리뷰 지적).
  // 뜻을 아예 지우지 않는 이유: 같은 표의 다른 활동성 지표 4개에는 뜻이
  // 있어 이것만 빈 칸이면 "설명할 수 없는 지표"로 보이는데, 실제로는
  // "설명은 있으나 검증하지 못했다"가 정확한 사실이다.
  "매입채무회전율": "매입채무 대비 매출액의 비율 (추정 — DART 값이 없어 산술로 확인하지 못했습니다)",
  "배당성향(%)": "당기순이익 중 현금배당금총액이 차지하는 비율",
});

/** 표시용 문자열. null·undefined·NaN이면 "—"다 — 값 없음을 조용히
 *  숨기지 않는다(0과는 다른 표기). 이름에 이미 "(%)"가 있으면(예:
 *  "배당성향(%)") %를 더 붙이지 않는다 — 안 그러면 "배당성향(%) 25.1%"
 *  처럼 단위가 중복된다(실측 경고, 계획 문서 "배경" 절 참고). DART가
 *  주는 값은 전부 %다(재무레버리지·이자보상배율처럼 이름이 "배"여도
 *  마찬가지) — 우리가 배수로 환산하지 않는다. 잘못 환산하면 틀린 숫자를
 *  자신 있게 보여주게 된다. */
function formatIndicator(idxNm, idxVal) {
  if (idxVal === null || idxVal === undefined) return "—";
  if (typeof idxVal === "number" && Number.isNaN(idxVal)) return "—";
  const s = String(idxVal);
  const hasPercentInName = typeof idxNm === "string" && idxNm.indexOf("(%)") !== -1;
  return hasPercentInName ? s : s + "%";
}

/** 서버가 준 indicators 값에서 행 목록만 꺼낸다.
 *
 *  fetch_indicator_history(dart_client)는 SE-4h 최종 수정부터 행 목록이
 *  아니라 봉투(`{years_requested, years_retrieved, years_failed, rows}`)를
 *  돌려준다 — 연도가 조용히 빠졌을 때 그 사실을 화면이 말할 수 있어야 하기
 *  때문이다(indicatorYearNote 참고). 예전 형태(행 목록 그대로)도 그대로
 *  받아 준다: 저장된 옛 작업 결과가 남아 있을 수 있고, 이 파일의 다른
 *  함수들처럼 "모르는 형태를 만나면 죽지 않는다"가 원칙이다. */
function indicatorRows(value) {
  if (Array.isArray(value)) return value;
  if (value && typeof value === "object" && Array.isArray(value.rows)) return value.rows;
  return [];
}

/** 요청한 연도보다 실제로 조회된 연도가 적으면 그 사실을 한 문장으로
 *  만든다. 다 조회됐거나(또는 옛 형태라 알 수 없으면) 빈 문자열이다.
 *
 *  **왜 필요한가**: 12콜(4분류 × 3연도) 중 몇 개가 실패해 한 해가 통째로
 *  빠져도, 화면은 남은 한 점을 그대로 "추이"라고 그린다 — 사용자는 그것이
 *  조회 사고인지 그 회사에 자료가 없는 것인지 알 방법이 없다. 덜 보여주면서
 *  다 보여주는 척하지 않기 위해, **어느 해가 실제로 조회됐는지**를 사실로
 *  적는다.
 *
 *  조회 실패(years_failed)와 자료 없음(DART가 013으로 확정 답변)을 구분해
 *  쓴다 — 사용자에게 서로 다른 사실이다. "데이터 부족" 같은 값매김 표현은
 *  쓰지 않는다(v0.8.5: 사실만 적고 판정하지 않는다). */
function indicatorYearNote(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  const requested = Array.isArray(value.years_requested) ? value.years_requested : [];
  const retrieved = Array.isArray(value.years_retrieved) ? value.years_retrieved : [];
  const failed = Array.isArray(value.years_failed) ? value.years_failed : [];
  if (requested.length === 0) return "";
  const missing = requested.filter(function (y) { return retrieved.indexOf(y) === -1; });
  if (missing.length === 0) return "";

  const parts = [
    "최근 " + requested.length + "년(" + requested.join("·") + ") 중 "
      + (retrieved.length > 0
          ? retrieved.join("·") + "만 조회됐습니다"
          : "조회된 연도가 없습니다"),
  ];
  const failedMissing = missing.filter(function (y) { return failed.indexOf(y) !== -1; });
  const absentMissing = missing.filter(function (y) { return failed.indexOf(y) === -1; });
  if (failedMissing.length > 0) {
    parts.push(failedMissing.join("·") + "은 DART 조회에 실패했습니다 — 자료가 없다는 뜻이 아닙니다");
  }
  if (absentMissing.length > 0) {
    parts.push(absentMissing.join("·") + "은 DART에 해당 자료가 없습니다");
  }
  return parts.join(". ") + ".";
}

/** rows({bsns_year, category, idx_nm, idx_val} 행 목록, 또는 그 목록을 담은
 *  fetch_indicator_history 봉투 — indicatorRows가 둘 다 받는다)를 분류별
 *  블록으로 묶는다.
 *
 *  분류 순서는 INDICATOR_CATEGORY_ORDER다. 그 목록에 없는 분류(응답이
 *  바뀌어 새 idx_cl_nm이 오는 경우)는 버리지 않고, 처음 등장한 순서
 *  그대로 맨 뒤에 붙인다 — "모르는 데이터를 조용히 삼키지 않는다"는 이
 *  파일 전체의 원칙과 같다(toRecords·tableLayout 주석 참고).
 *
 *  분류 안에서는 그 분류에 등장한 모든 연도의 합집합을 열로 쓴다 —
 *  지표마다 보고된 연도 수가 달라도(세전계속사업이익률처럼 두 해 다
 *  null이거나, 납입자본이익률처럼 한 해만 오거나) 표의 연도 열은 하나로
 *  맞추고, 없는 칸은 formatIndicator(idxNm, null)이 "—"로 채운다. 연도는
 *  최신이 먼저다.
 *
 *  INDICATOR_PRIMARY에 있는 지표만 note(뜻)를 달아 primary로 보내고,
 *  나머지는 rest로 보낸다 — 값이 전부 null이거나 자본금이 작아 값이 튀는
 *  지표(납입자본이익률 등)도 지우지 않고 rest에 남긴다. */
function indicatorBlocks(value) {
  const rows = indicatorRows(value);
  if (rows.length === 0) return [];

  // category → idx_nm → bsns_year → idx_val. 일반 객체 대신 Map을 쓴다 —
  // 객체 키가 "2025" 같은 정수형 문자열이면 자바스크립트가 삽입 순서와
  // 무관하게 오름차순으로 먼저 나열해 열 순서가 뒤집힌다(ui.js
  // indicatorTableEl 주석에 같은 함정을 적어 뒀다). Map은 이 재정렬이
  // 없다.
  const byCategory = new Map();
  for (const r of rows) {
    if (!r || typeof r !== "object") continue;
    if (r.idx_nm === undefined || r.idx_nm === null || r.idx_nm === "") continue;
    // normalizeIndicatorCategory: DART 원문("수익성지표" 등)을 표준 이름
    // ("수익성")으로 정규화한다 — 위 INDICATOR_CATEGORY_ALIASES 주석 참고
    // (SE-4h Task 3 라이브 검증에서 발견: 정규화 없이는 실 데이터에서
    // primary가 항상 빈 배열이 됐다).
    const category = normalizeIndicatorCategory(r.category);
    if (!byCategory.has(category)) byCategory.set(category, new Map());
    const byName = byCategory.get(category);
    if (!byName.has(r.idx_nm)) byName.set(r.idx_nm, new Map());
    byName.get(r.idx_nm).set(r.bsns_year, r.idx_val === undefined ? null : r.idx_val);
  }

  const present = Array.from(byCategory.keys());
  const known = INDICATOR_CATEGORY_ORDER.filter(function (c) { return present.indexOf(c) !== -1; });
  const unknown = present.filter(function (c) { return INDICATOR_CATEGORY_ORDER.indexOf(c) === -1; });
  const orderedCategories = known.concat(unknown);

  return orderedCategories.map(function (category) {
    const byName = byCategory.get(category);

    const yearSet = new Set();
    byName.forEach(function (byYear) {
      byYear.forEach(function (_v, y) { yearSet.add(y); });
    });
    const years = Array.from(yearSet).sort(function (a, b) { return Number(b) - Number(a); });
    const latestYear = years.length > 0 ? years[0] : null;

    const primaryNames = INDICATOR_PRIMARY[category] || [];
    const primarySet = new Set(primaryNames);
    const allNames = Array.from(byName.keys());

    function buildEntry(idxNm, withNote) {
      const byYear = byName.get(idxNm);
      const cells = years.map(function (y) {
        const v = byYear.has(y) ? byYear.get(y) : null;
        return { bsns_year: y, idx_val: v, display: formatIndicator(idxNm, v) };
      });
      const entry = { idx_nm: idxNm, cells: cells };
      if (withNote) entry.note = INDICATOR_NOTES[idxNm] || "";
      return entry;
    }

    const primary = primaryNames
      .filter(function (n) { return byName.has(n); })
      .map(function (n) { return buildEntry(n, true); });
    const rest = allNames
      .filter(function (n) { return !primarySet.has(n); })
      .map(function (n) { return buildEntry(n, false); });

    return { category: category, latestYear: latestYear, primary: primary, rest: rest };
  });
}

/** indicatorBlocks(rows)가 다루는 것과 같은 원본 행 목록에서, 한 분류
 *  (category)의 INDICATOR_PRIMARY 지표 중 값이 하나라도 있는 것만 걸러
 *  CHART_SPECS.indicators_<분류>가 그릴 수 있는 형태로 되돌린다(SE-4h
 *  Task 3). renderChart(ui.js)에 그대로 넘기는 `records` 인자가 이 함수의
 *  반환값이다.
 *
 *  **왜 indicatorBlocks의 피벗 결과(cells)가 아니라 원본 rows에서 다시
 *  거르나**: chartData(위)는 x=bsns_year·groupBy=idx_nm·y=idx_val인
 *  "평평한" 레코드 목록을 받는 계약이다(financial_ratios와 같은 모양) —
 *  indicatorBlocks가 이미 연도×지표로 피벗해 둔 cells 구조를 다시 풀어
 *  넣는 것보다, 원본에서 한 번만 필터링하는 편이 코드가 적고 chartData·
 *  writeChartCell(충돌 감지)을 그대로 재사용한다(새 렌더 경로를 만들지
 *  않는다, 이 파일의 기존 원칙).
 *
 *  **전 연도가 null인 지표는 계열 자체를 만들지 않는다**(브리프 요구사항
 *  — "선이 0으로 떨어지면 거짓이다"와 같은 이유로, 빈 계열이 범례에 남는
 *  것도 "값이 있는 척"이라 마찬가지로 거짓이다). chartData의 groupBy
 *  분기는 그 지표 이름이 한 번이라도 나오면(값이 전부 null이어도) 계열을
 *  만든다(값 유무와 무관하게 groups.set이 먼저 실행된다) — chartData
 *  자체를 고치면 이 화면 밖의 다른 7개 스펙까지 동작이 바뀌므로, 여기서는
 *  값이 하나도 없는 지표의 행을 아예 넘기지 않는 방식으로 그 지표의
 *  계열이 애초에 생기지 않게 막는다. */
function indicatorChartRecords(value, category) {
  const rows = indicatorRows(value);
  if (rows.length === 0 || !category) return [];
  const primaryNames = INDICATOR_PRIMARY[category] || [];
  if (primaryNames.length === 0) return [];
  const primarySet = new Set(primaryNames);
  // r.category를 그대로 비교하지 않는다 — 실 DART 값은 "수익성지표"처럼
  // 접미어가 붙어 있다(위 INDICATOR_CATEGORY_ALIASES 주석 참고). category
  // 인자(호출자가 넘기는 block.category)는 이미 indicatorBlocks가 정규화한
  // 값이므로, 여기서도 같은 정규화를 거쳐야 서로 비교가 맞는다.
  const filtered = rows.filter(function (r) {
    return r && typeof r === "object"
      && normalizeIndicatorCategory(r.category) === category
      && primarySet.has(r.idx_nm);
  });
  const hasValue = new Set();
  for (const r of filtered) {
    if (numeric(r.idx_val) !== null) hasValue.add(r.idx_nm);
  }
  return filtered.filter(function (r) { return hasValue.has(r.idx_nm); });
}

// ── 사실 강조 ────────────────────────────────────────────────────────────
// 표 안에서 눈으로 놓치기 쉬운 산술적 사실을 셀 단위로 표시한다.
// 강조는 사실의 가시화이지 위험 판정이 아니다 — 규칙은 부호·두 값의 비교·
// 원본 값 동등 비교뿐이고, 임계값("N% 초과")은 두지 않는다(v0.8.5).

// DART는 결측을 null이 아니라 문자열 "-" 로 채운다. 엔켐 타법인 출자
// 27건 중 21건이 그렇다 — "-"를 음수로 읽으면 21건이 전부 잘못 강조된다.
function markNumber(v) {
  if (isNoDataMarker(v)) return null;
  if (typeof v === "number") return isFinite(v) ? v : null;
  const n = Number(String(v).replace(/[,\s]/g, ""));
  return isFinite(n) ? n : null;
}

// 두 값 모두 있을 때만 비교한다. 한쪽이라도 결측이면 강조하지 않는다 —
// 모르는 것을 강조하면 없는 사실을 만들어내는 것이다.
function markLt(a, b) {
  const x = markNumber(a), y = markNumber(b);
  return x !== null && y !== null && x < y;
}

function markNeg(v) {
  const x = markNumber(v);
  return x !== null && x < 0;
}

const MARK_RULES = Object.create(null);

MARK_RULES.affiliates = [
  {
    key: "trmend_blce_acntbk_amount",
    when: function (r) { return markLt(r.trmend_blce_acntbk_amount, r.frst_acqs_amount); },
    why: "기말 장부가액 < 최초 취득금액",
  },
  {
    key: "incrs_dcrs_evl_lstmn",
    when: function (r) { return markNeg(r.incrs_dcrs_evl_lstmn); },
    why: "증감 평가손익 < 0",
  },
  {
    key: "recent_bsns_year_fnnr_sttus_thstrm_ntpf",
    when: function (r) { return markNeg(r.recent_bsns_year_fnnr_sttus_thstrm_ntpf); },
    why: "피투자사 당기순이익 < 0",
  },
];

// "부적정의견"은 부분 문자열 "적정"을 포함한다 — indexOf 로 판정하면
// 가장 무거운 의견을 정상으로 읽는다. 반드시 접두 일치로 본다.
function isCleanOpinion(v) {
  return String(v == null ? "" : v).trim().indexOf("적정") === 0;
}

// fetch_audit_opinion_history(dart_client.py)가 SE 서버로 내보내는 필드는
// "opinion"이다(DART 원본 accnutAdtorNmNdAdtOpinion.json의 필드명은
// adt_opinion이지만, core가 {"year","opinion","auditor","tenure_years",...}
// 로 다시 감싸 반환한다 — dart_client.py fetch_audit_opinion_history
// 반환 docstring 참고). registry.py Stage1Spec("audit_history", ...,
// "fetch_audit_opinion_history", ...)가 이 core 함수를 그대로 부르므로
// SE 화면에 실제로 도달하는 레코드는 opinion이지 adt_opinion이 아니다 —
// DART 원본 필드명을 그대로 옮겨 적으면(리뷰 지적) cellMarks의
// `rule.key in rec` 게이트에 걸려 영원히 발화하지 않는다.
MARK_RULES.audit_history = [
  {
    key: "opinion",
    when: function (r) { return !isNoDataMarker(r.opinion) && !isCleanOpinion(r.opinion); },
    why: '감사의견이 "적정"이 아님',
  },
];

// major_holders(최대주주 현황)에는 합계 행("계")이 사람 이름 자리에 섞여
// 온다. 합계 행에도 기초·기말 지분율이 있어(엔켐 실측 21.63 → 21.04) 규칙이
// 그대로 발화하는데, 그 행의 감소는 바로 위 구성원 행들의 감소를 더한 값일
// 뿐이다 — 같은 사실을 두 번 말하게 된다. track_insider_trading(v0.8.6)이
// 합산 행("계"/"합계")을 건너뛰는 것과 같은 관례를 화면에서도 지킨다.
// 판정은 isAggregateRow 하나에 맡긴다(공백 정규화·"계상혁" 함정이 이미
// 거기서 해결돼 있다 — 여기서 다시 짜면 그 함정도 다시 생긴다).
//
// bulk_holders(5% 대량보유, /majorstock.json 원본 그대로)의 stkrt_irds는
// 우리가 계산한 차이가 아니라 **보고서 자체가 부호를 달아 신고하는 값**
// (보유비율 증감)이다 — insider_timeline의 sp_stock_lmp_irds_rate와 같은
// 부류라 markNeg로 부호만 본다. 필드명은 dart_client.fetch_shareholder_
// status가 majorstock 응답을 개명 없이 그대로 실어 보내는 것을 확인했다
// (audit_history에서 DART 원본 필드명을 그대로 적어 규칙이 영원히
// 발화하지 않았던 사고의 반대 확인 — 여기서는 원본 이름이 곧 화면 이름이다).
MARK_RULES.shareholders = [
  {
    key: "trmend_posesn_stock_qota_rt",
    when: function (r) {
      return !isAggregateRow(r)
        && markLt(r.trmend_posesn_stock_qota_rt, r.bsis_posesn_stock_qota_rt);
    },
    why: "기말 지분율 < 기초 지분율",
  },
  {
    key: "stkrt_irds",
    when: function (r) { return markNeg(r.stkrt_irds); },
    why: "지분율 증감 < 0",
  },
];

// core(signals.is_amendment_disclosure)와 **같은 판별이 아니다.** 여기 규칙은
// "제목 맨 앞 대괄호 안에 '정정'이 들어 있는가" 하나뿐이다(대괄호 밖 본문의
// "정정"은 보지 않는다 — test_amendment_word_outside_bracket_is_not_marked).
// core의 정규식과는 양방향으로 어긋난다: "[첨부정정]"은 여기서 표시되지만
// core는 정정으로 보지 않고, "[첨부추가]"는 core가 정정으로 보지만 여기서는
// 표시하지 않는다(엔켐 실측 145건 중 1건이 실제로 갈렸다). 화면에 붙는
// 라벨("정정공시")은 대괄호 표기 그대로라 어느 쪽도 거짓말이 아니지만,
// 두 판별이 같다고 적어 두면 다음 사람이 한쪽만 고치고 같아졌다고 믿는다.
function isAmendmentName(v) {
  const s = String(v == null ? "" : v).trim();
  if (s.charAt(0) !== "[") return false;
  const close = s.indexOf("]");
  return close > 0 && s.slice(1, close).indexOf("정정") >= 0;
}

MARK_RULES.disclosures = [
  { key: "report_nm", when: function (r) { return isAmendmentName(r.report_nm); }, why: "정정공시" },
];

const MARGIN_INDICATORS = ["영업이익률", "순이익률"];

MARK_RULES.financial_ratios = [
  {
    key: "값",
    when: function (r) { return MARGIN_INDICATORS.indexOf(r["지표"]) >= 0 && markNeg(r["값"]); },
    why: "이익률 < 0",
  },
];

// insider_timeline: elestock 레코드에는 "특정증권 등 소유 증감"을 DART가
// 직접 신고하는 필드가 둘 있다 — sp_stock_lmp_irds_cnt
// (증감 주식수)와 sp_stock_lmp_irds_rate(증감 비율). 우리가 분기 간 차이를
// 계산한 값이 아니라 그 공시 건 자체가 보고하는 부호 있는 값이라 markNeg로
// 부호만 본다.
//
// 두 필드는 반드시 따로 규칙을 둔다. 실측(엔켐 오정강)에서 갈라진다:
//   2024-07-29  증감비율 -1.49   증감수 -32,123   ← 둘 다 감소
//   2025-05-20  증감비율 -0.26   증감수  +6,000   ← 주식은 늘었는데 비율은 감소
// 다른 특정증권 발행 등으로 전체 모수가 늘면 보유 주식수가 늘어도 비율은
// 내려갈 수 있다(희석) — 매도 없이도 벌어지는 일이다. 한 규칙으로 합치면
// 두 번째 행에서 "주식수도 줄었다"는 사실이 아닌 판정을 만들게 된다.
//
// ※ elestock은 **임원·주요주주 특정증권 등 소유상황보고**(opendart_api_
// guide.md §4.2)다. 5% 이상 대량보유 상황보고는 majorstock(§4.1)으로 다른
// 엔드포인트이고 필드도 다르다(stkrt·stkrt_irds — 위 MARK_RULES.shareholders
// 의 bulk_holders 규칙이 그쪽이다). 두 보고를 같은 이름으로 부르면 어느
// 보고서가 무엇을 신고한 것인지가 화면 설명에서 뒤바뀐다.
MARK_RULES.insider_timeline = [
  {
    key: "sp_stock_lmp_irds_cnt",
    when: function (r) { return markNeg(r.sp_stock_lmp_irds_cnt); },
    why: "증감 주식수 < 0",
  },
  {
    key: "sp_stock_lmp_irds_rate",
    when: function (r) { return markNeg(r.sp_stock_lmp_irds_rate); },
    why: "증감 비율 < 0",
  },
];

// 부도·영업정지·회생절차·해산사유 4개 엔드포인트를 통합한 레코드는 존재
// 자체가 사실이라 임계값이 필요 없다 — 레코드가 있다는 것 자체를 표시한다.
MARK_RULES.distress = [
  {
    key: "rcept_no",
    when: function () { return true; },
    why: "부도·영업정지·회생절차·해산사유 중 하나가 보고됨",
  },
];

// 반환 키는 ui.js 의 tableEl()이 이미 계산하는 좌표와 같은 형식이다:
// 가로 표는 (행번호, keys[열]), 세로 표는 (0, keys[행]).
function cellMarks(records, sectionKey) {
  const out = Object.create(null);
  const rules = MARK_RULES[sectionKey];
  if (!Array.isArray(records) || !Array.isArray(rules)) return out;
  records.forEach(function (rec, i) {
    if (!rec || typeof rec !== "object") return;
    for (const rule of rules) {
      if (!(rule.key in rec)) continue;
      let hit = false;
      try { hit = !!rule.when(rec); } catch (e) { hit = false; }
      if (hit) out[i + "|" + rule.key] = rule.why;
    }
  });
  return out;
}

/** cellMarks() 결과에서 강조가 하나라도 붙은 **열 키**만 뽑는다(중복 없이).
 *  tableLayout(records, markedKeys)이 이 목록을 받아 그 열을 접지 않는다 —
 *  좌표 "행번호|열키"에서 첫 "|" 뒤가 열 키다(열 키 자체에 "|"가 들어갈 일은
 *  없지만, split이 아니라 indexOf로 자르는 편이 그 가정에 덜 기댄다). */
function markedColumnKeys(marks) {
  const out = [];
  const seen = new Set();
  if (!marks || typeof marks !== "object") return out;
  for (const coord of Object.keys(marks)) {
    const bar = coord.indexOf("|");
    if (bar < 0) continue;
    const key = coord.slice(bar + 1);
    if (!seen.has(key)) { seen.add(key); out.push(key); }
  }
  return out;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    LS_DART_KEY, LS_SESSION, LS_JOB, LS_THEME, SECTION_GROUPS, formatCount,
    nextKeysToFetch, pollDecision, toRecords, tableLayout, LABELS, label,
    formatValue, formatAmount, AMOUNT_FIELDS, DATE_FIELDS,
    sectionBlocks, groupTitleFor, groupOrderIndex, normalizeRoster,
    ACTOR_STATUS, actorLine, resumeTarget, documentBlocks,
    dropAllEmptyColumns, recordsHaveSourceField, sourceGroupedBlocks,
    DOC_LIST_KEY, docKeyRceptNo, docListRow,
    CHART_SPECS, chartData, axisLabel, numeric, axisSortKey,
    normalizeDebtByKind, monthlyCounts, compositeXValue,
    financialRatios, classifyDisclosureCategory, monthlyCountsByCategory,
    DIVIDEND_SE_FIELDS, dividendVsIncome, fundPlanChanges, affiliateOverview,
    markNumber, MARK_RULES, cellMarks, markedColumnKeys,
    isAggregateRow, splitAggregateRows, splitVisibleFolded, MAX_VISIBLE_COLUMNS,
    INDICATOR_CATEGORY_ORDER, INDICATOR_PRIMARY, INDICATOR_NOTES,
    formatIndicator, indicatorBlocks, indicatorChartRecords,
    normalizeIndicatorCategory, indicatorRows, indicatorYearNote,
  };
}
