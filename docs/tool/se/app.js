"use strict";

// 브라우저에만 남는 값들. 서버에 저장하지 않는다.
const LS_DART_KEY = "se_dart_key";
const LS_SESSION = "se_session";

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

// DART 필드명 → 한국어 라벨. **확신하는 것만 넣는다.**
// 여기 없는 필드는 원본 키를 그대로 열 이름으로 쓴다 — 숨기면 데이터가
// 조용히 사라지고 사용자는 없는 줄 안다.
const LABELS = {
  rcept_no: "접수번호",
  rcept_dt: "접수일자",
  report_nm: "공시명",
  corp_name: "회사명",
  corp_code: "고유번호",
  stock_code: "종목코드",
  flr_nm: "공시제출인",
  ceo_nm: "대표자",
  est_dt: "설립일",
  adres: "주소",
  bsns_year: "사업연도",
};

/** 섹션 값을 표로 바꾼다. 표로 만들 수 없으면 null. */
function toTable(value) {
  let records;
  if (Array.isArray(value)) records = value;
  else if (value && typeof value === "object") records = [value];
  else return null;

  records = records.filter(function (r) { return r && typeof r === "object"; });
  if (records.length === 0) return null;

  // 열은 모든 레코드 키의 합집합이다. 레코드마다 필드가 다를 수 있고,
  // 첫 레코드만 보면 뒤쪽 필드가 통째로 사라진다.
  const cols = [];
  const seen = new Set();
  for (const r of records) {
    for (const k of Object.keys(r)) {
      if (!seen.has(k)) { seen.add(k); cols.push(k); }
    }
  }
  if (cols.length === 0) return null;

  return {
    columns: cols.map(function (k) { return LABELS[k] || k; }),
    rows: records.map(function (r) {
      return cols.map(function (k) { return cell(r[k]); });
    }),
  };
}

function cell(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
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

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    LS_DART_KEY, LS_SESSION, SECTION_GROUPS, formatCount,
    nextKeysToFetch, pollDecision, toTable, LABELS,
  };
}
