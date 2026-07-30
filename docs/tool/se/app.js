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
  // fundChain(uses[], SE-5a Task 3)이 조달건×용도 단위로 묶은 뒤 만드는
  // 파생 필드다 — DART 원본 필드명(plan_useprps 등)과는 다른 별도 이름을
  // 쓴다. fundChainCardEl(ui.js)의 표 열 키가 이 이름 그대로다 — SE-8
  // Task 8B의 강조 규칙(MARK_RULES.fund_chain, key: "real")이 좌표
  // "행번호|열키"로 표의 열과 짝을 맞추려면 rows의 property 이름이 이
  // 라벨의 키와 글자 그대로 같아야 한다(affiliates 등 다른 표와 같은
  // 관례 — 한글 문자열을 직접 키로 쓰면 그 좌표가 어긋나 강조가 조용히
  // 사라진다).
  purpose: "용도", plan: "계획", real: "보고된 집행", diff_reason: "차이 사유",

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
  // exctvSttus(임원현황, executive_roster — SE-6 Task 2b가 화면까지
  // 보낸 필드)의 ofcps·rgist_exctv_at·birth_ym이다. 위 isu_exctv_ofcps·
  // isu_exctv_rgist_at(내부자 지분 신고서 전용 필드)와 같은 한글 라벨을
  // 쓰면 라벨 충돌 검사(test_no_label_collides_with_a_different_raw_key)에
  // 걸린다 — 두 raw key가 서로 다른 신고서 필드이므로 라벨도 구분한다.
  // Task 3 브리핑이 요구하는 "이 회사에서의 직위·등기 여부·생년월"을
  // 사람이 읽을 수 있게 한다(레지스트리에 없는 생년월을 이용자가 직접
  // 대조할 재료다).
  ofcps: "임원 직위", rgist_exctv_at: "등기임원 여부", birth_ym: "생년월",
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
  // ── 감사의견 이력(audit_history.opinions 레코드, SE-8 Task 7) — 실사용자
  // (SG, corp_code=00963976) 지적: opinion·auditor·tenure_years가 영문
  // 필드명 그대로 노출됐다. 단위 모호성이 없는 필드라 정상 라벨링한다
  // (dart_client.fetch_audit_opinion_history docstring 그대로:
  // {year, opinion, auditor, tenure_years, audit_fee_okwon,
  // non_audit_fee_okwon}). audit_fee_okwon·non_audit_fee_okwon은 여기
  // 없다 — CLAUDE.md 269행의 기존 결정("단위 천원/백만원 혼용으로
  // v0.8.0에서 생략")을 그대로 따라 렌더 경로에서 뺀다(아래
  // sectionBlocks의 audit_history.opinions 특수 처리 참고). 새 단위
  // 라벨을 짓지 않는다 — 그 자체가 v0.8.0이 피하려던 함정이다.
  //
  // opinion을 "감사의견"으로 쓰지 못한다 — 그 값은 이미 위 opinions(리스트
  // 키, 이 레코드 배열 전체를 감싸는 블록 제목)가 쓰고 있어 LABELS 값
  // 전역 유일성(test_no_label_collides_with_a_different_raw_key)과
  // 충돌한다. 표 자체가 이미 "감사의견"이라는 제목 아래 그려지므로,
  // 그 안에서 구분되는 "의견"을 쓴다.
  opinion: "의견", auditor: "감사인", tenure_years: "연속 재직 연수",
  // auditor_changes 레코드({from_year, to_year, from, to}). 라이브 검증
  // (2026-07-30, 두산에너빌리티 00159193, lookback_years=5):
  // {"from_year": 2024, "to_year": 2025, "from": "한영회계법인",
  // "to": "삼정회계법인"} 1건 실측 — SG는 이 목록이 비어 있어(실측 확인)
  // 검증하지 못했다.
  from_year: "교체 전 연도", to_year: "교체 후 연도",
  from: "교체 전 감사인", to: "교체 후 감사인",
  major_holders: "최대주주", bulk_holders: "5% 대량보유",
  // bulk_holders(위)의 원본 필드(dart_client.fetch_shareholder_status가
  // /majorstock.json 응답을 개명 없이 그대로 싣는다 — 위 MARK_RULES.
  // shareholders 주석에서 이미 확인됨). SE-8 Task 6 실사용자(SG,
  // corp_code=00963976) 지적: stkqy·stkrt·ctr_stkqy가 raw로 노출됐다.
  // 값은 opendart_api_guide.md §4.1(대량보유 상황보고, 2019021) "응답
  // 결과" 표의 "명칭" 열을 그대로 옮긴 것이다(추측 금지 — 임의로 지어낸
  // 한글명이 아니다). 같은 표의 나머지 형제 필드도 함께 채운다 — 셋만
  // 고치면 같은 표의 나머지 열이 여전히 raw로 남는다.
  stkqy: "보유주식등의 수", stkqy_irds: "보유주식등의 증감",
  stkrt: "보유비율", stkrt_irds: "보유비율 증감",
  ctr_stkqy: "주요체결 주식등의 수", ctr_stkrt: "주요체결 보유비율",
  report_tp: "보고구분", report_resn: "보고사유",

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

// 공시 목록 rm(비고) 필드의 DART 공식 코드 → 한국어. dart_client 실측(SG,
// corp_code=00963976)에서 나온 값 집합은 {'연','정','코','코정'}이었지만
// DART가 공식 문서에 정의한 코드는 여덟 개다(fetch_company_disclosures
// docstring 근거) — 실측에 없던 나머지도 미리 채운다. 값 자체가 **문자
// 단위로 조합**돼 나온다("코정" = "코"+"정", 구분자 없음)는 것이 이
// 코드의 핵심 함정이다 — 아래 formatRemark가 문자 단위로 분해한다.
const DART_REMARK_LABELS = Object.assign(Object.create(null), {
  "유": "유가증권", "코": "코스닥", "채": "채권상장법인", "넥": "코넥스",
  "공": "공정위 대상 기업집단", "연": "연결대상 종속회사 있음",
  "정": "정정신고", "철": "철회",
});

/** rm(비고) 값을 사람이 읽는 말로 바꾼다. **모든 문자가 DART_REMARK_LABELS에
 *  있는 여덟 개 코드 중 하나일 때만** 문자 단위로 분해해 각각 매핑하고
 *  " · "로 이어붙인다("코정" -> "코스닥 · 정정신고"). 이 필드(rm)는 두
 *  서로 다른 코드 체계를 같은 이름으로 쓴다(위 DART_REMARK_LABELS 주석
 *  참고): 공시 목록(list.json)에서는 8개 코드의 문자 조합이지만, 다른
 *  여러 엔드포인트(예: hyslrSttus·hyslrChgSttus)에서는 같은 필드 이름이
 *  자유서술형 비고("시간외매매", "이사 임기만료" 등)로 온다. 문자 단위
 *  분해를 무조건 적용하면 이런 자유서술형 문장이 한 글자씩 쪼개져
 *  " · "로 이어붙는 사고가 난다(SE-8 최종 리뷰 지적 — 삼성전자
 *  fetch_insider_timeline 라이브 재현: "시간외매매" -> "시 · 간 · 외 ·
 *  매 · 매"). **한 글자라도 8개 코드에 없으면(공백·조사·코드 아닌
 *  한글 등) 분해하지 않고 원문을 그대로 돌려준다** — REPRT_CODE_LABELS·
 *  label()과 같은 "모르면 숨기지 않는다" 계약이되, 여기서는 "부분적으로
 *  안다"고 절반만 번역하지 않고 통째로 원문을 지킨다(전부 알거나 전혀
 *  건드리지 않거나, 둘 중 하나).
 *
 *  빈 값·"-"는 isNoDataMarker가 이미 결측으로 판정하는 값이라 새로
 *  재구현하지 않고 그대로 재사용한다: null/undefined는 formatValue의
 *  다른 필드와 같은 결측 표기("")로 맞추고, "-"는 이미 그 자체로 DART가
 *  쓰는 결측 마커라 문자 분해 없이 원문 그대로 돌려준다(빈 문자열도
 *  같은 경로로 그대로 ""를 돌려준다 — 분해할 문자가 없다는 뜻).
 */
function formatRemark(rm) {
  if (isNoDataMarker(rm)) return (rm === null || rm === undefined) ? "" : rm;
  const s = String(rm);
  const chars = s.split("");
  const allCoded = chars.length > 0 && chars.every(function (ch) {
    return Object.prototype.hasOwnProperty.call(DART_REMARK_LABELS, ch);
  });
  if (!allCoded) return s;
  return chars.map(function (ch) { return DART_REMARK_LABELS[ch]; }).join(" · ");
}

// SE-8 Task 3 — dffrnc_resn(자금 차이 사유)·rm(최대주주 합계 각주) 등에서
// DART가 "주1)" 같은 각주 마커만 돌려주고 본문(각주 내용)은 주지 않는지
// 판별한다. 실측(SG, corp_code=00963976, fetch_fund_usage): 차이 사유가
// 있는 8건 전부 dffrnc_occrrnc_resn == "주1)"였다 — 이건 우리 버그가
// 아니다. 각주 본문은 공시 원문(사람이 읽는 문서)에만 있고 API 구조화
// 데이터엔 없다(task-3-brief). hyslrSttus(최대주주 현황)의 rm 실측 값
// 집합에는 "주)"(번호 없음)·"주1,2)"(여러 각주 동시 표기)도 나온다 —
// "주" 뒤에 숫자·쉼표만 오고 그 외 본문이 없는 값 전부를 마커로 본다.
//
// **rm은 두 가지 서로 다른 코드 체계를 같은 필드 이름으로 쓴다**: 공시
// 목록(fetch_company_disclosures)에서는 DART_REMARK_LABELS 코드 조합
// ("코정")이고, hyslrSttus에서는 이 각주 마커다. 두 값 집합은 겹치지
// 않는다(DART 공식 비고 코드 8종은 전부 단일 한글 글자, 이 마커는 항상
// "주"로 시작해 숫자·쉼표·닫는 괄호로 끝난다) — formatValue가 이 함수로
// 먼저 분기해 formatRemark(문자 단위 분해)가 마커를 "주" · "1" · ")"로
// 쪼개 깨뜨리지 않게 한다.
function isFootnoteMarkerOnly(v) {
  if (typeof v !== "string") return false;
  return /^주[0-9,]*\)$/.test(v.trim());
}

/** isFootnoteMarkerOnly에 걸리는 값에 정직한 안내를 덧붙인다. **원문
 *  마커 자체는 지우지 않는다**(task-3-brief: "사용자가 원문에서 '주1)'을
 *  찾아 대조할 수 있어야 한다") — 마커 뒤에 안내를 잇는 형태다. 마커가
 *  아니면(서술형 사유·결측 등) 값을 그대로 돌려준다 — 이 함수는 마커만
 *  있는 경우만 건드린다.
 *
 *  rceptNo가 주어지면(그 레코드에 실제로 rcept_no가 있을 때만 — DART
 *  원본 값을 지어내지 않는다, Global Constraints) 원문 확인 안내에
 *  접수번호를 남긴다. fund_usage 레코드는 실측(dart_client.
 *  _normalize_fund_usage)상 애초에 rcept_no를 담지 않아 이 경로에서는
 *  항상 undefined다 — 그래도 값을 지어내 채우지 않고 정직한 안내
 *  문구만 남긴다(호출부가 undefined를 넘기면 이 함수는 안내만 붙인다).
 */
function footnoteMarkerNote(v, rceptNo) {
  if (!isFootnoteMarkerOnly(v)) return v;
  let note = v + " (공시 원문 참고)";
  if (rceptNo) note += " · 접수번호 " + rceptNo;
  return note;
}

