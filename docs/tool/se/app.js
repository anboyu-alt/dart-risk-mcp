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
  if (typeof b.done !== "boolean") {
    return { shouldStop: true,
             reason: "서버 응답을 이해하지 못했습니다." };
  }
  return { shouldStop: false, reason: "" };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    LS_DART_KEY, LS_SESSION, SECTION_GROUPS, formatCount,
    nextKeysToFetch, pollDecision,
  };
}
