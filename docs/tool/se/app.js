"use strict";

// 브라우저에만 남는 값들. 서버에 저장하지 않는다.
const LS_DART_KEY = "se_dart_key";
const LS_SESSION = "se_session";
const LS_JOB = "se_job"; // 진행 중인 분석 작업의 job_id — 상태 자체는
                          // 서버(Postgres)에 있고 브라우저는 이 id만 든다.

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
const SECTION_GROUPS = [
  { title: "자금", keys: ["fund_usage", "affiliates", "disclosures"] },
  { title: "재무", keys: ["financials", "indicators"] },
  { title: "지배구조", keys: ["shareholders", "insider_timeline", "executive_roster"] },
  { title: "감사·부실", keys: ["audit_history", "debt_balance", "distress", "dividends"] },
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
  stock_name: "종목명", bsns_year: "사업연도", reprt_code: "보고서코드",
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
  if (AMOUNT_FIELDS.has(key) && /^-?[\d,]*\d$/.test(s)) {
    return formatAmount(s.replace(/,/g, ""));
  }
  if (DATE_FIELDS.has(key) && /^\d{8}$/.test(s)) {
    return s.slice(0, 4) + "." + s.slice(4, 6) + "." + s.slice(6, 8);
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
 * 1건이면 세로(키-값), 여러 건이면 가로(표)다. 1건짜리 49열(indicators)을
 * 가로로 펴면 열 하나가 몇 픽셀이 되어 글자가 세로로 쪼개진다.
 *
 * 비객체 항목(문자열 등)을 조용히 버리지 않는 것은 호출부의 책임이 아니라
 * 이 함수의 계약이다 — sectionBlocks는 이미 toRecords로 감싸서 넘기지만,
 * 그 방어가 호출부에만 있으면 새 호출부가 다시 놓친다(전에 실제로 그랬다:
 * 리스트 안 문자열 항목이 필터로 걸러져 흔적 없이 사라졌다). toRecords와
 * 같은 감싸기 규칙을 여기서도 한 번 더 적용해, tableLayout 하나만 불러도
 * 안전하다.
 */
function tableLayout(records) {
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
  const split = splitVisibleFolded(finalKeys);
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
 * (원래 열 순서)에서 보이도록 순서 자체는 다시 섞지 않는다. */
function splitVisibleFolded(finalKeys) {
  if (finalKeys.length <= MAX_VISIBLE_COLUMNS) {
    return { visible: finalKeys, folded: [] };
  }
  const essential = finalKeys.filter(function (k) {
    return ALWAYS_VISIBLE_KEYS.indexOf(k) !== -1;
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
 *  depth는 내부 재귀 카운터다(호출자는 생략한다 — 기본 0). 상한을
 *  넘으면 재귀를 멈추되, 그 하위 데이터를 조용히 빠뜨리지 않고 상한에
 *  걸렸다는 사실 자체를 텍스트 블록으로 남긴다 — 이 화면의 원칙은
 *  "데이터를 조용히 숨기지 않는다"이다. */
function sectionBlocks(value, depth) {
  const d = depth || 0;
  if (value === null || value === undefined) return [];

  if (d > MAX_SECTION_DEPTH) {
    return [{
      title: null,
      text: "중첩이 너무 깊어(깊이 " + d + ") 더 펼치지 않습니다. 원본 데이터는 있습니다.",
    }];
  }

  if (Array.isArray(value)) {
    // tableLayout은 레코드(객체) 배열만 받는다 — toRecords로 비객체
    // 항목(문자열 등)을 "값" 한 칸에 감싸서 보존한 뒤 넘긴다. 그러지
    // 않으면 tableLayout이 비객체 항목을 조용히 걸러내(rows 필터), 예를
    // 들어 independence_warnings(문자열 리스트)가 흔적 없이 사라진다.
    const t = tableLayout(toRecords(value) || []);
    return t ? [{ title: null, table: t }] : [];
  }

  if (!isPlainObject(value)) {
    if (isLongText(value)) return [{ title: null, text: value }];
    const t = tableLayout(toRecords(value) || []);
    return t ? [{ title: null, table: t }] : [];
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
    // 이 경로가 indicators(1건 49열)를 세로로 바꾸는 핵심 지점이다.
    const t = tableLayout([flat]);
    if (t) blocks.push({ title: null, table: t });
  }
  for (const k of longTextKeys) {
    blocks.push({ title: label(k), text: value[k] });
  }
  for (const k of nestedKeys) {
    const sub = sectionBlocks(value[k], d + 1);
    if (sub.length === 0) {
      blocks.push({ title: label(k), table: null });
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

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    LS_DART_KEY, LS_SESSION, LS_JOB, SECTION_GROUPS, formatCount,
    nextKeysToFetch, pollDecision, toRecords, tableLayout, LABELS, label,
    formatValue, formatAmount, AMOUNT_FIELDS, DATE_FIELDS,
    sectionBlocks, groupTitleFor, groupOrderIndex,
    ACTOR_STATUS, actorLine, resumeTarget,
  };
}
