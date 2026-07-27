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

if (typeof module !== "undefined" && module.exports) {
  module.exports = { LS_DART_KEY, LS_SESSION, SECTION_GROUPS, formatCount };
}
