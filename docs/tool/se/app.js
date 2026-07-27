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
// Object.create(null)로 프로토타입 없는 객체를 만든다 — 일반 객체 리터럴이면
// 키가 "toString"·"constructor"일 때 LABELS[k]가 Object.prototype의 메서드로
// 새어나가 헤더가 함수가 된다(실제로 확인됨). 프로토타입이 없으면 그런 키는
// 그냥 undefined라 아래 label()의 `|| k` 폴백이 정상 동작한다.
const LABELS = Object.assign(Object.create(null), {
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
  // dict-of-lists 섹션(shareholders/audit_history/debt_balance 등)을
  // 하위 키별로 펼칠 때 소제목으로 쓰인다.
  major_holders: "최대주주",
  bulk_holders: "5% 대량보유",
  opinions: "감사의견",
  auditor_changes: "감사인 교체",
  independence_warnings: "감사인 독립성 경고",
  by_kind: "종류별 잔액",
  corporate_bond: "회사채",
  short_term_bond: "단기사채",
  commercial_paper: "기업어음",
  new_capital: "신종자본증권",
  cnd_capital: "조건부자본증권",
});

/** 키 → 한국어 라벨. 없으면 원본 키 그대로(숨기지 않는다). */
function label(k) {
  return LABELS[k] || k;
}

function cell(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/** 섹션 값을 표로 바꾼다. 무엇이든 표로 만든다 — 객체 리스트뿐 아니라
 *  객체가 아닌 항목(문자열 등)도, 스칼라 값 자체도 "값" 한 칸에 담아
 *  자기 행/자기 표를 갖는다. 표로 만들 것 자체가 없을 때만(빈 배열·
 *  빈 객체·null·undefined) null을 돌려준다.
 *
 *  이전에는 리스트 안 비객체 항목을 조용히 걸러냈고(흔적 없이 사라짐),
 *  스칼라 값 자체는 무조건 null이라 화면이 "표시할 데이터가 없습니다"로
 *  잘못 말했다 — 데이터가 있는데 없다고 하는 것과, 표로 만들 수 없어서
 *  없다고 하는 것은 다르다. */
function toTable(value) {
  if (value === null || value === undefined) return null;

  let records;
  if (Array.isArray(value)) records = value;
  else if (typeof value === "object") records = [value];
  else records = [value]; // 문자열·숫자 등 스칼라 자체 — 아래서 레코드로 감싼다

  records = records.map(function (r) {
    return (r && typeof r === "object" && !Array.isArray(r)) ? r : { "값": r };
  });
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
    columns: cols.map(label),
    rows: records.map(function (r) {
      return cols.map(function (k) { return cell(r[k]); });
    }),
  };
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

/** 섹션 값을 화면에 그릴 블록 목록 [{title, table}] 또는 [{title, text}]로
 *  바꾼다. title은 없을 수 있다(null). table/text 둘 다 없으면(표로 만들
 *  근거 자체가 없는 하위 키) 그 사실도 블록으로 남긴다 — 하위 항목이
 *  조용히 빠지는 것을 막기 위해서다.
 *
 *  shareholders({major_holders:[...], bulk_holders:[...]})처럼 dict 값
 *  안에 리스트/객체가 섞여 있으면("dict-of-lists") 한 표에 JSON 뭉치로
 *  욱여넣지 않고 하위 키마다 재귀적으로 소제목 + 개별 표로 펼친다.
 *  하위 키에 라벨이 없으면 원본 키를 그대로 쓴다. */
function sectionBlocks(value) {
  if (value === null || value === undefined) return [];

  if (Array.isArray(value)) {
    const t = toTable(value);
    return t ? [{ title: null, table: t }] : [];
  }

  if (!isPlainObject(value)) {
    if (isLongText(value)) return [{ title: null, text: value }];
    const t = toTable(value);
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
    const t = toTable(flat);
    if (t) blocks.push({ title: null, table: t });
  }
  for (const k of longTextKeys) {
    blocks.push({ title: label(k), text: value[k] });
  }
  for (const k of nestedKeys) {
    const sub = sectionBlocks(value[k]);
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
    LS_DART_KEY, LS_SESSION, SECTION_GROUPS, formatCount,
    nextKeysToFetch, pollDecision, toTable, LABELS, label,
    sectionBlocks, groupTitleFor, groupOrderIndex,
    ACTOR_STATUS, actorLine,
  };
}