// 자금 사용 내역 kind(구분) 필드. 실측(SG)된 값은 두 가지뿐이다
// ({'public','private'}) — 그 외 값이 오면 formatValue가 원문을 그대로
// 보여준다(지어내 번역하지 않는다, 위 REPRT_CODE_LABELS 계약과 동일).
const KIND_LABELS = Object.assign(Object.create(null), {
  public: "공모", private: "사모",
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
  // 공시 목록 rm(비고) 값을 사람이 읽는 말로 바꾼다(위 DART_REMARK_LABELS·
  // formatRemark 주석 참고) — 컬럼 헤더 라벨(LABELS.rm)은 건드리지 않고
  // 값만 고친다. 단, hyslrSttus(최대주주 현황)는 같은 필드 이름(rm)을
  // 각주 마커("주1)")로 쓴다(위 isFootnoteMarkerOnly 주석 참고) — 먼저
  // 이 값을 걸러 footnoteMarkerNote로 보내지 않으면 formatRemark의 문자
  // 단위 분해가 마커를 깨뜨린다.
  if (key === "rm") {
    return isFootnoteMarkerOnly(s) ? footnoteMarkerNote(s) : formatRemark(s);
  }
  // SE-8 Task 3 — fund_usage 원본 표(sectionBlocks가 그리는, fundChain으로
  // 묶이기 전의 400건 그대로)의 dffrnc_resn(차이 발생 사유) 열도 같은
  // 각주 마커 문제를 겪는다 — fundChain()에서 고친 것은 파생 카드
  // ("차이 사유" 열, 조달건 단위로 묶은 대표값)뿐이고, 이 원본 표는 별도
  // 경로(formatValue)로 각 레코드를 그대로 그린다. 여기서 고치지 않으면
  // 원본 표에는 여전히 "주1)"만 남는다(라이브 검증: SG 8건 전부 재현).
  if (key === "dffrnc_resn") {
    return isFootnoteMarkerOnly(s) ? footnoteMarkerNote(s) : s;
  }
  // 자금 사용 내역 kind(구분) 값. 실측 두 값만 안다 — 그 외 값은(모르는
  // 값을 지어내 번역하지 않는다는 REPRT_CODE_LABELS와 같은 계약으로)
  // 원문 그대로 s를 돌려준다.
  if (key === "kind" && Object.prototype.hasOwnProperty.call(KIND_LABELS, s)) {
    return KIND_LABELS[s];
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

// 접어서 얻는 게 없는 최소 접힘 개수(task-2-brief 요구사항 B). SG 타법인
// 출자 실측(20필드 원본, essential 승격 후 12열 초과분이 정확히 1개)에서
// "나머지 1개열" 버튼을 누르자고 클릭을 요구하는 건 배보다 배꼽이 크다 —
// 접힐 열이 이 값 미만이면 접지 않고 그 자리만큼 예산을 늘려 전부
// 보여준다. 2 미만(0·1)일 이유가 없다: 0은 애초에 접을 게 없는 경우이고,
// "나머지 1개"가 바로 이 상수가 막으려는 퇴화 사례다.
const MIN_FOLD_COUNT = 2;

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
 * 줄어들 뿐 표가 무한정 넓어지지 않는다. 단, 그 예산을 넘어 접힐 열이
 * MIN_FOLD_COUNT 미만이면(위 상수 주석 참고) 예산 자체를 늘려 전부
 * visible로 흡수한다 — 접힘이 충분히 많을 때(예: insider_timeline)는
 * 이 흡수가 발동하지 않으므로 기존 동작 그대로다. */
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
  const restAll = finalKeys.filter(function (k) { return !essentialSet.has(k); });
  let budget = Math.max(MAX_VISIBLE_COLUMNS - essential.length, 0);
  const wouldFold = Math.max(restAll.length - budget, 0);
  if (wouldFold > 0 && wouldFold < MIN_FOLD_COUNT) {
    budget = restAll.length; // 접을 게 애매하게 1개뿐이면 전부 보여준다
  }
  const rest = restAll.slice(0, budget);
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

/** isMetaOnlyRecords가 참인 그룹에 붙일 안내문(SE-9 Task 3, 3a). "없다"는
 *  사실만이 아니라 몇 건을 확인했는지(reportCount)도 남긴다 — 표 자체를
 *  없애면서 "없다"만 말하면 "아예 확인을 안 한 것" 같은 인상을 줄 수
 *  있어서다(사용자가 조회 범위·건수를 신뢰할 수 있어야 한다).
 *
 *  reportCount는 **서로 다른 rcept_no(접수번호, 즉 공시 필증) 개수**여야
 *  한다 — 행(레코드) 개수가 아니다(최종 리뷰 지적, task-4-report.md 추가
 *  수정). "보고서 N건"이라는 문구가 이미 "N개의 공시"를 뜻하는데, 호출부
 *  다섯 곳이 제각기 다른 것(사람 수·행 수·dedup 후 행 수)을 세어 넘기고
 *  있었다 — 특히 dividends 메타-only 그룹은 정의상 한 그룹 = 한 공시
 *  (rcept_no가 그룹 안에서 상수, dividendPeriodBlocks 주석 참고)인데
 *  잔존 행 개수(7)를 넘겨 "보고서 7건"이라는 사실과 다른 문구를 냈다.
 *  이제 모든 호출부가 distinctReportCount(records)로 같은 것을 센다. */
function metaOnlyNote(reportCount) {
  return "해당 기간에 보고된 내역이 없습니다. (보고서 " + reportCount + "건 확인)";
}

/** records에서 서로 다른 rcept_no(접수번호) 개수를 센다 — metaOnlyNote가
 *  "보고서 N건"이라 말할 때 N은 이 값이어야 한다(행 개수가 아니라 실제
 *  공시 필증 개수, 최종 리뷰 지적). rcept_no가 없거나 isNoDataMarker면
 *  (식별 불가능한 값) 세지 않는다 — 식별할 수 없는 행을 서로 다른
 *  보고서로 잘못 부풀리지 않기 위해서다. DART 원본 응답은 list.json 계열
 *  엔드포인트 전부가 rcept_no를 담아 보내므로(dart_client.py 각
 *  fetch_* 참고) 실측에서 이 값이 0이 되는 경우는 예상 밖 입력뿐이다. */
function distinctReportCount(records) {
  if (!Array.isArray(records)) return 0;
  const seen = new Set();
  for (const r of records) {
    if (!isPlainObject(r)) continue;
    const v = r.rcept_no;
    if (isNoDataMarker(v)) continue;
    seen.add(String(v));
  }
  return seen.size;
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
    //
    // SE-9 Task 2: source를 뺀 직후 reorderRecordFields로 열 순서를
    // 명시 규칙으로 고정한다 — jsonb가 삽입 순서를 파괴해도(위 함수
    // 주석 참고) 이 그룹만은 배포본에서도 순서가 살아남는다.
    // SOURCE_PRIORITY_KEYS에 없는 source(실측 안 된 우선순위)는 빈
    // 배열로 폴백해 tail 일반 규칙만 적용한다 — 추측으로 우선순위를
    // 만들지 않는다(brief 제약).
    const priorityKeys = SOURCE_PRIORITY_KEYS[s] || [];
    const withoutSource = groups.get(s).map(function (r) {
      const copy = Object.assign({}, r);
      delete copy.source;
      return reorderRecordFields(copy, priorityKeys, RECORD_TAIL_KEYS);
    });

    // hyslr(최대주주 현황)에는 합계 행("계")이 사람 이름(nm) 자리에 섞여
    // 온다 — shareholders.major_holders와 정확히 같은 문제다(둘 다
    // dart_client가 /hyslrSttus.json 원본을 그대로 준다, 위 splitAggregateRows
    // 주석 참고). SE-8 Task 6 실사용자(SG) 지적: 무엇을 합산한 행인지
    // 설명 없이 사람 이름 사이에 섞여 나왔다. 같은 판정(isAggregateRow)·
    // 같은 분리(splitAggregateRows)를 재구현하지 않고 그대로 가져와
    // 사람 표 + 합계 표(제자리에 소계로) 두 블록으로 나눈다 — "계" 원문은
    // 지우지 않는다(합계 표 자체에 nm="계"로 그대로 남는다).
    if (s === "hyslr") {
      const split = splitAggregateRows(withoutSource);
      const peopleCleaned = dropAllEmptyColumns(split.people);
      // SE-9 Task 3(3a): peopleCleaned가 메타-only면(사람 행은 있는데
      // 실데이터가 전부 "-") 아래 일반 분기와 같은 판정을 쓴다 — 표를
      // 만들지 않고 안내문(건수 포함)만 남긴다. 자세한 이유는 아래
      // 일반 분기의 3a 주석 참고(같은 판정을 여기서 다시 설명하지 않는다).
      let peoplePushed = false;
      if (isMetaOnlyRecords(peopleCleaned)) {
        blocks.push({
          title: label(s), table: null, records: null,
          note: metaOnlyNote(distinctReportCount(peopleCleaned)),
        });
        peoplePushed = true;
      } else {
        const pt = tableLayout(peopleCleaned);
        if (pt) {
          blocks.push({ title: label(s), table: pt, records: peopleCleaned });
          peoplePushed = true;
        }
      }
      let totalsPushed = false;
      if (split.totals.length > 0) {
        const totalsCleaned = dropAllEmptyColumns(split.totals);
        const tt = tableLayout(totalsCleaned);
        if (tt) {
          blocks.push({ title: label(s) + " · 합계", table: tt, records: totalsCleaned });
          totalsPushed = true;
        }
      }
      if (!peoplePushed && !totalsPushed) {
        blocks.push({ title: label(s), table: null, records: null });
      }
      continue;
    }

    // exec_treasury(임원·주요주주 자기주식)에는 두 가지 잡음이 섞여
    // 온다(SE-9 조사 se9-investigation.md Item 2-2 실측):
    // ① 소계/총계 행이 상세 행 사이에 acqs_mth3 값("소계" 등)으로
    //    섞여 온다 — hyslr의 "계"와 같은 문제이지만 검사 필드가 다르다.
    //    isAggregateRow/splitAggregateRows를 필드 매개변수화해(3b, 기본값
    //    nm — hyslr·major_holders 기존 호출부는 그대로) 재사용한다.
    // ② 같은 (rcept_no, acqs_mth1~3) 조합에 "쌍둥이" 행이 있다 — SG
    //    실측(lookback 2년) 145행 중 72그룹이 한쪽은 실데이터, 다른 한쪽은
    //    stock_knd·5개 수량 필드·rm 전부 "-"다. 빈 쪽은 정보가 아니라
    //    표만 두 배로 늘릴 뿐이라 생략하되(3c), 몇 건을 생략했는지는
    //    캡션(note)에 정직하게 남긴다 — 값이 하나라도 있으면(3a와 같은
    //    원칙) 생략하지 않는다.
    if (s === "exec_treasury") {
      const split = splitAggregateRows(withoutSource, "acqs_mth3");
      const padding = splitPaddingRows(split.people, EXEC_TREASURY_PADDING_FIELDS);
      const detailCleaned = dropAllEmptyColumns(padding.kept);
      if (isMetaOnlyRecords(detailCleaned)) {
        blocks.push({
          title: label(s), table: null, records: null,
          note: metaOnlyNote(distinctReportCount(detailCleaned)),
        });
      } else {
        const dt = tableLayout(detailCleaned);
        if (dt) {
          const dBlock = { title: label(s), table: dt, records: detailCleaned };
          if (padding.omitted > 0) {
            dBlock.note = "내용 없는 행 " + padding.omitted + "건 생략";
          }
          blocks.push(dBlock);
        } else if (split.people.length > 0) {
          // 상세 행이 있었지만(소계/총계 제외) 전부 패딩이라 표 자체가
          // 사라졌다 — "N건 생략" 대신 3a와 같은 메타-only 안내 형식으로
          // 수렴시킨다(브리프: 서로 다른 두 문구를 배우게 하지 않는다).
          blocks.push({
            title: label(s), table: null, records: null,
            note: metaOnlyNote(distinctReportCount(split.people)),
          });
        }
      }
      if (split.totals.length > 0) {
        const totalsCleaned = dropAllEmptyColumns(split.totals);
        const tt = tableLayout(totalsCleaned);
        if (tt) {
          blocks.push({ title: label(s) + " · 합계", table: tt, records: totalsCleaned });
        }
      }
      continue;
    }

    const cleaned = dropAllEmptyColumns(withoutSource);
    // records는 표가 실제로 그린 것과 같은 레코드(source 제거·빈 열 제거
    // 반영 후)를 그대로 싣는다 — 다음 태스크(차트)가 이 레코드로 그리므로
    // 표와 다른 값을 보여주면 안 된다.
    //
    // SE-9 Task 3(3a) — task-6(SE-4f)의 "표는 지우지 않는다(접수번호로
    // 원문을 직접 열어 확인할 수 있어야 한다)" 결정을 뒤집는다. 그
    // 결정으로 실제 배포본에서 나온 결과를 실사용자(SG)가 재지적했다:
    // 안내문이 이미 "내역이 없다"고 말하는데, 그 밑에 식별자(rcept_no·
    // stlm_dt 등)만 남은 표가 그대로 깔려 있는 게 오히려 혼란스럽다 —
    // "없다"고 말해놓고 표를 보여주면 사용자는 표에서 뭔가를 다시
    // 찾으려 하게 된다. 원문 접근성 문제(접수번호로 원문을 열 수 있어야
    // 한다는 옛 근거)는 이제 다른 경로가 해결한다 — 공시 목록 탭이
    // 접수번호·원문 링크를 이미 별도로 제공하므로, 이 표가 사라져도
    // 원문을 못 찾게 되지 않는다. 그래서 메타-only면 표 자체를 만들지
    // 않고 안내문만 남기되, 몇 건을 확인했는지(N)는 함께 남긴다 —
    // "이상 없음"·"정상" 같은 판정 어휘가 아니라 "보고된 내역이 없다"는
    // 사실과 확인 건수만 말한다(v0.8.5 원칙).
    if (isMetaOnlyRecords(cleaned)) {
      blocks.push({
        title: label(s), table: null, records: null,
        note: metaOnlyNote(distinctReportCount(cleaned)),
      });
      continue;
    }
    const t = tableLayout(cleaned);
    if (t) {
      blocks.push({ title: label(s), table: t, records: cleaned });
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

/** 임원현황을 레코드 목록으로 바꾼다. 서버가 두 형태를 보낼 수 있다.
 *
 * **새 형태(SE-6 Task 2b, `fetch_executive_roster_detail`)**: 사람 단위
 * 행 목록 `[{nm, corp_name, birth_ym, ofcps, rgist_exctv_at, years}, ...]`.
 * `birth_ym`(생년월)·`ofcps`(직위)·`rgist_exctv_at`(등기 여부)은 레지스트리에
 * 동명이인을 자동으로 가리지 않는 이 화면에서 이용자가 직접 확인할 재료다
 * — 여기서 지우면 확인할 재료 없이 "확인하세요"만 남는다. 그래서 이
 * 필드들을 행에 그대로 남긴다(executiveMatches·Task 3 패널이 그대로 씀).
 *
 * **옛 형태**: `fetch_executive_roster`(dart_client.py)가 돌려주는
 * {임원명: {연도}}(set)를 se_server의 _jsonable이 정렬된 list로 낮춘
 * {"김기범": ["2025","2026"], ...}. 저장된 옛 작업 결과가 남아 있을 수
 * 있어(SE-4h가 같은 이유로 봉투/배열 양쪽을 받았다) 계속 받아준다.
 *
 * 어느 형태든 이름을 열 제목으로 쓰면 임원 7명일 때 7열짜리 1행 표가
 * 되어 읽을 수 없다(실측 docs/superpowers/plans/2026-07-27-se-4c-field-
 * inventory.json). 사람이 행이 되어야 한다.
 */
function normalizeRoster(value) {
  if (Array.isArray(value)) {
    // 새 형태: 이름이 없는 행(예상 밖 응답)은 조용히 건너뛴다 — 여기서
    // 던지면 나머지 임원까지 렌더가 통째로 멈춘다.
    return value
      .filter(function (row) { return row && typeof row === "object" && row.nm; })
      .map(function (row) {
        const years = Array.isArray(row.years) ? row.years : [];
        return {
          "성명": row.nm,
          "재직 연도": years.slice().sort().join(", "),
          corp_name: row.corp_name || "",
          birth_ym: row.birth_ym || "",
          ofcps: row.ofcps || "",
          rgist_exctv_at: row.rgist_exctv_at || "",
        };
      });
  }
  if (!value || typeof value !== "object") return [];
  // 옛 형태 — 연도 쪽은 배열이 정상이지만, 방어적으로 객체(키가 연도인
  // 형태)와 스칼라/null도 흡수한다. 어느 쪽이 와도 이름 자체는 잃지 않는다.
  return Object.keys(value).map(function (name) {
    const raw = value[name];
    const years = Array.isArray(raw) ? raw
                : (raw && typeof raw === "object") ? Object.keys(raw)
                : (raw === null || raw === undefined) ? [] : [String(raw)];
    return { "성명": name, "재직 연도": years.slice().sort().join(", ") };
  });
}

/** executiveMatches(rosterRows, lookupResults) — 임원 명단을 GET
 *  /api/se/actors?name= 조회 결과(handlers.py `_actors`의 name 분기, SE-6
 *  Task 1)와 대조한다.
 *
 *  rosterRows는 normalizeRoster(value)가 만드는 최소 형태({"성명",
 *  "재직 연도"})다. 호출부(ui.js, Task 3)가 exctvSttus 원문 필드
 *  (corp_name·birth_ym·ofcps·rgist_exctv_at)를 같은 행에 덧붙여 넘길 수
 *  있으므로 그 확장 형태도 그대로 받아들인다.
 *
 *  lookupResults는 UI가 임원 이름마다 그 엔드포인트를 호출해 모은
 *  "이름 → 서버 응답"(`{name, actors, disclaimer}`) 묶음이다. **이름
 *  매칭 자체는 서버(`lookup_actor`)가 이미 정확·정규화·폴딩 3단계로
 *  처리한다** — 여기서는 그 결과를 그대로 lookupResults[성명]으로
 *  찾아 쓸 뿐, 클라이언트에서 별도의 매칭 규칙을 새로 만들지 않는다
 *  (규칙이 두 벌이면 서버와 화면이 다른 답을 낼 수 있다).
 *
 *  "이 회사 자신"을 companies에서 빼는 판정은 행의 corp_name 필드
 *  하나만 본다. corp_name이 없으면 비교할 방법이 없으므로 아무것도
 *  빼지 않는다 — 회사명 표기가 서버 쪽 정규화와 어긋날 수 있으니
 *  "어긋날 때는 제외하지 않는 쪽(정보를 남기는 쪽)으로 실패하라"는
 *  지침(SE-6 Task 2 브리핑)을 그대로 따른다. corp_name이 있을 때도
 *  앞뒤 공백·대소문자 차이만 흡수하는 최소 정규화만 쓴다 — "엔켐"과
 *  "(주)엔켐"처럼 표기 자체가 갈리는 경우까지 맞히려 들면 그게 바로
 *  금지된 클라이언트 쪽 매칭 규칙이 된다.
 *
 *  status는 그대로 statuses 배열에 싣는다(정보를 지우지 않는다) —
 *  actor_status가 서버에서 이미 화이트리스트 검증을 마쳤으므로 여기서
 *  다시 걸러내지 않는다.
 *
 *  매칭이 0건인 임원도 결과에 포함한다(registered: false) — 화면이
 *  "대조했고 없었다"와 "대조하지 않았다"를 구분해야 한다.
 */
function executiveMatches(rosterRows, lookupResults) {
  const out = {};
  if (!Array.isArray(rosterRows) || rosterRows.length === 0) return out;
  const lookups = (lookupResults && typeof lookupResults === "object") ? lookupResults : {};

  for (const row of rosterRows) {
    if (!row || typeof row !== "object") continue;
    const name = row["성명"];
    if (!name) continue;

    const ownCompany = typeof row.corp_name === "string" ? row.corp_name.trim().toLowerCase() : "";
    const resp = (lookups[name] && typeof lookups[name] === "object") ? lookups[name] : null;
    const actors = (resp && Array.isArray(resp.actors)) ? resp.actors : [];

    const companies = [];
    const seen = new Set();
    const statuses = [];
    for (const actor of actors) {
      if (!actor || typeof actor !== "object") continue;
      statuses.push(actor.status);
      const list = Array.isArray(actor.companies) ? actor.companies : [];
      for (const c of list) {
        if (typeof c !== "string") continue;
        if (ownCompany && c.trim().toLowerCase() === ownCompany) continue;
        if (!seen.has(c)) { seen.add(c); companies.push(c); }
      }
    }

    out[name] = { registered: actors.length > 0, companies, statuses };
  }
  return out;
}

// SE-6 Task 3이 표에 붙이는 강조 문구. 신원을 단정하는 표현(이 임원이
// 다른 곳에도 나타난다는 식)이 아니라 "같은 이름이 레지스트리에 있음"만
// 말한다 — 판정선(계획 문서 "말할 수 있는 것과 없는 것")이 요구하는
// 정확한 문구다. 동일인 여부는 이 문구가 말하지 않는다.
const EXEC_MATCH_WHY = "같은 이름이 레지스트리에 있음";

/** executiveMatches(records, lookupResults)의 결과(matches)를
 *  cellMarks(records, sectionKey)와 같은 좌표 형식({"행번호|열키": 문구})
 *  으로 바꾼다.
 *
 *  executive_roster의 강조는 서버 조회(비동기, 임원 이름마다 GET
 *  /api/se/actors?name=)에 의존한다 — MARK_RULES(app.js)의 다른 모든
 *  규칙처럼 레코드 하나만 보고 동기적으로 판정할 수 없다. 그래서
 *  MARK_RULES에 넣는 대신 이 별도 변환을 두되, **반환 좌표 형식은 완전히
 *  같게 맞춘다** — 그래야 ui.js가 이미 갖고 있는 SE-4g 강조 파이프라인
 *  (tableEl(table, marks)의 `.mk` 클래스 + 범례)에 새 렌더 경로 없이
 *  그대로 꽂힌다.
 *
 *  records는 normalizeRoster(value)의 출력(각 행에 "성명" 키가 있다)이고,
 *  matches는 executiveMatches(records, lookupResults)의 출력이다. 매칭
 *  안 된 임원(registered:false)이나 조회 자체가 안 된 임원(matches에
 *  이름이 없음)은 강조하지 않는다 — 둘 다 "강조할 근거가 없다"는 점에서
 *  같다.
 */
function executiveRosterMarks(records, matches) {
  const out = {};
  if (!Array.isArray(records) || !matches || typeof matches !== "object") return out;
  records.forEach(function (r, i) {
    if (!r || typeof r !== "object") return;
    const name = r["성명"];
    const m = name ? matches[name] : null;
    if (m && m.registered) out[i + "|성명"] = EXEC_MATCH_WHY;
  });
  return out;
}

/** url이 dart.fss.or.kr 호스트일 때만 그대로 돌려주고, 그 외(다른 호스트·
 *  문자열이 아님)는 null.
 *
 *  레지스트리는 Notion에서 오는 외부 데이터다(계획 문서: "레지스트리는
 *  외부 데이터다 — 저장소를 신뢰해 렌더 규칙을 느슨하게 할 이유가
 *  없다"). 호출부(ui.js)는 이 함수가 null을 돌려주면 앵커를 만들지 않고
 *  텍스트로만 둔다.
 *
 *  `new URL()`을 쓰지 않는다 — ui.js 테스트 하네스(node vm 샌드박스)에는
 *  DOM 표준 전역인 URL이 없다(WHATWG 전역이지 ECMAScript 표준이 아니다).
 *  스킴+호스트 바로 뒤가 경로 구분자(`/`·`?`·`#`) 또는 문자열 끝이어야만
 *  통과시켜, `https://dart.fss.or.kr.evil.com/`이나
 *  `https://dart.fss.or.kr@evil.com/`처럼 호스트를 흉내 낸 값을 걸러낸다.
 */
function dartDisclosureLink(url) {
  if (typeof url !== "string") return null;
  return /^https?:\/\/dart\.fss\.or\.kr(?:[/?#]|$)/i.test(url) ? url : null;
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
//
// "소계"는 SE-9 Task 3(3b)에서 추가했다 — exec_treasury(임원·주요주주
// 자기주식)의 acqs_mth3(취득방법3) 필드가 "소계"로 부분합계 행을 표시한다
// (se9-investigation.md Item 2-2 실측). hyslr·major_holders(nm 필드)에는
// "소계"가 실측된 적이 없지만, 같은 집합을 공유해도 해가 없다 — "소계"도
// 한국어로 합계류 값이고, 어떤 nm 값도 우연히 "소계"와 같아질 사람 이름이
// 아니다(동명이인 함정과 무관).
const AGGREGATE_ROW_NAMES = new Set(["계", "합계", "총계", "소계"]);

/** r[field]가 합계류 값("계"·"합계"·"총계"·"소계")인가. field 생략 시
 *  기본값은 "nm"(major_holders·hyslr이 사람을 식별하는 필드) — 기존
 *  호출부(field를 안 주는 곳)는 전부 이 기본값으로 동작이 그대로다.
 *  field 값이 아예 없거나 문자열이 아니면(예상 밖 응답) 합계가 아닌
 *  쪽(사람/상세 행)으로 본다 — 판정을 못 하면 지우지도, 다르게 다루지도
 *  않는 쪽이 안전하다.
 *
 *  비교 전에 모든 공백(앞뒤·내부)을 제거한다 — DART가 "합 계"처럼 내부에
 *  공백을 넣어 보내는 경우가 있어 trim()만으로는 사람 목록에 남는다.
 *  다만 공백 "제거"이지 부분/접두 일치가 아니다 — "계상혁"처럼 실제
 *  인물명은 공백이 없어 원래 글자 그대로 남고, AGGREGATE_ROW_NAMES의
 *  어떤 항목과도 같아지지 않는다(동명이인 원칙과 같은 이유로 정확히
 *  일치할 때만 합계로 분류한다). field를 "acqs_mth3"로 바꿔도(exec_treasury)
 *  이 정확 일치 규칙은 그대로다 — SE-9 Task 3 3b, 필드만 매개변수화했지
 *  판정 방식은 바꾸지 않았다.
 *
 *  splitAggregateRows(표를 사람/합계로 나누기)와 shareholders 강조 규칙
 *  (합계 행에는 강조를 붙이지 않기, 이 파일 아래쪽) 두 곳이 이 하나의
 *  판정을 공유한다 — 같은 질문을 두 군데서 각자 답하면 "계상혁 함정"도
 *  두 군데서 각자 재발한다. shareholders 강조 규칙은 field를 지정하지
 *  않고 부르므로(기존 호출부) 기본값 "nm"을 그대로 쓴다. */
function isAggregateRow(r, field) {
  const f = field || "nm";
  const v = isPlainObject(r) ? r[f] : undefined;
  return typeof v === "string" && AGGREGATE_ROW_NAMES.has(v.replace(/\s+/g, ""));
}

/** records를 {people, totals}로 나눈다(판정은 isAggregateRow 하나에
 *  맡긴다). field 생략 시 기본값 "nm"(major_holders·hyslr) — SE-9 Task 3
 *  3b에서 exec_treasury("acqs_mth3")를 위해 매개변수화했다. */
function splitAggregateRows(records, field) {
  const people = [];
  const totals = [];
  for (const r of records) {
    if (isAggregateRow(r, field)) totals.push(r);
    else people.push(r);
  }
  return { people: people, totals: totals };
}

// exec_treasury(임원·주요주주 자기주식)의 "쌍둥이" 빈 행 판정 필드
// (SE-9 Task 3, 3c). se9-investigation.md Item 2-2 실측: SG lookback 2년
// 145행 중 72그룹이 (rcept_no, acqs_mth1, acqs_mth2, acqs_mth3)로 묶었을 때
// 한쪽은 실데이터, 다른 한쪽은 stock_knd(주식종류)·5개 수량 필드·rm(비고)
// 전부가 리터럴 "-"다 — 이는 DART 원본 자체의 모양이다(취득방법 조합마다
// 주식종류별로 행을 하나씩 내보내는데, 활동이 없는 주식종류에도 빈 행을
// 낸다). acqs_mth1~3은 일부러 뺐다 — 그 필드들은 빈 쪽에도 "이 행이 어느
// 취득방법·구분에 해당하는지"를 실제로 말해주는 값이 남아 있어(실측:
// 빈 쪽도 acqs_mth1="배당가능이익범위 이내 취득" 등 채워져 있다), 여기
// 넣으면 진짜 빈 행을 놓친다.
const EXEC_TREASURY_PADDING_FIELDS = [
  "stock_knd", "bsis_qy", "change_qy_acqs", "change_qy_dsps",
  "change_qy_incnr", "trmend_qy", "rm",
];

/** r의 fields 전부가 리터럴 문자열 "-"일 때만 true. isNoDataMarker보다
 *  좁다(null·빈 문자열은 여기서 패딩으로 보지 않는다) — DART 실측이 이
 *  자리에 항상 "-"만 채워 보내는 것을 확인했고(위 isNoDataMarker 주석과
 *  같은 근거), 값이 예상 밖 모양이면 판정을 보수적으로 포기해 행을
 *  지우지 않는 쪽이 "값이 하나라도 있으면 표를 그대로 보여준다"(3a와
 *  같은) 원칙에 맞는다. */
function isPaddingRow(r, fields) {
  if (!isPlainObject(r)) return false;
  return fields.every(function (k) { return r[k] === "-"; });
}

/** records를 fields 기준으로 {kept, omitted}로 나눈다. omitted는 지운
 *  레코드를 담지 않고 개수만 센다 — 브리프 3c: "캡션에 생략 건수를
 *  정직하게 표기한다"를 위해 값은 버리되(표에 안 남긴다) 몇 건인지는
 *  호출부가 알 수 있게 남긴다. */
function splitPaddingRows(records, fields) {
  const kept = [];
  let omitted = 0;
  for (const r of records) {
    if (isPaddingRow(r, fields)) omitted++;
    else kept.push(r);
  }
  return { kept: kept, omitted: omitted };
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
    let records = toRecords(value) || [];
    // financials 원본 표: 계정과목(account_nm)·금액이 분류 메타(fs_div·
    // sj_div·fs_nm·sj_nm)보다 뒤에 오는 DART 원본 열 순서를 보기 좋게
    // 재배치한다(SE-8 Task 4, reorderFinancialsFields 주석 참고). depth 0 +
    // 부모 key로 게이트한다 — executive_roster·debt_balance.by_kind와 같은
    // 방식이라 재귀 호출(하위 어딘가의 우연한 "financials" 키)에는 적용되지
    // 않는다. SE-10 Task 2부터는 재배치 직후 dividends와 같은 이른 return을
    // 탄다(financialsGroupedBlocks 주석 참고) — 원본 표가 fs_div(연결/별도)
    // 별로 나뉜 표 + 제목을 얻는다(이전에는 title: null인 평면 표 하나였다,
    // se10-investigation.md Q3a).
    if (d === 0 && key === "financials") return financialsGroupedBlocks(reorderFinancialsFields(records));
    // SE-9 Task 4: dividends는 더 이상 단일 평면 표로 그리지 않는다 —
    // 같은 사업연도·결산일이 매 행마다 반복돼 어느 행이 어느 보고
    // 시점 것인지 한눈에 안 들어온다는 실사용자(SG) 지적에 따라,
    // dividendPeriodBlocks가 (bsns_year, reprt_code, stlm_dt) 그룹별로
    // 표를 나누고 그룹 안에서는 그 필드들을 지워 제목으로 승격한다(아래
    // dividendPeriodBlocks 주석 참고). 예전에 이 자리에서 부르던
    // reorderDividendsFields(bsns_year/stlm_dt를 앞으로 당기기만 하던
    // 재배치)는 이제 무의미하다 — 그 필드 자체가 행에서 사라지기
    // 때문이다. 이 분기가 아래 sourceGroupedBlocks·tail 일반 규칙보다
    // 먼저 와야 한다(dividends는 source 필드가 없어 그 분기를 어차피
    // 안 타지만, tail 일반 규칙에 먼저 걸리면 그룹핑 전에 필드 순서가
    // 한 번 더 섞인다).
    if (d === 0 && key === "dividends") return dividendPeriodBlocks(records);
    // insider_timeline처럼 레코드 전부가 source 필드를 가지면(4개
    // 엔드포인트를 합친 결과) source별로 작은 표 여러 개로 나눈다 —
    // source가 없는 다른 섹션은 이 분기를 타지 않는다(recordsHaveSourceField
    // 계약). 이 경로는 sourceGroupedBlocks가 블록별로 자기 레코드를
    // 따로 싣는다(source가 레코드에서 빠지므로 섹션 전체 레코드를
    // 넘기는 방식은 여기서 성립하지 않는다).
    if (recordsHaveSourceField(records)) return sourceGroupedBlocks(records);
    // financials는 위 이른 return으로 이 지점에 더 이상 도달하지 않는다
    // (SE-10 Task 2부터 dividends와 같은 처지 — 자기 그룹핑 규칙을 이미
    // 마쳤다). 여기 남는 나머지 모든 평면 배열(source 없는 원본 표)엔 tail
    // 일반 규칙(메타 키 뒤로, 비고 맨 뒤로)만 적용한다 — jsonb가 순서를
    // 파괴해도 최소한의 가독성은 명시 규칙으로 지킨다.
    records = records.map(function (r) { return reorderRecordFields(r, [], RECORD_TAIL_KEYS); });
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
      // splitAggregateRows는 원본 필드 순서(잡담 jsonb 순서 포함)로 사람/
      // 합계를 나눈다 — isAggregateRow는 nm 값만 보고 열 순서와는 무관하니
      // 분리 자체는 재배치 전에 해도 안전하다. tail 재배치는 분리된 각
      // 레코드에 나머지 평면 배열과 같은 규칙(RECORD_TAIL_KEYS)으로 적용해
      // 사람 표·합계 표 둘 다 jsonb 순서 파괴에서 벗어나게 한다.
      const split = splitAggregateRows(arr);
      const peopleRecords = (toRecords(split.people) || []).map(function (r) {
        return reorderRecordFields(r, [], RECORD_TAIL_KEYS);
      });
      const pt = tableLayout(peopleRecords);
      if (pt) blocks.push({ title: label(k), table: pt, records: peopleRecords });
      if (split.totals.length > 0) {
        const totalRecords = (toRecords(split.totals) || []).map(function (r) {
          return reorderRecordFields(r, [], RECORD_TAIL_KEYS);
        });
        const tt = tableLayout(totalRecords);
        if (tt) blocks.push({ title: label(k) + " · 합계", table: tt, records: totalRecords });
      }
      if (!pt && split.totals.length === 0) {
        blocks.push({ title: label(k), table: null, records: null });
      }
      continue;
    }
    // audit_history.opinions만 특수 처리한다(같은 게이트 방식 — depth 0 +
    // 부모 key). SE-8 Task 7 — 실사용자(SG, corp_code=00963976) 지적:
    // audit_fee_okwon(280)·non_audit_fee_okwon(220000)이 단위 설명 없는
    // 숫자로 그대로 노출됐다. CLAUDE.md 269행의 기존 결정("DART 감사보수
    // 절대 금액 표시는 단위 천원/백만원 혼용으로 v0.8.0에서 생략. 비중만
    // 경고 섹션에서 제공.")을 SE에도 그대로 적용한다 — **새 단위 라벨을
    // 짓지 않고 이 두 필드를 렌더 경로에서만 뺀다.** 비율 기반 대체
    // (비감사용역 비중 경고)는 이미 independence_warnings로 따로 나온다.
    //
    // **숨기는 것은 렌더 경로뿐이다.** value[k](원본 opinions 배열과 그
    // 안의 레코드 객체)는 건드리지 않는다 — 각 레코드를 Object.assign으로
    // 복사한 뒤 그 복사본에서만 두 필드를 지운다. 원본을 직접
    // delete하면 나중에 이 값을 다른 용도로 쓰려는 호출부(brief: "향후
    // 다른 용도로 필요할 수 있다")가 이미 지워진 데이터를 받는다.
    if (d === 0 && key === "audit_history" && k === "opinions") {
      const arr = Array.isArray(value[k]) ? value[k] : [];
      const records = arr.map(function (r) {
        if (!r || typeof r !== "object" || Array.isArray(r)) return r;
        const copy = Object.assign({}, r);
        delete copy.audit_fee_okwon;
        delete copy.non_audit_fee_okwon;
        return copy;
      });
      const t = tableLayout(records);
      blocks.push(t
        ? { title: label(k), table: t, records: records }
        : { title: label(k), table: null, records: null });
      continue;
    }
    // shareholders.bulk_holders만 특수 처리한다(같은 게이트 방식 — depth 0 +
    // 부모 key). major_holders와 같은 처지다: nm이 아니라 repror(보고자)로
    // 식별하는 레코드라 source 필드가 없어 sourceGroupedBlocks도, 일반
    // 평면 배열 tail-only 경로(위 Array.isArray 분기 마지막 줄)도 이 표에
    // "보고자를 앞으로" 규칙을 못 준다. 실사용자 지적(SK하이닉스 5%
    // 대량보유 스크린샷): 첫 열이 stkqy(보유주식등의 수)라 누구의
    // 수치인지 표 첫눈에 안 보인다 — repror를 priorityKeys로 앞당긴다.
    // tail 규칙(RECORD_TAIL_KEYS)은 그대로 둬 jsonb 순서 파괴로부터도
    // 보호한다.
    if (d === 0 && key === "shareholders" && k === "bulk_holders") {
      const records = (toRecords(value[k]) || []).map(function (r) {
        return reorderRecordFields(r, BULK_HOLDERS_PRIORITY_KEYS, RECORD_TAIL_KEYS);
      });
      const t = tableLayout(records);
      blocks.push(t
        ? { title: label(k), table: t, records: records }
        : { title: label(k), table: null, records: null });
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

// financials 원본 표(원본 필드 그대로, financialRatios 파생값이 아니다)의
// 열 순서를 계정과목·금액 중심으로 재배치한다(SE-8 Task 4). DART가 주는
// /fnlttSinglAcnt.json 필드 순서는 실측(SG, corp_code=00963976, 2026-07-30)
// 기준 rcept_no·reprt_code·bsns_year·corp_code·stock_code·**fs_div·fs_nm·
// sj_div·sj_nm**·account_nm·thstrm_nm·thstrm_dt·thstrm_amount·... 순이다 —
// 분류 메타(연결/별도, 재무상태표/손익계산서)가 계정과목보다 앞에 온다.
// tableLayout(위)은 각 레코드의 키 "등장 순서"를 그대로 헤더 순서로 쓰므로
// (Object.keys 기반), 렌더 직전 이 함수로 그 순서를 한 번 바꾼다 — DART
// 응답 자체나 core(dart_client.py)는 건드리지 않는다(이 파일 수정
// 범위 밖).
//
// META(분류 메타)를 PRIORITY(계정과목·금액) 중 마지막으로 등장하는 열
// 바로 뒤로 옮긴다 — 그 외 열(rcept_no·기간명·순번 등)의 상대 순서는
// 손대지 않는다. PRIORITY가 레코드에 하나도 없으면(예상 밖 모양) 원본을
// 그대로 둔다 — 옮길 기준점이 없는데 META를 앞으로 당기면 오히려 임의
// 순서가 된다.
const FINANCIALS_META_KEYS = ["fs_div", "sj_div", "fs_nm", "sj_nm"];
const FINANCIALS_PRIORITY_KEYS = ["account_nm", "thstrm_amount", "frmtrm_amount", "bfefrmtrm_amount"];

function reorderFinancialsRecord(r) {
  if (!r || typeof r !== "object") return r;
  const keys = Object.keys(r);
  const hasPriority = keys.some(function (k) { return FINANCIALS_PRIORITY_KEYS.indexOf(k) !== -1; });
  if (!hasPriority) return r;

  const metaSet = new Set(FINANCIALS_META_KEYS);
  const rest = keys.filter(function (k) { return !metaSet.has(k); });
  let insertAt = 0;
  for (let i = 0; i < rest.length; i++) {
    if (FINANCIALS_PRIORITY_KEYS.indexOf(rest[i]) !== -1) insertAt = i + 1;
  }
  const metaPresent = keys.filter(function (k) { return metaSet.has(k); });
  const newKeys = rest.slice(0, insertAt).concat(metaPresent, rest.slice(insertAt));

  const out = Object.create(null);
  for (const k of newKeys) out[k] = r[k];
  return out;
}

/** financials(원본 재무제표 레코드 배열) 전체에 reorderFinancialsRecord를
 *  적용한다. sectionBlocks가 "financials" 섹션을 tableLayout에 넘기기
 *  직전 호출한다 — 값 자체는 하나도 바꾸지 않는다(순서만). */
function reorderFinancialsFields(records) {
  if (!Array.isArray(records)) return records;
  return records.map(reorderFinancialsRecord);
}

// financials 원본 표의 thstrm_dt/frmtrm_dt/bfefrmtrm_dt(당기/전기/전전기
// 기간)를 앞 4자리(연도)로 축약할 때 건드리는 필드 목록(SE-10 Task 2,
// task-2-brief.md).
const FINANCIALS_DATE_KEYS = ["thstrm_dt", "frmtrm_dt", "bfefrmtrm_dt"];

/** thstrm_dt류 값 하나를 앞 4자리(연도)로 축약한다. DART 원본은
 *  재무상태표(BS) 행이면 시점형("2025.12.31 현재"), 손익계산서(IS) 행이면
 *  기간형("2025.01.01 ~ 2025.12.31")이라 형태가 다르지만, 둘 다 앞
 *  4자리가 그 값이 가리키는 연도라는 사실은 같다(se10-investigation.md
 *  Q1a 실측 — 당기 예시 두 형태 모두 "2025"). 정규식 하나(^\d{4})로 두
 *  형태를 구분하지 않고 같은 방식으로 처리할 수 있는 이유가 이것이다.
 *  문자열이 아니거나 앞 4자리가 숫자가 아니면(예상 밖 형태) 원본을 그대로
 *  돌려준다 — 판정 불가 시 지우지 않는다 원칙(다른 축약·그룹핑 함수와
 *  동일). */
function shortenFinancialsDate(v) {
  if (typeof v !== "string") return v;
  const m = v.match(/^\d{4}/);
  return m ? m[0] : v;
}

/** 레코드 하나에서 FINANCIALS_DATE_KEYS 세 필드만 shortenFinancialsDate로
 *  축약한 사본을 돌려준다. 그 외 필드·키 순서는 손대지 않는다 —
 *  financialsGroupedBlocks가 reorderFinancialsFields로 이미 열 순서를
 *  정한 뒤에만 이 함수를 부르므로 순서를 다시 섞을 이유가 없다. */
function shortenFinancialsDateFields(r) {
  if (!r || typeof r !== "object") return r;
  const out = Object.assign({}, r);
  for (const k of FINANCIALS_DATE_KEYS) {
    if (k in out) out[k] = shortenFinancialsDate(out[k]);
  }
  return out;
}

/** financialsGroupedBlocks의 그룹(같은 fs_div) 대표 레코드 하나로 제목을
 *  만든다 — "{연도}년 {fs_nm}"(브리프 예시: "2025년 연결재무제표") 형태다.
 *  연도는 financialRatiosBaseYear(SE-10 Task 1, 위 financialRatios 주석
 *  참고)를 그대로 재사용한다 — 이 함수가 하는 일(records 배열에서
 *  bsns_year를 한 번 읽어 상수로 쓴다)은 financials 원본 레코드에도 그대로
 *  성립한다(financialRatios가 받는 것과 정확히 같은 배열이 이 함수의
 *  입력이라 별도 일반화가 필요 없다). bsns_year를 못 읽으면(null, 판정
 *  불가) 연도 없이 fs_nm만 쓴다 — 제목이 아예 없던 이전보다는 나은
 *  폴백이다(최소한 연결/별도 구분은 여전히 보인다). fs_nm 자체가
 *  없으면(예상 밖 응답) label("financials")로 폴백해 빈 제목을 만들지
 *  않는다(dividendGroupTitle과 같은 방어). */
function financialsGroupTitle(r, baseYear) {
  const fsNm = r && r.fs_nm !== undefined && r.fs_nm !== null && r.fs_nm !== ""
    ? String(r.fs_nm) : label("financials");
  return baseYear !== null ? String(baseYear) + "년 " + fsNm : fsNm;
}

/** financials(원본 재무제표 레코드 배열, reorderFinancialsFields 적용 후)를
 *  fs_div(CFS/OFS)별로 표 하나씩 나눈다(SE-10 Task 2, task-2-brief.md) —
 *  실사용자(SG) 지적: 연결/별도가 한 표에 섞여 있어 어디서부터 별도인지
 *  한눈에 안 보인다(se10-investigation.md Q3c — DART 응답 자체가 CFS·OFS를
 *  같은 배열에 함께 준다, fs_div 요청 파라미터가 실제로 필터링하지
 *  않는다). dividendPeriodBlocks와 같은 Map+groupOrder 메커니즘(그룹
 *  순서는 첫 등장 순서 — DART가 실측상 CFS 블록을 먼저, OFS 블록을 뒤에
 *  연속으로 준다, Q3c)이지만 그룹 키가 fs_div 하나뿐이라 더 단순하다.
 *  별도만 있는 회사(레코드 전부가 같은 fs_div)는 자연히 그룹이 하나뿐이라
 *  표도 하나만 나온다 — 별도 분기 없이 이 메커니즘 자체가 그 경우를
 *  포함한다.
 *
 *  각 그룹 안에서는 thstrm_dt/frmtrm_dt/bfefrmtrm_dt를 앞 4자리 연도로
 *  축약한다(shortenFinancialsDateFields) — 브리프가 예상한 부수효과:
 *  축약 전에는 같은 그룹 안에서도 재무상태표 행("2025.12.31 현재")과
 *  손익계산서 행("2025.01.01 ~ 2025.12.31")의 원본 문자열이 서로 달라 세
 *  열이 tableLayout의 상수-열 캡션 승격 조건(그룹 내 모든 행에서 값이
 *  같음)을 만족하지 못했지만, 축약 후에는 두 형태 모두 같은 연도
 *  문자열("2025")이 되어 그룹 안 전 행에서 값이 같아지고 — 별도 메커니즘을
 *  새로 만들지 않아도 tableLayout의 기존 캡션 승격이 그대로 세 열을 표
 *  밖으로 옮긴다(실렌더 검증 결과는 task-2-report.md 참고).
 *
 *  thstrm_nm/frmtrm_nm/bfefrmtrm_nm(기수명, 예: "제 17 기")은 이 함수가
 *  손대지 않는다 — 그룹 안에서 이미 상수라 tableLayout이 그전부터 캡션으로
 *  승격했고, 이 함수는 그 값 자체를 바꾸지 않는다(건드리는 건 날짜 세
 *  필드의 값뿐).
 *
 *  fs_div가 없는 레코드(예상 밖 응답)는 빈 문자열 키 그룹으로 묶인다 —
 *  판정 불가 시 지우지 않는다 원칙(다른 그룹핑 함수와 동일). */
function financialsGroupedBlocks(records) {
  if (!Array.isArray(records)) return [];
  const baseYear = financialRatiosBaseYear(records);
  const order = [];
  const groups = new Map();
  for (const r of records) {
    if (!isPlainObject(r)) continue;
    const key = r.fs_div !== undefined && r.fs_div !== null ? String(r.fs_div) : "";
    if (!groups.has(key)) { groups.set(key, []); order.push(key); }
    groups.get(key).push(r);
  }

  const blocks = [];
  for (const key of order) {
    const shortened = groups.get(key).map(shortenFinancialsDateFields);
    const title = financialsGroupTitle(shortened[0], baseYear);
    const t = tableLayout(shortened);
    if (t) blocks.push({ title: title, table: t, records: shortened });
  }
  return blocks;
}

/** record(레코드 하나)의 키를 priorityKeys(주어진 순서대로 앞으로) →
 *  나머지(원본 상대 순서 유지) → tailKeys(주어진 순서대로 뒤로) 순으로
 *  재배치한다. 값은 하나도 바꾸지 않는다 — 순서만 바꾼다.
 *
 *  **왜 필요한가(SE-9 조사, docs/superpowers/plans/2026-07-30-se-9-table-
 *  legibility.md "핵심 발견")**: se_server가 섹션 상태를 Postgres jsonb로
 *  저장한다(se_server/jobs/schema.sql:6 `state jsonb not null`). Postgres
 *  jsonb는 객체를 저장할 때 키를 **길이순 → 바이트순**으로 조용히
 *  재정렬한다 — DART가 준 원 순서도, 로컬 dict(삽입 순서 보존)의 순서도
 *  아니다. tableLayout이 레코드의 키 "등장 순서"를 그대로 헤더로 쓰는 한
 *  (Object.keys 기반), 배포본의 모든 표는 이 jsonb 정렬로 렌더된다 —
 *  실사용자(SG) 스크린샷의 "비고가 첫 열" 같은 기괴한 순서가 정확히
 *  이것이었다. **명시적으로 재배치한 열만** 배포본에서 순서가 살아남는다.
 *
 *  reorderDividendsRecord(SE-8 Task 8A, priorityKeys만 있고 tailKeys가
 *  없는 특수화)의 "우선 키를 앞으로" 로직을 일반화하고 "tail 키를 뒤로"를
 *  더한 것이다.
 *
 *  priorityKeys·tailKeys 각각 레코드에 실제로 있는 키만, 주어진 배열
 *  순서 그대로 앞/뒤로 옮긴다. 둘 다에 없는 키("나머지")는 원본 상대
 *  순서를 그대로 유지한다. 한 키가 두 목록에 동시에 있으면 priorityKeys가
 *  이긴다(뒤로 보내라는 tailKeys 쪽 지시를 무시). priorityKeys·tailKeys
 *  둘 다 레코드에서 하나도 못 찾으면(옮길 기준점이 없다) 원본을 그대로
 *  돌려준다 — reorderFinancialsRecord와 같은 방어(임의로 아무 열이나
 *  앞뒤로 당기면 오히려 임의 순서가 된다). */
function reorderRecordFields(record, priorityKeys, tailKeys) {
  if (!record || typeof record !== "object") return record;
  const keys = Object.keys(record);
  const pKeys = Array.isArray(priorityKeys) ? priorityKeys : [];
  const tKeys = Array.isArray(tailKeys) ? tailKeys : [];

  const front = pKeys.filter(function (k) { return k in record; });
  const frontSet = new Set(front);
  const tail = tKeys.filter(function (k) { return !frontSet.has(k) && k in record; });
  if (front.length === 0 && tail.length === 0) return record;

  const tailSet = new Set(tail);
  const middle = keys.filter(function (k) { return !frontSet.has(k) && !tailSet.has(k); });
  const newKeys = front.concat(middle, tail);

  const out = Object.create(null);
  for (const k of newKeys) out[k] = record[k];
  return out;
}

// 전 표 공통 tail 규칙(brief "일반 규칙"): 메타 키(stlm_dt·bsns_year·
// reprt_code·rcept_no)는 실질 열 뒤로, 비고(rm)는 맨 뒤로 — 이 배열 순서
// 그대로 tailKeys에 넘기면 rm이 자동으로 최후미가 된다. corp_cls·
// corp_code·corp_name은 일부러 뺐다 — 그 셋은 값이 상수면 tableLayout의
// 캡션 승격이 이미 표 밖(캡션)으로 뺀다. 여기 넣으면 그 승격과 뒤섞여
// "정체를 밝힐 뿐 사건을 서술하지 않는 필드"(META_ONLY_KEYS 주석 참고)의
// 판정 기준이 두 곳(순서용·의미용)으로 갈라진다 — META_ONLY_KEYS와
// 이름이 겹치지만 목적은 다르다(이건 순서, META_ONLY_KEYS는 "실데이터
// 없음" 판정).
const RECORD_TAIL_KEYS = ["stlm_dt", "bsns_year", "reprt_code", "rcept_no", "rm"];

// source별 우선순위(브리프 실측 순서 그대로 — 추측으로 만들지 않는다).
// sourceGroupedBlocks가 그룹(source)마다 이 표로 priorityKeys를 찾는다 —
// 목록에 없는 source는 tail 일반 규칙만 적용한다(빈 배열 폴백).
const EXEC_TREASURY_PRIORITY_KEYS = [
  "stock_knd", "acqs_mth1", "acqs_mth2", "acqs_mth3", "bsis_qy",
  "change_qy_acqs", "change_qy_dsps", "change_qy_incnr", "trmend_qy",
];
const HYSLR_CHG_PRIORITY_KEYS = [
  "change_on", "mxmm_shrholdr_nm", "posesn_stock_co", "qota_rt", "change_cause",
];
const SOURCE_PRIORITY_KEYS = {
  exec_treasury: EXEC_TREASURY_PRIORITY_KEYS,
  hyslr_chg: HYSLR_CHG_PRIORITY_KEYS,
};

// shareholders.bulk_holders(majorstock.json 원본, source 필드 없음) 전용
// 우선순위 — repror(보고자)를 앞으로 당긴다(SE-11, 위 sectionBlocks의
// bulk_holders 분기 주석 참고).
const BULK_HOLDERS_PRIORITY_KEYS = ["repror"];

// dividends 원본 표(alotMatter, fetch_dividend_history)의 열 순서를
// 기준 기간 → 항목 → 당기 값 중심으로 재배치한다(SE-8 Task 8A). 실측(SG,
// corp_code=00963976, 2026-07-30, fetch_dividend_history 직접 호출)
// 기준 원본 필드 순서는 rcept_no·corp_cls·corp_code·corp_name·se·
// stock_knd·thstrm·frmtrm·lwfr·stlm_dt·bsns_year·reprt_code다(dart_client.
// fetch_dividend_history가 dict(item) 뒤에 bsns_year·reprt_code를
// 덧붙인다) — "이 값이 어느 시점 것인지"(bsns_year·stlm_dt)가 항목(se)
// 보다도 뒤, 사실상 맨 끝 근처에 있다.
//
// reorderFinancialsRecord(META를 PRIORITY 뒤로 밀어내는 방식)와 달리
// 여기는 **PRIORITY 자체를 앞으로 당긴다** — financials는 이미 계정과목
// (account_nm)이 값보다 먼저 오고 fs_div류 분류 메타만 뒤로 보내면
// 됐지만, dividends는 "이 값이 무슨 기간 것인지"조차 맨 끝에 있어 옮길
// 기준점이 앞쪽에 없다(위 브리프: "항목을 없애는 게 아니라 기준 시점
// 뒤로 둔다"의 반대 방향 — 여기서는 기준 시점을 앞으로 당긴다).
// 우선순위 안의 상대 순서는 고정(bsns_year → stlm_dt → se → thstrm)이고,
// 나머지 열(rcept_no·frmtrm·lwfr·reprt_code 등)은 원래 상대 순서를
// 그대로 유지한다. 우선 열이 레코드에 하나도 없으면(예상 밖 모양) 원본을
// 그대로 둔다.
//
// SE-9 Task 2: reorderRecordFields(일반 함수)의 특수화로 재구현했다 —
// tailKeys를 빈 배열로 넘겨 "메타 키를 뒤로 미는" 일반 tail 규칙을 끄고
// 기존 동작(bsns_year/stlm_dt를 오히려 맨 앞으로 당김)만 그대로 살린다.
// 동작은 한 글자도 바뀌지 않는다(TestReorderDividendsFields 회귀 참고).
const DIVIDENDS_PRIORITY_KEYS = ["bsns_year", "stlm_dt", "se", "thstrm"];

function reorderDividendsRecord(r) {
  return reorderRecordFields(r, DIVIDENDS_PRIORITY_KEYS, []);
}

/** dividends(원본 배당 레코드 배열) 전체에 reorderDividendsRecord를
 *  적용한다. sectionBlocks가 "dividends" 섹션을 tableLayout에 넘기기
 *  직전 호출한다 — 값 자체는 하나도 바꾸지 않는다(순서만). dividendVsIncome
 *  (파생 "배당 vs 당기순이익" 비교 블록)은 이 함수와 무관하게 원본
 *  value를 그대로 받는다 — 필드를 이름으로 찾을 뿐 순서에 기대지
 *  않으므로 이 재배치와 상관없이 그대로 동작한다. */
function reorderDividendsFields(records) {
  if (!Array.isArray(records)) return records;
  return records.map(reorderDividendsRecord);
}

// SE-9 Task 4: reorderDividendsRecord/reorderDividendsFields는 더 이상
// 렌더 경로에 배선돼 있지 않다(sectionBlocks가 dividends를
// dividendPeriodBlocks로 바로 보낸다, 아래 참고) — bsns_year/stlm_dt를
// "맨 앞으로 당기는" 이 함수의 역할 자체가 dividendPeriodBlocks에서
// "그룹 안 행에서 완전히 지우고 제목으로 승격"으로 대체됐다. 지운 게
// 아니라 순수 함수로 남겨 기존 회귀(TestReorderDividendsFields, 값 자체는
// 안 바뀐다)를 계속 지킨다 — 호출부만 바뀌었다.

// dividendPeriodBlocks가 그룹 안 행에서 지워 제목으로 승격하는 필드 —
// "이 값이 어느 시점 보고인지"를 밝히는 메타 4종이다. 그룹 키(브리프
// 명시) 자체는 이 넷 중 rcept_no를 뺀 세 필드(bsns_year, reprt_code,
// stlm_dt)만 쓴다 — rcept_no는 같은 그룹(같은 보고서) 안에서는 상수라
// (SG 실측, se9-investigation.md Item 3 — 같은 그룹의 모든 행이 같은
// rcept_no를 공유) 그룹을 가르는 기준이 아니라 함께 지워지는 부수
// 필드일 뿐이다.
const DIVIDEND_GROUP_META_KEYS = ["bsns_year", "stlm_dt", "reprt_code", "rcept_no"];

/** 레코드 하나에서 dividendPeriodBlocks의 그룹 키 문자열을 만든다 —
 *  (bsns_year, reprt_code, stlm_dt) 세 필드(브리프 명시 그룹 키)를 "|"로
 *  이어 붙인다. 값이 없는 필드는 빈 문자열로 취급한다(다른 필드와
 *  구분자로 갈라지므로 undefined/null이 다른 실값과 같은 그룹으로
 *  잘못 뭉치지 않는다). */
function dividendGroupKey(r) {
  const year = r.bsns_year !== undefined && r.bsns_year !== null ? String(r.bsns_year) : "";
  const reprt = r.reprt_code !== undefined && r.reprt_code !== null ? String(r.reprt_code) : "";
  const stlm = r.stlm_dt !== undefined && r.stlm_dt !== null ? String(r.stlm_dt) : "";
  return year + "|" + reprt + "|" + stlm;
}

/** dividendGroupKey가 묶은 그룹의 대표 레코드(그 그룹의 첫 행) 하나로
 *  화면에 보여줄 제목을 만든다 — "2025 사업보고서 (결산일 2025-12-31)"
 *  형태(브리프 예시 그대로). reprt_code → 보고서명은 REPRT_CODE_LABELS를
 *  그대로 재사용한다(지어내 번역하지 않는다는 그 계약과 같다) — 목록에
 *  없는 코드(예상 밖 값)는 코드 원문을 그대로 보여준다(label()과 같은
 *  "모르면 숨기지 않는다" 계약). bsns_year·reprt_code·stlm_dt가 전부
 *  없으면(예상 밖 입력) label("dividends")로 폴백해 빈 제목을 만들지
 *  않는다. */
function dividendGroupTitle(r) {
  const year = r.bsns_year !== undefined && r.bsns_year !== null && r.bsns_year !== ""
    ? String(r.bsns_year) : "";
  const reprtRaw = r.reprt_code !== undefined && r.reprt_code !== null ? String(r.reprt_code) : "";
  const reprtLabel = Object.prototype.hasOwnProperty.call(REPRT_CODE_LABELS, reprtRaw)
    ? REPRT_CODE_LABELS[reprtRaw] : reprtRaw;
  const stlm = r.stlm_dt !== undefined && r.stlm_dt !== null && r.stlm_dt !== ""
    ? String(r.stlm_dt) : "";
  const head = [year, reprtLabel].filter(function (s) { return s; }).join(" ") || label("dividends");
  return stlm ? head + " (결산일 " + stlm + ")" : head;
}

/** 레코드 두 개가 모든 키·값에서 완전히 같은지 판정한다(키 순서 무관) —
 *  dividendPeriodBlocks의 완전 동일 중복 dedup(브리프 요구, SG 실측
 *  16쌍)에 쓴다. 키 개수가 다르면 즉시 false — jsonb 재정렬로 키 "순서"
 *  만 달라진 두 사본은 여전히 같다고 판정해야 하므로 Object.keys를 각자
 *  정렬해 비교한다(JSON.stringify는 키 순서에 민감해 이 목적에 못 쓴다).
 *  값 비교는 ===다 — 이 표의 모든 필드는 문자열(또는 null)이라 얕은
 *  비교로 충분하다(중첩 객체·배열이 없다, alotMatter 응답 형태 실측
 *  근거). 필드 하나라도 다르면(예: stock_knd가 "보통주"/"-") false다 —
 *  브리프 제약: "필드 하나라도 다르면 남긴다"(보통주/우선주 구분 가능성
 *  보존, 부분 매칭으로 지우지 않는다). */
function recordsIdentical(a, b) {
  if (!isPlainObject(a) || !isPlainObject(b)) return false;
  const aKeys = Object.keys(a).sort();
  const bKeys = Object.keys(b).sort();
  if (aKeys.length !== bKeys.length) return false;
  for (let i = 0; i < aKeys.length; i++) {
    if (aKeys[i] !== bKeys[i]) return false;
    if (a[aKeys[i]] !== b[bKeys[i]]) return false;
  }
  return true;
}

/** records(같은 dividendGroupKey 그룹) 안에서 완전 동일한 중복 사본을
 *  1건만 남긴다 — 먼저 나온 사본을 기준으로, 그 뒤에 완전히 같은 값의
 *  레코드가 또 나오면 생략한다(recordsIdentical). 순서는 유지(첫 등장만
 *  남긴다). */
function dedupIdenticalRecords(records) {
  const kept = [];
  let omitted = 0;
  for (const r of records) {
    const isDup = kept.some(function (k) { return recordsIdentical(k, r); });
    if (isDup) { omitted++; continue; }
    kept.push(r);
  }
  return { kept: kept, omitted: omitted };
}

/** dividends(alotMatter, fetch_dividend_history) 원본 레코드를
 *  (bsns_year, reprt_code, stlm_dt) 그룹당 표 하나로 나눈다(SE-9 Task 4,
 *  task-4-brief.md) — 실사용자(SG) 지적: 같은 사업연도·결산일이 매 행마다
 *  반복돼 어느 행이 어느 보고 시점 것인지 한눈에 안 들어온다. 그룹 제목이
 *  그 시점을 한 번만 말하고, 행에서는 그 세 필드(+그룹 안에서 상수인
 *  rcept_no)를 지운다 — 반복 제거가 요구의 핵심이다.
 *
 *  그룹 순서는 레코드가 등장하는 순서(첫 등장 기준) 그대로 둔다 —
 *  sourceGroupedBlocks·fundChain과 같은 이유(Map+groupOrder)로, DART가
 *  이미 최신 우선으로 주는 순서(브리프: "그룹 순서는 최신 우선(현 표시
 *  순서 유지)")를 임의로 재정렬하지 않는다.
 *
 *  그룹 안에서는 두 가지를 순서대로 한다:
 *  ① 완전 동일 중복 dedup(SG 실측 16쌍) — dedupIdenticalRecords, 몇
 *     건을 지웠는지는 note로 정직하게 남긴다(exec_treasury 패딩 생략과
 *     같은 원칙: "정보 보존" 예외에는 생략 사실을 화면에 표기한다).
 *  ② 그룹의 실질 값(항목명 se를 뺀 나머지 — stock_knd·thstrm·frmtrm·
 *     lwfr)이 전부 isNoDataMarker면(2026 1분기 실측: 항목명은 있는데
 *     값이 전부 "-") isMetaOnlyRecords와 같은 판정·같은 문구
 *     (metaOnlyNote)로 표를 만들지 않고 안내문만 남긴다(Task 3a와 동일
 *     처리 — 브리프 명시). se를 미리 빼는 이유: isMetaOnlyRecords는
 *     META_ONLY_KEYS 밖의 키에 실값이 하나라도 있으면 false를 돌려주는데,
 *     se(항목명, 예: "주당액면가액(원)")는 값이 전부 "-"인 그룹에서도
 *     늘 실제 문자열이라 그대로 두면 이 판정이 절대 참이 되지 않는다 —
 *     sourceGroupedBlocks가 source를 먼저 지우고 같은 함수를 부르는
 *     것과 같은 이유·같은 패턴이다.
 *
 *  차트(CHART_SPECS.dividends)는 이 그룹핑과 무관하게 renderSection
 *  (ui.js)이 원본 전체(value)로 따로 한 번만 그린다 — 그룹별 records를
 *  차트에 넘기면 그룹당 x축 점이 하나뿐이라 "연도·보고서구분별 추이"
 *  자체가 성립하지 않는다(브리프: "차트 입력을 바꾸지 않는다"). */
function dividendPeriodBlocks(records) {
  if (!Array.isArray(records)) return [];
  const order = [];
  const groups = new Map();
  for (const r of records) {
    if (!isPlainObject(r)) continue;
    const key = dividendGroupKey(r);
    if (!groups.has(key)) { groups.set(key, []); order.push(key); }
    groups.get(key).push(r);
  }

  const blocks = [];
  for (const key of order) {
    const dedup = dedupIdenticalRecords(groups.get(key));
    const title = dividendGroupTitle(dedup.kept[0]);

    const withoutGroupMeta = dedup.kept.map(function (r) {
      const copy = Object.assign({}, r);
      for (const k of DIVIDEND_GROUP_META_KEYS) delete copy[k];
      return copy;
    });

    const forBlankCheck = withoutGroupMeta.map(function (r) {
      const copy = Object.assign({}, r);
      delete copy.se;
      return copy;
    });
    if (isMetaOnlyRecords(forBlankCheck)) {
      blocks.push({
        title: title, table: null, records: null,
        note: metaOnlyNote(distinctReportCount(dedup.kept)),
      });
      continue;
    }

    // DIVIDENDS_PRIORITY_KEYS는 bsns_year/stlm_dt도 포함하지만, 이미 위
    // withoutGroupMeta에서 지워진 뒤라 reorderRecordFields가 "record에
    // 없는 키"로 자동 걸러(front 계산의 `k in record` 필터) 사실상
    // se → thstrm 순서만 남는다 — 별도 상수를 새로 만들 필요가 없다.
    const cleaned = withoutGroupMeta.map(function (r) {
      return reorderRecordFields(r, DIVIDENDS_PRIORITY_KEYS, RECORD_TAIL_KEYS);
    });
    const t = tableLayout(cleaned);
    if (t) {
      const block = { title: title, table: t, records: cleaned };
      if (dedup.omitted > 0) {
        block.note = "완전 동일한 중복 행 " + dedup.omitted + "건 생략";
      }
      blocks.push(block);
    }
  }
  return blocks;
}

// financialRatios가 만드는 기간 3종과, 각 기간이 financials 레코드의 어느
// 금액 열에서 오는지의 대응표. **당기를 마지막에 둔다** — 이 배열 순서가
// 곧 out.push 호출 순서이고(전전기→전기→당기), 그 순서가 그대로 두 곳에서
// 쓰인다: ① 아래 CHART_SPECS.financial_ratios의 x축("기간")은 SE-10부터
// 실제 연도 문자열("2023" 등)이라 chartData가 allNumeric 분기로 오름차순
// 정렬한다(위 chartData 주석 ①, numeric()이 "2023" 같은 순수 숫자 문자열을
// 그대로 파싱하므로 별도 정렬 키 없이 자동으로 과거→현재가 된다 —
// financialRatiosBaseYear가 없어(폴백) 값이 여전히 서수 문자열이면 숫자가
// 없는 순수 범주형이라 chartData가 정렬하지 않고 이 배열의 등장 순서를
// 그대로 쓴다, chartData 주석 ③ — 당기를 마지막에 두는 게 그 폴백 경로의
// 안전망이다). ② 같은 (구분, 지표) 조합이 기간마다 반복 나오므로, 이
// 조합만으로 마지막 값을 찾는 코드(예: dict 컴프리헨션)는 자연히 당기
// 값을 얻는다 — 순서를 바꾸면 이런 코드가 조용히 옛 기간 값을 돌려주게
// 된다.
//
// yearOffset: 당기(bsns_year)로부터 몇 해를 빼야 이 기간의 실제 연도가
// 되는지(SE-10 Task 1). financialRatios가 records에서 bsns_year를 한 번
// 계산해(financialRatiosBaseYear) `String(baseYear - yearOffset)`로 실제
// 연도 문자열을 만든다 — 계산 불가(레코드에 bsns_year가 전혀 없거나 숫자로
// 못 읽음)면 이 period 리터럴("전전기" 등)로 안전 폴백한다(판정 불가 시
// 지우지 않는다 원칙, se10-investigation.md Q1b).
const RATIO_PERIODS = [
  { period: "전전기", field: "bfefrmtrm_amount", yearOffset: 2 },
  { period: "전기", field: "frmtrm_amount", yearOffset: 1 },
  { period: "당기", field: "thstrm_amount", yearOffset: 0 },
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

/** 지표 하나(예: 영업이익률)를 한 기간에 대해 계산한다. `기간` 인자는
 *  SE-10부터 financialRatios가 미리 계산해 넘기는 문자열이다 — 실제
 *  연도("2024") 또는(bsns_year를 못 읽었을 때) 서수 라벨("전기") 둘 다
 *  올 수 있다. 이 함수는 그 값을 그대로 결과 행에 싣기만 할 뿐, 어느 쪽인지
 *  판단하지 않는다(연도 계산·폴백 판단은 호출부 financialRatios의 책임).
 *  분자·분모 계정 중 하나라도 없거나(계정 자체가 안 잡힘) 분모가 0이면
 *  값은 null이고 **왜 없는지 사유로 남긴다** — 조용히 항목을 빼지 않는다
 *  (브리프 원칙). 재료는 항상 두 계정 이름을 키로 갖는 객체를 돌려준다(값이 null이어도
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

  // SE-8 Task 4: 반환 키 순서는 지표→값→구분→기간→계산식→재료다(task-4-brief.md
  // — 실사용자 지적: "표를 구성할 때 이용자에게 어떤 정보가 유용할지 고민부터
  // 하고 배치를 해야한다"). 구분(연결/별도)은 지우지 않는다 — 순서만
  // 뒤로 밀 뿐, 각 값 옆에 그대로 붙어 있다(SE-4f 원칙: 연결·별도를 섞으면
  // 거짓이 된다). 이 함수를 키 "이름"으로 읽는 호출부(ratioBasisText의
  // row.계산식·row.재료, buildFinancialRatiosBlock의 r.구분 등)는 순서가
  // 아니라 이름으로 접근하므로 이 재배치에 영향받지 않는다.
  const out = { 지표: def.name, 값: 값, 구분: 구분, 기간: 기간, 계산식: def.formula, 재료: 재료 };
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

  // 키 순서는 computeRatio와 같은 이유로 지표→값→구분→기간→계산식→재료다
  // (SE-8 Task 4, 위 computeRatio 주석 참고).
  const out = {
    지표: "자본잠식률", 값: 값, 구분: 구분, 기간: 기간,
    계산식: "(자본금 − 자본총계) ÷ 자본금", 재료: 재료,
  };
  if (값 === null) out.사유 = 사유;
  return out;
}

/** records(원본 financials 레코드 배열, financialRatios가 받는 것과 같은
 *  배열)에서 bsns_year를 한 번 계산한다(SE-10 Task 1, se10-investigation.md
 *  Q1a) — se_server가 financials를 연도 파라미터 없이 단일 호출하는
 *  구조라 배열 전체에서 bsns_year가 상수인 것이 구조적으로 보장되므로,
 *  첫 유효값 하나만 보면 된다(모든 행을 순회해 일치를 검증하지 않는다 —
 *  그 보장 자체가 이 함수의 전제다). 값을 못 읽으면(레코드에 필드 자체가
 *  없거나 숫자로 파싱되지 않으면) null을 돌려줘 호출부가 기존 서수
 *  라벨("전전기" 등)로 안전 폴백하게 한다 — 판정 불가 시 지우지 않는다
 *  원칙(브리프). */
function financialRatiosBaseYear(records) {
  if (!Array.isArray(records)) return null;
  for (const r of records) {
    if (!r || typeof r !== "object") continue;
    const y = r.bsns_year;
    if (y === undefined || y === null || y === "") continue;
    const n = Number(y);
    if (Number.isFinite(n)) return n;
  }
  return null;
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
 *  이유가 바로 이 혼입이었다(위 CHART_SPECS 주석 참고).
 *
 *  **SE-10 Task 1**: 각 행의 `기간`은 서수 라벨("전전기" 등)이 아니라
 *  records에서 한 번 계산한 실제 연도 문자열("2024")이다 —
 *  financialRatiosBaseYear가 bsns_year를 못 읽으면(null) 이 함수 자체가
 *  깨지지 않고 RATIO_PERIODS의 서수 라벨로 조용히 폴백한다(사용자에게는
 *  이전 화면과 동일하게 보인다 — 회귀가 아니다). */
function financialRatios(records) {
  if (!Array.isArray(records)) return [];
  const byDiv = indexAccountsByDiv(records);
  const baseYear = financialRatiosBaseYear(records);

  const out = [];
  for (const [div, accounts] of byDiv) {
    const 구분 = FS_DIV_LABELS[div] || div;
    for (const p of RATIO_PERIODS) {
      const 기간 = baseYear !== null ? String(baseYear - p.yearOffset) : p.period;
      for (const def of RATIO_DEFS) {
        out.push(computeRatio(구분, 기간, def, accounts, p.field));
      }
      out.push(computeCapitalImpairment(구분, 기간, accounts, p.field));
    }
  }
  return out;
}

/** financialRatios(records)가 만든 파생 지표 행을 `기간`(실제 연도 또는
 *  폴백 서수 라벨) 값으로 묶는다(SE-10 Task 1) — dividendPeriodBlocks
 *  (위)와 같은 Map+groupOrder 메커니즘이지만 그룹 순서 규칙은 다르다.
 *  dividendPeriodBlocks는 원본 레코드가 이미 최신 우선으로 오는 것을
 *  전제로 첫 등장 순서를 그대로 쓰지만(그 함수 주석 참고), financialRatios
 *  는 정반대로 RATIO_PERIODS 순서(전전기→전기→당기, 오래된 것부터) 그대로
 *  행을 내보낸다(위 RATIO_PERIODS 주석) — 그래서 여기서는 연도를 **명시
 *  내림차순(최신 먼저)** 으로 정렬한다(브리프: "기존 화면 표시 순서
 *  유지" — 사용자가 보던 순서가 최신 항목이 위에 오는 흐름이었다).
 *
 *  연도 계산이 폴백된 경우(기간 값이 여전히 "전전기"/"전기"/"당기" 같은
 *  서수 문자열)에는 숫자가 아니라 정렬 기준이 없다 — 억지로 정렬하지
 *  않고 원래 등장 순서(전전기→전기→당기, 그 자체가 이미 시간순)를 그대로
 *  둔다. 두 경우를 구분하는 기준은 그룹 키 전부가 순수 숫자 문자열인지
 *  하나로 충분하다(financialRatiosBaseYear가 성공하면 모든 그룹 키가
 *  4자리 연도이고, 실패하면 전부 서수 라벨이다 — 한 호출 안에서 섞이지
 *  않는다, 위 financialRatios 주석).
 *
 *  그룹 제목으로 승격된 정보(연도)는 표를 그리는 쪽(ui.js
 *  buildFinancialRatiosBlock)이 행에서 지운다 — 이 함수 자신은 행을
 *  변형하지 않고 원본 그대로 묶어서만 돌려준다(원칙: 그룹 제목으로
 *  승격된 정보는 행에서 제거 — SE-9 Task 4 dividendPeriodBlocks와 동일
 *  패턴, 실제 제거는 표시 형태를 만드는 ui.js 쪽 책임). 그룹 안에서는
 *  구분(연결/별도)을 또 표로 쪼개지 않는다(task-1-brief.md 결정 사항) —
 *  이 함수는 기간으로만 묶고, 구분은 각 행에 그대로 남아 있다. */
function financialRatiosByYear(ratios) {
  if (!Array.isArray(ratios)) return [];
  const order = [];
  const groups = new Map();
  for (const r of ratios) {
    if (!isPlainObject(r)) continue;
    const key = r.기간 !== undefined && r.기간 !== null ? String(r.기간) : "";
    if (!groups.has(key)) { groups.set(key, []); order.push(key); }
    groups.get(key).push(r);
  }

  const allYearsNumeric = order.length > 0 && order.every(function (k) { return /^\d+$/.test(k); });
  const groupOrder = allYearsNumeric
    ? order.slice().sort(function (a, b) { return Number(b) - Number(a); })
    : order;

  const blocks = [];
  for (const key of groupOrder) {
    const title = allYearsNumeric ? key + "년" : key;
    blocks.push({ title: title, key: key, ratios: groups.get(key) });
  }
  return blocks;
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

// DIVIDEND_DRAIN(적자 시점 배당 유출) — se 문자열·판정 조건은
// core(dart_risk_mcp/core/dart_client.py의 detect_dividend_drain, 2026-07-30
// 두산 00117212 실측으로 확정)와 정확히 같다(SE-12 Task 2, task-2-brief.md).
// 정확 일치(느슨한 "현금배당금" in se 매칭 아님)를 쓰는 이유는 위
// DIVIDEND_SE_FIELDS 주석과 같다 — "주당 현금배당금(원)"(단가, 다른
// 개념)까지 걸리는 걸 막는다.
//
// ⚠ CFS(연결) net_income은 alotMatter가 원래 담고 있는
// 지배기업소유주지분순이익(비지배지분 제외분)이지 회사 전체 연결
// 당기순이익이 아니다(core 주석과 동일 근거, 두산 2023 실측: alotMatter
// CFS -388,279백만원 vs 실제 총 연결당기순이익 +272,073,643,932원 — 부호까지
// 다름, 2023 두산로보틱스 IPO로 비지배지분 확대). OFS(별도)는 비지배지분
// 개념이 없어 무관하다. 화면 문구(ui.js buildDividendDrainBlock)는 이
// 사실을 "(연결·지배지분 기준)"으로 병기한다 — server.py의 track_fund_usage
// 렌더와 같은 라벨.
const DIVIDEND_DRAIN_DIVIDEND_SE = "현금배당금총액(백만원)";
const DIVIDEND_DRAIN_NI_SE = {
  CFS: "(연결)당기순이익(백만원)",
  OFS: "(별도)당기순이익(백만원)",
};

// 최종 리뷰 지적(2026-07-30 SK하이닉스 00164779 실측 확정, core
// dart_client.py의 _DIVIDEND_DRAIN_ANNUAL_REPRT_CODE 주석과 동일 근거):
// alotMatter는 사업연도 하나당 reprt_code 4종(11011 사업·11012 반기·
// 11013 1분기·11014 3분기)을 각각 별도 호출로 채우는데, 분기/반기
// 배당 지급 회사는 4개 reprt_code 모두 "-"가 아닌 값이 채워진다 —
// 이 값들은 그 시점까지의 누적치일 뿐, 독립된 사업연도 결과가 아니다.
// 사업보고서(11011)만 최종 확정치이므로 이것만 대상으로 삼는다 —
// 아니면 같은 사업연도가 최대 4배로 중복 플래그된다.
const DIVIDEND_DRAIN_ANNUAL_REPRT_CODE = "11011";

/** dividends 원본 배열에서 "당기순이익이 음수인데 같은 사업연도에
 *  현금배당이 있었다"는 사실을 CFS/OFS 별개로 뽑는다(SE-12 Task 2).
 *  그룹핑 키((bsns_year, reprt_code))와 순회 방식은 위 dividendVsIncome을
 *  그대로 따른다 — 신규 그룹핑 로직을 새로 만들지 않는다.
 *
 *  reprt_code="11011"(사업보고서)만 대상으로 삼는다 — 위
 *  DIVIDEND_DRAIN_ANNUAL_REPRT_CODE 주석 참고. 11012/11013/11014는 그
 *  시점까지의 누적치일 뿐이라 포함하면 같은 사업연도가 중복 플래그된다
 *  (SK하이닉스 실측 확정, core detect_dividend_drain 주석과 동일 근거).
 *
 *  연결(CFS)·별도(OFS)는 절대 하나로 합쳐 판정하지 않는다 — 두산 실측이
 *  정확히 "한쪽만 적자"(2022 CFS만) 또는 "양쪽 다 적자"(2023 CFS·OFS
 *  둘 다) 사례라, 병합하면 놓치거나 왜곡된다(core detect_dividend_drain
 *  주석과 동일 원칙).
 *
 *  반환: {bsns_year, reprt_code, fs_div, dividend, net_income}(둘 다
 *  백만원) 목록, bsns_year마다 최대 2건(fs_div CFS/OFS), reprt_code는
 *  항상 "11011". bsns_year → fs_div 순 정렬 — core의 반환 계약과 동일. */
function dividendDrainFlags(records) {
  if (!Array.isArray(records)) return [];
  const groups = new Map();
  const order = [];
  for (const r of records) {
    if (!r || typeof r !== "object") continue;
    const reprt = r.reprt_code !== undefined && r.reprt_code !== null ? String(r.reprt_code) : "";
    if (reprt !== DIVIDEND_DRAIN_ANNUAL_REPRT_CODE) continue; // 반기/분기 누적치 노이즈 제외
    const year = r.bsns_year !== undefined && r.bsns_year !== null ? String(r.bsns_year) : "";
    const key = year + " " + reprt;
    if (!groups.has(key)) {
      groups.set(key, { bsns_year: year, reprt_code: reprt, se: Object.create(null) });
      order.push(key);
    }
    const se = r.se;
    if (se === DIVIDEND_DRAIN_DIVIDEND_SE || se === DIVIDEND_DRAIN_NI_SE.CFS || se === DIVIDEND_DRAIN_NI_SE.OFS) {
      groups.get(key).se[se] = r.thstrm;
    }
  }

  const flags = [];
  for (const key of order) {
    const g = groups.get(key);
    const dividend = numeric(g.se[DIVIDEND_DRAIN_DIVIDEND_SE]);
    if (dividend === null || dividend <= 0) continue; // 현금배당이 없으면(또는 0/음수면) 유출이라 말할 근거가 없다
    for (const fsDiv of ["CFS", "OFS"]) {
      const ni = numeric(g.se[DIVIDEND_DRAIN_NI_SE[fsDiv]]);
      if (ni === null || ni >= 0) continue; // 당기순이익이 없거나 흑자면 발화하지 않는다
      flags.push({
        bsns_year: g.bsns_year, reprt_code: g.reprt_code, fs_div: fsDiv,
        dividend: dividend, net_income: ni,
      });
    }
  }
  flags.sort(function (a, b) {
    if (a.bsns_year !== b.bsns_year) return a.bsns_year < b.bsns_year ? -1 : 1;
    if (a.reprt_code !== b.reprt_code) return a.reprt_code < b.reprt_code ? -1 : 1;
    if (a.fs_div !== b.fs_div) return a.fs_div < b.fs_div ? -1 : 1;
    return 0;
  });
  return flags;
}

/** financials(재무제표, 단일 최근 사업연도)의 이익잉여금(CFS/OFS)과
 *  dividends(배당)의 같은 사업연도 현금배당금총액을 나란히 놓는다(SE-12
 *  Task 2, 요구사항 B).
 *
 *  **단일 연도 비교다, 추이가 아니다** — financials는 se_server가 연도
 *  파라미터 없이 단일 호출하는 구조라 항상 한 사업연도만 담는다
 *  (financialRatiosBaseYear 주석, SE-10 Task 1 발견과 동일 구조적 한계).
 *  이 함수도 그 단일 연도만 보고, 그 연도와 dividends의 같은 연도를
 *  찾을 뿐 여러 해를 훑지 않는다.
 *
 *  **연도가 안 겹치면 억지로 비교하지 않는다** — financials의 사업연도와
 *  일치하는 dividends 그룹이 없으면(배당 자체가 없거나 다른 연도만 있으면)
 *  overlap:false로 그 사실만 돌려준다(호출부가 "배당 기록 없음" 안내로
 *  표기, ui.js buildDividendVsRetainedEarningsBlock).
 *
 *  **단위**: financials의 이익잉여금은 원 단위 그대로(원본), dividends의
 *  현금배당금총액은 백만원 단위라 원으로 환산해(×1,000,000) 반환한다 —
 *  financials 원본 표(formatValue/formatAmount)가 이미 원 단위를 화면
 *  표준으로 쓰고 있어(AMOUNT_FIELDS), 그 기존 표기 관례를 따르는 쪽이
 *  새 표기 하나를 더 만드는 것보다 낫다.
 *
 *  이익잉여금 자체가 CFS·OFS 둘 다 없으면(계정이 아예 안 잡히면, 또는
 *  financials가 아직 도착 전이면) null을 돌려준다 — 비교할 재료가 없다는
 *  사실은 "연도가 안 겹친다"는 사실과 다르다(호출부는 null이면 블록 자체를
 *  그리지 않는다, dividendVsIncome이 빈 배열일 때 블록이 안 생기는 것과
 *  같은 SE 관례). */
function dividendVsRetainedEarnings(financialsRecords, dividendRecords) {
  if (!Array.isArray(financialsRecords) || !Array.isArray(dividendRecords)) return null;
  const year = financialRatiosBaseYear(financialsRecords);
  if (year === null) return null; // 사업연도를 못 읽으면 비교 자체를 시도하지 않는다

  const byDiv = indexAccountsByDiv(financialsRecords);
  function retainedFor(div) {
    const accounts = byDiv.get(div);
    if (!accounts) return null;
    const row = accounts.get("이익잉여금");
    return row ? numeric(row.thstrm_amount) : null;
  }
  const cfs = retainedFor("CFS");
  const ofs = retainedFor("OFS");
  if (cfs === null && ofs === null) return null; // 이익잉여금 계정 자체가 없다

  const yearStr = String(year);
  const dvRows = dividendVsIncome(dividendRecords); // 신규 그룹핑 로직 발명 금지 — 재사용
  const matches = dvRows.filter(function (r) { return r.bsns_year === yearStr; });

  if (matches.length === 0) {
    return { bsns_year: yearStr, overlap: false, retained_earnings: { CFS: cfs, OFS: ofs }, dividend_won: null };
  }
  // 같은 사업연도에도 분기 보고서(1분기·반기·3분기·사업보고서)마다 그룹이
  // 따로 있을 수 있다 — 사업보고서(11011, 연간 확정치)를 우선하고, 없으면
  // (드물게 사업보고서 자체가 아직 없는 연도) 등장한 첫 그룹을 쓴다.
  const chosen = matches.find(function (r) { return r.reprt_code === "11011"; }) || matches[0];
  const dividendManwon = chosen[DIVIDEND_SE_FIELDS[0]]; // "현금배당금총액(백만원)" — dividendVsIncome이 null이면 애초에 행을 안 만든다
  return {
    bsns_year: yearStr, overlap: true,
    retained_earnings: { CFS: cfs, OFS: ofs },
    dividend_won: dividendManwon * 1e6,
  };
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

/** fund_usage(자금사용 내역) 원본 행(회사에 따라 94개까지 나온다)을
 *  납입일(pay_de) 단위 "조달건"으로 묶고, 그 안에서 용도(plan_useprps)별로
 *  계획 금액을 분해한다(SE-5a Task 1, task-1-brief.md).
 *
 *  **DART는 분기 보고서마다 같은 누적치를 다시 보고한다.** 실측(엔켐
 *  2021.10.26)은 24행이지만 용도는 3종뿐이다 — 같은 (pay_de,
 *  plan_useprps) 쌍이 최대 8번 반복 보고된다. 그대로 합치면 계획 합계가
 *  N배로 부풀려지므로, 같은 쌍에서는 **행 하나만** 남긴다.
 *
 *  남길 기준은 plan_amount가 가장 큰 행이다. "가장 최근 보고"를 고르는
 *  편이 더 자연스러워 보이지만, 이 응답에는 그걸 판단할 신뢰할 만한
 *  필드가 없다 — year는 보고 시점이 아니라 사업연도이고, tm은 실측상
 *  항상 "-"이며, 분기 구분(reprt_code)은 core(dart_client.fetch_fund_usage)가
 *  공모·사모 두 엔드포인트를 합치는 과정에서 이미 떨어져 나간다. 그렇다고
 *  아무 행이나 골라도 되는 것도 아니다 — 계획 금액 자체가 보고 시점마다
 *  바뀐 사례가 이미 확인됐다(fundPlanChanges 위 주석: 엔켐 운영자금이
 *  34,291,000,000 → 35,291,000,000으로 바뀜). **"최신값을 안다"고
 *  주장하지 않고, "고를 근거가 없으니 지금까지 보고된 것 중 가장 큰
 *  값을 쓴다"는 명시적 선택**이다 — 동률이면 먼저 나온 행을 유지한다
 *  (strictly-greater일 때만 교체).
 *
 *  용도 텍스트의 개행은 공백 하나로 정규화한다(실측: "원재료 매입대금
 *  및\n해외공장 증설자금") — 정규화 없이 비교하면 개행 유무 차이만으로
 *  같은 용도가 서로 다른 항목 두 개로 쪼개진다.
 *
 *  pay_de가 결측(isNoDataMarker — "-" 등)인 행도 버리지 않는다.
 *  pay_de: null 묶음 하나로 모은다 — 제이스코홀딩스처럼 26건 전부
 *  pay_de·plan_useprps·real_dtls_cn이 결측인 회사가 실재하고, "내역이
 *  없다"와 "내역은 있는데 납입일이 공시되지 않았다"는 다른 사실이다.
 *
 *  결과는 sort_key(axisSortKey) 내림차순 — 최신 조달이 위로 온다.
 *  sort_key가 null인 묶음(pay_de 결측)은 맨 뒤로 보낸다. 새 날짜 파서를
 *  쓰지 않고 axisSortKey를 그대로 재사용한다 — numeric()은 "2021.10.26"
 *  처럼 점이 섞인 문자열을 통째로 null로 돌려줘(SE-4f에서 정렬이
 *  실동작 없이 죽은 원인) 이런 날짜 비교에 쓸 수 없다. */
function fundChain(records) {
  if (!Array.isArray(records)) return [];

  const groups = new Map(); // key: pay_de(문자열) 또는 null
  const groupOrder = [];

  for (const r of records) {
    if (!r || typeof r !== "object") continue;
    const payDe = isNoDataMarker(r.pay_de) ? null : String(r.pay_de);
    if (!groups.has(payDe)) {
      groups.set(payDe, []);
      groupOrder.push(payDe);
    }
    groups.get(payDe).push(r);
  }

  const out = [];
  for (const payDe of groupOrder) {
    const rows = groups.get(payDe);

    const uses = new Map(); // key: 정규화된 purpose(문자열) 또는 null
    const useOrder = [];
    for (const r of rows) {
      const purpose = isNoDataMarker(r.plan_useprps)
        ? null
        : String(r.plan_useprps).replace(/\s*\n\s*/g, " ").trim();
      if (!uses.has(purpose)) {
        uses.set(purpose, []);
        useOrder.push(purpose);
      }
      uses.get(purpose).push(r);
    }

    let totalPlan = 0;
    const useList = [];
    for (const purpose of useOrder) {
      const useRows = uses.get(purpose);
      // 같은 (pay_de, purpose) 반복 보고 중 plan_amount가 가장 큰 행을
      // 남긴다 — 위 함수 주석에 그 이유를 적었다.
      let best = useRows[0];
      let bestAmount = markNumber(best.plan_amount);
      for (let i = 1; i < useRows.length; i++) {
        const amt = markNumber(useRows[i].plan_amount);
        if (amt !== null && (bestAmount === null || amt > bestAmount)) {
          best = useRows[i];
          bestAmount = amt;
        }
      }
      const plan = bestAmount === null ? 0 : bestAmount;
      totalPlan += plan;
      // SE-8 Task 3 — dffrnc_resn이 각주 마커("주1)")뿐이면 원문 마커를
      // 지우지 않고 정직한 안내를 덧붙인다(footnoteMarkerNote, 위 주석
      // 참고). best.rcept_no는 실측(dart_client._normalize_fund_usage)
      // 상 fund_usage 레코드에 애초에 없는 필드라 오늘은 항상 undefined지만,
      // 값을 지어내는 대신 있으면 쓰고 없으면 안내만 남기도록 그대로
      // 넘긴다(있지도 않은 값을 만들어내지 않는다).
      const diffReason = isNoDataMarker(best.dffrnc_resn) ? null
        : footnoteMarkerNote(best.dffrnc_resn, isNoDataMarker(best.rcept_no) ? null : best.rcept_no);
      useList.push({
        purpose: purpose,
        plan: plan,
        real: markNumber(best.real_dtls_amount),
        diff_reason: diffReason,
        rows: useRows.length,
      });
    }

    out.push({
      pay_de: payDe,
      sort_key: payDe === null ? null : axisSortKey(payDe),
      total_plan: totalPlan,
      uses: useList,
      row_count: rows.length,
    });
  }

  out.sort(function (a, b) {
    if (a.sort_key === null && b.sort_key === null) return 0;
    if (a.sort_key === null) return 1;
    if (b.sort_key === null) return -1;
    return b.sort_key - a.sort_key;
  });

  return out;
}

// fundChainDisclosureHints가 매칭 대상으로 삼는 신호 키 5개(task-2-brief.md).
// classifyDisclosureCategory(아래)의 카테고리(0~8) 단위로는 이 목적에 쓸 수
// 없다 — 예를 들어 category 1("CB/채권")에는 CB_BW 말고도 CB_REPAY·
// CB_ROLLOVER·CB_BUYBACK·TREASURY_EB 등 조달과 무관한 키가 섞여 있어,
// category만 보고 "조달 공시다"라고 단정하면 과다 매칭이 된다.
const PROCUREMENT_SIGNAL_KEYS = ["CB_BW", "3PCA", "RIGHTS_UNDER", "EB", "RCPS"];

/** reportNm이 PROCUREMENT_SIGNAL_KEYS 중 하나의 키워드에 걸리는지만 본다.
 *  classifyDisclosureCategory와 같은 원본(signalsData.signals·keywords·
 *  amendment_pattern)·같은 알고리즘(정정공시 제외 → 키워드 포함 검사)을
 *  쓴다 — "로직을 새로 만들지 마라"(브리프)는 이 signalsData·이 매칭
 *  방식을 그대로 쓰라는 뜻이지, 이미 있는 함수의 반환 단위(카테고리)를
 *  억지로 재활용하라는 뜻은 아니라고 판단했다(위 PROCUREMENT_SIGNAL_KEYS
 *  주석 참고 — 카테고리로는 이 5개만 골라낼 수 없다).
 *
 *  정정공시([기재정정] 등)는 공개 뷰어·classifyDisclosureCategory와
 *  마찬가지로 제외한다 — 정정은 새 조달 결정이 아니라 기존 보고를
 *  고친 것이다. */
function isProcurementDisclosure(reportNm, signalsData) {
  const nm = typeof reportNm === "string" ? reportNm : "";
  if (typeof signalsData.amendment_pattern === "string") {
    try {
      if (new RegExp(signalsData.amendment_pattern).test(nm)) return false;
    } catch (e) {
      // 정규식 자체가 깨졌으면(예상 밖 데이터) 정정 판정만 건너뛰고
      // 아래 키워드 매칭으로 이어간다 — 분류를 통째로 포기하지 않는다.
    }
  }
  for (const s of signalsData.signals) {
    if (!s || PROCUREMENT_SIGNAL_KEYS.indexOf(s.key) === -1) continue;
    const keywords = Array.isArray(s.keywords) ? s.keywords : [];
    for (const kw of keywords) {
      if (kw && nm.indexOf(kw) !== -1) return true;
    }
  }
  return false;
}

/** axisSortKey가 만든 8자리 정수(YYYYMMDD, 예: 20211026)를 실제 달력
 *  날짜로 되돌린다. 8자리가 아니거나(예상 밖 rcept_dt) 월/일이 달력에
 *  없으면(예: 13월, 2월 30일) null — 날짜를 알 수 없는 값을 "이전"이라
 *  우기지 않는다.
 *
 *  이건 axisSortKey를 대체하는 새 날짜 파서가 아니다 — 원본 문자열
 *  ("2021.10.26"·"20260123")을 다시 파싱하지 않고, axisSortKey가 이미
 *  정규화해 준 숫자 하나만 년/월/일로 다시 쪼갠다. 필요한 이유는
 *  days_before(실제 날짜 차이)가 axisSortKey 정수끼리의 뺄셈으로는 나오지
 *  않기 때문이다 — 20260101 - 20251231 = 8730이지만 실제로는 하루
 *  차이다(월경계를 정수 뺄셈이 모른다). */
function sortKeyToUTCDate(sortKey) {
  if (sortKey === null || sortKey === undefined) return null;
  const s = String(sortKey);
  if (!/^\d{8}$/.test(s)) return null;
  const y = Number(s.slice(0, 4));
  const mo = Number(s.slice(4, 6));
  const d = Number(s.slice(6, 8));
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return null;
  const dt = new Date(Date.UTC(y, mo - 1, d));
  // 존재하지 않는 날짜(예: 2021-02-30)는 Date.UTC가 다음 달로 굴려버린다
  // (JS의 관용 동작) — 되읽어 원래 년/월/일과 다르면 애초에 없는 날짜였다는
  // 뜻이므로 null로 되돌린다.
  if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== d) {
    return null;
  }
  return dt;
}

const MS_PER_DAY = 24 * 60 * 60 * 1000;

/** fundChain(records) 결과(조달건)와 disclosures(공시 원본 레코드)를
 *  날짜 근접으로 병치한다(SE-5a Task 2, task-2-brief.md).
 *
 *  **조인이 아니다.** 자금사용 내역 행과 특정 공시를 잇는 열쇠(rcept_no
 *  등)가 DART 응답에 없다(계획 "배경: 실측으로 확인한 것" §조달 공시는
 *  있다). 여기서 하는 일은 "이 납입일 이전 windowDays 안에 이런 조달
 *  신호 공시가 있었다"는 시간 근접 사실만 나열하는 것이고, 그 이상(어느
 *  공시가 이 조달건의 원인인지)은 단정하지 않는다 — 함수 이름을
 *  fundChainMatch가 아니라 fundChainDisclosureHints로 둔 것, 하나로
 *  좁히지 않고 걸리는 공시를 전부 돌려주는 것, days_before를 감춘 판정
 *  없이 그대로 노출하는 것, 화면(Task 3)이 windowDays 값을 반드시
 *  표시하는 것 모두 이 불확실성을 지우지 않기 위해서다.
 *
 *  **납입일 "이전"만 본다.** 조달 결정은 납입에 앞선다 — days_before가
 *  0 이하(당일 포함)이거나 음수(공시가 납입 이후)면 인과가 뒤집히므로
 *  제외한다.
 *
 *  **날짜는 axisSortKey로만 다룬다.** pay_de("2021.10.26")·rcept_dt
 *  ("20260123") 형식이 다르다 — numeric()은 점이 섞이면 통째로 null을
 *  돌려줘(SE-4f 사고) 이 비교에 쓸 수 없다. axisSortKey는 숫자만
 *  이어붙여 두 형식 모두 YYYYMMDD 정수로 정규화하고, sortKeyToUTCDate
 *  (위)가 그 정수를 실제 날짜로 되돌려 days_before를 계산한다.
 *
 *  sort_key가 null인 조달건(pay_de 결측)은 앵커로 삼을 날짜가 없어
 *  결과에서 아예 빠진다 — 화면이 "언제 공시됐는지" 자체를 물을 수
 *  없는 묶음이기 때문이다.
 *
 *  signalsData가 없거나 형태가 예상과 다르면(로드 실패) {}를 돌려주고
 *  예외를 던지지 않는다 — 호출자(Task 3 렌더)가 이 신호로 힌트 블록만
 *  건너뛴다(SE-4f classifyDisclosureCategory와 같은 폴백 계약). */
function fundChainDisclosureHints(chain, disclosures, signalsData, windowDays) {
  if (!signalsData || !Array.isArray(signalsData.signals)) return {};
  if (!Array.isArray(chain) || !Array.isArray(disclosures)) return {};
  const window = typeof windowDays === "number" && windowDays > 0 ? windowDays : 90;

  const out = {};
  for (const entry of chain) {
    if (!entry || entry.sort_key === null || entry.sort_key === undefined) continue;
    const payDate = sortKeyToUTCDate(entry.sort_key);
    if (payDate === null) continue;

    const hits = [];
    for (const d of disclosures) {
      if (!d || typeof d !== "object") continue;
      if (!isProcurementDisclosure(d.report_nm, signalsData)) continue;
      const discDate = sortKeyToUTCDate(axisSortKey(d.rcept_dt));
      if (discDate === null) continue;

      const daysBefore = Math.round((payDate.getTime() - discDate.getTime()) / MS_PER_DAY);
      if (daysBefore <= 0 || daysBefore > window) continue;

      hits.push({
        rcept_no: d.rcept_no,
        rcept_dt: d.rcept_dt,
        report_nm: d.report_nm,
        days_before: daysBefore,
      });
    }

    if (hits.length > 0) {
      // 가까운 공시(days_before가 작을수록)를 앞에 둔다 — 순위·중요도
      // 판정이 아니라 화면이 나열하는 순서일 뿐이다(v0.8.5).
      hits.sort(function (a, b) { return a.days_before - b.days_before; });
      out[entry.sort_key] = hits;
    }
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
  // index.html의 matchSignals 키워드 매칭 순서를 그대로 재현한다(브리프).
  // 단, 정정공시(AMEND_RE) 처리는 SE-7 Task 2에서 갈라졌다 — 공개
  // 뷰어는 정정이면 배제하지만 여기는 접두어만 벗기고 내용을 계속
  // 본다(아래 classifyDisclosureCategory 주석 참고). signalsData가
  // 없거나(로드 실패) 형태가 예상과 다르면 chartData가
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
  // 참고). x는 "기간"이다 — SE-10부터 이 값은 보통 실제 연도 문자열
  // ("2023" 등, financialRatiosBaseYear가 bsns_year를 읽었을 때)이라
  // chartData의 allNumeric 분기(위 chartData 주석 ①)가 숫자로 오름차순
  // 정렬한다(numeric()이 순수 숫자 문자열을 그대로 파싱하므로 "2023" <
  // "2024" < "2025"가 사전순이 아니라 실제 크기 비교로 성립한다) — 과거→
  // 현재 왼쪽에서 오른쪽으로 흐르는 것이 저절로 보장된다. bsns_year를
  // 못 읽어 서수 라벨("전전기" 등)로 폴백한 경우에만 숫자가 없는 순수
  // 범주형이 되어 chartData가 정렬하지 않고 등장 순서를 그대로 쓴다
  // (chartData 주석 ③) — financialRatios가 그 폴백 경로에서도 전전기→
  // 전기→당기 순으로 내보내므로(위 RATIO_PERIODS 주석) 등장 순서 자체가
  // 이미 시간순이라 정렬이 없어도 안전하다. 다섯 지표 모두 단위가 %로
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

/** reportNm이 signalsData.amendment_pattern(정정 접두어 전용 정규식,
 *  실측: `^\[(?:기재정정|첨부추가|정정)[^\]]*\]\s*`)에 걸리는 "정정
 *  공시"인지 사실만 돌려준다(SE-7 Task 2, task-2-brief.md).
 *
 *  core의 `is_amendment_disclosure`(dart_risk_mcp/core/signals.py)와
 *  같은 원본 정규식을 쓰지만 이 함수는 표시 계층 전용이다 — core
 *  버전을 대신 부르지 않는 이유는 그게 Python이라 브라우저/node에서
 *  못 부르기 때문이고, signals-data.json이 export_tool_data.py를 통해
 *  이미 그 정규식 문자열을 그대로 실어 나른다(브리프: "이미 있어서
 *  만들지 않는 것" — 재구현이 아니라 같은 데이터를 그대로 읽는 것).
 *
 *  signalsData가 없거나 amendment_pattern이 문자열이 아니거나(로드
 *  실패·형태 변경) 정규식 자체가 깨졌으면(예상 밖 데이터) false —
 *  "정정인지 모른다"를 "정정이 아니다"로 보수적으로 처리해, 아래
 *  classifyDisclosureCategory가 접두어를 벗기지 않고 원본 그대로
 *  키워드 매칭을 계속하게 한다(분류를 통째로 포기하지 않는다).
 *
 *  죽은 코드가 아니다 — classifyDisclosureCategory가 접두어를 벗길지
 *  판단하는 데 그대로 재사용한다(정정 판별 정규식을 두 곳에서 따로
 *  손으로 맞추지 않는 단일 출처). */
function isAmendmentDisclosure(reportNm, signalsData) {
  if (!signalsData || typeof signalsData.amendment_pattern !== "string") return false;
  const nm = typeof reportNm === "string" ? reportNm : "";
  try {
    return new RegExp(signalsData.amendment_pattern).test(nm);
  } catch (e) {
    return false;
  }
}

/** 정기 보고 카테고리 번호(SE-7 Task 3, task-3-brief.md). 위험 신호
 *  (SIGNAL_TYPES) taxonomy 카테고리는 0(기타)~8(위기/부실)만 쓰므로 9는
 *  절대 겹치지 않는다 — scripts/export_tool_data.py의
 *  ROUTINE_FILING_CATEGORY와 같은 값이어야 한다(그쪽이 categories 맵의
 *  "9" 키에 "정기 보고" 라벨을 실어 나른다. 숫자 자체가 위험 신호와
 *  안 겹친다는 계약이라 여기 상수로 하드코딩한다 — signalsData에서
 *  읽어오면 로드 실패 시 undefined가 되어 오히려 위험해진다). */
const ROUTINE_FILING_CATEGORY = 9;

/** reportNm 하나를 signalsData(docs/tool/signals-data.json 로드 결과) 기준
 *  으로 분류해 카테고리 번호(0~8은 위험 신호, 0="기타", 9="정기 보고" —
 *  SE-7 Task 3)를 돌려준다. 키워드 매칭 순서(signals 배열 순서상 첫
 *  매칭)는 docs/tool/index.html의 matchSignals(564행)와 같은 로직이다
 *  (브리프: "로직을 새로 만들지 마라 — 읽어서 맞춘다").
 *
 *  **정정공시(is_amendment_disclosure) 처리는 SE-7 Task 2에서 공개
 *  뷰어·core와 의도적으로 갈라졌다.** core의 `match_signals`는
 *  정정공시를 만나면 빈 리스트를 돌려준다 — 위험 신호 **집계**에서
 *  같은 사건의 정정본을 중복 계산하지 않으려는 것으로, 그 용도로는
 *  옳다. 하지만 여기(SE 표시 계층)는 "이번 달 공시가 무슨 색이었나"
 *  전체 목록을 색칠하는 게 목적이라 그 배제를 그대로 재사용하면
 *  정정 접두어가 붙었다는 이유만으로 내용과 무관하게 전부 "기타"로
 *  뭉개진다(엔켐 실측: "기타" 110건 중 61건이 정정 배제 때문이었고,
 *  접두어를 벗기고 재매칭하면 40건이 회복된다). 그래서 이 함수는
 *  정정 접두어를 만나면 **제외하지 않고 벗겨낸 뒤** 나머지 텍스트로
 *  키워드 매칭을 계속한다 — 매칭되면 그 카테고리, 안 되면 여전히
 *  "기타"(0)이지만 그 0은 "내용까지 보고 못 찾은 0"이다.
 *
 *  amendment_pattern이 `^`로 시작하는 접두어 전용(anchored) 정규식임을
 *  실측으로 확인했다 — 문자열 시작에만 걸리므로 `.replace()`로 접두어를
 *  잘라내도 본문 중간이 잘릴 위험이 없다. 혹시 이후 데이터가 `^`로
 *  시작하지 않는(문자열 어디서든 걸리는) 패턴을 준다면 `.replace()`를
 *  적용하지 않고 원본 그대로 매칭한다 — 검증 안 된 패턴으로 본문을
 *  잘라내는 쪽보다, 접두어를 못 벗겨 "기타"로 떨어지는 쪽이 안전하다.
 *
 *  **정정 여부 자체("이 공시가 정정이었다"는 사실)는 이 함수의 반환값
 *  에서는 사라진다 — 대신 isAmendmentDisclosure(위)로 따로 노출한다.**
 *  카테고리 숫자만 반환하던 기존 계약을 유지하기로 했다:
 *  monthlyCountsByCategory(아래)가 이 반환값을 그대로 합산하고,
 *  SE-4f에서 "월별 합계 = 원본 건수" 불변식을 고정해 뒀다({category,
 *  isAmendment} 객체로 바꾸면 그 불변식 검증 테스트까지 전부 같이
 *  고쳐야 해서 위험이 커진다) — 정정 여부가 필요한 화면(범례·툴팁
 *  등)은 이 함수 대신 isAmendmentDisclosure를 직접 부르는 편이 더
 *  안전하다는 판단이다.
 *
 *  **공시 하나는 정확히 한 카테고리에만 속한다.** matchSignals(공개
 *  뷰어)는 여러 신호가 동시에 걸리면 배열 전부를 돌려주지만, 여기서는
 *  signals 배열 순서상 첫 매칭만 쓴다 — 월별 스택 막대에서 한 공시를
 *  두 카테고리에 겹쳐 세면 막대 합이 원본 건수를 넘어서는 거짓말이
 *  된다(브리프: "월별 합계가 원본 건수와 일치해야 합니다").
 *
 *  signalsData가 없거나 signals 배열을 갖추지 못한 예상 밖 형태면(로드
 *  실패·형태 변경) null을 돌려준다 — 호출자가 분류를 포기하고 기존
 *  단색 집계로 물러나는 신호다(브리프: "로드 실패에 대비하세요").
 *
 *  **SE-7 Task 3**: 위험 신호(1~8) 어디에도 안 걸리면, "기타"(0)로
 *  떨어지기 전에 signalsData.routine_filing_keywords(고빈도 정기 보고
 *  목록 — 임원 지분 1주 변동 보고 등, task-3-brief.md)를 마지막으로
 *  검사한다. 위험 신호 매칭이 **항상 먼저**이므로(위 for 루프가 이미
 *  return으로 끝낸 뒤에만 여기 도달한다) 정기 보고 키워드가 실제 위험
 *  신호를 가리는 경우는 없다 — 위험 신호와 정기 보고 키워드가 한
 *  제목에 동시에 걸리는 합성 케이스에서도 위험 신호가 이긴다.
 *
 *  정정 접두어 스트립(위)은 이미 끝난 뒤라 "[기재정정]임원ㆍ주요주주
 *  특정증권등소유상황보고서"도 접두어가 벗겨진 나머지 텍스트로 이
 *  검사를 받는다 — Task 2의 스트립 로직 위에 얹을 뿐 새로 만들지
 *  않는다.
 *
 *  routine_filing_keywords가 없거나 배열이 아니면(구버전 signals-
 *  data.json, 로드 실패) 빈 배열로 취급해 조용히 "기타"로 물러난다 —
 *  위험 신호 매칭 계약 자체는 이 필드 유무와 무관하게 그대로다. */
function classifyDisclosureCategory(reportNm, signalsData) {
  if (!signalsData || !Array.isArray(signalsData.signals)) return null;
  let nm = typeof reportNm === "string" ? reportNm : "";
  if (isAmendmentDisclosure(nm, signalsData)) {
    // isAmendmentDisclosure가 true를 돌려준 시점에 signalsData.amendment_
    // pattern은 이미 문자열이고 정규식 컴파일·매칭에 성공했다는 뜻이라
    // (내부에서 실패하면 false만 돌려준다) 아래 재구성이 새로 던질 예외는
    // 없다 — 그래도 방어적으로 값 자체는 다시 안 만들고 같은 문자열만
    // 재사용한다.
    if (signalsData.amendment_pattern.charAt(0) === "^") {
      nm = nm.replace(new RegExp(signalsData.amendment_pattern), "");
    }
    // else: 앞으로 들어올지 모르는, 문자열 시작에 고정되지 않은 패턴이다
    // — 어디를 잘라야 안전한지 알 수 없으므로 원본 그대로 두고 아래
    // 키워드 매칭으로 넘어간다(정정이라는 사실 자체는 이미
    // isAmendmentDisclosure로 확인됐고, 위 함수를 부르는 쪽이 필요하면
    // 그 사실을 따로 쓸 수 있다).
  }
  for (const s of signalsData.signals) {
    const keywords = Array.isArray(s.keywords) ? s.keywords : [];
    for (const kw of keywords) {
      if (kw && nm.indexOf(kw) !== -1) {
        return typeof s.category === "number" ? s.category : 0;
      }
    }
  }
  // 위험 신호(1~8) 어디에도 안 걸렸다 — 여기 도달했다는 사실 자체가
  // "위험 신호가 이긴다"는 우선순위를 이미 지킨 것이다(위 for 루프가
  // 매칭되면 곧장 return하므로 아래로 내려오지 않는다). 정기 보고
  // 후보를 마지막으로 검사한다.
  const routineKeywords = Array.isArray(signalsData.routine_filing_keywords)
    ? signalsData.routine_filing_keywords : [];
  for (const kw of routineKeywords) {
    if (kw && nm.indexOf(kw) !== -1) return ROUTINE_FILING_CATEGORY;
  }
  return 0;
}

/* ── 복합 패턴(CROSS_SIGNAL_PATTERNS) 매칭 — SE-13 Task 3 ───────────────
 *
 * 공개 뷰어(docs/tool/index.html)는 최초 커밋부터 client-side로
 * signals-data.json의 patterns 배열을 detectedTax(공시에서 탐지된 taxonomy
 * ID 집합)에 대해 부분집합 매칭한다(matchSignals:564-572, buildResult:
 * 627-628) — "PATTERN MATCH" 패널. SE는 이 기능이 아예 없었다(조사 문서
 * se13-investigation.md Q3, grep 0건). 여기서는 **공개 뷰어와 같은 규칙
 * (부분집합, 순서 무관)**을 SE로 이식하되, ①classifyDisclosureCategory
 * (위)와 달리 공시 하나가 여러 신호에 동시에 걸릴 수 있다는 사실을 그대로
 * 보존하고(패턴 매칭에는 "이 공시가 촉발한 taxonomy ID 전부"가 필요하다 —
 * 한 카테고리로 뭉개면 정보가 사라진다), ②매칭된 패턴마다 "어떤 공시가
 * 어떤 taxonomy를 촉발했는지" 역추적 정보를 함께 돌려준다(SE 쪽 "더
 * 자세하게" 요구, task-3-brief.md ②).
 */

/** reportNm 하나에 매칭되는 신호 객체 전부를 돌려준다 — 공개 뷰어
 *  index.html의 matchSignals(564-572행)를 그대로 이식한 것이다(새 키워드
 *  매칭 규칙을 만들지 않는다, 브리프 "새 분류기 금지"). classifyDisclosureCategory
 *  (위)와 다른 점: 그 함수는 SE-7의 "공시 하나는 정확히 한 카테고리"
 *  표시 계약 때문에 첫 매칭에서 멈추지만, 여기서는 매칭되는 신호 전부를
 *  모은다 — 패턴 매칭에는 신호 하나가 아니라 이 공시가 가리키는 taxonomy
 *  ID 전부가 필요하다.
 *
 *  signalsData가 없거나 형태가 예상과 다르면 빈 배열(classifyDisclosureCategory·
 *  isAmendmentDisclosure와 같은 폴백 계약). */
function matchSignalsForReport(reportNm, signalsData) {
  if (!signalsData || !Array.isArray(signalsData.signals)) return [];
  const nm = typeof reportNm === "string" ? reportNm : "";
  const out = [];
  for (const s of signalsData.signals) {
    const keywords = Array.isArray(s.keywords) ? s.keywords : [];
    for (const kw of keywords) {
      if (kw && nm.indexOf(kw) !== -1) { out.push(s); break; }
    }
  }
  return out;
}

/** disclosures(원본 공시 레코드 배열)에서 신호 탐지 결과를 공시 단위로
 *  모은다 — matchCrossPatterns(아래)의 입력이자, 매칭된 패턴의 "이
 *  회사에서 실제 탐지된 구성 신호가 어느 공시에서 잡혔는지" 역추적
 *  표시(task-3-brief.md ②)에 그대로 재사용한다.
 *
 *  **정정공시는 제외한다** — 공개 뷰어(index.html:618-620: `matchSignals`를
 *  부르기 전에 `isAmend`면 빈 배열)와 core(`match_signals`)가 신호
 *  **탐지**(집계·매칭용) 단계에서 공통으로 지키는 규칙이다. SE-7의
 *  classifyDisclosureCategory(위)는 표시 목적이 달라(정정공시도 색을
 *  칠해야 한다) 정정 접두어를 벗기고 계속 매칭하지만, 여기서는 패턴
 *  매칭이 core·공개 뷰어와 동일한 신호 집합을 봐야 한다는 제약(브리프
 *  "매칭은 공개 뷰어와 동일 규칙")이 더 우선한다 — 두 함수가 정정공시를
 *  다르게 다루는 것은 의도된 차이이지 불일치가 아니다.
 *
 *  반환: [{rcept_no, rcept_dt, report_nm, signals: [신호 객체...]}] —
 *  신호가 하나도 안 걸린 공시는 배열에서 빠진다. */
function detectSignalsByDisclosure(disclosures, signalsData) {
  if (!Array.isArray(disclosures) || !signalsData || !Array.isArray(signalsData.signals)) return [];
  const out = [];
  for (const d of disclosures) {
    if (!d || typeof d !== "object") continue;
    const nm = typeof d.report_nm === "string" ? d.report_nm : "";
    if (isAmendmentDisclosure(nm, signalsData)) continue;
    const sigs = matchSignalsForReport(nm, signalsData);
    if (sigs.length === 0) continue;
    out.push({
      rcept_no: d.rcept_no !== undefined ? d.rcept_no : null,
      rcept_dt: d.rcept_dt !== undefined ? d.rcept_dt : null,
      report_nm: nm,
      signals: sigs,
    });
  }
  return out;
}

/** core(dart_client.py detect_capital_churn, signals.py 576-598행)의
 *  희석성/비희석성 자본 이벤트 분류를 그대로 옮긴 것이다 — 정적인 신호
 *  key 목록이라 값이 자주 바뀌지 않고, signals-data.json의
 *  `capital_event_keys`는 둘을 합친 것만 export하고 있어(Task 2 export
 *  범위 밖) 여기서는 ROUTINE_FILING_CATEGORY(위)와 같은 이유로 상수를
 *  직접 든다 — signalsData에서 읽어오려다 실패하면 undefined가 되어
 *  오히려 위험해진다.
 *
 *  **이 구분이 실제로 필요하다는 사실을 라이브 검증에서 직접 확인했다.**
 *  처음에는 이 구분 없이 "capital_event_keys에 해당하는 신호라면 무엇
 *  이든 12개월에 3건이면 churn"으로 단순화했는데, 삼성전자가 자사주
 *  취득·처분(TREASURY — 정상 기업이 흔히 반복하는 주주환원, 아래
 *  NON_DILUTIVE_CAPITAL_EVENTS)만으로 capital_churn_anomaly에 거짓
 *  매칭됐다 — task-3-brief.md가 명시적으로 요구하는 "미매칭 회사(삼성
 *  전자 등)에서 블록이 안 나오는 것" 확인 도중 실측으로 드러난 문제다.
 *  같은 기간 core의 analyze_company_risk(detect_capital_churn의 원본
 *  규칙 사용)는 삼성전자에 이 패턴을 전혀 표시하지 않는다(대조 확인
 *  완료) — 원인은 core가 희석성 이벤트(CB·유상증자·감자 등, 주주가치
 *  훼손 우려)와 비희석성 이벤트(자사주 등)를 구분해 비희석성만으로는
 *  churn을 인정하지 않기 때문이다. 그 구분을 옮기지 않으면 "매칭 규칙은
 *  core·공개 뷰어와 같아야 한다"는 제약 자체가 깨진다. */
const DILUTIVE_CAPITAL_EVENTS = new Set([
  "3PCA", "RIGHTS_UNDER", "GAMJA_MERGE", "REVERSE_SPLIT",
  "CB_BW", "EB", "RCPS", "CB_ROLLOVER",
]);
const NON_DILUTIVE_CAPITAL_EVENTS = new Set([
  "TREASURY", "CB_BUYBACK", "TREASURY_EB", "TREASURY_TRUST",
]);

/** taxonomy 2.7(CAPITAL_CHURN)은 개별 공시 제목이 아니라 공시 "빈도"로
 *  판정되는 파생 신호라 signals-data.json의 CAPITAL_CHURN 신호 자체는
 *  keywords가 빈 배열이다(core detect_capital_churn — dart_client.py
 *  1753행). CAPITAL_IMPAIRMENT·AR_SURGE·CASH_GAP 등 다른 파생 전용 신호
 *  키들도 마찬가지로 keywords:[]다.
 *
 *  **다만 이게 패턴 매칭을 막지는 않는다** — SIGNAL_KEY_TO_TAXONOMY(core
 *  signals.py)는 같은 taxonomy ID에 여러 신호 키를 매핑하는 경우가 많고,
 *  키워드가 빈 파생 전용 키 옆에 키워드 있는 형제 키가 같은 ID를 가리키는
 *  사례가 대부분이다(예: 8.2는 CAPITAL_IMPAIRMENT 외에 키워드 있는
 *  DEBT_RESTR로도 도달, 6.1은 AR_SURGE·CASH_GAP 외에 REVENUE_IRREG로도
 *  도달, 4.2는 DECISION_RELATED_PARTY 외에 RELATED_PARTY로도 도달).
 *  검증 결과(리뷰 재확인, 2026-07-30) taxonomy 9종의 signal_sequence
 *  전체를 훑으면 진짜로 키워드 경로가 전혀 없는 ID는 2.7·2.8·3.6·5.6·8.5
 *  뿐이고, 그중 이 9개 패턴이 실제로 걸치는 건 2.7 하나(zombie_ma·
 *  delisting_evasion·capital_churn_anomaly 3종). 그 2.7을 아래
 *  detectCapitalChurn이 core와 동일 규칙으로 메우므로, **9개 패턴
 *  전부가 이 파일의 매칭 로직만으로 도달 가능하다** — "8종은 공개
 *  뷰어에서 구조적으로 영원히 매칭 안 된다"는 이전 버전의 이 주석은
 *  틀렸다(SE-13 Task 3 리뷰가 실측으로 잡음, 5개 패턴을 키워드만으로
 *  직접 매칭 재현). 나머지 진짜 파생 전용 taxonomy(2.8·3.6·5.6·8.5)를
 *  core처럼 별도 synthetic 신호로 주입하는 일반화된 메커니즘은 여전히
 *  없다 — 이 9개 패턴엔 필요 없었을 뿐, 향후 새 패턴이 그 ID들을 쓰면
 *  또 막힐 수 있다는 뜻으로 남겨둔다. */
const CAPITAL_CHURN_TAXONOMY = "2.7";

/** events(각 {rcept_dt: "YYYYMMDD", key})에서 core detect_capital_churn과
 *  같은 365일 슬라이딩 윈도우(각 이벤트를 시작점으로 그 뒤 365일)로
 *  희석성/비희석성 건수를 따로 세고, 판정 조건 (A) 희석성≥3 또는 (B)
 *  희석성≥2 AND 비희석성≥2 를 만족하는 윈도우가 하나라도 있으면
 *  {flagged, maxDilutive, maxNonDilutive}를 돌려준다 — dart_client.py
 *  detect_capital_churn 1800-1840행과 정확히 같은 규칙이다(정렬·날짜
 *  형식 검증도 동일하게 조용히 건너뛴다, 짐작해서 채우지 않는다). */
function detectCapitalChurn(events) {
  const parsed = (Array.isArray(events) ? events : [])
    .map(function (e) {
      const raw = e && typeof e.rcept_dt === "string" ? e.rcept_dt.slice(0, 8) : "";
      if (!/^\d{8}$/.test(raw)) return null;
      const d = new Date(raw.slice(0, 4) + "-" + raw.slice(4, 6) + "-" + raw.slice(6, 8));
      if (isNaN(d.getTime())) return null;
      return { date: d, isDilutive: DILUTIVE_CAPITAL_EVENTS.has(e.key) };
    })
    .filter(function (e) { return e !== null; })
    .sort(function (a, b) { return a.date - b.date; });

  let flagged = false;
  let maxDilutive = 0;
  let maxNonDilutive = 0;
  for (let i = 0; i < parsed.length; i++) {
    const start = parsed[i].date;
    const end = new Date(start.getTime() + 365 * MS_PER_DAY);
    let dil = 0, non = 0;
    for (let j = i; j < parsed.length; j++) {
      const d = parsed[j].date;
      if (d >= start && d <= end) {
        if (parsed[j].isDilutive) dil++; else non++;
      }
    }
    maxDilutive = Math.max(maxDilutive, dil);
    maxNonDilutive = Math.max(maxNonDilutive, non);
    if (dil >= 3 || (dil >= 2 && non >= 2)) flagged = true;
  }
  return { flagged: flagged, maxDilutive: maxDilutive, maxNonDilutive: maxNonDilutive };
}

/** disclosures(공시 원본 레코드 배열)에서 매칭되는 CROSS_SIGNAL_PATTERNS를
 *  찾는다 — 공개 뷰어(index.html:627-628)와 정확히 같은 부분집합 판정
 *  (`signal_sequence.every(t => detectedTax.has(t))`, 순서 무관)이지만,
 *  core `find_pattern_match`(taxonomy.py)처럼 **첫 매치 하나만** 돌려주지
 *  않는다 — 공개 뷰어의 `DATA.patterns.filter(...)`가 이미 조건을
 *  만족하는 패턴 전부를 돌려주고 있고, task-3-brief.md가 "공개 뷰어와
 *  동일 규칙"이라 지목하는 대상이 이 필터 동작이다.
 *
 *  반환: [{...pattern, evidence: [{taxonomy, disclosures: [...]} |
 *  {taxonomy, disclosures: [], aggregate_note, aggregate_disclosures}]}].
 *  evidence는 pattern.signal_sequence 순서대로, 각 taxonomy ID를 실제로
 *  촉발한 공시들을 담는다(task-3-brief.md ② "매칭의 근거를 공시 단위로
 *  역추적"). taxonomy 2.7(자본 churn)은 개별 공시 하나의 키워드가 아니라
 *  빈도 판정이라 aggregate_note로 별도 표시한다(위 detectCapitalChurn
 *  주석 참고) — 없는 공시-신호 연결을 지어내지 않는다. */
function matchCrossPatterns(disclosures, signalsData) {
  if (!signalsData || !Array.isArray(signalsData.patterns)) return [];
  const byDisclosure = detectSignalsByDisclosure(disclosures, signalsData);

  const detectedTax = new Set();
  for (const d of byDisclosure) {
    for (const s of d.signals) {
      for (const t of (s.taxonomies || [])) detectedTax.add(t);
    }
  }

  const capitalKeys = new Set(
    Array.isArray(signalsData.capital_event_keys) ? signalsData.capital_event_keys : []);
  const capitalHits = byDisclosure.filter(function (d) {
    return d.signals.some(function (s) { return capitalKeys.has(s.key); });
  });
  const capitalEventsForChurn = [];
  capitalHits.forEach(function (d) {
    d.signals.forEach(function (s) {
      if (capitalKeys.has(s.key)) capitalEventsForChurn.push({ rcept_dt: d.rcept_dt, key: s.key });
    });
  });
  const churn = capitalKeys.size > 0
    ? detectCapitalChurn(capitalEventsForChurn)
    : { flagged: false, maxDilutive: 0, maxNonDilutive: 0 };
  const churnFlagged = churn.flagged;
  if (churnFlagged) detectedTax.add(CAPITAL_CHURN_TAXONOMY);

  const matched = signalsData.patterns.filter(function (p) {
    return Array.isArray(p.signal_sequence) && p.signal_sequence.length > 0
      && p.signal_sequence.every(function (t) { return detectedTax.has(t); });
  });

  return matched.map(function (p) {
    const evidence = p.signal_sequence.map(function (taxId) {
      const hits = [];
      for (const d of byDisclosure) {
        const hitSignals = d.signals.filter(function (s) {
          return Array.isArray(s.taxonomies) && s.taxonomies.indexOf(taxId) !== -1;
        });
        if (hitSignals.length > 0) {
          hits.push({
            rcept_no: d.rcept_no, rcept_dt: d.rcept_dt, report_nm: d.report_nm,
            signal_keys: hitSignals.map(function (s) { return s.key; }),
            signal_labels: hitSignals.map(function (s) { return s.label; }),
          });
        }
      }
      if (hits.length === 0 && taxId === CAPITAL_CHURN_TAXONOMY && churnFlagged) {
        return {
          taxonomy: taxId,
          disclosures: [],
          aggregate_note: "개별 공시 하나가 아니라 자본 관련 공시 " + capitalHits.length
            + "건(12개월 내 최대 희석성 " + churn.maxDilutive + "건·비희석성 "
            + churn.maxNonDilutive + "건)이 판정 조건(희석성 3건 이상, 또는 희석성 "
            + "2건 이상+비희석성 2건 이상)을 만족한 빈도 관찰입니다.",
          aggregate_disclosures: capitalHits.map(function (d) {
            return { rcept_no: d.rcept_no, rcept_dt: d.rcept_dt, report_nm: d.report_nm };
          }),
        };
      }
      return { taxonomy: taxId, disclosures: hits };
    });
    return Object.assign({}, p, { evidence: evidence });
  });
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

// ── 재무지표 4분류 · 용어 · 단위 (SE-4h Task 2, SE-8 Task 5) ─────────────
// fnlttSinglIndx(주요 재무지표)는 4분류(수익성·안정성·성장성·활동성)
// 66개를 idx_cl_nm과 함께 준다(dart_client.fetch_indicator_history, SE-4h
// Task 1). 여기서는 그 분류를 보존해 4블록으로 묶고, 22개 핵심 지표는
// primary로 앞에 두고 나머지 44개는 rest로 접는다(indicatorBlocks) — 이
// primary/rest 구분은 여전히 22 vs 44다. 뜻(INDICATOR_NOTES)은 SE-4h
// 때는 primary 22개에만 있었지만, SE-8 Task 5부터 66개 중 65개(유보액
// 대비율 제외)로 확대돼 rest 표에도 대부분 뜻이 붙는다(사용자가 실측으로
// 지적한 문제 — 접힌 지표는 뜻이 아예 안 보인다 — 를 고친 것, buildEntry·
// indicatorRestFold 참고). ui.js가 이 함수들을 renderSection에서 직접
// 불러 그린다 — indicators는 더 이상 sectionBlocks/tableLayout 경로를
// 타지 않는다(위 tableLayout·flatKeys 분기 주석 참고).

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
  // SE-8 Task 5로 22개(SE-4h)에서 확대. 세전계속사업이익 계열 4종(세전
  // 계속사업이익률·총자산세전계속사업이익률·자기자본세전계속사업이익률·
  // 자본금세전계속사업이익률)은 분모만 매출액→총자산→자기자본→자본금으로
  // 바뀌는 같은 계열이다(한국기업평가 "주요 재무지표의 정의" 웹 확인 —
  // 세전계속사업이익률=(세전계속사업이익/매출액)*100, 2026-07-30).
  "세전계속사업이익률": "매출액 대비 법인세비용 차감 전 계속사업이익의 비율",
  "총포괄이익률": "매출액 대비 총포괄이익(당기순이익에 기타포괄손익을 더한 금액)의 비율",
  "총자산영업이익률": "총자산 대비 영업이익의 비율",
  "총자산세전계속사업이익률": "총자산 대비 세전계속사업이익의 비율",
  "자기자본영업이익률": "자기자본 대비 영업이익의 비율",
  "자기자본세전계속사업이익률": "자기자본 대비 세전계속사업이익의 비율",
  "자본금영업이익률": "자본금 대비 영업이익의 비율",
  "자본금세전계속사업이익률": "자본금 대비 세전계속사업이익의 비율",
  // 납입자본이익률 = 당기순이익/납입자본금×100(시사경제용어사전 웹 확인,
  // 2026-07-30) — 자본유보율(자본잉여금+이익잉여금÷자본금, 아래)과는
  // 분자·분모가 다른 별개 지표다.
  "납입자본이익률": "납입자본금 대비 당기순이익의 비율",
  "영업수익경비율": "영업수익(매출액) 대비 영업비용의 비율",
  "부채비율": "자기자본 대비 부채총계의 비율 — 빌린 돈이 자기 돈의 몇 %인가",
  "자기자본비율": "총자산 대비 자기자본의 비율",
  "유동비율": "1년 안에 갚을 유동부채 대비, 1년 안에 현금화할 수 있는 유동자산의 비율",
  "당좌비율": "유동자산에서 재고자산을 뺀 당좌자산이 유동부채의 몇 %인가",
  "이자보상배율": "영업이익이 이자비용의 몇 배인가 — 값은 DART가 준 그대로 %로 표시된다",
  "순이자보상배율": "영업이익이 이자비용에서 이자수익을 뺀 순이자비용의 몇 배인가 — 값은 DART가 준 그대로 %로 표시된다",
  "유동부채비율": "자기자본 대비 유동부채의 비율",
  "비유동부채비율": "자기자본 대비 비유동부채의 비율",
  "비유동비율": "자기자본 대비 비유동자산의 비율",
  "금융비용부담률": "매출액 대비 금융비용(이자비용 등)의 비율",
  // 자본유보율 = (자본잉여금+이익잉여금)/자본금 — 자본잉여금(주식발행초과금
  // 등 납입된 돈)까지 포함한다. "벌어서 쌓아둔 돈"(이익잉여금만)이라고만
  // 쓰면 절반(자본잉여금)을 빼먹은 설명이 된다(리뷰 지적, SE-4h Task 2).
  "자본유보율": "자본잉여금과 이익잉여금을 더한 유보액이 자본금의 몇 %인가",
  // "유보액대비율"에는 일부러 뜻을 달지 않았다. 이름·산식이 위 자본유보율과
  // 거의 같아 보이지만(둘 다 "유보액"이 들어간다), 두 지표가 정말 같은
  // 산식인지 분모가 자본금인지 다른 값인지를 신뢰할 수 있는 출처로 확인하지
  // 못했다(SE-8 Task 5 웹 조사 — DART API 문서·한국은행 기업경영분석
  // 해설서 어디서도 이 지표만의 산식을 못 찾음). 확인 못 한 채 자본유보율과
  // 같다고 적으면 실제로는 다른 두 지표를 같은 뜻으로 보여주는 거짓이 될
  // 수 있다 — 지어내지 않는다는 이 프로젝트 원칙(재지 않은 값을 실측이라고
  // 적지 않는다)에 따라 여기만 빈 칸으로 남긴다. indicatorBlocks의 rest에는
  // 그대로 남아 이름만 보인다(값을 숨기지 않는다는 원칙과는 별개 — 뜻 설명만
  // 비운 것이다).
  // 재무레버리지 = 총자산/자기자본. 부채까지 포함한 총자산을 자기자본이
  // 몇 배 굴리는가를 보는 지표다(아이투자 "재무레버리지(A/E)" 웹 확인,
  // 2026-07-30). 이름은 "레버리지"지만 이자보상배율과 마찬가지로 DART는
  // %로 준다 — 우리가 배수로 환산하지 않는다(계획 문서 "배경" 절과 동일
  // 원칙).
  "재무레버리지": "자기자본 대비 총자산의 비율 — 값은 DART가 준 그대로 %로 표시된다",
  // 비유동적합률(고정장기적합률) = 비유동자산÷(자기자본+비유동부채)×100 —
  // 장기간 쓸 자산을 장기 자금원으로 얼마나 충당했는가를 보는 지표다(웹
  // 확인, 2026-07-30).
  "비유동적합률": "비유동자산이 자기자본과 비유동부채를 합한 금액의 몇 %인가",
  "비유동자산구성비율": "총자산 중 비유동자산이 차지하는 비율",
  "유형자산구성비율": "총자산 중 유형자산이 차지하는 비율",
  "유동자산구성비율": "총자산 중 유동자산이 차지하는 비율",
  "재고자산구성비율": "총자산 중 재고자산이 차지하는 비율",
  "유동자산/비유동자산비율": "비유동자산 대비 유동자산의 비율",
  "재고자산/유동자산비율": "유동자산 대비 재고자산의 비율",
  "매출채권/매입채무비율": "매입채무 대비 매출채권의 비율",
  "매입채무/재고자산비율": "재고자산 대비 매입채무의 비율",
  "매출액증가율(YoY)": "전년 매출액 대비 이번 사업연도 매출액의 변화율",
  // 아래 "…증가율"은 전부 같은 문형이다 — 전년 대비 이번 사업연도의
  // 변화율. 이미 있던 6개(매출액·영업이익·순이익·총자산·자기자본·
  // 부채총계)와 같은 계열이라 그대로 따른다(SE-8 Task 5).
  "매출총이익증가율(YoY)": "전년 매출총이익 대비 이번 사업연도 매출총이익의 변화율",
  "영업이익증가율(YoY)": "전년 영업이익 대비 이번 사업연도 영업이익의 변화율",
  "세전계속사업이익증가율(YoY)": "전년 세전계속사업이익 대비 이번 사업연도 세전계속사업이익의 변화율",
  "순이익증가율(YoY)": "전년 당기순이익 대비 이번 사업연도 당기순이익의 변화율",
  "총포괄이익증가율(YoY)": "전년 총포괄이익 대비 이번 사업연도 총포괄이익의 변화율",
  "총자산증가율": "전년 총자산 대비 이번 사업연도 총자산의 변화율",
  "비유동자산증가율": "전년 비유동자산 대비 이번 사업연도 비유동자산의 변화율",
  "유형자산증가율": "전년 유형자산 대비 이번 사업연도 유형자산의 변화율",
  "부채총계증가율": "전년 부채총계 대비 이번 사업연도 부채총계의 변화율",
  "총차입금증가율": "전년 총차입금 대비 이번 사업연도 총차입금의 변화율",
  "자기자본증가율": "전년 자기자본 대비 이번 사업연도 자기자본의 변화율",
  "유동자산증가율": "전년 유동자산 대비 이번 사업연도 유동자산의 변화율",
  "매출채권증가율": "전년 매출채권 대비 이번 사업연도 매출채권의 변화율",
  "재고자산증가율": "전년 재고자산 대비 이번 사업연도 재고자산의 변화율",
  "유동부채증가율": "전년 유동부채 대비 이번 사업연도 유동부채의 변화율",
  "매입채무증가율": "전년 매입채무 대비 이번 사업연도 매입채무의 변화율",
  "비유동부채증가율": "전년 비유동부채 대비 이번 사업연도 비유동부채의 변화율",
  "총자산회전율": "총자산 대비 매출액의 비율",
  "매출채권회전율": "매출채권 대비 매출액의 비율",
  // 재고자산회전율 자체는 매출액 ÷ 재고자산이다("매출원가 ÷ 재고자산"이
  // 아니다 — 그건 DART가 별도로 제공하는 다른 지표다). 엔켐 실측으로
  // 산술 검증: 재고자산회전율 454.463 ÷ (매출원가/재고자산) 456.673 =
  // 0.99516, 매출액÷매출원가(=1/매출원가율)도 0.99516로 일치한다(리뷰
  // 지적, SE-4h Task 2 — 이전 노트가 그 별도 지표의 정의를 옮겨 붙인
  // 오류였다).
  "재고자산회전율": "재고자산 대비 매출액의 비율",
  // 매출원가/재고자산 = 매출원가÷재고자산 — 위 재고자산회전율(매출액÷
  // 재고자산)과 분자만 다른 별개 지표다. 산술 검증은 위 재고자산회전율
  // 주석과 동일한 실측 근거다(SE-8 Task 5).
  "매출원가/재고자산": "재고자산 대비 매출원가의 비율",
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
  // 아래 3개도 매입채무회전율과 같은 계열(매출액÷X)이다 — 코드 위 주석과
  // 같은 관행을 따른 것이지 산술로 개별 검증하지는 못했다. 타인자본은
  // 부채총계를 가리키는 표준 회계 용어다.
  "비유동자산회전율": "비유동자산 대비 매출액의 비율",
  "유형자산회전율": "유형자산 대비 매출액의 비율",
  "타인자본회전율": "타인자본(부채총계) 대비 매출액의 비율",
  "자기자본회전율": "자기자본 대비 매출액의 비율",
  "자본금회전율": "자본금 대비 매출액의 비율",
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
  // DART가 주는 자릿수는 지표·연도마다 제각각이다(실측: -22.56 · -152.661 ·
  // -144.09 가 한 표에 나란히 온다). 그대로 쓰면 자릿수가 들쭉날쭉해 읽기
  // 어렵다 — 소수 첫째 자리로 통일한다. 반올림은 표시에만 적용하고 원본
  // 값은 indicatorBlocks의 idx_val로 그대로 남아 툴팁·차트가 쓴다.
  const n = typeof idxVal === "number" ? idxVal : Number(idxVal);
  const s = Number.isFinite(n) ? n.toFixed(1) : String(idxVal);
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

    // SE-8 Task 5: note는 primary·rest 구분 없이 항상 붙인다. SE-4h
    // Task 2 때는 rest(44개) 중 22개만 뜻이 있어 rest 표에 뜻 열을 두면
    // 대부분이 빈 칸이었다(그래서 당시 두 번째 인자로 primary만 true를
    // 줬다) — 지금은 66개 중 65개(유보액대비율 제외)에 뜻이 있어 그
    // 전제가 더 이상 맞지 않는다. 뜻이 없는 지표는 INDICATOR_NOTES[idxNm]
    // 이 undefined라 ""로 떨어진다 — indicatorTableEl(ui.js)이 그대로
    // 빈 칸으로 그린다(값을 숨기지 않는다는 원칙과 동일하게, 없으면 없다고
    // 보여준다). rest 표에서 이 note를 실제로 보여주려면 ui.js
    // indicatorRestFold가 indicatorTableEl(restEntries, true)를 불러야
    // 한다(같이 수정) — 이 함수만 고치면 데이터는 있는데 화면에 안 나오는
    // 죽은 값이 된다.
    function buildEntry(idxNm) {
      const byYear = byName.get(idxNm);
      const cells = years.map(function (y) {
        const v = byYear.has(y) ? byYear.get(y) : null;
        return { bsns_year: y, idx_val: v, display: formatIndicator(idxNm, v) };
      });
      return { idx_nm: idxNm, cells: cells, note: INDICATOR_NOTES[idxNm] || "" };
    }

    const primary = primaryNames
      .filter(function (n) { return byName.has(n); })
      .map(function (n) { return buildEntry(n); });
    const rest = allNames
      .filter(function (n) { return !primarySet.has(n); })
      .map(function (n) { return buildEntry(n); });

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

// 두 값 모두 있고 서로 다를 때만 강조한다(markLt와 같은 결측 규약, 위 주석
// 참고) — SE-8 Task 8B: fundChain(uses[])의 plan(계획)·real(보고된 집행)을
// 비교하는 데 쓴다. real이 결측(보고 자체가 없음)이면 강조하지 않는다 —
// "보고가 없다"와 "보고된 값이 다르다"는 다른 사실이라 결측을 강조하면
// 없는 사실을 만들어내는 것이다.
function markNeq(a, b) {
  const x = markNumber(a), y = markNumber(b);
  return x !== null && y !== null && x !== y;
}

// SE-4i — 주요 재무지표 표(indicatorTableEl, ui.js)는 위 MARK_RULES가 다루는
// "레코드 배열 + rec[key]" 모양이 아니라, indicatorBlocks가 이미 연도×지표로
// 피벗해 둔 cells({bsns_year, idx_val, display})를 그린다. 그래서 cellMarks를
// 그대로 못 쓰고, 같은 markNeg 판정을 쓰는 얇은 전용 함수를 둔다(markNeg
// 자체를 export하지 않고 이 wrapper만 내보낸다 — 호출부(ui.js)가 알아야 할
// 것은 "이 값이 강조되는가·왜"뿐이지 markNumber 파싱 방식이 아니다).
//
// 규칙은 하나뿐이다: idx_val < 0. 순이익률·ROE·매출총이익률처럼 부호 있는
// 지표가 실제로 음수인 것은 산술적 사실이지만, "매출원가율 > 100%"나
// "부채비율 > 100%"처럼 우리가 고른 경계선은 판정이다(v0.8.5 — 점수·등급·
// 임계값 금지). 0은 음수가 아니고(markNeg가 이미 `< 0`으로만 판정), null(값
// 없음)도 markNumber가 먼저 null로 걸러 음수로 읽지 않는다 — 엔켐 실측에서
// 51개 null 셀이 있다.
function indicatorCellWhy(idxVal) {
  return markNeg(idxVal) ? "지표 값 < 0" : null;
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

// SE-8 Task 8B — fundChain(uses[], 위 fundChain 함수)의 plan(계획 금액)·
// real(보고된 집행 금액)은 DART 원본 두 값(plan_amount·real_dtls_amount)을
// 조달건×용도 단위로 묶은 뒤 그대로 비교한 것이다 — 임계값도 판정도
// 아니다(SE-4g 규칙과 동일한 부류, v0.8.5). 강조 문구는 사실만 말한다:
// "유용"·"의심" 같은 평가 어휘를 쓰지 않는다(SE-5a가 이미 정한 원칙).
//
// **이 규칙이 실제로 발화하는 표는 fund_usage 원본 표(sectionBlocks가
// 그리는, MARK_RULES.fund_usage — 그런 항목은 없다)가 아니라
// fundChainCardEl(ui.js)이 그리는 파생 카드다.** 원본 표는 (pay_de,
// purpose) 조합이 분기 보고서(1분기·반기·3분기·사업보고서)마다 반복
// 보고되는 개별 행이라 real이 plan과 1:1로 짝지어 보이지 않는다 —
// fundChain이 이미 그 반복 중 대표값 하나만 남겨 조달건×용도 단위로
// 묶은 뒤에야 두 값이 나란히 비교 가능해진다. sectionKey "fund_chain"은
// STAGE1_SPECS의 실제 섹션 키가 아니라 이 파생 카드 전용으로 새로 만든
// cellMarks 버킷 이름이다 — cellMarks(records, sectionKey)의 sectionKey는
// MARK_RULES의 임의 키일 뿐 서버 섹션 이름과 일치할 필요가 없다.
// SE-8 최종 리뷰 지적 — fundChain()은 그 조달건×용도에서 plan_amount가
// 한 번도 보고되지 않았을 때도 위 plan(2099번 줄)을 0으로 채운다("모른다"를
// "0으로 계획했다"로 바꿔치기하지 않기 위한 표시값일 뿐, DART가 실제로
// 보고한 계획 금액이 아니다). markNeq(real, plan)만으로는 이 코드화된 0과
// "진짜로 계획이 0원"을 구분하지 못해, {plan_amount: null, real: 50억}
// 레코드에 "보고된 집행 ≠ 계획(계획 0원)"이라는, DART가 말한 적 없는
// 사실을 만들어낸다(라이브 재현: real_dtls_amount=5,000,000,000 사례).
// core의 동등 판정(dart_client.py _detect_fund_anomaly, plan_amount > 0
// 게이트)과 같은 기준을 맞춘다 — plan이 실제로 양수로 보고된 경우에만
// 비교를 발화시킨다.
MARK_RULES.fund_chain = [
  {
    key: "real",
    when: function (u) { return markNumber(u.plan) > 0 && markNeq(u.real, u.plan); },
    why: "보고된 집행 ≠ 계획",
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
    executiveMatches, executiveRosterMarks, dartDisclosureLink,
    ACTOR_STATUS, actorLine, resumeTarget, documentBlocks,
    dropAllEmptyColumns, recordsHaveSourceField, sourceGroupedBlocks,
    DOC_LIST_KEY, docKeyRceptNo, docListRow,
    CHART_SPECS, chartData, axisLabel, numeric, axisSortKey,
    normalizeDebtByKind, monthlyCounts, compositeXValue,
    financialRatios, financialRatiosBaseYear, financialRatiosByYear,
    isAmendmentDisclosure, classifyDisclosureCategory, monthlyCountsByCategory,
    matchSignalsForReport, detectSignalsByDisclosure, detectCapitalChurn,
    matchCrossPatterns, CAPITAL_CHURN_TAXONOMY,
    DILUTIVE_CAPITAL_EVENTS, NON_DILUTIVE_CAPITAL_EVENTS,
    DIVIDEND_SE_FIELDS, dividendVsIncome, fundPlanChanges, fundChain, affiliateOverview,
    DIVIDEND_DRAIN_DIVIDEND_SE, DIVIDEND_DRAIN_NI_SE, dividendDrainFlags,
    dividendVsRetainedEarnings, indexAccountsByDiv, FS_DIV_LABELS,
    fundChainDisclosureHints,
    markNumber, MARK_RULES, cellMarks, markedColumnKeys, indicatorCellWhy,
    isAggregateRow, splitAggregateRows, splitVisibleFolded, MAX_VISIBLE_COLUMNS,
    MIN_FOLD_COUNT, isMetaOnlyRecords, metaOnlyNote, distinctReportCount,
    EXEC_TREASURY_PADDING_FIELDS, isPaddingRow, splitPaddingRows,
    INDICATOR_CATEGORY_ORDER, INDICATOR_PRIMARY, INDICATOR_NOTES,
    formatIndicator, indicatorBlocks, indicatorChartRecords,
    normalizeIndicatorCategory, indicatorRows, indicatorYearNote,
    DART_REMARK_LABELS, formatRemark, KIND_LABELS,
    isFootnoteMarkerOnly, footnoteMarkerNote,
    FINANCIALS_META_KEYS, FINANCIALS_PRIORITY_KEYS,
    reorderFinancialsRecord, reorderFinancialsFields,
    FINANCIALS_DATE_KEYS, shortenFinancialsDate, shortenFinancialsDateFields,
    financialsGroupTitle, financialsGroupedBlocks,
    DIVIDENDS_PRIORITY_KEYS, reorderDividendsRecord, reorderDividendsFields,
    reorderRecordFields, RECORD_TAIL_KEYS, EXEC_TREASURY_PRIORITY_KEYS,
    HYSLR_CHG_PRIORITY_KEYS, SOURCE_PRIORITY_KEYS,
    DIVIDEND_GROUP_META_KEYS, dividendGroupKey, dividendGroupTitle,
    recordsIdentical, dedupIdenticalRecords, dividendPeriodBlocks,
  };
}
