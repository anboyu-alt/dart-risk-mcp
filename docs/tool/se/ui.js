"use strict";

let CONFIG = null;      // {supabase_url, supabase_anon_key}
let SESSION = null;     // {access_token, refresh_token, expires_at}
let LOGGING_IN = false; // 로그인 버튼 연타로 중복 인증 요청이 나가는 것을 막는다
let ANALYZING = false;  // 분석 버튼 연타로 중복 작업이 생성되는 것을 막는다 —
                         // 분석은 수 분이 걸리고, 중복 생성되면 사용자의
                         // DART 호출 한도를 태운다.
let CURRENT_COMPANY = null; // 지금 화면에 떠 있는 분석의 회사명 — 행위자
                             // 패널을 "이 회사"로 열 때 쓴다(누가 사람인지
                             // 추측하지 않고, 헤더 버튼 하나로만 연다).

// ── SE-6 Task 3 — 임원 명단 ↔ 레지스트리 대조 상태 ──────────────────
// executive_roster는 서버 조회(임원 이름마다 GET /api/se/actors?name=,
// 순차)가 끝나야 강조(.mk)를 붙일 수 있다 — DISCLOSURES_DATA·
// FUND_USAGE_DATA와 같은 자리에 모듈 전역으로 둔다. showGate()가 전부
// 초기화한다(실명 잔류 금지 — 이 저장소가 이미 두 번 겪었다).
let EXEC_ROSTER_SOURCE = null; // 마지막으로 대조를 시작한 원본 roster
                                // 값(참조 비교로 "새로 도착한 값"인지
                                // 판단 — 같은 값으로 renderSection이 다시
                                // 불리면(아래 enrichExecutiveRoster의
                                // 내부 재호출) 대조를 다시 시작하지 않는다).
let EXEC_MATCHES = {};   // executiveMatches(records, lookups) 결과 캐시
let EXEC_LOOKUPS = {};   // 이름 → GET /api/se/actors?name= 원본 응답(패널 재사용)
let EXEC_STATUS = "idle"; // "idle" | "done" | "partial" | "failed"
let EXEC_GEN = 0; // 로그아웃·재분석 중인 배치를 무효화하는 세대 번호
                   // (POLL_GEN과 같은 패턴) — showGate()가 올리면, 이미
                   // 날아간 서버 조회가 뒤늦게 돌아와도 지워진 화면
                   // 위에 이전 사용자의 실명을 다시 그리지 않는다.
let POLL_GEN = 0; // 폴링 세대 토큰. analyze()·resumeIfAny()가 폴링을 새로
                   // 시작할 때마다 올린다. pollUntilDone()은 매 확인 지점에서
                   // 자기 세대를 이 값과 비교해, 더 새 루프가 시작된 뒤에는
                   // 스스로 멈춘다 — 렌더도 하지 않고 forgetJob()도 부르지
                   // 않는다. 이어받기 루프가 도는 중 새 분석이 시작되면
                   // (또는 그 반대) 늦게 도착한 옛 루프의 응답이 새 화면
                   // 위에 섞이거나, 옛 루프가 새 작업의 se_job을 지워버리는
                   // 사고를 막기 위해서다.
let CHART_INSTANCES = []; // renderChart()가 만든 Chart.js 인스턴스 목록.
                           // resetCharts()가 destroy() 대상으로 쓴다 —
                           // showGate()·renderHeadPlaceholder()가 #body를
                           // 비우는 자리와 같은 곳에서 함께 정리한다. 안
                           // 그러면 회사를 바꾸거나 로그아웃할 때마다
                           // 캔버스와 메모리가 쌓인다.
let SIGNALS_DATA = null; // docs/tool/signals-data.json 로드 결과(SE-4f
                          // Task 3, loadSignalsData()가 채운다) — 공시
                          // 목록 차트를 유형별로 나누는 데 쓴다. init()이
                          // 백그라운드로 불러오는 동안(또는 실패한 채로)
                          // null일 수 있다 — renderChart→chartData(app.js)가
                          // null이면 기존 단색 막대로 물러난다(화면이
                          // 죽지 않는다).
let DISCLOSURES_DATA = null; // disclosures 섹션이 renderSection에 도착할
                              // 때마다 원본 배열을 그대로 기억해 둔다(SE-5a
                              // Task 3). fund_usage 카드의 조달 공시 근접
                              // 힌트(fundChainDisclosureHints, Task 2)가 이
                              // 배열을 필요로 하는데, 두 섹션은 서로 다른
                              // 폴링 응답으로 각각 도착해 fund_usage 쪽
                              // 렌더 호출만으로는 접근할 방법이 없다.
                              // STAGE1_SPECS(se_server/jobs/registry.py)에서
                              // disclosures가 fund_usage보다 먼저 등록돼
                              // 있어 보통 이 값이 fund_usage보다 먼저
                              // 채워진다 — 그렇지 않더라도(아직 도착 전이면)
                              // SIGNALS_DATA와 같은 폴백 계약이다:
                              // fundChainDisclosureHints가 빈 배열을 받아
                              // {}를 돌려주고, 카드 자체는 힌트 블록만 뺀 채
                              // 그대로 렌더된다. 회사를 바꾸거나 로그아웃하면
                              // (renderHeadPlaceholder·showGate) null로
                              // 되돌려 이전 회사의 공시가 새 화면에 섞이지
                              // 않게 한다.
let DISCLOSURES_FAILED = false; // disclosures 섹션을 끝내 못 가져왔다는 사실
                                 // (renderFailures가 세운다). "아직 안 왔다"와
                                 // "못 가져왔다"는 다른 사실이고, 조달건 블록은
                                 // 후자일 때만 "대조하지 못했습니다"라고 말한다.
let FUND_USAGE_DATA = null; // fund_usage 섹션 원본 — disclosures가 fund_usage
                             // **뒤에** 도착(또는 뒤늦게 실패 확정)했을 때
                             // 조달건 블록만 다시 그리기 위해 들고 있는다.
                             // 서버 응답을 다시 받지 않는다(폴링 루프는 이미
                             // 받은 섹션을 두 번 주지 않는다 — fetched Set).
let FUND_CHAIN_DISCLOSURE_STATE = null; // 조달건 블록에 **이미 반영된**
                                         // disclosures 상태("ok"/"failed"/
                                         // "pending"). 상태가 그대로면 다시
                                         // 그리지 않는다 — renderFailures는
                                         // 폴링마다 불리므로 이 가드가 없으면
                                         // 매 바퀴 재렌더가 돈다.
let FINANCIALS_DATA = null; // financials 섹션 원본 — dividendVsRetainedEarnings
                             // (app.js, SE-12 Task 2)가 dividends 섹션을 그릴
                             // 때 필요로 하는데, 두 섹션은 위 DISCLOSURES_DATA와
                             // 같은 이유로 서로 다른 폴링 응답으로 도착한다.
                             // se_server/jobs/registry.py는 financials를
                             // dividends보다 먼저 등록해 두어 보통 먼저
                             // 도착하지만 보장은 아니다 — dividends가 먼저 오면
                             // 이 값 없이(이익잉여금 비교 없이) 그려진 뒤,
                             // financials 도착 시 refreshRetainedEarningsBlock이
                             // dividends 섹션만 다시 그린다.
let DIVIDENDS_DATA = null; // dividends 섹션 원본 — 위 FINANCIALS_DATA와 대칭.
                            // financials가 dividends보다 늦게 도착했을 때
                            // 이 값으로 dividends 섹션만 다시 그리기 위해
                            // 들고 있는다(서버에 다시 요청하지 않는다).

/** 지금 조달건 블록이 기댈 수 있는 disclosures 상태. 세 값은 서로 다른
 *  사실이라 하나로 뭉치지 않는다: "ok"(목록을 받았다 — 걸린 공시가 0건일
 *  수도 있고 그건 그것대로 사실이다), "failed"(못 가져왔다 — 대조 자체를
 *  못 했다), "pending"(아직 안 왔다 — 곧 다시 그린다). */
function fundChainDisclosureState() {
  if (Array.isArray(DISCLOSURES_DATA)) return "ok";
  if (DISCLOSURES_FAILED) return "failed";
  return "pending";
}

/** disclosures 상태가 바뀌었으면 조달건 블록(fund_usage 섹션)만 다시
 *  그린다(리뷰 지적 ②).
 *
 *  **왜 필요한가**: 폴링 루프(pollUntilDone)는 200으로 받은 섹션만
 *  fetched에 넣는다 — `GET /section/disclosures`가 실패하면 그 키는
 *  다음 바퀴에 재시도되지만, 그 사이 fund_usage는 이미 힌트 없이 그려지고
 *  fetched에 들어간다. 그 뒤 disclosures가 성공해도 fund_usage를 다시
 *  부르는 경로가 없어 힌트 블록이 조용히, 영구히 사라졌다.
 *
 *  **왜 renderSection(fund_usage) 하나만인가**: 다른 섹션은 disclosures에
 *  의존하지 않는다. 전체를 다시 그리면 사용자가 보던 스크롤·접기 상태까지
 *  뒤엎는다. renderSection은 자기 holder를 비우고 다시 채우므로(append가
 *  아니다) 카드가 두 배로 늘지 않는다. */
function refreshFundChainForDisclosures() {
  if (FUND_USAGE_DATA === null) return; // fund_usage가 아직 안 왔다 — 도착할
                                        // 때 최신 상태로 처음부터 그려진다
  const state = fundChainDisclosureState();
  if (FUND_CHAIN_DISCLOSURE_STATE === state) return;

  // 상태가 바뀌었어도 **화면이 실제로 달라질 때만** 다시 그린다. 목록을
  // 받았는데 걸린 조달 공시가 한 건도 없으면 재렌더 결과가 지금 화면과
  // 글자 하나까지 같다 — 그런데 renderSection은 이 섹션의 차트를 지우고
  // 새로 만든다(pruneChartsIn → new Chart). 눈에 보이는 변화가 없는데
  // 캔버스만 새로 만드는 일은 피한다. 단, 직전에 "대조하지 못했습니다"
  // 문구를 붙여 둔 상태(failed)라면 그 문구를 걷어내야 하므로 반드시
  // 다시 그린다.
  if (state === "ok" && FUND_CHAIN_DISCLOSURE_STATE !== "failed") {
    const chain = fundChain(Array.isArray(FUND_USAGE_DATA) ? FUND_USAGE_DATA : []);
    const hints = fundChainDisclosureHints(
      chain, DISCLOSURES_DATA, SIGNALS_DATA, FUND_CHAIN_WINDOW_DAYS);
    if (Object.keys(hints).length === 0) {
      // 반영할 것이 없다는 사실 자체는 기록해 둔다 — 다음 폴링마다 같은
      // 계산을 되풀이하지 않기 위해서다.
      FUND_CHAIN_DISCLOSURE_STATE = state;
      return;
    }
  }
  renderSection("fund_usage", FUND_USAGE_DATA);
}

/** financials가 dividends보다 늦게 도착해도 "배당 vs 이익잉여금" 비교가
 *  누락되지 않게 한다(위 refreshFundChainForDisclosures와 같은 이유·같은
 *  패턴, SE-12 Task 2). registry.py는 financials를 dividends보다 먼저
 *  등록해 두어 보통은 먼저 도착하지만 보장되지 않는다 — dividends가
 *  financials 없이 먼저 그려졌다면, financials가 도착하는 순간 dividends
 *  섹션만 다시 그려 비교를 채운다(원본 데이터를 다시 요청하지 않는다).
 *
 *  fund_usage 쪽과 달리 상태 값("ok"/"failed"/"pending")이 아니라 원본
 *  배열 유무만 보면 된다 — financials는 disclosures처럼 "실패했다"는
 *  별도 상태를 만들지 않고(renderFailures가 다루는 실패 섹션 목록에
 *  financials도 포함되지만, 여기서는 dividends가 이미 그려졌는지만
 *  중요하다) 도착 여부만 판단 기준이다. */
function refreshRetainedEarningsBlock() {
  if (DIVIDENDS_DATA === null) return; // dividends가 아직 안 왔다 — 도착할 때
                                        // FINANCIALS_DATA를 이미 들고 처음부터 그려진다
  renderSection("dividends", DIVIDENDS_DATA);
}

/** 사용자에게 그대로 보여줘도 되는 문구로만 만든 오류. 원시 오류(네트워크
 *  실패의 "Failed to fetch" 같은 브라우저 내부 문구, 서버 응답 원문 등)는
 *  이 마커가 없으므로 화면에 그대로 노출되지 않는다. */
function safeError(msg) {
  const e = new Error(msg);
  e.userSafe = true;
  return e;
}

/** 화면에 표시할 메시지를 고른다 — safeError로 만든 오류만 원문을 쓰고,
 *  그 외(네트워크 예외 등)는 폴백 문구로 대체한다. */
function safeMessage(e, fallback) {
  return (e && e.userSafe && e.message) || fallback;
}

/** SE API 호출. 이 함수 하나만 네트워크를 만진다. */
async function api(method, path, opts) {
  const o = opts || {};
  const headers = {};
  if (o.token) headers["Authorization"] = "Bearer " + o.token;
  // DART 키는 헤더로만 보낸다. 쿼리스트링에 실으면 URL 로그에 남는다.
  if (o.dartKey) headers["X-DART-Key"] = o.dartKey;
  if (o.body) headers["Content-Type"] = "application/json";
  const r = await fetch(path, {
    method: method,
    headers: headers,
    body: o.body ? JSON.stringify(o.body) : undefined,
  });
  let body = {};
  try { body = await r.json(); } catch (e) { body = {}; }
  return { status: r.status, body: body };
}

/** 브라우저 로그인에 필요한 공개 설정. 이 경로만 인증이 없다. */
async function loadConfig() {
  const r = await api("GET", "/api/se/config");
  if (r.status !== 200) throw safeError("서버 설정을 불러오지 못했습니다");
  const cfg = r.body || {};
  // 환경변수(SUPABASE_URL/SUPABASE_ANON_KEY)가 비어 있어도 서버는 200 +
  // 빈 문자열을 돌려줄 수 있다(se_server/config.py, se_server/api/handlers.py
  // _config). 여기서 걸러내지 않으면 gotrue()가 상대 경로("/auth/v1/token…")로
  // 요청해 404를 받고, 사용자에겐 원인 불명의 "로그인 실패"로만 보인다.
  if (!cfg.supabase_url || !cfg.supabase_anon_key) {
    throw safeError("서버 설정이 비어 있습니다 — 관리자에게 문의하세요");
  }
  CONFIG = cfg;
  return CONFIG;
}

/** signals-data.json(공개 뷰어 docs/tool/index.html과 공유하는 신호 분류
 *  데이터)을 불러온다. 실패하면(네트워크 오류·형태가 예상과 다름) null을
 *  돌려준다 — 공시 목록 차트가 유형별로 못 나뉠 뿐 화면 전체가 죽으면
 *  안 된다(브리프: "로드 실패에 대비하세요", chartData(app.js)가 이
 *  신호로 기존 단색 막대로 물러난다).
 *
 *  **`/signals-data.json`처럼 루트 기준 절대경로를 쓴다** — 이 파일은
 *  배포 루트(docs/tool, vercel.json의 outputDirectory)에 se/와 함께
 *  있다. 상대경로("signals-data.json")를 쓰면 trailingSlash:false 때문에
 *  `/se`가 `/se/`가 아니라 `/se`로 되돌아갈 때 상대경로가 루트 기준으로
 *  잘못 해석돼 404가 난다 — 이 저장소가 실제로 겪은 사고와 같은 부류다
 *  (tests/se/test_se_page_assets.py의 TestAssetPathsSurviveTrailingSlashRedirect·
 *  TestFetchPathsAreRootAbsolute 참고). */
async function loadSignalsData() {
  try {
    const r = await fetch("/signals-data.json");
    if (!r.ok) return null;
    const j = await r.json();
    if (!j || !Array.isArray(j.signals)) return null;
    return j;
  } catch (e) {
    return null;
  }
}

/** GoTrue REST 직접 호출 — SDK를 쓰지 않는다. */
async function gotrue(grant, payload) {
  const r = await fetch(
    CONFIG.supabase_url + "/auth/v1/token?grant_type=" + grant,
    {
      method: "POST",
      headers: {
        "apikey": CONFIG.supabase_anon_key,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    }
  );
  const body = await r.json().catch(function () { return {}; });
  if (r.status !== 200 || !body.access_token) {
    // 서버 원문을 그대로 보여주지 않는다 — 계정 존재 여부가 샐 수 있다.
    // 다만 실패 유형은 구분한다: 세션 만료(refresh_token)를 비밀번호 오류로
    // 안내하면 사용자가 애먼 비밀번호를 의심하며 헤맨다.
    if (grant === "refresh_token") {
      throw safeError("세션이 만료되었습니다. 다시 로그인하세요.");
    }
    throw safeError("로그인에 실패했습니다. 이메일과 비밀번호를 확인하세요.");
  }
  return body;
}

function saveSession(tok) {
  SESSION = {
    access_token: tok.access_token,
    refresh_token: tok.refresh_token,
    // 만료 60초 전을 만료로 친다 — 경계에서 401을 맞지 않기 위해서다.
    expires_at: Date.now() + (Number(tok.expires_in || 3600) - 60) * 1000,
  };
  localStorage.setItem(LS_SESSION, JSON.stringify(SESSION));
}

/** 메모리·로컬 저장소 양쪽에서 세션을 지운다. 갱신 실패·로그아웃이 공유한다. */
function clearSession() {
  SESSION = null;
  localStorage.removeItem(LS_SESSION);
}

/** 만료됐으면 갱신하고 유효한 access_token을 돌려준다. */
async function token() {
  if (!SESSION) throw safeError("로그인이 필요합니다");
  if (Date.now() < SESSION.expires_at) return SESSION.access_token;
  try {
    // CONFIG가 없는 채로 gotrue()를 부르면 CONFIG.supabase_url에서 TypeError가
    // 난다 — 저장된 세션을 복원하는 경로에서 발생할 수 있으므로 여기서 보장한다.
    if (!CONFIG) await loadConfig();
    saveSession(await gotrue("refresh_token", { refresh_token: SESSION.refresh_token }));
  } catch (e) {
    // 정리하지 않으면 (Task 2의) 폴링 루프가 매번 같은 실패를 반복하면서
    // 화면이 본문에 멈춰, 새로고침 전까지 로그인 화면으로 돌아가지 못한다.
    clearSession();
    showGate(safeMessage(e, "세션이 만료되었습니다. 다시 로그인하세요."));
    throw e;
  }
  return SESSION.access_token;
}

// ── 다크/라이트 테마 ───────────────────────────────────────────────

/** theme("light"|그 외 전부 다크)을 <html data-theme>·토글 버튼 문구에
 *  반영한다. "dark"·"light" 둘 다 속성으로 항상 명시한다(생략하지
 *  않는다) — index.html의 `:root[data-theme="light"]`만 라이트를
 *  오버라이드하고 기본 `:root` 자체가 다크 값이라, data-theme="dark"를
 *  명시해도 다크로 보이는 결과는 같다. */
function applyTheme(theme) {
  const isLight = theme === "light";
  document.documentElement.setAttribute("data-theme", isLight ? "light" : "dark");
  const btn = document.getElementById("theme-toggle");
  // 버튼은 "지금 상태"가 아니라 "누르면 바뀔 다음 모드"를 보여준다 —
  // 라이트 화면이면 클릭했을 때 다크로 돌아가므로 "다크 모드"라고
  // 안내한다(지금 라이트라는 상태를 다시 알려주는 게 아니다).
  if (btn) btn.textContent = isLight ? "다크 모드" : "라이트 모드";
  // 이미 그려진 차트가 있으면 새 테마 색으로 다시 칠한다 — 안 그러면
  // 라이트 모드로 바꿔도 다크 모드 때 정한 밝은 글자색이 그대로 남아
  // 축·범례가 흰 배경 위에서 안 보인다.
  repaintCharts();
}

/** 테마 토글 버튼 핸들러 — 선택을 localStorage(LS_THEME)에 기억한다. */
function toggleTheme() {
  const current = localStorage.getItem(LS_THEME) === "light" ? "light" : "dark";
  const next = current === "light" ? "dark" : "light";
  localStorage.setItem(LS_THEME, next);
  applyTheme(next);
}

// ── 차트 ──────────────────────────────────────────────────────────
//
// Chart.js(vendor/chart.umd.js)는 index.html이 app.js·ui.js보다 먼저
// <script>로 실어 전역 Chart를 만든다. 이 파일은 node vm 가짜 DOM으로도
// 실행되는데(TOC_ITEMS 주석과 같은 이유) 그 환경에는 Chart도
// getComputedStyle도 없다 — renderChart()가 가장 먼저 Chart 존재를
// 확인해, 없으면 표만 그리고 조용히 물러난다(표를 지우지 않는다: 차트는
// "얹는" 것일 뿐 필수가 아니다).

// 계열 구분에만 쓰는 색 10종. 값에 따라 바뀌지 않는다(v0.8.5 — 판정
// 색이 되면 안 된다). index.html의 :root/:root[data-theme="light"]가
// --c0~--c9를 정의한다. --c9는 SE-7 Task 3에서 "정기 보고" 범주(disclosures
// 차트, 위험 신호 8종 + 기타 = 9종에 이어 10번째 계열)를 "기타"와
// 시각적으로 구분하려고 기존 팔레트에 하나만 얹은 것이다 — 새 팔레트를
// 설계하지 않았다(task-3-brief.md).
const CHART_SERIES_VARS = [
  "--c0", "--c1", "--c2", "--c3", "--c4", "--c5", "--c6", "--c7", "--c8",
  "--c9",
];

/** CSS 변수 값을 읽는다. getComputedStyle이 없는 환경(가짜 DOM 테스트)
 *  에서는 빈 문자열을 돌려준다 — renderChart()가 Chart 존재를 먼저
 *  확인하므로 실제로는 Chart.js가 있는 화면에서만 불리지만, 방어적으로
 *  둔다. */
function cssVar(name) {
  if (typeof getComputedStyle !== "function") return "";
  const v = getComputedStyle(document.documentElement).getPropertyValue(name);
  return v ? v.trim() : "";
}

/** i번째 계열의 색. 값과 무관하게 순서로만 정해진다(위 CHART_SERIES_VARS
 *  주석과 같은 이유) — `--c0`~`--c9`를 순환한다. */
function chartSeriesColor(i) {
  return cssVar(CHART_SERIES_VARS[i % CHART_SERIES_VARS.length]);
}

/** 그려진 Chart 인스턴스를 모두 destroy()하고 목록을 비운다. 인스턴스가
 *  남으면 회사를 바꾸거나 로그아웃할 때마다 캔버스와 메모리가 계속
 *  쌓인다 — showGate()·renderHeadPlaceholder()가 #body를 비우는 자리와
 *  같은 곳(한 곳 정리 패턴, resetToc()과 동일한 이유)에서 부른다. */
function resetCharts() {
  for (const c of CHART_INSTANCES) {
    if (c && typeof c.destroy === "function") {
      try { c.destroy(); } catch (e) { /* 정리 실패로 나머지 정리까지 막지 않는다 */ }
    }
  }
  CHART_INSTANCES = [];
}

/** wrap(그 블록의 div) 안에 key에 대응하는 차트를 그린다. records는 그
 *  블록의 원본 레코드다 — table.rows(formatValue를 거친 문자열)가 아니라
 *  sectionBlocks가 함께 실어준 숫자 원본이다.
 *
 *  CHART_SPECS(app.js)에 이 key 정의가 없거나 chartData가 그릴 게
 *  없다고 판단하면(null) 아무것도 만들지 않고 false를 돌려준다 — 표만
 *  남는다(브리프 원칙: 표를 지우지 않는다). 만들면 true를 돌려준다.
 *
 *  canvas 안의 숫자는 복사도 검색도 안 되므로, wrap 안에 이미 있는
 *  <table> 바로 위에 끼워 넣는다 — 표를 대체하지 않는다. 표가 없으면
 *  (텍스트 블록 등, records 자체가 비어 chartData가 null을 주므로
 *  실제로는 여기까지 오지 않는다) 방어적으로 끝에 붙인다.
 *
 *  색은 계열 구분 용도로만 쓴다(v0.8.5) — `--c0`~`--c9`를 값과 무관하게
 *  순서대로 배정한다. `--red` 등 판정 색은 여기서 절대 쓰지 않는다.
 *
 *  signalsData(선택, SE-4f Task 3)는 disclosures처럼 spec.classifyField가
 *  있는 차트에서만 chartData(app.js)로 그대로 전달된다 — 다른 스펙은
 *  이 인자를 쓰지 않으므로 undefined여도 그대로 이전과 같다.
 */
function renderChart(wrap, key, records, signalsData) {
  if (typeof Chart === "undefined") return false;
  const spec = CHART_SPECS[key];
  if (!spec) return false;
  const data = chartData(records, spec, signalsData);
  if (!data) return false;

  const gridColor = cssVar("--dim2");
  const textColor = cssVar("--tx") || cssVar("--dim2");

  // series(계획 vs 실제 등) 계열은 데이터셋마다 자기 키(spec.series[i].key)를
  // 쓰고, groupBy(보고자별 등) 계열은 모든 데이터셋이 같은 y 필드(spec.y)를
  // 쓴다 — 툴팁이 어느 열의 단위(억/조 등)로 포맷할지 알려면 이 매핑이
  // 필요하다.
  const seriesKeys = spec.series
    ? spec.series.map(function (s) { return s.key; })
    : null;

  const datasets = data.datasets.map(function (d, i) {
    const color = chartSeriesColor(i);
    return Object.assign({}, d, {
      borderColor: color,
      backgroundColor: color,
      // 실제 값끼리만 시간순으로 잇는다 — 추세선·예측선이 아니다(v0.8.5).
      // Chart.js 기본값(false)을 명시해 null 구간을 이어붙이지 않는다.
      spanGaps: false,
    });
  });

  const canvas = document.createElement("canvas");
  canvas.className = "chart-canvas";
  // canvas 안의 그림은 스크린 리더가 읽지 못한다 — role="img" + aria-label로
  // 최소한 "무슨 차트인지"는 전달한다(리뷰 지적 ⑤). 정확한 값은 어차피
  // 표(같은 wrap 안, 이 canvas 바로 아래)가 텍스트로 책임진다 — 여기서는
  // 차트의 존재와 제목만 알리면 된다.
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", spec.title || label(key));
  const table = typeof wrap.querySelector === "function" ? wrap.querySelector("table") : null;
  if (table && typeof wrap.insertBefore === "function") {
    wrap.insertBefore(canvas, table);
  } else {
    wrap.appendChild(canvas);
  }

  const chart = new Chart(canvas, {
    type: spec.kind,
    data: { labels: data.labels, datasets: datasets },
    options: {
      responsive: true,
      plugins: {
        legend: { labels: { color: textColor } },
        tooltip: {
          callbacks: {
            // 툴팁 값은 formatValue로 포맷한다 — 억/조 표기가 표와 어긋나면
            // 같은 값을 두 가지로 말하는 셈이 된다.
            //
            // 재무지표(spec.tooltipFormat === "indicator")만 예외다: 그 표는
            // formatIndicator로 "130.248%"라고 쓰는데 formatValue는 단위 없는
            // 맨숫자를 돌려줘, 같은 값을 표와 툴팁이 서로 다르게 말했다(리뷰
            // 지적 ④). 계열 이름(dataset.label)이 곧 지표명이라 그대로 넘기면
            // 이름에 이미 "(%)"가 있는 지표(배당성향(%))의 단위 중복도
            // formatIndicator가 표와 똑같이 처리한다.
            label: function (ctx) {
              const k = seriesKeys ? seriesKeys[ctx.datasetIndex] : spec.y;
              const shown = spec.tooltipFormat === "indicator"
                ? formatIndicator(ctx.dataset.label, ctx.parsed.y)
                : formatValue(k, ctx.parsed.y);
              return ctx.dataset.label + ": " + shown;
            },
          },
        },
      },
      scales: {
        // spec.xScale(app.js CHART_SPECS)을 그대로 쓴다 — "category"만
        // 있고 "time"은 없다는 설계 결정(별도 날짜 어댑터 회피)을 여기서
        // 실제로 지킨다. 값이 없으면 Chart.js 기본값과 같은 "category"로
        // 떨어진다. spec.stacked(disclosures 등, SE-4f Task 3)는 x·y 축
        // 양쪽에 걸어야 Chart.js가 막대를 누적으로 그린다 — 없으면
        // Chart.js 기본값(false)과 같다(이전 동작 그대로).
        x: {
          type: spec.xScale || "category", stacked: !!spec.stacked,
          ticks: { color: textColor }, grid: { color: gridColor },
        },
        y: {
          stacked: !!spec.stacked,
          ticks: { color: textColor }, grid: { color: gridColor },
          title: { display: !!spec.yLabel, text: spec.yLabel || "", color: textColor },
        },
      },
    },
  });
  CHART_INSTANCES.push(chart);
  return true;
}

/** 지금 그려진 모든 차트의 축·범례 색을 다시 칠한다. applyTheme()이
 *  테마를 바꿀 때마다 부른다 — repaintCharts가 없으면 라이트 모드로
 *  바꿔도 다크 모드 때 정한 색이 옵션 객체에 그대로 남는다(Chart.js는
 *  옵션을 스스로 다시 읽지 않는다). */
function repaintCharts() {
  if (CHART_INSTANCES.length === 0) return;
  const gridColor = cssVar("--dim2");
  const textColor = cssVar("--tx") || cssVar("--dim2");
  for (const chart of CHART_INSTANCES) {
    const opts = chart.options || {};
    if (opts.plugins && opts.plugins.legend && opts.plugins.legend.labels) {
      opts.plugins.legend.labels.color = textColor;
    }
    if (opts.scales) {
      if (opts.scales.x) {
        if (opts.scales.x.ticks) opts.scales.x.ticks.color = textColor;
        if (opts.scales.x.grid) opts.scales.x.grid.color = gridColor;
      }
      if (opts.scales.y) {
        if (opts.scales.y.ticks) opts.scales.y.ticks.color = textColor;
        if (opts.scales.y.grid) opts.scales.y.grid.color = gridColor;
        if (opts.scales.y.title) opts.scales.y.title.color = textColor;
      }
    }
    if (typeof chart.update === "function") chart.update();
  }
}

/** node 서브트리 안의 canvas 엘리먼트를 전부 모은다(재귀). 실제 브라우저
 *  DOM(tagName)과 이 파일이 함께 실행되는 가짜 DOM 테스트(tag) 양쪽을
 *  모두 지원한다 — querySelectorAll("canvas")에 기대지 않는 이유는
 *  FakeEl(테스트 하네스)이 "table" 선택자만 흉내 내기 때문이다. */
function collectCanvasesIn(node, out) {
  out = out || [];
  if (!node) return out;
  const tag = node.tag || (node.tagName ? node.tagName.toLowerCase() : "");
  if (tag === "canvas") out.push(node);
  const kids = node.children;
  if (kids) for (let i = 0; i < kids.length; i++) collectCanvasesIn(kids[i], out);
  return out;
}

/** node 서브트리 안의 canvas에 연결된 Chart 인스턴스를 destroy()하고
 *  CHART_INSTANCES에서 뺀다.
 *
 *  renderSection이 섹션을 다시 그릴 때(같은 key로 두 번째 이후 호출)
 *  holder를 비우기 직전에 부른다 — holder.removeChild는 DOM에서만
 *  canvas를 떼어낼 뿐, 그 canvas로 만든 Chart.js 인스턴스(내부 이벤트
 *  리스너·캔버스 컨텍스트를 쥐고 있다)는 CHART_INSTANCES에 그대로
 *  남는다(리뷰 지적 ④) — showGate()의 resetCharts()는 회사를 바꾸거나
 *  로그아웃할 때만 불리므로, 같은 회사 안에서 같은 섹션이 다시 그려지는
 *  경로는 이 함수가 없으면 정리되지 않는다. */
function pruneChartsIn(node) {
  const canvases = collectCanvasesIn(node, []);
  if (canvases.length === 0 || CHART_INSTANCES.length === 0) return;
  const stale = new Set(canvases);
  CHART_INSTANCES = CHART_INSTANCES.filter(function (c) {
    if (!c || !stale.has(c.canvas)) return true;
    if (typeof c.destroy === "function") {
      try { c.destroy(); } catch (e) { /* 정리 실패로 나머지 정리까지 막지 않는다 */ }
    }
    return false;
  });
}

// ── 좌측 목차 ─────────────────────────────────────────────────────
//
// TOC_ITEMS: {el, link} 목록. addTocEntry가 그룹(groupHolder)·섹션
// (sectionHolder)이 처음 만들어질 때마다 채운다 — 섹션은 폴링마다
// 순차적으로 도착하므로 목차도 그 순서대로 자란다.
//
// TOC_OBSERVER: IntersectionObserver 하나를 지연 생성해 모든 항목이
// 공유한다. 이 파일은 node vm 테스트용 가짜 DOM으로도 실행되는데(위
// TOC_ITEMS 주석과 같은 이유), 그 가짜 DOM에는 #toc 자체가 없고
// IntersectionObserver도 없다 — addTocEntry가 document.getElementById("toc")
// 부터 확인해 없으면 조용히 아무 일도 하지 않으므로 그 환경에서도
// 안전하다.
let TOC_ITEMS = [];
let TOC_OBSERVER = null;

function ensureTocObserver() {
  if (TOC_OBSERVER || typeof IntersectionObserver === "undefined") return TOC_OBSERVER;
  TOC_OBSERVER = new IntersectionObserver(function (entries) {
    for (const entry of entries) {
      const item = TOC_ITEMS.find(function (t) { return t.el === entry.target; });
      if (!item) continue;
      if (entry.isIntersecting) item.link.classList.add("active");
      else item.link.classList.remove("active");
    }
  }, { rootMargin: "-10% 0px -70% 0px" });
  return TOC_OBSERVER;
}

/** 목차 항목 하나를 추가한다. #toc가 없는 환경(가짜 DOM 테스트)에서는
 *  아무 것도 만들지 않는다 — groupHolder·sectionHolder는 실제 브라우저
 *  밖에서도(node vm 테스트) 호출되므로 여기서 막아야 그 테스트들이
 *  안전하다.
 *
 *  order는 이 항목이 속한 그룹의 groupOrderIndex다 — 그룹 자신도, 그
 *  그룹 소속 섹션도 같은 값을 쓴다(groupHolder·sectionHolder가 넘긴다).
 *  groupHolder()는 이미 이 값으로 #body 안 DOM 위치를 insertBefore로
 *  정하고 있다 — 목차가 언제나 `appendChild`로만 쌓이면(이전 버전) 그
 *  순서와 어긋난다. 실측 회귀: company_info가 STAGE1_SPECS 첫 항목이라
 *  다른 어떤 섹션보다 먼저 도착하므로, company_info가 속한(당시)
 *  "기타" 그룹이 매번 목차 맨 위를 차지했지만, 화면(#body)에서는
 *  groupOrderIndex가 가장 커서 항상 맨 아래였다 — 사이드바 클릭과 실제
 *  스크롤 위치가 어긋났다. TOC_ITEMS에 이미 들어 있는 항목 중 order가
 *  더 큰 첫 항목 앞에 끼워 넣으면(같은 order끼리는 도착 순서 그대로
 *  뒤에 붙는다) groupHolder()의 insertBefore 로직과 같은 결과가 된다. */
function addTocEntry(titleText, targetEl, isSection, order) {
  const tocEl = document.getElementById("toc");
  if (!tocEl) return;
  const link = document.createElement("div");
  link.className = isSection ? "toc-item toc-section" : "toc-item";
  link.textContent = titleText;
  link.addEventListener("click", function () {
    targetEl.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  let before = null;
  for (const item of TOC_ITEMS) {
    if (item.order > order) { before = item.link; break; }
  }
  tocEl.insertBefore(link, before);
  TOC_ITEMS.push({ el: targetEl, link: link, order: order });
  const obs = ensureTocObserver();
  if (obs) obs.observe(targetEl);
}

/** 새 회사 분석을 시작할 때(#body를 비울 때) 목차도 함께 비운다 — 안
 *  그러면 이전 회사에서 만든 목차 항목이 남아, 클릭해도 이미 사라진
 *  섹션을 가리키게 된다(showGate()가 #panel·#body를 함께 정리하는 것과
 *  같은 "한 곳 정리" 이유).
 *
 *  SEC_WRAP(섹션 키 → .sec 엘리먼트, sectionHolder() 참고)도 여기서
 *  함께 비운다. #body의 자식 노드를 지우는 곳(showGate()·
 *  renderHeadPlaceholder())은 모두 이 함수를 바로 뒤이어 부르므로,
 *  비우지 않으면 이전 회사에만 있던 섹션 키가 새 회사에서 다시
 *  렌더되지 않는 한 SEC_WRAP에 detached된 옛 엘리먼트 참조가 계속
 *  남는다. */
function resetToc() {
  const tocEl = document.getElementById("toc");
  if (tocEl) { while (tocEl.firstChild) tocEl.removeChild(tocEl.firstChild); }
  if (TOC_OBSERVER) { TOC_OBSERVER.disconnect(); TOC_OBSERVER = null; }
  TOC_ITEMS = [];
  for (const k in SEC_WRAP) delete SEC_WRAP[k];
  DOC_LIST_ROWS = [];
}

// ── 화면 전환 + 로컬 저장 ──────────────────────────────────────────

function showMain() {
  document.getElementById("gate").hidden = true;
  document.getElementById("main").hidden = false;
}

function showGate(msg) {
  document.getElementById("gate").hidden = false;
  document.getElementById("main").hidden = true;
  const msgEl = document.getElementById("gate-msg");
  msgEl.textContent = msg || "";
  // 패널이 열린 채 남으면 로그인 화면 위로 이전 사용자의 실명이 계속
  // 보인다 — #panel은 #main 밖(형제 노드)이라 #main을 숨겨도 안
  // 가려진다. showGate()는 로그아웃(doLogout)뿐 아니라 세션 만료
  // (token() 갱신 실패, init()의 자동 로그인 실패)에서도 불린다 —
  // 여기 한 곳에서만 정리하면 그 모든 경로가 한 번에 덮인다.
  closePanel();
  const panelBox = document.getElementById("panel-body");
  if (panelBox) panelBox.textContent = "";
  // #main을 hidden으로 숨기는 것만으로는 그 안의 내용이 지워지지 않는다.
  // 사용자 A가 조회 → 로그아웃 → 사용자 B가 로그인하면, showMain()이
  // #main을 다시 보여줄 뿐이라 A가 조회한 회사의 실명 표(#body)·헤더
  // (#head-name)·진행률(#bar)이 그대로 남아 B에게 보인다. 위 패널 정리와
  // 같은 이유로 여기 한 곳에서 비워야 로그아웃·세션 만료 등 화면을 떠나는
  // 모든 경로가 한 번에 덮인다.
  const headEl = document.getElementById("head-name");
  if (headEl) headEl.textContent = "";
  const barEl = document.getElementById("bar");
  if (barEl) barEl.textContent = "";
  const bodyBox = document.getElementById("body");
  if (bodyBox) {
    while (bodyBox.firstChild) bodyBox.removeChild(bodyBox.firstChild);
  }
  // company_info(헤더)는 #body 밖의 별도 고정 박스(#company-info)에
  // 그려진다(renderCompanyInfo 참고) — #body를 비우는 것만으로는 이
  // 박스가 비워지지 않으므로 따로 비워야 한다. 안 그러면 로그아웃 후
  // 로그인 화면 위로 이전 사용자가 조회한 회사의 대표자·주소 등이 남는다.
  const companyInfoBox = document.getElementById("company-info");
  if (companyInfoBox) {
    while (companyInfoBox.firstChild) companyInfoBox.removeChild(companyInfoBox.firstChild);
  }
  resetToc(); // #body를 비우는 자리와 같이 — 목차만 남으면 죽은 링크가 된다
  resetCharts(); // 같은 자리 — 인스턴스가 남으면 다음 사용자 화면 위에 이어붙는다
  CURRENT_COMPANY = null;
  DISCLOSURES_DATA = null; // #body는 지웠지만(위) 이 JS 변수 자체는 남아있던
                            // 문제 — 다음 사용자가 새로 로그인해 다른 회사를
                            // 조회하면 fund_usage 카드의 공시 힌트가 이전
                            // 사용자의 회사 공시를 근거로 뜬다(같은 종류의
                            // 사고가 이 저장소에서 이미 두 번 났다).
  DISCLOSURES_FAILED = false; // 같은 이유 — 이전 사용자 화면의 실패 사실이
                               // 새 화면의 조달건 블록에 문구로 남는다.
  FUND_USAGE_DATA = null;     // 같은 이유 — 이전 사용자가 조회한 회사의
                               // 자금사용 원본을 들고 있으면, 다음 화면에서
                               // disclosures가 도착하는 순간 그 원본으로
                               // 조달건 블록이 되살아난다.
  FUND_CHAIN_DISCLOSURE_STATE = null;
  FINANCIALS_DATA = null; // 같은 이유 — 이전 사용자가 조회한 회사의 재무제표를
                           // 들고 있으면, 다음 사용자의 dividends 섹션이
                           // 이전 회사의 이익잉여금과 잘못 짝지어질 수 있다.
  DIVIDENDS_DATA = null;  // 같은 이유 — refreshRetainedEarningsBlock이 이전
                           // 사용자의 배당 원본으로 다시 그리지 않게 한다.
  const actorBtn = document.getElementById("actor-btn");
  if (actorBtn) actorBtn.hidden = true;
  // SE-6 Task 3 — #body·#panel-body는 위에서 이미 비웠지만(실명 DOM은
  // 지워졌다), 진행 중인 enrichExecutiveRoster 배치가 아직 날아가 있는
  // 채로 남을 수 있다. EXEC_GEN을 올리면 그 배치의 myGen 비교가 어긋나
  // (enrichExecutiveRoster 참고) 늦게 돌아온 응답이 이미 비운 화면 위에
  // 이전 사용자의 실명을 다시 그리지 않는다. 나머지 EXEC_* 캐시도 함께
  // 비운다 — 이 저장소는 로그아웃 후 잔류 사고를 이미 두 번 겪었다.
  EXEC_ROSTER_SOURCE = null;
  EXEC_MATCHES = {};
  EXEC_LOOKUPS = {};
  EXEC_STATUS = "idle";
  EXEC_GEN++;
}

function loadStoredSession() {
  try {
    const raw = localStorage.getItem(LS_SESSION);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || !parsed.access_token || !parsed.refresh_token) return null;
    return parsed;
  } catch (e) {
    return null;
  }
}

function saveDartKey(key) {
  localStorage.setItem(LS_DART_KEY, key);
}

/** 로그인 버튼 핸들러 — 이메일·비밀번호로 GoTrue 인증 후 DART 키를 저장한다. */
async function doLogin() {
  if (LOGGING_IN) return; // 연타 시 중복 인증 요청 방지
  const msgEl = document.getElementById("gate-msg");
  msgEl.textContent = "";
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;
  const dartKey = document.getElementById("dartkey").value.trim();
  if (!email || !password) {
    msgEl.textContent = "이메일과 비밀번호를 입력하세요.";
    return;
  }
  LOGGING_IN = true;
  try {
    if (!CONFIG) await loadConfig();
    const tok = await gotrue("password", { email: email, password: password });
    saveSession(tok);
    if (dartKey) saveDartKey(dartKey);
    // 인증정보가 DOM에 평문으로 남지 않도록 비운다.
    document.getElementById("password").value = "";
    document.getElementById("dartkey").value = "";
    showMain();
    // 탭을 닫았다 다시 로그인한 경우에도 12시간 이내 작업이 있으면
    // 이어받는다 — resumeIfAny 자체가 없거나 오래된 작업이면 조용히
    // false를 돌려주므로 여기서 결과를 기다릴 필요는 없다.
    resumeIfAny();
  } catch (e) {
    msgEl.textContent = safeMessage(e, "로그인에 실패했습니다. 잠시 후 다시 시도하세요.");
  } finally {
    LOGGING_IN = false;
  }
}

/** 로그아웃 — 세션과 DART 키를 모두 지운다.
 *  공용 PC에서 다음 사용자가 앞사람의 DART 키로 조회하지 못하게 한다. */
function doLogout() {
  clearSession();
  localStorage.removeItem(LS_DART_KEY);
  const dartEl = document.getElementById("dartkey");
  if (dartEl) dartEl.value = "";
  const pwEl = document.getElementById("password");
  if (pwEl) pwEl.value = "";
  // 패널·본문(#body)·헤더(#head-name)·진행률(#bar)을 비우고 CURRENT_COMPANY·
  // actor-btn을 초기화하는 처리는 showGate() 안으로 옮겼다 — 세션 만료
  // 경로(token())와 공유하기 위해서다. 여기서 다시 하면 중복이다.
  showGate();
}

/** 저장된 세션이 있으면 갱신을 시도해 자동 로그인, 없거나 실패하면 로그인 화면. */
async function init() {
  // 저장된 테마를 가장 먼저 적용한다 — 기본은 다크(저장된 값이 없거나
  // "light"가 아니면 다크)이고, 이전에 라이트를 골랐던 사용자만 밝은
  // 화면으로 시작한다.
  applyTheme(localStorage.getItem(LS_THEME) === "light" ? "light" : "dark");
  // 마크업에 #theme-toggle이 없는 예상 밖 상황(배포 실수 등)에서 null에
  // addEventListener를 호출하면 async init()이 여기서 예외를 던지고,
  // 그 뒤로 이어지는 login·logout·analyze-btn·actor-btn·panel-close 배선이
  // 전부 통째로 건너뛰어진다 — 아무 버튼도 반응하지 않는데 오류 안내조차
  // 없다. 가드로 그 연쇄를 끊는다.
  const themeToggleBtn = document.getElementById("theme-toggle");
  if (themeToggleBtn) themeToggleBtn.addEventListener("click", toggleTheme);
  resetToc(); // 페이지를 새로 열 때 목차를 빈 상태로 시작한다

  // 공시 목록 차트를 유형별로 나누는 데 쓴다(SE-4f Task 3) — analyze()가
  // 끝나 disclosures 섹션을 그릴 때까지는 시간이 걸리므로(수 분) 로그인
  // 흐름을 기다리게 하지 않고 백그라운드로 불러온다. 실패해도 renderChart
  // (chartData, app.js)가 signalsData=null을 받아 기존 단색 막대로
  // 물러난다 — await하지 않는다고 오류를 삼키는 게 아니다(loadSignalsData
  // 자체가 실패를 null로 흡수한다).
  loadSignalsData().then(function (d) { SIGNALS_DATA = d; });

  document.getElementById("login").addEventListener("click", doLogin);
  document.getElementById("logout").addEventListener("click", doLogout);
  // 회사 입력 폼 — 버튼 클릭과 입력창 Enter 둘 다 doAnalyze()로 이어진다.
  // Enter는 select(lookback-years)가 아니라 company-input에만 건다 — select의
  // 기본 Enter 동작(옵션 확정)과 충돌하지 않기 위해서다.
  document.getElementById("analyze-btn").addEventListener("click", doAnalyze);
  document.getElementById("company-input").addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      doAnalyze();
    }
  });
  // 행위자 패널은 회사 단위 API(GET /api/se/actors?company=)라서, 본문
  // 어느 열이 사람 이름인지 추측할 필요가 없다 — 헤더 버튼 하나로
  // "지금 분석 중인 회사"를 그대로 연다.
  document.getElementById("actor-btn").addEventListener("click", function () {
    if (CURRENT_COMPANY) openActorPanel(CURRENT_COMPANY);
  });
  document.getElementById("panel-close").addEventListener("click", closePanel);
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closePanel();
  });

  const stored = loadStoredSession();
  if (!stored) {
    showGate();
    return;
  }
  SESSION = stored;
  try {
    await loadConfig();
    await token();
    showMain();
    // 저장된 세션으로 자동 로그인한 경우(탭을 닫았다 다시 연 경우가
    // 여기 해당한다)에도 12시간 이내 이어받을 작업이 있으면 재개한다.
    resumeIfAny();
  } catch (e) {
    // token()이 자체 실패 경로에서 이미 정리·안내를 했을 수 있지만(같은 e가
    // 다시 올라옴), loadConfig() 자체가 실패하는 경우엔 여기가 유일한 안내
    // 지점이라 다시 한번 확실히 정리한다.
    clearSession();
    showGate(safeMessage(e, ""));
  }
}

// ── 분석 실행 + 진행률 폴링 ────────────────────────────────────────

function showBar(msg) { document.getElementById("bar").textContent = msg; }
function showProgress(p) {
  showBar(p.company + " — " + formatCount(p.finished) + "/" + formatCount(p.total));
}
/** message를 생략하면 "N 분석을 시작합니다…"(새 작업 기본 문구)를 쓴다.
 *  resumeIfAny()는 이어받는 작업이라 다른 문구(message)를 넘긴다 —
 *  이미 진행 중인 작업을 "시작합니다"로 안내하면 사용자가 새 분석이
 *  시작된 줄 오해한다. */
function renderHeadPlaceholder(name, message) {
  document.getElementById("head-name").textContent = message || (name + " 분석을 시작합니다…");
  // 패널이 이전 회사(실명·공시 원문)를 띄운 채 열려 있으면, 화면은 새
  // 회사를 보여주는데 패널만 이전 회사 정보로 남는다 — 회사를 바꿔
  // 다시 분석할 때 특히 실명이 그렇게 남을 수 있다.
  closePanel();
  const panelBox = document.getElementById("panel-body");
  if (panelBox) panelBox.textContent = "";
  // 이전 회사의 섹션·오류 블록이 새 회사 화면 위에 남아 섞이지 않도록
  // 본문을 비운다. sectionHolder/groupHolder/renderFailures는 모두
  // "sec-<key>" 같은 고정 id 노드를 재사용하므로, 여기서 비우지 않으면
  // 새 회사가 채우지 않는 섹션(예: 이전 회사에만 있던 신호)이 그대로
  // 남아 두 회사의 정보가 뒤섞여 보인다.
  const bodyBox = document.getElementById("body");
  if (bodyBox) {
    while (bodyBox.firstChild) bodyBox.removeChild(bodyBox.firstChild);
  }
  // showGate()와 같은 이유 — company_info 고정 박스는 #body 밖에 있어
  // 따로 비워야 이전 회사의 대표자·주소 등이 새 회사 화면 위에 남지 않는다.
  const companyInfoBox = document.getElementById("company-info");
  if (companyInfoBox) {
    while (companyInfoBox.firstChild) companyInfoBox.removeChild(companyInfoBox.firstChild);
  }
  resetToc(); // 같은 이유 — 새 회사의 목차를 처음부터 다시 쌓는다
  resetCharts(); // 이전 회사의 차트 인스턴스가 새 회사 화면 위에 남지 않게 정리한다
  DISCLOSURES_DATA = null; // showGate()와 같은 이유 — 새 회사의 fund_usage
                            // 카드가 아직 도착하지 않은 자기 disclosures
                            // 대신 이전 회사의 공시로 힌트를 만들지 않게 한다.
  DISCLOSURES_FAILED = false;         // showGate()와 같은 이유(그 주석 참고)
  FUND_USAGE_DATA = null;             // 〃 — 이전 회사의 자금사용 원본으로
  FUND_CHAIN_DISCLOSURE_STATE = null; //    새 화면에 조달건 블록이 되살아나지
                                      //    않게 한다.
  FINANCIALS_DATA = null; // showGate()와 같은 이유 — 이전 회사의 재무제표로
                           // 새 회사의 배당 vs 이익잉여금 비교가 되살아나지
                           // 않게 한다.
  DIVIDENDS_DATA = null;  // 〃
  CURRENT_COMPANY = name;
  const btn = document.getElementById("actor-btn");
  if (btn) btn.hidden = false;
}

/** 표를 DOM으로 만든다. 값은 전부 textContent로 넣는다 —
 *  공시 원문과 실명이 그대로 들어오는 자리다.
 *
 *  table은 app.js의 tableLayout() 결과다 — {orientation, caption, columns,
 *  keys, rows, raw}. caption(모든 행의 값이 같아 표 위로 올린 열)이 있으면
 *  표 앞에 <div class="cap">로 한 번 보여준다 — 숨기는 게 아니라 145줄
 *  반복 대신 한 번만 보여주는 것이다.
 *
 *  `rcept_no` 열의 셀만 클릭 가능하게 만든다 — table.keys(tableLayout()이
 *  라벨과 나란히 남긴 원본 키)로 정확히 그 열을 찾는다. 어느 열이 공시
 *  제목인지, 어느 열이 사람 이름인지는 추측하지 않는다 — 확인되지 않은
 *  필드명을 코드에 박는 것이 이 프로젝트에서 반복해서 사고를 낸 방식이고,
 *  rcept_no만 LABELS·2단 섹션 키(`doc:<접수번호>`)로 이미 확인된 필드다.
 *
 *  orientation이 "vertical"이면 rows[i]는 [라벨, 값] 한 쌍이고 값은
 *  rows[i][1]에 있다 — 가로(rows[i][col])와 셀 위치가 달라 rcept_no 클릭
 *  배선도 두 경우를 모두 처리해야 한다(keys[i]가 그 행이 어느 원본
 *  키인지를 알려준다).
 *
 *  rcept_no가 모든 행에서 같으면(affiliates·financials 실측 — 27줄·30줄
 *  전부 같은 접수번호) tableLayout이 그 열을 caption으로 승격시켜
 *  table.keys에서 빼버린다 — 위 rceptCol 배선만으로는 그 섹션에서 공시
 *  원문 패널을 열 방법이 사라진다(캡션 div는 textContent만이라 클릭도
 *  안 됐다). caption 항목의 key가 "rcept_no"면 그 값도 똑같이 클릭
 *  가능하게 만들어, "반복 열은 캡션으로 줄인다"와 "공시 원문은 항상 열 수
 *  있다" 두 성질을 함께 지킨다.
 *
 *  `marks`(선택 인자, app.js cellMarks(records, sectionKey)의 반환값 —
 *  "행번호|열키" → 규칙 문구)가 있으면 그 좌표의 셀에 강조(.mk)를 입힌다.
 *  호출부가 넘기지 않으면(undefined) 아무 표시도 하지 않아 기존 동작이
 *  그대로다. 강조는 **세 경로 모두**에서 확인해야 한다 — 본문 셀만
 *  처리하면 (a) 모든 행에서 값이 같아 caption으로 승격된 열, (b) 12열
 *  넘어 접힌 열에서는 강조가 조용히 사라진다(승격·접기는 "표시를 줄이는"
 *  경로라 강조 배선이 거기서 끊기기 쉽다). 좌표는 이미 위에서 계산한
 *  isValueCell/cellKey를 그대로 쓴다(브리프: "새로 계산하지 않는다") —
 *  세로 표는 레코드가 하나라 행번호는 항상 0이다. */
function tableEl(table, marks, records) {
  const frag = document.createDocumentFragment();
  // 범례는 이 표에 실제로 찍힌 강조만 말해야 한다 — marks(cellMarks 반환값)
  // 전체가 아니라, 아래 세 경로(caption·본문·접힌 열)가 셀에 실제로 붙인
  // 사유만 여기 모은다. 이유: buildAffiliateOverviewBlock처럼 원본
  // 레코드로 marks를 계산하되 열은 7개만 추려 보여주는 파생 표에서는,
  // marks에는 있지만 그 표에는 열 자체가 없는 규칙(예: 증감 평가손익)이
  // 있을 수 있다 — marks를 그대로 다 나열하면 "이 규칙도 강조됐다"고
  // 말하면서 정작 표에는 강조된 칸이 하나도 없는 모순이 생긴다.
  const appliedWhys = [];
  const seenWhys = new Set();
  function noteApplied(why) {
    if (!seenWhys.has(why)) { seenWhys.add(why); appliedWhys.push(why); }
  }

  if (Array.isArray(table.caption) && table.caption.length > 0) {
    const cap = document.createElement("div");
    cap.className = "cap";
    table.caption.forEach(function (c, i) {
      if (i > 0) cap.appendChild(document.createTextNode(" · "));
      const b = document.createElement("b");
      b.textContent = c.label;
      cap.appendChild(b);
      cap.appendChild(document.createTextNode(": "));
      // caption은 모든 행에서 값이 같아 표 밖으로 승격된 열이다 — 값은
      // 레코드 0번 것이므로 marks 조회도 행번호 0으로 고정한다("N|열키"
      // 좌표, cellMarks 주석 참고). 본문 셀만 처리하면 여기서 강조가
      // 조용히 사라진다(브리프가 지적한 함정).
      const capWhy = marks ? marks["0|" + c.key] : null;
      if (c.key === "rcept_no" && c.value) {
        const span = document.createElement("span");
        span.className = "doc";
        span.textContent = c.value;
        span.addEventListener("click", function () { openDocPanel(c.value); });
        // className을 이어 붙인다(덮어쓰면 위 "doc" 클릭 표시가 사라진다) —
        // 이 코드베이스는 classList를 쓰지 않는다(.doc·.cap·.derived 모두
        // className 대입, 아래 td도 같은 방식).
        if (capWhy) { span.className += " mk"; span.title = capWhy; noteApplied(capWhy); }
        cap.appendChild(span);
      } else if (capWhy) {
        noteApplied(capWhy);
        const span = document.createElement("span");
        span.className = "mk";
        span.title = capWhy;
        span.textContent = c.value;
        cap.appendChild(span);
      } else {
        cap.appendChild(document.createTextNode(c.value));
      }
    });
    frag.appendChild(cap);
  }

  const t = document.createElement("table");
  const isVertical = table.orientation === "vertical";
  // 접힌 열은 가로 표에만 있다(세로는 tableLayout이 애초에 접지 않는다 —
  // app.js 주석 참고). 행마다 접힌 열 수는 같으므로 표 전체에서 한 번만
  // 판단한다.
  const hasFolded = !isVertical && Array.isArray(table.foldedKeys) && table.foldedKeys.length > 0;
  if (!isVertical) {
    // 세로는 각 행이 이미 [라벨, 값]이라 별도 헤더가 필요 없다 — 헤더를
    // 넣으면 "항목/값"이 열 제목과 데이터 사이에 낀 군더더기가 된다.
    const thead = t.createTHead().insertRow();
    for (const c of table.columns) {
      const th = document.createElement("th");
      th.textContent = c;
      thead.appendChild(th);
    }
    if (hasFolded) {
      // 펼치기 버튼 칸의 헤더 — 내용은 없지만 칸 수를 표 본문과 맞춰야
      // 열이 밀리지 않는다.
      thead.appendChild(document.createElement("th"));
    }
  }
  const rceptCol = Array.isArray(table.keys) ? table.keys.indexOf("rcept_no") : -1;
  // SE-6 Task 3 — 임원 이름 클릭 → 우측 패널. "성명"은 normalizeRoster
  // (app.js)가 executive_roster에서만 실제로 만드는 리터럴 키다 — 다른
  // 어떤 DART 원본 필드도 이 한글 키를 쓰지 않는다("nm"이 label()로
  // "성명"이라 *보일* 뿐, table.keys 자체는 원본 키 그대로다). records가
  // 함께 넘어오지 않으면(다른 모든 섹션·renderCompanyInfo·doc-click
  // 하네스 등) 아무 일도 하지 않는다.
  const nameCol = Array.isArray(table.keys) ? table.keys.indexOf("성명") : -1;
  const tb = t.createTBody();
  table.rows.forEach(function (row, rowIdx) {
    const tr = tb.insertRow();
    row.forEach(function (v, i) {
      const td = tr.insertCell();
      td.textContent = v;
      // 세로: keys[rowIdx]가 이 행의 원본 키다 → 값은 두 번째 칸(i===1).
      // 가로: keys[i]가 이 칸의 원본 키다 → 값은 그 칸 자신(i===열 위치).
      const isValueCell = isVertical ? (i === 1) : true;
      const cellKey = isVertical ? table.keys[rowIdx] : table.keys[i];
      // 강조 좌표는 cellMarks(app.js)와 같은 형식이다: 세로는 레코드가
      // 하나라 행번호가 항상 0, 가로는 rowIdx가 곧 레코드 순번이다(rows가
      // tableLayout에서 records.map(...)으로 만들어져 순서가 그대로다).
      const markKey = (isVertical ? 0 : rowIdx) + "|" + cellKey;
      const why = marks && isValueCell ? marks[markKey] : null;
      // 억·조 단위로 줄인 값(td.textContent)만으로는 정확한 원 단위 금액을
      // 알 수 없다(예: 1,308,239,417 → "13.1억") — AMOUNT_FIELDS(app.js)
      // 열이면 tableLayout()이 나란히 남긴 raw(원본 값)를 title로 붙여
      // 마우스를 올리면 정확한 값을 볼 수 있게 한다. raw가 표시값과 같으면
      // (반올림 없는 작은 수 등) 군더더기 툴팁을 남기지 않는다.
      if (isValueCell && AMOUNT_FIELDS.has(cellKey) && Array.isArray(table.raw)) {
        const raw = isVertical ? table.raw[rowIdx] : table.raw[rowIdx][i];
        if (raw !== undefined && raw !== v) td.title = raw;
      }
      const isDocCell = isVertical
        ? (rowIdx === rceptCol && i === 1)
        : (i === rceptCol);
      if (isDocCell && v) {
        td.className = "doc";
        td.addEventListener("click", function () { openDocPanel(v); });
      }
      // SE-6 Task 3 리뷰 수정 — 세로 표(임원 1명뿐인 회사)도 클릭을
      // 배선한다. 처음엔 배선하지 않았으나, 이사회가 작은 회사·SPC성
      // 법인일수록 이 도구가 정확히 노리는 대상이라 "강조는 뜨는데
      // 경고·확인방법으로 가는 길이 없다"가 더 위험하다는 지적을 받아
      // 뒤집었다. 세로에서는 rowIdx가 곧 table.keys의 필드 순번이라
      // (tableLayout이 keys.map(...)으로 rows를 만든다) rowIdx===nameCol일
      // 때가 "성명" 필드 행이고, 값 칸은 i===1(isValueCell)이다. 레코드는
      // 항상 하나뿐이므로 records[0]을 쓴다(records[rowIdx]가 아니다 —
      // rowIdx는 여기서 필드 순번이지 레코드 순번이 아니다).
      const isNameCell = Array.isArray(records) && (isVertical
        ? (rowIdx === nameCol && i === 1 && records[0])
        : (i === nameCol && records[rowIdx]));
      if (isNameCell) {
        td.className = td.className ? (td.className + " exec-name") : "exec-name";
        const rec = isVertical ? records[0] : records[rowIdx];
        td.addEventListener("click", function () { openExecutivePanel(rec); });
      }
      // SE-8 Task 2 — 공시 목록 표만 report_nm(공시명)·flr_nm(공시제출인)
      // 열 폭을 개별화한다(task-2-brief 요구사항 A, index.html 실측 ②).
      // 전역 th,td{max-width:280px}는 모든 표·모든 열에 같은 상한을 걸어
      // 공시명(긴 텍스트)이 잘리고 제출인(짧은 이름) 칸은 남는 문제가
      // 있었다. report_nm·flr_nm은 disclosures 섹션에서만 실제로 쓰이는
      // 원본 키라(다른 어떤 표도 이 두 열을 갖지 않는다) tableEl()이
      // 키 이름만으로 셀에 클래스를 붙여도 다른 표 열 폭에 영향이 없다 —
      // 별도 "이 표는 disclosures인가"를 판별해 넘길 필요가 없다. 가로
      // 표에서만 의미가 있다(세로는 회사 1건이라 이미 [라벨,값] 두 칸뿐
      // 이고 잘림 문제 자체가 없다).
      if (!isVertical && cellKey === "report_nm") {
        td.className = td.className ? (td.className + " wide") : "wide";
      } else if (!isVertical && cellKey === "flr_nm") {
        td.className = td.className ? (td.className + " narrow") : "narrow";
      }
      // 강조 사유는 원본 값 툴팁 다음에 붙인다(순서가 반대면 아래 줄이
      // 위 raw 툴팁을 덮어써 왜 강조됐는지가 사라진다 — affiliates 3개
      // 규칙 열이 전부 AMOUNT_FIELDS라 실제로 겹친다). className은 이어
      // 붙인다(대입하면 위 "doc" 클릭 표시가 지워진다) — 이 코드베이스는
      // classList를 쓰지 않는다(.doc·.cap·.derived 모두 className 대입).
      if (why) {
        td.className = td.className ? (td.className + " mk") : "mk";
        td.title = td.title ? (td.title + " · " + why) : why;
        noteApplied(why);
      }
    });

    if (hasFolded) {
      // 펼치기 버튼 — 이 행의 접힌 열을 세로(라벨: 값)로 보여준다. 없애는
      // 게 아니라 접는 것이므로, 클릭하면 언제든 원래 값을 볼 수 있어야
      // 한다(브리프 원칙).
      const btnCell = tr.insertCell();
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "fold-btn";
      btn.textContent = "나머지 " + table.foldedKeys.length + "개 열";
      btnCell.appendChild(btn);

      // 상세 행은 항상 만들어 두고(위치가 이 행 바로 다음으로 고정된다)
      // hidden 속성으로만 여닫는다 — 클릭 시점에 특정 위치에 행을
      // 끼워넣으려 하면(tbody는 append만 지원) 이미 그려진 다음 행들
      // 뒤로 밀려나 버린다.
      const detailTr = tb.insertRow();
      detailTr.className = "fold-detail";
      detailTr.hidden = true;
      const detailTd = detailTr.insertCell();
      detailTd.colSpan = table.columns.length + 1;
      const foldedForRow = (Array.isArray(table.foldedRows) && table.foldedRows[rowIdx]) || [];
      // innerHTML을 쓰지 않는다 — 공시 원문·실명이 그대로 섞여 들어오는
      // 값이라 textContent로만 채운다(각 [라벨, 값] 쌍을 별도 엘리먼트로
      // 만들고 <br>로 줄바꿈한다).
      foldedForRow.forEach(function (pair, idx) {
        if (idx > 0) detailTd.appendChild(document.createElement("br"));
        const b = document.createElement("b");
        b.textContent = pair[0];
        detailTd.appendChild(b);
        // 접힌 열도 본문 셀과 같은 좌표계다 — 세로는 애초에 접지 않으므로
        // (tableLayout 주석 참고) 여기 도달하는 표는 항상 가로이고, 행번호는
        // rowIdx 그대로다. table.foldedKeys[idx]가 이 쌍이 어느 원본 열인지
        // 알려준다(foldedRows가 foldedKeys와 같은 순서로 만들어졌다 — app.js
        // tableLayout 참고).
        const foldKey = Array.isArray(table.foldedKeys) ? table.foldedKeys[idx] : undefined;
        const foldWhy = marks && foldKey !== undefined ? marks[rowIdx + "|" + foldKey] : null;
        if (foldWhy) {
          noteApplied(foldWhy);
          detailTd.appendChild(document.createTextNode(": "));
          const span = document.createElement("span");
          span.className = "mk";
          span.title = foldWhy;
          span.textContent = pair[1];
          detailTd.appendChild(span);
        } else {
          detailTd.appendChild(document.createTextNode(": " + pair[1]));
        }
      });

      btn.addEventListener("click", function () {
        detailTr.hidden = !detailTr.hidden;
      });
    }
  });
  frag.appendChild(t);

  // 범례 — 위 세 경로(caption·본문·접힌 열)가 실제로 셀에 붙인 사유만,
  // 중복 없이 한 줄로(appliedWhys, 등장 순서 그대로 — 사실을 나열하는
  // 목록이지 우선순위 순위가 아니라 MARK_RULES 선언 순서로 다시 정렬하지
  // 않는다). marks를 그대로 다 쓰지 않는 이유는 위 appliedWhys 선언부
  // 주석 참고 — 파생 표처럼 열 자체가 없는 규칙까지 "강조됐다"고 말하면
  // 안 된다. 발화한 규칙이 없으면 아무것도 만들지 않는다 — 빈 줄을
  // 남기면 "여기 강조할 게 있었는데 없다"는 착각을 준다.
  if (appliedWhys.length > 0) {
    const legend = document.createElement("div");
    legend.className = "mk-legend";
    const b = document.createElement("b");
    b.textContent = "강조: ";
    legend.appendChild(b);
    // textContent만 쓴다 — 문구가 MARK_RULES(app.js)의 고정 문자열뿐이라
    // 실명·공시 원문이 섞일 자리는 아니지만, 이 파일 어디서도 데이터를
    // innerHTML로 넣지 않는다는 규칙을 여기서도 그대로 지킨다.
    legend.appendChild(document.createTextNode(appliedWhys.join(" · ")));
    frag.appendChild(legend);
  }

  return frag;
}

/** 그룹 제목에 해당하는 컨테이너를 찾거나 만든다. SECTION_GROUPS 정의
 *  순서를 따라 DOM 위치를 정한다 — 그룹은 섹션이 도착하는 순서(=완료
 *  순서)와 무관하게 항상 같은 자리에 나와야 한다. 목록에 없는 제목
 *  ("기타" 등, groupOrderIndex가 맨 뒤로 보낸다)은 이미 자리 잡은
 *  그룹들 뒤에 붙는다.
 *
 *  반환하는 holder는 sectionHolder()가 이 그룹의 .sec들을 appendChild
 *  하는 중간 컨테이너다 — id를 고정해 두 번째 호출부터는 기존 노드를
 *  재사용한다(제목 → 노드 조회용 앵커). class="grp-holder"를 붙이는
 *  이유: index.html의 `.grp,.grp-holder{display:contents}`가 이 박스를
 *  없애야 .sec이 #body 그리드의 직속 아이템이 된다 — 안 그러면 .sec은
 *  이 holder 안의 평범한 블록 자식일 뿐이라 그리드 아이템이 아니게
 *  되고, .sec.wide{grid-column:1/-1}이 완전히 무효화된다(실측 확인된
 *  회귀 — wide 표가 그리드 1칸 폭으로 도로 좁아졌다). */
function groupHolder(title) {
  const id = "grp-" + title;
  let holder = document.getElementById(id);
  if (holder) return holder;

  const wrap = document.createElement("section");
  wrap.className = "grp";
  wrap.dataset.title = title;
  const h1 = document.createElement("h1");
  h1.textContent = title;
  wrap.appendChild(h1);

  holder = document.createElement("div");
  holder.id = id;
  holder.className = "grp-holder";
  wrap.appendChild(holder);

  const body = document.getElementById("body");
  const idx = groupOrderIndex(title);
  let before = null;
  for (const child of body.children) {
    if (groupOrderIndex(child.dataset.title) > idx) { before = child; break; }
  }
  body.insertBefore(wrap, before);
  addTocEntry(title, wrap, false, idx);
  return holder;
}

/** 섹션 키에 해당하는 표시 영역을 찾거나 만든다.
 *
 * id를 키로 고정해두면 renderSection이 같은 키로 여러 번 불려도(폴링마다
 * 그럴 수 있다) 매번 같은 노드를 돌려준다 — 새 노드를 계속 추가하면
 * 화면에 같은 섹션이 쌓인다. h2 제목은 한 번만 만들고, 내용만 담는
 * 자식(holder)을 별도로 둬서 제목까지 지웠다 다시 만들지 않는다.
 *
 * 자기 그룹(groupTitleFor) 아래에 붙인다 — SECTION_GROUPS를 실제로
 * 쓰지 않으면 그룹 제목도 순서도 화면에 나오지 않는다. */
// 섹션 키 → 감싸는 .sec 엘리먼트. renderSection이 표 orientation을 보고
// "wide" 클래스를 붙였다 뗐다 할 때 이 wrap을 찾는 데 쓴다 — holder(내용
// 칸)는 매 렌더마다 비워지고 다시 채워지지만 wrap(h2를 포함한 바깥
// 칸)은 sectionHolder가 처음 만들 때 한 번만 생기므로 별도로 기억해
// 둬야 한다(parentNode를 쓰지 않는 이유: 이 파일은 parentNode를 구현하지
// 않는 가짜 DOM으로도 실행된다 — 위 TOC_ITEMS 주석 참고).
const SEC_WRAP = Object.create(null);

// doc:<접수번호> 섹션이 도착할 때마다(폴링마다 하나씩) 쌓이는 목록 행.
// 한 회사 분석 안에서만 유효한 지역 상태라 resetToc()가 SEC_WRAP과
// 함께 비운다 — 안 그러면 새 회사를 분석하거나 로그아웃 후 다른
// 사용자가 로그인해도 이전 회사의 공시 목록 행이 새 목록에 이어 붙는다
// (showGate()가 실명·본문을 정리하는 것과 같은 이유, addDocListEntry 참고).
let DOC_LIST_ROWS = [];

function sectionHolder(key) {
  const id = "sec-" + key;
  let holder = document.getElementById(id);
  if (holder) return holder;

  const groupTitle = groupTitleFor(key);
  const group = groupHolder(groupTitle);

  const wrap = document.createElement("div");
  wrap.className = "sec";
  const h2 = document.createElement("h2");
  // label()이 아는 키만 한국어로 바뀐다 — 없으면 원본 키 그대로다
  // (app.js의 label() 계약: 라벨이 없다고 숨기지 않는다).
  h2.textContent = label(key);
  wrap.appendChild(h2);

  holder = document.createElement("div");
  holder.id = id;
  wrap.appendChild(holder);

  group.appendChild(wrap);
  SEC_WRAP[key] = wrap;
  // 자기 그룹과 같은 order를 써야 목차에서 그룹 항목 바로 뒤(같은 order
  // 블록 안)에 붙는다 — addTocEntry 주석 참고.
  addTocEntry(label(key), wrap, true, groupOrderIndex(groupTitle));
  return holder;
}

/** 블록 하나(소제목 + 표, 또는 소제목 + 원문 텍스트)를 DOM으로 만든다.
 *  `marks`(선택 인자)는 그대로 tableEl에 넘긴다 — cellMarks(records,
 *  sectionKey)의 반환값이다(호출부인 renderSection이 block.records로
 *  계산한다, block 자신은 자기 sectionKey를 모른다).
 *  `records`(선택 인자, SE-6 Task 3)도 그대로 tableEl에 넘긴다 — 임원
 *  이름 클릭 배선(tableEl의 isNameCell)에만 쓰이고, "성명" 열이 없는
 *  표에서는 tableEl이 아무 일도 하지 않는다. */
function blockEl(block, marks, records) {
  const wrap = document.createElement("div");
  if (block.title) {
    const h3 = document.createElement("h3");
    h3.textContent = block.title;
    wrap.appendChild(h3);
  }
  // SE-9 Task 3(3a) — task-6(SE-4f)의 "표는 지우지 않는다" 결정을
  // 뒤집었다(app.js의 sourceGroupedBlocks 3a 주석 참고). 예전에는 표가
  // 항상 있었으므로 note가 있어도 table/text와 배타적이지 않게 항상
  // 먼저 보여주면 됐지만, 이제 meta-only·전 행 패딩 그룹은 block.table이
  // null이면서 block.note만 있는 모양으로 온다(sourceGroupedBlocks의
  // metaOnlyNote 분기) — 이 경우 아래 표/텍스트 분기가 falsy로 떨어져
  // "표시할 데이터가 없습니다."까지 덧붙이면 같은 뜻의 문구가 두 번
  // 나온다(note가 이미 몇 건을 확인했는지까지 구체적으로 말하는데, 그
  // 아래 일반 "데이터가 없다" 문구가 그 정보를 다시 뭉갠다). 그래서
  // hasNote를 계산해 마지막 fallback 분기에서만 note 유무를 확인한다.
  const hasNote = typeof block.note === "string" && block.note;
  if (hasNote) {
    const note = document.createElement("p");
    note.className = "note";
    note.textContent = block.note;
    wrap.appendChild(note);
  }
  if (block.table) {
    wrap.appendChild(tableEl(block.table, marks, records));
  } else if (typeof block.text === "string") {
    // 표 셀(max-width:280px)에 욱여넣기엔 너무 긴 문자열 — 별도 문단으로
    // 그대로 보여준다. textContent만 쓴다.
    const p = document.createElement("p");
    p.textContent = block.text;
    wrap.appendChild(p);
  } else if (!hasNote) {
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = "표시할 데이터가 없습니다.";
    wrap.appendChild(p);
  }
  return wrap;
}

/** financialRatios(app.js)가 만든 한 행의 계산식(row.계산식)에서 재료
 *  이름을 실제 값으로 치환한다 — "영업이익 ÷ 매출액"이 "영업이익
 *  -783.9억 ÷ 매출액 3,127.9억"이 된다(브리프 예시와 같은 형태). 값이
 *  null인 재료는 "이름 없음"으로 바꿔 어느 재료가 빠졌는지 그대로
 *  드러낸다 — 조용히 숨기지 않는다.
 *
 *  재료 이름(영업이익·매출액·부채총계·자본총계·유동자산·유동부채·자본금)은
 *  서로의 부분 문자열이 아니므로(app.js RATIO_DEFS·computeCapitalImpairment
 *  참고) split/join 치환이 서로 다른 재료를 잘못 건드릴 위험이 없다. */
function ratioBasisText(row) {
  let basis = row.계산식 || "";
  const materials = row.재료 || {};
  for (const name of Object.keys(materials)) {
    const v = materials[name];
    const shown = v === null ? (name + " 없음") : (name + " " + formatAmount(v));
    basis = basis.split(name).join(shown);
  }
  return basis;
}

/** financials 섹션에서만 쓰는 파생 지표(계산값) 블록을 만든다.
 *  financialRatios(app.js)가 만든 구분·기간·지표·값·계산식·재료·사유
 *  레코드를 연도별 표(계산식+재료를 문장으로 풀어서)로 그리고, CHART_SPECS.
 *  financial_ratios로 3기간(전전기→전기→당기, 보통 실제 연도) 추이도
 *  함께 그린다.
 *
 *  **공시 원본과 반드시 구분한다**(SE-4f 판정선: "공시 원본 숫자와 우리
 *  계산값이 구분되지 않으면 그것도 거짓말이다") — class="derived"로
 *  시각적으로도 나누고(index.html), "DART 공시 수치로 계산한 값"이라고
 *  문구로도 밝힌다.
 *
 *  값이 없는 지표도 조용히 빼지 않는다 — 값 칸에 그 행의 사유(row.사유,
 *  예: "매출액 없음"·"잠식 없음")를 그대로 보여준다.
 *
 *  **SE-10 Task 1: 표를 기간(보통 실제 연도)별로 나눈다** —
 *  financialRatiosByYear(app.js)가 dividendPeriodBlocks와 같은
 *  Map+groupOrder 메커니즘으로 묶어 준 그룹마다 소제목(h3, "2025년" 등)과
 *  표를 하나씩 만든다. 그룹 제목이 이미 그 정보를 말하므로 표 안에서는
 *  `기간` 열을 지운다(그룹 제목으로 승격된 정보는 행에서 제거하는 원칙,
 *  SE-9 Task 4 dividendPeriodBlocks와 동일) — 그룹 안에서는 구분(연결/별도)
 *  만 행의 첫 열로 남긴다(연결/별도를 또 표로 쪼개지 않는다는 결정,
 *  task-1-brief.md).
 *
 *  **강조(marks) 좌표는 표마다 새로 계산한다.** cellMarks(app.js)가 쓰는
 *  "행번호|열키" 좌표(app.js cellMarks 주석)의 행번호는 **그 표 안에서의**
 *  행 순서다(tableEl이 table.rows.forEach의 rowIdx를 그대로 쓴다) — 표를
 *  연도별로 나눈 뒤에도 원본 ratios 배열 전체 기준 인덱스를 그대로 쓰면
 *  강조가 엉뚱한 행(다른 연도, 다른 구분)에 붙는다. 그래서 cellMarks를
 *  yb.ratios(그 연도 그룹의 원본 부분 배열, 표시용으로 문자열화하기 전)로
 *  매번 다시 부른다 — 그 표의 행 순서와 정확히 같은 순서이므로 좌표가
 *  어긋나지 않는다.
 *
 *  차트에는 financialRatios가 돌려준 원본 레코드 전체(ratios, 값이
 *  숫자|null인 그대로, 연도별로 나누지 않은 것)를 넘긴다 — 표시용으로
 *  문자열화한 records를 넘기면 chartData(app.js)가 숫자를 못 읽어 그려지지
 *  않고, 그룹별로 쪼개 넘기면 그룹당 x축 점이 하나뿐이라 "연도별 추이"
 *  자체가 성립하지 않는다(dividendPeriodBlocks 주석과 같은 이유 — "차트
 *  입력을 바꾸지 않는다"). */
function buildFinancialRatiosBlock(ratios) {
  const wrap = document.createElement("div");
  wrap.className = "derived";

  const h3 = document.createElement("h3");
  h3.textContent = "재무 파생 지표 (계산값)";
  wrap.appendChild(h3);

  const notice = document.createElement("p");
  notice.className = "note";
  notice.textContent = "DART 공시 수치로 계산한 값입니다 — 공시 원본이 아닙니다. "
    + "연결과 별도를 섞지 않고 계산식과 재료 값을 함께 표시합니다.";
  wrap.appendChild(notice);

  // SE-8 Task 4: 열 순서는 지표→값→구분→계산식·재료다(기간은 SE-10부터
  // 그룹 제목으로 승격돼 행에서 빠진다, 위 함수 주석) — 실사용자가 이
  // 표를 지적했다("표를 구성할 때 이용자에게 어떤 정보가 유용할지 고민부터
  // 하고 배치를 해야한다"). tableLayout(app.js)이 각 레코드의 키 등장
  // 순서를 그대로 표 헤더로 쓰므로(Object.keys 기반) 여기서 만드는 객체의
  // 키 순서가 곧 화면 순서다. 구분은 지우지 않는다 — 위치만 옮길 뿐, 각
  // 값 옆에 그대로 남아 있다(SE-4f: 연결·별도를 섞으면 거짓이 된다).
  let firstTable = null;
  for (const yb of financialRatiosByYear(ratios)) {
    const yh3 = document.createElement("h3");
    yh3.textContent = yb.title;
    wrap.appendChild(yh3);

    const records = yb.ratios.map(function (r) {
      return {
        지표: r.지표,
        값: r.값 === null ? r.사유 : (r.값.toFixed(1) + "%"),
        구분: r.구분,
        "계산식·재료": ratioBasisText(r),
      };
    });
    // cellMarks는 이 연도 그룹의 원본 ratios(값이 숫자|null)로 계산한다 —
    // 위 records는 표시용으로 "%"를 붙여 문자열화해서, 거기다 markNeg를
    // 돌리면 숫자 파싱이 깨진다(app.js markNumber는 "%"를 걷어내지
    // 않는다). records가 yb.ratios.map(...)으로 만들어져 순서가 같으므로
    // 행번호(rowIdx)는 그대로 맞는다 — sectionKey는 renderSection이 받는
    // "financials"가 아니라 이 파생 표 전용 키 "financial_ratios"다
    // (MARK_RULES.financial_ratios 참고, 다른 어떤 호출부도 이 sectionKey로
    // cellMarks를 부르지 않는다). 강조가 붙은 열은 접지 않는다(app.js
    // splitVisibleFolded 주석) — 이 표는 4열뿐이라 오늘은 접힐 일이
    // 없지만, 열이 늘어도 강조가 버튼 뒤로 숨지 않도록 renderSection의
    // relayoutForMarks와 같은 계약을 여기서도 지킨다.
    const yearMarks = cellMarks(yb.ratios, "financial_ratios");
    const table = tableLayout(records, markedColumnKeys(yearMarks));
    if (table) {
      wrap.appendChild(tableEl(table, yearMarks));
      if (!firstTable) firstTable = table;
    }
  }

  renderChart(wrap, "financial_ratios", ratios, SIGNALS_DATA);
  return { el: wrap, table: firstTable };
}

/** "%" 항목만 뒤에 "%"를 붙이고, 그 밖의 백만원 단위 값은 천 단위
 *  구분자로 사람이 읽기 쉽게 만든다. null(값 자체가 없음)은 빈 문자열 —
 *  0으로 채우지 않는다(numeric() 주석과 같은 원칙, formatValue와 달리
 *  이 값들은 이미 백만원 단위라 억·조로 다시 줄이면 오히려 헷갈린다). */
function formatDividendSeValue(se, value) {
  if (value === null || value === undefined) return "";
  if (se.indexOf("(%)") !== -1) return value + "%";
  return value.toLocaleString("ko-KR");
}

/** dividendVsIncome(app.js)이 뽑은 "배당 vs 당기순이익" 사실 비교를
 *  표로 그린다(SE-4f Task 4).
 *
 *  **공시 원본과 반드시 구분한다**(buildFinancialRatiosBlock과 같은
 *  이유) — class="derived"로 시각적으로 나누고, 이 값이 dividends 원본
 *  se 항목을 그대로 나란히 놓은 것일 뿐 새로 계산하거나 판정한 게
 *  아니라고 문구로도 밝힌다(판정선: "배당 여력 부족" 같은 해석은 쓰지
 *  않는다). */
function buildDividendVsIncomeBlock(rows) {
  const wrap = document.createElement("div");
  wrap.className = "derived";

  const h3 = document.createElement("h3");
  h3.textContent = "배당 vs 당기순이익 (사실 비교)";
  wrap.appendChild(h3);

  const notice = document.createElement("p");
  notice.className = "note";
  notice.textContent = "DART 배당(dividends) 공시의 항목(se) 중 이미 같은 백만원 단위로 "
    + "들어있는 현금배당금총액과 당기순이익을 보고 시점(사업연도·보고서구분)별로 "
    + "나란히 보여줍니다 — 공시 원본 항목 두 개를 나란히 놓은 것일 뿐 새로 계산하거나 "
    + "판정한 값이 아닙니다.";
  wrap.appendChild(notice);

  const records = rows.map(function (r) {
    const out = { bsns_year: r.bsns_year, reprt_code: r.reprt_code };
    for (const se of DIVIDEND_SE_FIELDS) out[se] = formatDividendSeValue(se, r[se]);
    return out;
  });
  const table = tableLayout(records);
  if (table) wrap.appendChild(tableEl(table));

  return { el: wrap, table: table };
}

// dividendDrainFlags(app.js)의 fs_div → 화면 라벨. CFS는 위 app.js
// DIVIDEND_DRAIN_NI_SE 주석·core detect_dividend_drain 주석과 동일한 이유로
// "연결·지배지분 기준"까지 명시한다(그냥 FS_DIV_LABELS.CFS="연결"을 쓰면
// 이 값이 회사 전체 연결당기순이익이라는 오독을 유발한다) — 가운데점은
// server.py 렌더(track_fund_usage)가 중첩 괄호를 피하려고 고른 것과 같은
// 표기(task-1-report.md "처음엔 label = '연결(지배지분 기준)'으로 시도했으나
// ... 가운데점으로 교체"). OFS(별도)는 이 개념이 없어 FS_DIV_LABELS와 같다.
const DIVIDEND_DRAIN_LABELS = { CFS: "연결·지배지분 기준", OFS: "별도" };

/** dividendDrainFlags(app.js)가 뽑은 "당기순이익 음수 + 현금배당 존재"
 *  사실을 표로 그린다(SE-12 Task 2, 요구사항 A).
 *
 *  core MCP 도구(track_fund_usage)와 같은 사실을 담지만 어투는 다르다 —
 *  core는 자유 텍스트 응답이라 "자금 유출 경로 검토 권장" 같은 권고 문구가
 *  허용되지만, SE는 무판정 원칙(v0.8.5)의 표 화면이라 "위험"·"유출" 같은
 *  해석 없이 사실만("당기순이익 음수 + 현금배당 존재") 말한다(브리프,
 *  SE-8 "보고된 집행 ≠ 계획"과 같은 톤). */
function buildDividendDrainBlock(flags) {
  const wrap = document.createElement("div");
  wrap.className = "derived";

  const h3 = document.createElement("h3");
  h3.textContent = "적자 시점 배당 (사실 표기)";
  wrap.appendChild(h3);

  const notice = document.createElement("p");
  notice.className = "note";
  notice.textContent = "같은 사업연도·보고서구분 안에서 당기순이익이 음수인데 현금배당이 "
    + "있었던 사실만 나열합니다 — 연결과 별도는 따로 봅니다. 연결(CFS) 당기순이익은 "
    + "배당 공시(alotMatter)가 원래 담고 있는 지배기업소유주지분순이익(비지배지분 제외분)이며, "
    + "회사 전체 연결당기순이익과 다를 수 있어 \"연결·지배지분 기준\"으로 표기합니다. "
    + "별도(OFS)는 비지배지분 개념이 없어 해당하지 않습니다.";
  wrap.appendChild(notice);

  const records = flags.map(function (f) {
    const 구분 = DIVIDEND_DRAIN_LABELS[f.fs_div] || f.fs_div;
    return {
      bsns_year: f.bsns_year,
      reprt_code: f.reprt_code,
      "구분": 구분,
      "당기순이익(백만원)": f.net_income.toLocaleString("ko-KR"),
      "현금배당금총액(백만원)": f.dividend.toLocaleString("ko-KR"),
      "사실": "이 사업연도 (" + 구분 + ") 당기순이익 음수 + 현금배당 존재",
    };
  });
  const table = tableLayout(records);
  if (table) wrap.appendChild(tableEl(table));

  return { el: wrap, table: table };
}

/** dividendVsRetainedEarnings(app.js)가 뽑은 "이번 사업연도 배당 vs
 *  이익잉여금"을 표로 그린다(SE-12 Task 2, 요구사항 B).
 *
 *  **단일 연도 비교임을 화면 문구에 정직하게 반영한다** — financials가
 *  단일 최근 사업연도만 수집하는 SE의 구조적 한계를 숨기지 않는다(브리프).
 *  "추이"라는 말은 쓰지 않는다. */
function buildDividendVsRetainedEarningsBlock(result) {
  const wrap = document.createElement("div");
  wrap.className = "derived";

  const h3 = document.createElement("h3");
  h3.textContent = "배당 vs 이익잉여금 (이번 사업연도)";
  wrap.appendChild(h3);

  const notice = document.createElement("p");
  notice.className = "note";
  notice.textContent = "financials(재무제표) 섹션은 최근 사업연도 하나만 수집합니다 — "
    + "그래서 이 비교는 여러 해를 이어 보는 것이 아니라 이번 사업연도 한 시점만의 "
    + "사실 병기입니다. 연결(CFS)과 별도(OFS)는 따로 봅니다. 이익잉여금은 재무제표 "
    + "원본 단위(원) 그대로, 현금배당금총액은 배당 공시 원본(백만원)을 원 단위로 "
    + "환산해 나란히 놓았습니다.";
  wrap.appendChild(notice);

  if (!result.overlap) {
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = "이번 사업연도(" + result.bsns_year + ") 배당 기록 없음 — 배당 공시에 "
      + "이 사업연도와 일치하는 현금배당금총액이 없어 억지로 비교하지 않습니다.";
    wrap.appendChild(p);
  }

  const record = { bsns_year: result.bsns_year };
  record["이익잉여금(연결, 원)"] = result.retained_earnings.CFS === null
    ? "" : formatAmount(result.retained_earnings.CFS);
  record["이익잉여금(별도, 원)"] = result.retained_earnings.OFS === null
    ? "" : formatAmount(result.retained_earnings.OFS);
  record["현금배당금총액(원)"] = result.overlap ? formatAmount(result.dividend_won) : "배당 기록 없음";

  const table = tableLayout([record]);
  if (table) wrap.appendChild(tableEl(table));

  return { el: wrap, table: table };
}

/** fundPlanChanges(app.js)가 뽑은 "계획 금액이 보고 시점마다 다르게
 *  보고된 조달 건" 목록을 표로 그린다(SE-4f Task 7).
 *
 *  amounts는 등장한 서로 다른 값들이지 "이전값→이후값" 순서가 아니다
 *  (reprt_code가 core 정규화 과정에서 탈락해 어느 보고가 먼저인지 이
 *  레벨에서 알 수 없다, 위 fundPlanChanges 주석 참고) — 그래서 "→"
 *  같은 방향 표시 없이 " / "로 나열만 한다. 판정선: "용도 변경 의심"
 *  같은 해석은 쓰지 않는다 — 서로 다른 값이 보고됐다는 사실만 말한다. */
function buildFundPlanChangeBlock(changes) {
  const wrap = document.createElement("div");
  wrap.className = "derived";

  const h3 = document.createElement("h3");
  h3.textContent = "계획 금액 변경 (사실 표기)";
  wrap.appendChild(h3);

  const notice = document.createElement("p");
  notice.className = "note";
  notice.textContent = "같은 자금 납입일·계획 용도인데 계획 금액이 서로 다른 값으로 "
    + "보고된 조달 건입니다. 어느 보고가 먼저인지는 원본 데이터(reprt_code)가 "
    + "남아있지 않아 표시하지 않습니다 — 서로 다른 값이 보고된 적이 있다는 "
    + "사실만 보여줍니다.";
  wrap.appendChild(notice);

  const records = changes.map(function (c) {
    return {
      pay_de: c.pay_de,
      plan_useprps: c.plan_useprps,
      kind: c.kind,
      "보고된 계획 금액": c.amounts.map(formatAmount).join(" / "),
    };
  });
  const table = tableLayout(records);
  if (table) wrap.appendChild(tableEl(table));

  return { el: wrap, table: table };
}

// fundChainDisclosureHints(app.js, SE-5a Task 2)의 기본 조회 창과 같은
// 값이다 — 여기서 다시 선언하는 이유는 화면 문구("납입일 이전 90일 이내")가
// 실제로 힌트를 만들 때 쓴 값과 어긋나지 않게 하기 위해서다(문구와 계산이
// 서로 다른 상수를 쓰면, 창을 나중에 조정할 때 한쪽만 고치고 잊는 사고가
// 난다). fundChainDisclosureHints(chain, disclosures, signalsData, windowDays)
// 호출부(아래 renderSection)가 이 상수를 그대로 인자로 넘긴다.
const FUND_CHAIN_WINDOW_DAYS = 90;

/** fundChain(app.js, Task 1) 결과 조달건 하나를 카드로 그린다(SE-5a
 *  Task 3, task-3-brief.md).
 *
 *  **왜 Chart.js가 아니라 CSS flexbox 비례 막대인가**: 이 표현은 "한
 *  조달건의 계획 금액을 용도별로 나눈 비율"이다 — 축도 시간도 없다.
 *  flexbox 막대면 (a) 라벨이 실제 텍스트 노드라 선택·복사가 되고
 *  (canvas는 그림일 뿐이라 안 된다), (b) canvas destroy 관리
 *  (CHART_INSTANCES/pruneChartsIn, resetCharts)가 필요 없고, (c)
 *  다크·라이트 전환이 --fund-bar-*(index.html) 두 값만으로 자동
 *  처리된다. 막대 조각의 배경은 여기서 --c0~--c9(index.html, "차트 계열
 *  구분 전용 색 10종… 판정 색이 아니다")를 재사용한다 — 이 카드도 용도
 *  구분일 뿐 판정이 아니므로 같은 색 계열을 쓰는 것이 자연스럽다.
 *
 *  막대 폭은 plan/total_plan이다. 아주 좁은 조각(실측: 130.8억/7,682.4억
 *  = 1.7%)은 라벨이 잘려 안 보일 수 있는데, 폭 자체를 부풀리지 않는다 —
 *  대신 바로 아래 표(전 용도 행)가 항상 같이 붙어 있어 막대에서 사라진
 *  정보가 표에는 반드시 남는다(브리프 요구사항). 라벨이 넘치면 CSS
 *  overflow:hidden이 자연스럽게 자른다 — JS가 "이 라벨은 숨긴다"를
 *  판단하지 않는다(판단할수록 임계값이 생긴다, v0.8.5).
 */
function fundChainCardEl(entry, hints, windowDays) {
  const card = document.createElement("div");
  card.className = "fund-chain-card";

  const h4 = document.createElement("h4");
  h4.textContent = (entry.pay_de === null ? "납입일이 공시되지 않은 내역" : entry.pay_de)
    + " 조달 · 계획 합계 " + formatAmount(entry.total_plan);
  card.appendChild(h4);

  // total_plan이 0이면 분모가 0이라 폭 계산이 NaN%가 된다 — 막대 자체를
  // 그리지 않는다(브리프 "0으로 나누지 마라"). 계획 합계가 0이라는 사실은
  // 위 h4가 이미 말하고 있어 사라지지 않는다.
  if (entry.total_plan > 0) {
    const bar = document.createElement("div");
    bar.className = "fund-bar";
    entry.uses.forEach(function (u, i) {
      const seg = document.createElement("span");
      seg.className = "fund-bar-seg";
      const label = u.purpose === null ? "(용도 미기재)" : u.purpose;
      const pct = (u.plan / entry.total_plan) * 100;
      seg.style.flexBasis = pct + "%";
      seg.style.backgroundColor = "var(--c" + (i % 9) + ")";
      seg.textContent = label;
      seg.title = label + " · " + formatAmount(u.plan);
      bar.appendChild(seg);
    });
    card.appendChild(bar);
  }

  // 표 — 막대에서 좁아 안 보이는 라벨도 여기서는 항상 읽힌다. 열 키는
  // entry.uses의 원본 필드명(purpose/plan/real/diff_reason, app.js LABELS
  // 주석 참고)을 그대로 쓴다 — 한글 문자열이 아니다. cellMarks(아래)가
  // 계산하는 강조 좌표는 "행번호|열키" 형식이고, 그 열키는 tableLayout에
  // 넘긴 레코드의 property 이름 그 자체다(affiliates 표와 같은 관례,
  // buildAffiliateOverviewBlock 주석 참고) — 한글로 바꿔 넘기면 좌표가
  // 어긋나 강조가 조용히 사라진다. 화면에 보이는 헤더 문구는 그대로다
  // (LABELS.purpose 등이 "용도" 등을 낸다).
  const rows = entry.uses.map(function (u) {
    return {
      purpose: u.purpose === null ? "(용도 미기재)" : u.purpose,
      plan: formatAmount(u.plan),
      real: u.real === null ? "—" : formatAmount(u.real),
      diff_reason: u.diff_reason === null ? "—" : u.diff_reason,
    };
  });
  // SE-8 Task 8B — plan(계획)과 real(보고된 집행)이 DART 원본 두 값에서
  // 그대로 다르면 강조한다(MARK_RULES.fund_chain, app.js). cellMarks는
  // rows(이미 formatAmount를 거친 문자열)가 아니라 entry.uses(원본 숫자
  // 필드)를 받는다 — 표시용 문자열로는 markNeq의 숫자 비교를 할 수 없다
  // (affiliates와 같은 이유, cellMarks는 "표가 실제로 그린 레코드"의
  // 원본을 받는 관례). rows와 entry.uses는 map()으로 만들어져 순서가
  // 같으므로 cellMarks의 행번호 좌표가 그대로 rows에도 맞는다.
  const marks = cellMarks(entry.uses, "fund_chain");
  const table = tableLayout(rows, markedColumnKeys(marks));
  if (table) card.appendChild(tableEl(table, marks));

  // 반복 보고 — (납입일,용도) 조합이 여러 보고서에서 되풀이돼 fundChain이
  // 한 건만 남긴 사실을 숨기지 않는다(브리프: "우리가 골라 버린 것이
  // 있음을 숨기지 않는다"). entry.row_count(원본 행 수)가 uses.length
  // (남긴 용도 수)보다 많으면 어딘가에서 접힌 것이다.
  if (entry.row_count > entry.uses.length) {
    const repeated = entry.uses.filter(function (u) { return u.rows > 1; });
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = "이 조달건은 원본 " + entry.row_count + "건의 보고에서 용도별로 "
      + "한 건씩(" + entry.uses.length + "건)만 남겼습니다 — 같은 금액이 여러 "
      + "보고서에 반복 보고됐기 때문입니다"
      + (repeated.length > 0
        ? "(" + repeated.map(function (u) {
            return (u.purpose === null ? "(용도 미기재)" : u.purpose) + " " + u.rows + "회";
          }).join(", ") + ")."
        : ".");
    card.appendChild(p);
  }

  // 조달 공시 근접 힌트(Task 2) — hints[sort_key]가 undefined인지로
  // 판정한다(length===0이 아니라). fundChainDisclosureHints는 히트가 없는
  // 조달건을 아예 담지 않는 희소 맵을 돌려준다(브리프 인터페이스 절, 이
  // 파일의 cellMarks 관례와 같다) — sort_key가 null인(납입일 미공시)
  // 묶음은 애초에 이 맵에 없다. **조인이 아니다** — 화면에도 그 불확실성을
  // 지우지 않는다: 창 크기(windowDays)를 반드시 문구에 적고, 여러 건이면
  // 하나로 좁히지 않고 전부 나열한다(fundChainDisclosureHints 주석 참고).
  const hits = (entry.sort_key !== null && hints) ? hints[entry.sort_key] : undefined;
  if (hits !== undefined && hits.length > 0) {
    const hp = document.createElement("p");
    hp.className = "note";
    hp.textContent = "납입일 이전 " + windowDays + "일 이내 조달 공시 "
      + hits.length + "건 · 클릭하면 원문";
    card.appendChild(hp);

    const ul = document.createElement("ul");
    ul.className = "fund-hint-list";
    hits.forEach(function (h) {
      const li = document.createElement("li");
      li.className = "doc";
      li.textContent = h.report_nm + " (" + h.rcept_dt + " · " + h.days_before + "일 전)";
      // 기존 openDocPanel(rcept_no) 배선을 그대로 재사용한다(브리프) —
      // tableEl()의 rcept_no 열 클릭과 같은 함수, 새 경로를 만들지 않는다.
      li.addEventListener("click", function () { openDocPanel(h.rcept_no); });
      ul.appendChild(li);
    });
    card.appendChild(ul);
  }

  return card;
}

/** fundChain(records) 결과 전체를 조달건 카드 목록으로 그린다(SE-5a
 *  Task 3). chain이 비어 있으면(records 자체가 없거나 빈 배열) 호출하지
 *  않는다 — 다른 파생 블록(ratioBlock 등)과 같은 "값이 없으면 안 만든다"
 *  패턴(renderSection 참고).
 *
 *  **"조달건이 하나도 없다"의 정의**: fundChain은 모든 행이 pay_de 결측
 *  (제이스코홀딩스처럼 전부 "-")이어도 예외 없이 pay_de:null 묶음
 *  하나를 돌려준다(Task 1 계약) — 즉 chain.length가 0이 되는 경우는
 *  거의 없다. 여기서 "조달건이 없다"는 chain.length===0이 아니라 **날짜를
 *  알 수 있는 조달건이 하나도 없다**(모든 항목의 pay_de가 null)는 뜻이다
 *  — 그 상태에서 카드를 그려봐야 "납입일이 공시되지 않은 내역" 카드
 *  하나에 용도조차 "(용도 미기재)"뿐이라 정보가 없다. 이때는 카드 대신
 *  "자금사용 내역 N건이 있으나 납입일·용도가 공시되지 않았습니다"라고
 *  말한다 — "내역이 없습니다"는 거짓이다(브리프, 내역 자체는 N건 있다).
 *
 *  **리뷰 지적 ① — 그 판정을 pay_de만으로 하면 안 된다**: 처음 구현은
 *  "날짜 있는 조달건이 하나도 없다"만 보고 카드를 통째로 버린 뒤 위
 *  문장을 냈다. 그런데 납입일만 "-"이고 용도(운영자금·시설자금)는 실제로
 *  공시된 형태가 있다 — 그 화면은 **용도가 공시되지 않았다고 거짓을
 *  말하면서** fundChain이 이미 계산해 둔 용도별 계획 합계까지 함께
 *  버렸다. 그래서 판정 기준을 "카드로 보여줄 게 있는가"로 바꾼다: 날짜가
 *  있거나(dated) 날짜가 없어도 용도가 하나라도 공시된 묶음이 있으면
 *  카드를 그린다. 무날짜 묶음의 카드 제목이 "납입일이 공시되지 않은
 *  내역"이라 날짜가 없다는 사실 자체는 화면에 그대로 남는다
 *  (fundChainCardEl 참고). 위 문장은 날짜도 용도도 정말로 없을 때
 *  (제이스코홀딩스: 26행 전 필드가 "-")만 낸다.
 *
 *  disclosureState는 fundChainDisclosureState()의 세 값 중 하나다 —
 *  "failed"면 조달 공시 대조를 못 했다는 사실을 블록 안에서 말한다
 *  (힌트가 그냥 없는 것과 "대조 자체를 못 했다"는 다른 사실이다). */
function buildFundChainBlock(chain, hints, windowDays, disclosureState) {
  const wrap = document.createElement("div");
  wrap.className = "derived";

  const h3 = document.createElement("h3");
  h3.textContent = "자금 조달건 (조달일 단위)";
  wrap.appendChild(h3);

  // 카드로 보여줄 것이 하나라도 있는가 — 납입일이 있거나, 납입일이 없어도
  // 용도가 공시된 묶음(위 주석).
  const renderable = chain.some(function (e) {
    return e.pay_de !== null || e.uses.some(function (u) { return u.purpose !== null; });
  });

  if (!renderable) {
    const totalRows = chain.reduce(function (s, e) { return s + e.row_count; }, 0);
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = "자금사용 내역 " + totalRows + "건이 있으나 납입일·용도가 "
      + "공시되지 않았습니다.";
    wrap.appendChild(p);
    return { el: wrap };
  }

  // 막대 설명은 막대를 실제로 그릴 때만 붙인다(리뷰 지적 ④) — 위 조기
  // 반환보다 **뒤에** 있어야 한다. 앞에 두면 카드도 막대도 없는 화면에서
  // 막대 설명만 읽힌다.
  const notice = document.createElement("p");
  notice.className = "note";
  notice.textContent = "같은 납입일·같은 용도로 여러 번 보고된 자금사용 내역(아래 원본 표)을 "
    + "조달건 하나로 묶고, 계획 금액에 비례한 막대로 용도별 비중을 보여줍니다 — "
    + "새로 계산한 값이 아니라 원본 plan_amount를 용도별로 합친 것입니다.";
  wrap.appendChild(notice);

  // 조달 공시를 끝내 못 가져왔으면 그 사실을 말한다(리뷰 지적 ②) —
  // 힌트 블록이 그냥 없는 화면은 "대조했는데 걸린 공시가 없다"와 구분되지
  // 않는데, 그 둘은 서로 다른 사실이다.
  if (disclosureState === "failed") {
    const fp = document.createElement("p");
    fp.className = "note";
    fp.textContent = "공시 목록을 가져오지 못해 이 조달건들과 조달 공시(전환사채·"
      + "유상증자 등)를 대조하지 못했습니다 — 대조 결과가 없다는 뜻이지 해당 "
      + "공시가 없다는 뜻이 아닙니다.";
    wrap.appendChild(fp);
  }

  chain.forEach(function (entry) {
    wrap.appendChild(fundChainCardEl(entry, hints, windowDays));
  });

  return { el: wrap };
}

/** affiliateOverview(app.js)가 최초취득일 순으로 재배열한 타법인 출자
 *  레코드를 표+차트로 그린다(SE-4f Task 5, task-5-brief.md).
 *
 *  사용자 요청: "피투자사에 대한 정보를 처음부터 보여줄 필요도 있음" —
 *  원본 표(affiliates)는 20열 중 피투자사 재무(총자산·당기순이익)가 맨
 *  뒤쪽 두 열에 있어 눈에 잘 안 띈다. 여기서는 피출자 법인·출자목적·
 *  최초취득일·기말지분율·기말장부가액·피투자사 총자산·피투자사 당기순이익
 *  일곱 열만 추려 원본 표보다 먼저(위쪽에) 보여준다 — 값을 새로 계산하지
 *  않고 원본 필드를 그대로 옮긴다(label()·formatValue()가 원본 키로 자동
 *  으로 한글 라벨·금액/날짜 서식을 입힌다 — dividendVsIncome처럼 새 한글
 *  키를 만들지 않는 이유는, 이 값들이 이미 LABELS·AMOUNT_FIELDS·
 *  DATE_FIELDS에 등록돼 있어 그대로 재사용할 수 있기 때문이다).
 *
 *  **공시 원본과 반드시 구분한다**(buildFinancialRatiosBlock과 같은 이유) —
 *  class="derived"로 나누고, 순서를 다시 배열했을 뿐 새 값이 아니라고
 *  문구로 밝힌다. 적자 피투자사가 여러 건 있어도(엔켐 실측: -105.3억·
 *  -14.1억 등) 색을 칠하거나 "부실 자회사" 같은 말을 붙이지 않는다(v0.8.5
 *  판정선 — 사실 표기만).
 *
 *  차트(CHART_SPECS.affiliate_timeline)에는 이 함수가 받은 것과 같은
 *  정렬된 레코드를 그대로 넘긴다 — 표와 차트가 다른 순서를 말하면 안 된다. */
function buildAffiliateOverviewBlock(records) {
  const wrap = document.createElement("div");
  wrap.className = "derived";

  const h3 = document.createElement("h3");
  h3.textContent = "피투자사 정보 (최초취득일 순)";
  wrap.appendChild(h3);

  const notice = document.createElement("p");
  notice.className = "note";
  notice.textContent = "타법인 출자현황(아래 원본 표)의 값을 최초취득일 순으로 다시 "
    + "배열해 피출자 법인과 피투자사 재무(총자산·당기순이익)를 먼저 보여줍니다 — "
    + "새로 계산하거나 판정한 값이 아니라 원본 값을 그대로 옮긴 것입니다. 이 "
    + "데이터는 한 사업연도 스냅샷이라 여러 사업연도에 걸친 추이는 알 수 없고, "
    + "기초→기말 장부가액 변화(아래 차트)는 이번 사업연도 안에서의 증감만 "
    + "보여줍니다.";
  wrap.appendChild(notice);

  const rows = records.map(function (r) {
    return {
      inv_prm: r.inv_prm,
      invstmnt_purps: r.invstmnt_purps,
      frst_acqs_de: r.frst_acqs_de,
      trmend_blce_qota_rt: r.trmend_blce_qota_rt,
      trmend_blce_acntbk_amount: r.trmend_blce_acntbk_amount,
      recent_bsns_year_fnnr_sttus_tot_assets: r.recent_bsns_year_fnnr_sttus_tot_assets,
      recent_bsns_year_fnnr_sttus_thstrm_ntpf: r.recent_bsns_year_fnnr_sttus_thstrm_ntpf,
    };
  });
  // records는 원본 필드를 전부 가진 채 순서만 바뀐 것이라(위 주석 —
  // affiliateOverview가 재배열만 한다) cellMarks("affiliates")가 그대로
  // 통한다. rows는 **이 함수가 받은 records를 그대로 map한 것**이라 행번호가
  // 맞는다 — records를 여기서 다시 정렬하거나 거르면 그 순간 강조가 한 칸씩
  // 밀려 다른 회사의 사실이 된다(정렬은 호출부의 affiliateOverview가 이미
  // 끝냈고, 이 함수는 정렬된 결과만 받는다).
  const marks = cellMarks(records, "affiliates");
  const table = tableLayout(rows, markedColumnKeys(marks));
  if (table) wrap.appendChild(tableEl(table, marks));

  renderChart(wrap, "affiliate_timeline", records, SIGNALS_DATA);
  return { el: wrap, table: table };
}

/** matchCrossPatterns(app.js, SE-13 Task 3)가 돌려준 매칭 패턴 하나를
 *  카드로 그린다. buildPatternMatchBlock(아래)만 부른다.
 *
 *  카드 구성 — task-3-brief.md "더 자세하게" 요구를 그대로 옮긴 것:
 *  ① 패턴명·설명(공개 뷰어 patterncard와 같은 필드)
 *  ② 이 회사에서 실제 탐지된 구성 신호 → 그 신호를 촉발한 공시 목록
 *     (rcept_no 있으면 기존 openDocPanel 배선을 그대로 재사용해 클릭하면
 *     원문이 열린다 — .doc 클래스·클릭 배선 모두 fundChainCardEl과 같은
 *     재사용). taxonomy 2.7(자본 churn)처럼 개별 공시가 아니라 빈도로
 *     판정된 항목은 aggregate_note로 그 사실 자체를 밝힌다(app.js
 *     matchCrossPatterns 주석 참고) — 특정 공시 하나를 근거인 것처럼
 *     보여주지 않는다.
 *  ③ field_evidence(Task 2가 export한 금감원 등 사실 인용)
 *  ④ 면책 문구는 카드 하나하나가 아니라 buildPatternMatchBlock이 블록
 *     맨 위에 한 번만 붙인다(공개 뷰어 index.html:834와 같은 자리·같은
 *     문구 — 아래 참고).
 *
 *  severity·점수는 patterns 객체 자체에 없다(Task 2 export 단계에서
 *  구조적으로 제외) — 여기서도 만들어내지 않는다. */
function patternCardEl(p) {
  const card = document.createElement("div");
  card.className = "pattern-card";

  const h4 = document.createElement("h4");
  h4.textContent = p.name;
  card.appendChild(h4);

  if (p.description) {
    const desc = document.createElement("p");
    desc.className = "note";
    desc.textContent = p.description;
    card.appendChild(desc);
  }

  const seqNote = document.createElement("p");
  seqNote.className = "note";
  seqNote.textContent = "구성 신호 taxonomy: " + p.signal_sequence.join(" + ")
    + " · 관찰 윈도우 " + p.timeline_months + "개월";
  card.appendChild(seqNote);

  // ② 이 회사에서 실제 탐지된 구성 신호 → 공시 역추적
  const evList = document.createElement("ul");
  evList.className = "pattern-evidence-list";
  let evCount = 0;
  (p.evidence || []).forEach(function (ev) {
    (ev.disclosures || []).forEach(function (d) {
      const li = document.createElement("li");
      const labels = (d.signal_labels || []).join(", ");
      li.textContent = "[" + ev.taxonomy + "] " + labels + " — " + d.report_nm
        + (d.rcept_dt ? " (" + d.rcept_dt + ")" : "");
      if (d.rcept_no) {
        li.className = "doc";
        li.addEventListener("click", function () { openDocPanel(d.rcept_no); });
      }
      evList.appendChild(li);
      evCount++;
    });
    if (ev.aggregate_note) {
      const li = document.createElement("li");
      li.textContent = "[" + ev.taxonomy + "] " + ev.aggregate_note;
      evList.appendChild(li);
      evCount++;
      (ev.aggregate_disclosures || []).forEach(function (d) {
        const sub = document.createElement("li");
        sub.textContent = "  · " + d.report_nm + (d.rcept_dt ? " (" + d.rcept_dt + ")" : "");
        if (d.rcept_no) {
          sub.className = "doc";
          sub.addEventListener("click", function () { openDocPanel(d.rcept_no); });
        }
        evList.appendChild(sub);
        evCount++;
      });
    }
  });
  if (evCount > 0) card.appendChild(evList);

  // ③ 사실 근거(field_evidence)
  if (Array.isArray(p.field_evidence) && p.field_evidence.length > 0) {
    const fh = document.createElement("p");
    fh.className = "note";
    fh.textContent = "실제 사례 근거(금감원 보도자료 등):";
    card.appendChild(fh);
    const fl = document.createElement("ul");
    fl.className = "pattern-field-evidence";
    p.field_evidence.forEach(function (fe) {
      const li = document.createElement("li");
      li.textContent = fe;
      fl.appendChild(li);
    });
    card.appendChild(fl);
  }

  return card;
}

/** matchCrossPatterns(app.js) 결과 전체를 카드 목록으로 그린다(SE-13
 *  Task 3). patterns가 비어 있으면(매칭 없음) renderSection이 아예 이
 *  함수를 부르지 않는다 — 다른 파생 블록과 같은 "값이 없으면 안 만든다"
 *  관례(브리프: "과시적 '이상 없음' 금지").
 *
 *  면책 문구는 공개 뷰어(index.html:834)와 **글자 그대로 같다** — 브리프가
 *  "기존 문구를 재사용하고 새로 짓지 말라"고 명시했고, 같은 사실을 두
 *  화면이 다른 말로 부르면 안 된다(Task 4가 공개 뷰어에 근거를 보강할
 *  때도 이 문구를 그대로 쓴다). */
function buildPatternMatchBlock(patterns) {
  const wrap = document.createElement("div");
  wrap.className = "derived";

  const h3 = document.createElement("h3");
  h3.textContent = "복합 패턴";
  wrap.appendChild(h3);

  const disclaimer = document.createElement("p");
  disclaimer.className = "note";
  disclaimer.textContent = "아래 패턴의 구성 신호가 모두 관찰됐습니다. "
    + "패턴 \"조건 충족\"은 사실 관찰이며 판정이 아닙니다.";
  wrap.appendChild(disclaimer);

  patterns.forEach(function (p) {
    wrap.appendChild(patternCardEl(p));
  });

  return { el: wrap };
}

/** indicators 전용 렌더(SE-4h Task 2) — indicatorBlocks(app.js)가 만든
 *  4분류(수익성·안정성·성장성·활동성, 모르는 분류는 맨 뒤) 블록을 각각
 *  그린다. renderSection이 sectionBlocks/tableLayout 경로를 아예 타지
 *  않고 이 함수를 직접 부른다(위 renderSection 주석 참고).
 *
 *  뜻(note) 열은 primary·rest 표 모두에 있다(SE-8 Task 5). SE-4h
 *  Task 2 때는 66개 중 22개에만 뜻이 있어 rest(접힌 44개) 표까지 뜻
 *  열을 만들면 대부분이 빈 칸이었다 — 그래서 그때는 primary 표에만
 *  열을 뒀다. 사용자가 실측으로 지적한 문제(일부 지표는 이름+뜻이
 *  보이는데 접힌 지표는 뜻이 아예 안 보인다)가 바로 그 결과였다.
 *  지금은 66개 중 65개(유보액대비율 제외)에 뜻이 있어 그 전제가 더는
 *  맞지 않는다 — rest도 indicatorTableEl(..., true)로 그린다(아래
 *  indicatorRestFold). rest는 여전히 기존 열 접기와 같은 시각 패턴
 *  (.fold-btn 버튼 + .fold-detail 토글)을 쓴다 — "표 전체를 접는다"는
 *  tableEl()의 열 단위 접기와 모양이 달라 그 함수를 그대로 재사용하지
 *  않고 클래스만 같이 쓴다. */
function renderIndicatorBlocks(holder, value, wrap) {
  const blocks = indicatorBlocks(value);

  // 어느 해가 실제로 조회됐는지 먼저 말한다(SE-4h 최종 수정, 리뷰 지적 ②).
  // 12콜 중 몇 개가 실패해 한 해가 통째로 빠져도 화면은 남은 점을 그대로
  // "추이"라고 그린다 — 그 침묵이 이 화면이 고치려던 실패 모양 그 자체다.
  // 블록보다 위에 두는 이유: 표·차트를 읽기 *전에* 그 범위를 알아야 한다.
  // 데이터가 아예 없을 때(아래 early return)도 이 문장은 남긴다 — 그때야말로
  // "조회 실패인가 자료가 없는 것인가"가 가장 궁금한 순간이다.
  const yearNote = indicatorYearNote(value);
  if (yearNote) {
    const yp = document.createElement("p");
    yp.className = "note";
    yp.textContent = yearNote;
    holder.appendChild(yp);
  }

  if (blocks.length === 0) {
    if (wrap) wrap.className = "sec";
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = "표시할 데이터가 없습니다.";
    holder.appendChild(p);
    return;
  }
  // 지표 표는 지표명+연도 여러 열이라 항상 넓다 — 다른 섹션의
  // hasWideTable 판정(orientation === "horizontal")과 결론이 같으므로
  // 여기서는 무조건 wide로 둔다(narrow 2단 그리드에 가두면 연도 열이
  // 줄바꿈된다).
  if (wrap) wrap.className = "sec wide";

  blocks.forEach(function (block) {
    const section = document.createElement("div");
    const h3 = document.createElement("h3");
    h3.textContent = block.category;
    section.appendChild(h3);

    if (block.primary.length > 0) {
      section.appendChild(indicatorTableEl(block.primary, true));
      // SE-4h Task 3 — 분류별 추이 차트. indicatorChartRecords(app.js)가
      // 이 분류의 primary 지표 중 값이 있는 것만 걸러 records로 넘긴다 —
      // renderChart는 표 바로 위(querySelector("table")로 찾은 자리)에
      // canvas를 끼워 넣는다(위 renderChart 주석 참고, affiliate_timeline과
      // 같은 "표 먼저 붙이고 renderChart" 순서). CHART_SPECS["indicators_" +
      // category](app.js)가 없는 분류(모르는 분류가 온 경우)면 renderChart가
      // 조용히 false를 돌려주고 표만 남는다 — 화면이 죽지 않는다.
      renderChart(section, "indicators_" + block.category, indicatorChartRecords(value, block.category));
    }
    if (block.rest.length > 0) {
      section.appendChild(indicatorRestFold(block.rest));
    }

    // SE-4f에서 파생 지표(계산값)에 붙인 고지("DART 공시 수치로 계산한
    // 값입니다 — 공시 원본이 아닙니다")와 방향이 반대다 — 이 표는 우리가
    // 계산하지 않은 DART 원본 지표라서 문구를 구분한다(브리프 요구사항).
    const notice = document.createElement("p");
    notice.className = "note";
    notice.textContent = "DART가 계산해 공시한 값입니다 — 우리가 계산한 값이 아닙니다.";
    section.appendChild(notice);

    holder.appendChild(section);
  });
}

/** indicatorBlocks 항목(entries: [{idx_nm, note?, cells}]) 하나를 표로
 *  그린다. withNote가 true면 지표 열 바로 뒤에 뜻 열을 넣는다(primary
 *  전용). 연도 열은 entries[0].cells 순서(indicatorBlocks가 이미 최신
 *  연도부터 정렬해 뒀다)를 그대로 쓴다.
 *
 *  tableLayout(app.js)을 재사용하지 않는 이유: 연도 문자열("2025" 등)을
 *  레코드 키로 쓰면, 자바스크립트 객체는 정수형 문자열 키를 삽입 순서와
 *  무관하게 오름차순으로 먼저 나열한다(정수 인덱스 키 규칙) — "지표 |
 *  뜻 | 2025 | 2024"로 두려던 열 순서가 "2024 | 2025 | 지표 | 뜻"로
 *  뒤집힌다. 여기서는 열 순서를 배열로 직접 통제해 이 함정을 피한다.
 *
 *  SE-4i — 사실 강조(.mk). SE-4g가 다른 모든 표에 붙인 강조가 이 표에는
 *  없었다(indicatorTableEl이 cellMarks를 부르지 않고 만들어진 별도 경로라
 *  — 이 함수 docstring 첫 줄이 이미 그 이유를 말한다). tableEl()과 같은
 *  관례를 그대로 따른다: className·title은 이어 붙이고(대입하면 다른 곳에서
 *  이미 겪은 사고 — 클릭 표시·툴팁 유실 — 가 재발한다), 표에 실제로 붙은
 *  사유만 모아 표 아래 범례(.mk-legend)로 보여주며, 하나도 안 붙으면 범례
 *  자체를 만들지 않는다(빈 범례는 "강조할 게 있었는데 없다"는 착각을
 *  준다). 지표 이름·뜻 열은 대상이 아니다 — 연도 값 칸(entry.cells)만
 *  본다. */
function indicatorTableEl(entries, withNote) {
  const frag = document.createDocumentFragment();
  const years = entries.length > 0 ? entries[0].cells.map(function (c) { return c.bsns_year; }) : [];

  const table = document.createElement("table");
  const thead = table.createTHead().insertRow();
  const th0 = document.createElement("th");
  th0.textContent = "지표";
  thead.appendChild(th0);
  if (withNote) {
    const thNote = document.createElement("th");
    thNote.textContent = "뜻";
    thead.appendChild(thNote);
  }
  years.forEach(function (y) {
    const th = document.createElement("th");
    th.textContent = y;
    thead.appendChild(th);
  });

  const appliedWhys = [];
  const seenWhys = new Set();
  function noteApplied(why) {
    if (!seenWhys.has(why)) { seenWhys.add(why); appliedWhys.push(why); }
  }

  const tbody = table.createTBody();
  entries.forEach(function (entry) {
    const tr = tbody.insertRow();
    const tdName = tr.insertCell();
    tdName.textContent = entry.idx_nm;
    if (withNote) {
      const tdNote = tr.insertCell();
      tdNote.textContent = entry.note || "";
    }
    entry.cells.forEach(function (c) {
      const td = tr.insertCell();
      td.textContent = c.display;
      const why = indicatorCellWhy(c.idx_val);
      if (why) {
        td.className = td.className ? (td.className + " mk") : "mk";
        td.title = td.title ? (td.title + " · " + why) : why;
        noteApplied(why);
      }
    });
  });
  frag.appendChild(table);

  if (appliedWhys.length > 0) {
    const legend = document.createElement("div");
    legend.className = "mk-legend";
    const b = document.createElement("b");
    b.textContent = "강조: ";
    legend.appendChild(b);
    legend.appendChild(document.createTextNode(appliedWhys.join(" · ")));
    frag.appendChild(legend);
  }

  return frag;
}

/** rest(접힌 지표)를 기존 .fold-btn/.fold-detail과 같은 시각 패턴(버튼 +
 *  hidden 토글)으로 접는다 — 없애는 게 아니라 접는 것이므로 클릭하면
 *  언제든 볼 수 있다(tableEl()의 열 접기와 같은 원칙).
 *
 *  indicatorTableEl(restEntries, true) — SE-8 Task 5부터 rest도 뜻 열을
 *  그린다(위 renderIndicatorBlocks 주석 참고). 뜻이 없는 지표(유보액대비율
 *  등)는 entry.note가 ""라 그 칸만 빈 채로 보인다 — 표 전체를 숨기지
 *  않는다. */
function indicatorRestFold(restEntries) {
  const wrap = document.createElement("div");

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "fold-btn";
  btn.textContent = "나머지 " + restEntries.length + "개 지표";
  wrap.appendChild(btn);

  const detail = document.createElement("div");
  detail.className = "fold-detail";
  detail.hidden = true;
  detail.appendChild(indicatorTableEl(restEntries, true));
  wrap.appendChild(detail);

  btn.addEventListener("click", function () {
    detail.hidden = !detail.hidden;
  });

  return wrap;
}

/** 강조가 붙은 열이 접히지 않도록 이 블록의 표를 다시 배치한다.
 *
 *  왜 다시 부르나: sectionBlocks(app.js)가 표를 만드는 시점에는 강조가
 *  아직 계산되지 않았다(강조는 섹션 키가 필요한데, 그 키는 재귀 안쪽까지
 *  전달되지 않는다 — sectionBlocks 주석의 게이트 원칙). 강조는 여기
 *  renderSection에서 block.records로 계산되므로, 그 결과를 알고 난 뒤에
 *  같은 레코드로 tableLayout을 한 번 더 부르는 것이 배선을 가장 적게
 *  건드리는 방법이다.
 *
 *  **안전한 이유**: sectionBlocks가 만드는 모든 블록에서 block.table은
 *  예외 없이 `tableLayout(block.records)`다(source 제거·빈 열 제거 등
 *  가공은 전부 block.records 자체에 이미 반영돼 있다 — sourceGroupedBlocks
 *  의 `cleaned`, shareholders의 peopleRecords 등). 따라서 같은 레코드로
 *  다시 부른 결과는 markedKeys를 뺀 모든 면에서 원래와 같다. 실패해도
 *  (null 반환) 원래 표를 그대로 둔다.
 *
 *  강조가 하나도 없으면 아무 일도 하지 않는다 — 접기 규칙이 조용히
 *  달라지는 일이 없도록 발화한 경우에만 개입한다. */
function relayoutForMarks(block, marks) {
  if (!block || !block.table || !Array.isArray(block.records) || !marks) return;
  const markedKeys = markedColumnKeys(marks);
  if (markedKeys.length === 0) return;
  const relaid = tableLayout(block.records, markedKeys);
  if (relaid) block.table = relaid;
}

/** 섹션 하나를 그린다. 같은 키로 다시 불리면 **교체**한다 — 누적하면
 *  화면에 같은 섹션이 계속 쌓인다(섹션은 한 번만 오도록 돼 있지만,
 *  렌더 함수가 누적식이면 다른 경로에서 쉽게 깨진다).
 *
 *  값이 dict-of-lists(shareholders 등)면 sectionBlocks가 하위 키별로
 *  여러 블록을 돌려준다 — 표 하나에 JSON으로 뭉치지 않고 소제목 + 개별
 *  표로 나눠 그린다. */
function renderSection(key, value) {
  const holder = sectionHolder(key);
  // holder를 비우기 전에, 그 안에 남아 있는 canvas의 Chart 인스턴스를
  // 먼저 정리한다(리뷰 지적 ④) — removeChild만으로는 DOM에서 canvas가
  // 사라질 뿐 CHART_INSTANCES의 참조는 그대로 남는다.
  pruneChartsIn(holder);
  while (holder.firstChild) holder.removeChild(holder.firstChild);

  // indicators(주요 재무지표)는 SE-4h부터 {bsns_year, category, idx_nm,
  // idx_val} 행 목록으로 온다 — sectionBlocks/tableLayout에 그대로
  // 넘기면 지표 × 연도가 뒤섞인 표 하나가 되어(엔켐 실측 기준 최대
  // 198행) 예전 49열 세로 표보다 오히려 읽기 나쁘다(app.js indicatorBlocks
  // 주석 참고). sectionBlocks 자체를 부르지 않고 여기서 가로채 4분류
  // 블록으로 그린다.
  if (key === "indicators") {
    renderIndicatorBlocks(holder, value, SEC_WRAP[key]);
    return;
  }

  // disclosures 원본을 기억해 둔다(SE-5a Task 3) — fund_usage 카드의 조달
  // 공시 근접 힌트(fundChainDisclosureHints)가 이 배열을 필요로 하는데, 두
  // 섹션은 서로 다른 renderSection 호출로 각각 도착한다(위 DISCLOSURES_DATA
  // 선언 주석 참고).
  if (key === "disclosures" && Array.isArray(value)) {
    DISCLOSURES_DATA = value;
    DISCLOSURES_FAILED = false; // 앞선 폴링에서 실패했더라도 이제 받았다
    // fund_usage가 이 섹션보다 먼저 도착해 힌트 없이 그려졌으면 지금 다시
    // 그린다(리뷰 지적 ②) — 그 함수가 "상태가 바뀌었을 때만" 그리므로
    // 여기서 조건을 중복해 판단하지 않는다. fund_usage 홀더 하나만 다시
    // 그리므로 이 disclosures 렌더와 서로 간섭하지 않는다.
    refreshFundChainForDisclosures();
  }

  // 복합 패턴(CROSS_SIGNAL_PATTERNS) 매칭 — SE-13 Task 3. disclosures
  // 섹션 자체가 SE-7 신호 분류(classifyDisclosureCategory)가 보이는
  // 자리라 여기 derived 블록으로 얹는다(브리프 "표시 위치: 공시 목록/
  // 신호 요약 근처"). matchCrossPatterns(app.js)가 빈 배열을 돌려주면
  // (매칭 없음) 블록을 아예 만들지 않는다 — SE의 "과시적 이상 없음 금지"
  // 관례(다른 파생 블록들과 동일).
  let patternBlock = null;
  if (key === "disclosures") {
    const patterns = matchCrossPatterns(Array.isArray(value) ? value : [], SIGNALS_DATA);
    if (patterns.length > 0) patternBlock = buildPatternMatchBlock(patterns);
  }

  const blocks = sectionBlocks(value, 0, key);

  // financials는 원본 표 외에 파생 지표(계산값) 블록도 함께 그린다
  // (SE-4f Task 2) — financialRatios(app.js)는 순수 함수로 계산만 하고,
  // 여기서는 그 결과를 표+차트로 렌더만 한다. 원본 표는 지우지 않는다 —
  // 브리프 원칙("파생 블록은 기존 표 위에 얹는다")대로 derived 블록을
  // 원본 표보다 먼저(=화면에서 더 위에) 붙인다(아래 holder.appendChild
  // 순서 참고).
  let ratioBlock = null;
  if (key === "financials") {
    // dividendVsRetainedEarnings(app.js, SE-12 Task 2)가 dividends 섹션을
    // 그릴 때 이 원본을 필요로 한다(위 FINANCIALS_DATA 선언 주석 참고) —
    // dividends가 이미 이 값 없이 그려졌다면 지금 다시 그려 채운다.
    FINANCIALS_DATA = value;
    refreshRetainedEarningsBlock();
    const ratios = financialRatios(Array.isArray(value) ? value : []);
    if (ratios.length > 0) ratioBlock = buildFinancialRatiosBlock(ratios);
  }

  // dividends: "배당 vs 당기순이익" 사실 비교(SE-4f Task 4) — 배당
  // 기록 자체가 없는 회사(엔켐 등)는 dividendVsIncome이 빈 배열을
  // 돌려주므로 이 블록 자체가 안 생긴다(위 dividendVsIncome 주석 참고).
  let dividendBlock = null;
  // dividends: "적자 시점 배당"(DIVIDEND_DRAIN) 사실 표기 + "배당 vs
  // 이익잉여금"(단일 연도) 비교(SE-12 Task 2, 요구사항 A·B) — 둘 다
  // dividendVsIncome과 같은 자리(dividends 섹션)에 나란히 렌더한다.
  let dividendDrainBlock = null;
  let retainedEarningsBlock = null;
  if (key === "dividends") {
    const dvRows = dividendVsIncome(Array.isArray(value) ? value : []);
    if (dvRows.length > 0) dividendBlock = buildDividendVsIncomeBlock(dvRows);

    DIVIDENDS_DATA = value; // 위 refreshRetainedEarningsBlock이 참조하는 원본
    const drainFlags = dividendDrainFlags(Array.isArray(value) ? value : []);
    if (drainFlags.length > 0) dividendDrainBlock = buildDividendDrainBlock(drainFlags);

    const retained = dividendVsRetainedEarnings(
      Array.isArray(FINANCIALS_DATA) ? FINANCIALS_DATA : [],
      Array.isArray(value) ? value : []);
    if (retained) retainedEarningsBlock = buildDividendVsRetainedEarningsBlock(retained);
  }

  // fund_usage: 조달건 카드 + 비례 막대(SE-5a Task 3) — fundChain(records)이
  // 빈 배열을 돌려주면(원본 자체가 없다) 이 블록도 안 생긴다. buildFundChainBlock
  // 안에서 "날짜를 알 수 있는 조달건이 하나도 없다"(제이스코 형태)는
  // 별도로 다시 판정해 카드 대신 안내문을 낸다(위 함수 주석 참고).
  let fundChainBlock = null;
  if (key === "fund_usage") {
    // disclosures가 뒤늦게 도착(또는 실패 확정)했을 때 이 섹션만 다시
    // 그릴 수 있도록 원본과 "그릴 때 쓴 상태"를 남긴다 —
    // refreshFundChainForDisclosures가 이 둘을 본다(리뷰 지적 ②).
    FUND_USAGE_DATA = value;
    FUND_CHAIN_DISCLOSURE_STATE = fundChainDisclosureState();
    const chain = fundChain(Array.isArray(value) ? value : []);
    if (chain.length > 0) {
      const hints = fundChainDisclosureHints(
        chain,
        Array.isArray(DISCLOSURES_DATA) ? DISCLOSURES_DATA : [],
        SIGNALS_DATA,
        FUND_CHAIN_WINDOW_DAYS
      );
      fundChainBlock = buildFundChainBlock(
        chain, hints, FUND_CHAIN_WINDOW_DAYS, FUND_CHAIN_DISCLOSURE_STATE);
    }
  }

  // fund_usage: 계획 금액 변경 사실 표기(SE-4f Task 7) — 변경이 없는
  // 조달 건만 있으면 fundPlanChanges가 빈 배열을 돌려주므로 이 블록
  // 자체가 안 생긴다(위 fundPlanChanges 주석 참고).
  let fundChangeBlock = null;
  if (key === "fund_usage") {
    const changes = fundPlanChanges(Array.isArray(value) ? value : []);
    if (changes.length > 0) fundChangeBlock = buildFundPlanChangeBlock(changes);
  }

  // affiliates: 피투자사 정보를 최초취득일 순으로 먼저 보여준다(SE-4f
  // Task 5) — 유효한 레코드(inv_prm이 있는)가 하나도 없으면
  // affiliateOverview가 빈 배열을 돌려주므로 이 블록 자체가 안 생긴다
  // (위 dividendBlock·fundChangeBlock과 같은 패턴).
  let affiliateBlock = null;
  if (key === "affiliates") {
    const overview = affiliateOverview(Array.isArray(value) ? value : []);
    if (overview.length > 0) affiliateBlock = buildAffiliateOverviewBlock(overview);
  }

  // 가로(여러 행) 표가 하나라도 있으면 2단 폭 중 한 칸에 가두지 않고
  // 전체 폭을 쓴다 — 세로(1건, 키-값) 표는 원래도 좁아 한 칸이면
  // 충분하다(app.js tableLayout 주석 참고: 세로/가로 구분 기준과 같다).
  // 앞 태스크에서 12열까지 보이게 넓힌 표가 2단으로 다시 좁아지는
  // 재발을 막는다. 파생 블록들의 표도 가로일 수 있어 함께 본다 — 안
  // 그러면 파생 표가 넓은데 .sec은 좁게 남는다.
  const derivedBlocks = [
    ratioBlock, dividendBlock, dividendDrainBlock, retainedEarningsBlock,
    fundChainBlock, fundChangeBlock, affiliateBlock, patternBlock,
  ];
  const hasWideTable = blocks.some(function (b) {
    return b.table && b.table.orientation === "horizontal";
  }) || derivedBlocks.some(function (b) {
    return !!(b && b.table && b.table.orientation === "horizontal");
  });
  const wrap = SEC_WRAP[key];
  if (wrap) wrap.className = hasWideTable ? "sec wide" : "sec";

  if (blocks.length === 0 && !ratioBlock && !dividendBlock && !dividendDrainBlock
      && !retainedEarningsBlock && !fundChainBlock && !fundChangeBlock && !affiliateBlock
      && !patternBlock) {
    const p = document.createElement("p");
    p.className = "note";
    // SE-6 Task 3 — DART가 013(자료 없음)을 주는 회사가 실제로 있다
    // (실측: 셀트리온). "표시할 데이터가 없습니다"(다른 모든 섹션의
    // 일반 문구)는 "우리가 확인했는데 0건"으로 읽힌다 — 여기서는 DART
    // 자체가 제공하지 않는다는 사실을 구분해 말한다.
    if (key === "executive_roster") {
      p.textContent = "DART가 이 회사의 임원현황을 제공하지 않습니다.";
      EXEC_ROSTER_SOURCE = null;
      EXEC_MATCHES = {};
      EXEC_LOOKUPS = {};
      EXEC_STATUS = "idle";
      EXEC_GEN++;
    } else {
      p.textContent = "표시할 데이터가 없습니다.";
    }
    holder.appendChild(p);
    return;
  }
  // fund_usage: 같은 회차(tm)가 분기 보고서(1분기·반기·3분기·사업보고서)
  // 마다 반복 수집된다(fetch_fund_usage 루프: bsns_year × reprt_code
  // 4종) — 그런데 정규화 과정(dart_client._normalize_fund_usage)이
  // reprt_code를 버려(core 수정 불가) 표 안 어느 행이 어느 분기 보고인지
  // 구분할 수 없다. sectionBlocks(순수 데이터 변환)에 넣지 않고 여기
  // 렌더 단계에서만 안내문을 얹는 이유: sectionBlocks의 반환 모양(블록
  // 개수·순서)은 다른 여러 테스트·차트 삽입 로직(renderChart가 block.
  // records를 그대로 쓴다)이 그대로 의존하고 있어, 표 블록이 아닌 안내
  // 문단을 그 목록 안에 섞으면 그 계약이 깨진다 — 안내는 화면에만
  // 붙이고 데이터 모양은 건드리지 않는다. 같은 회차가 여러 행으로
  // 나오는 것이 오류가 아니라는 사실을 감추지 않고 말한다(v0.8.5: 판정이
  // 아니라 있는 그대로의 사실 고지) — 사용자가 "같은 수치가 두 번씩
  // 들어가는 모양"이라고 지적한 것이 이 반복이다.
  if (key === "fund_usage") {
    const note = document.createElement("p");
    note.className = "note";
    note.textContent = "같은 회차가 여러 행으로 나오는 것은 오류가 아닙니다 — "
      + "자금 조달 건 하나를 분기 보고서(1분기·반기·3분기·사업보고서)마다 "
      + "다시 보고하기 때문입니다. 어느 분기의 보고인지는 원본 데이터에 "
      + "없어 표시하지 않습니다. \"자금 납입일\"은 자금이 들어온 날짜이며 "
      + "집행일이 아닙니다.";
    holder.appendChild(note);
  }
  // SE-6 Task 3 — 임원 명단 ↔ 레지스트리 대조. value(원본 roster)가 마지막
  // 대조를 시작한 값과 다르면(참조 비교) 새 데이터가 도착한 것이므로
  // 대조를 새로 시작한다 — enrichExecutiveRoster가 끝나면 이 함수를
  // **같은 값**으로 다시 불러(재귀 재조회는 이 가드에 걸려 안 일어난다)
  // 강조(.mk)·안내문을 반영한다. execEnrichPromise는 이 함수 끝에서
  // 반환한다 — renderSection이 언제나 동기였던 기존 호출부는
  // undefined를 그대로 받아 영향이 없다.
  let execEnrichPromise;
  if (key === "executive_roster" && value !== EXEC_ROSTER_SOURCE) {
    EXEC_ROSTER_SOURCE = value;
    EXEC_MATCHES = {};
    EXEC_LOOKUPS = {};
    EXEC_STATUS = "idle";
    const myGen = ++EXEC_GEN;
    execEnrichPromise = enrichExecutiveRoster(blocks[0] && blocks[0].records, myGen);
  }
  if (key === "executive_roster" && EXEC_STATUS !== "idle" && EXEC_STATUS !== "done") {
    const note = document.createElement("p");
    note.className = "note";
    if (EXEC_STATUS === "failed") {
      // 침묵하면 "대조했는데 없었다"로 읽힌다(브리프) — 대조 자체를
      // 시도하지 못했다는 사실을 명시한다. 표시가 없다고 해서 등재가
      // 없다는 뜻이 아니다.
      note.textContent = "레지스트리 대조를 하지 못했습니다 — 조회 자체가 실패해 "
        + "표시가 비어 있는 것이며, 등재가 없다고 확인된 것이 아닙니다.";
    } else if (EXEC_STATUS === "partial") {
      note.textContent = "일부 임원은 레지스트리 대조를 하지 못했습니다 — 그 이름들은 "
        + "표시 여부와 무관하게 대조되지 않은 상태입니다.";
    }
    holder.appendChild(note);
  }
  // 파생 블록들을 원본 표들보다 먼저 붙인다 — "파생 블록은 기존 표 위에
  // 얹는다"(브리프, financials·dividends·fund_usage 공통)를 DOM 순서
  // (위쪽에 먼저 나온다)로 그대로 지킨다. 원본 표(아래 for 루프)는
  // 지우지 않는다.
  if (patternBlock) holder.appendChild(patternBlock.el);
  if (ratioBlock) holder.appendChild(ratioBlock.el);
  if (dividendBlock) holder.appendChild(dividendBlock.el);
  if (dividendDrainBlock) holder.appendChild(dividendDrainBlock.el);
  if (retainedEarningsBlock) holder.appendChild(retainedEarningsBlock.el);
  if (fundChainBlock) holder.appendChild(fundChainBlock.el);
  if (fundChangeBlock) holder.appendChild(fundChangeBlock.el);
  if (affiliateBlock) holder.appendChild(affiliateBlock.el);
  for (const block of blocks) {
    // 강조는 이 섹션 키(key)의 규칙(MARK_RULES[key])을 block.records(그
    // 표가 실제로 그린 레코드 — sourceGroupedBlocks 등이 source 제거·빈
    // 열 제거를 거친 뒤의 것)에 대해 계산한다. cellMarks는 sectionKey에
    // 등록된 규칙이 없거나 records가 없으면(예: debt_balance.by_kind처럼
    // table만 있고 records가 null인 블록) 빈 객체를 돌려줄 뿐이라 다른
    // 섹션·블록에 부작용이 없다.
    // SE-6 Task 3 — executive_roster는 서버 조회(비동기) 결과에 의존해
    // MARK_RULES(레코드 하나만 보는 동기 규칙)로 표현할 수 없다.
    // executiveRosterMarks(app.js)가 EXEC_MATCHES를 cellMarks와 같은
    // 좌표 형식으로 바꿔주므로, 그 결과를 그대로 tableEl에 넘겨 기존
    // SE-4g 강조 파이프라인(.mk + 범례)을 그대로 재사용한다.
    const marks = key === "executive_roster"
      ? executiveRosterMarks(block.records, EXEC_MATCHES)
      : (block.records ? cellMarks(block.records, key) : undefined);
    relayoutForMarks(block, marks);
    const el = blockEl(block, marks, block.records);
    // 차트는 표 위에 얹는다 — 표를 지우지 않는다. canvas 안의 숫자는
    // 복사도 검색도 안 되므로 정확한 값은 항상 표가 책임진다(브리프
    // 원칙). CHART_SPECS에 이 섹션 정의가 없거나 그릴 데이터가 없으면
    // renderChart가 false를 돌려주고 el을 건드리지 않는다. SIGNALS_DATA
    // (SE-4f Task 3)는 disclosures에서만 실제로 쓰인다 — 다른 키는
    // chartData(app.js)가 이 인자를 무시한다.
    //
    // SE-9 Task 4 — dividends는 이제 여러 그룹 블록(기간별)으로 온다.
    // 이 블록 루프 안에서 block.records(그 그룹 하나의 행)로 차트를
    // 부르면 CHART_SPECS.dividends가 그리려던 "연도·보고서구분별 추이"가
    // 그룹마다 x축 점 하나짜리 조각 차트 여러 개로 쪼개진다 — 브리프
    // 제약("그룹핑이 차트 입력을 바꾸지 않는다")과 충돌한다. 그래서
    // dividends만 여기서 차트를 그리지 않고, 루프가 끝난 뒤 원본 전체
    // (value, 그룹핑 이전)로 딱 한 번만 그린다(아래).
    if (key !== "dividends") {
      renderChart(el, key, block.records, SIGNALS_DATA);
    }
    holder.appendChild(el);
  }
  if (key === "dividends") {
    const chartWrap = document.createElement("div");
    if (renderChart(chartWrap, key, Array.isArray(value) ? value : [], SIGNALS_DATA)) {
      holder.appendChild(chartWrap);
    }
  }
  return execEnrichPromise;
}

/** doc:<접수번호> 섹션이 도착할 때마다 부른다(pollUntilDone).
 *
 * 승인된 방향: 원문 전체(text, 최대 20,000자)를 그때그때 새 h2 섹션으로
 * 쏟아내면 엔켐 실측 기준 34건 × 약 13만 자가 본문에 쌓인다
 * (docs/superpowers/plans/2026-07-27-se-4c-field-inventory.json) — 본문에는
 * "어떤 공시를 가져왔는지" 목록 하나만 남기고, 원문은 각 행의 접수번호를
 * 클릭해 우측 패널(openDocPanel, 기존 rcept_no 클릭 배선을 그대로 재사용
 * — table.keys.indexOf("rcept_no"))에서 본다.
 *
 * 섹션은 폴링마다 하나씩 도착한다(SE-2 청크 오케스트레이터) — 도착할
 * 때마다 누적 목록(DOC_LIST_ROWS)에 행을 하나 더하고 renderSection을
 * 다시 부른다. renderSection(key, value)은 같은 key로 다시 불리면
 * **교체**하므로(app.js/ui.js 공통 계약) 34번을 다시 불러도 34개의 목록이
 * 쌓이지 않고 매번 전체 목록 하나로 갱신된다.
 */
function addDocListEntry(rceptNo, value) {
  DOC_LIST_ROWS.push(docListRow(rceptNo, value));
  renderSection(DOC_LIST_KEY, DOC_LIST_ROWS.slice());
}

/** company_info(STAGE1_SPECS의 "헤더" 섹션)를 본문 맨 위 고정 박스
 *  (#company-info)에 그린다.
 *
 *  일반 섹션(renderSection)과 달리 groupHolder/sectionHolder(그룹별
 *  정렬)를 거치지 않는다 — 헤더는 어떤 그룹보다도 항상 맨 위에 고정이어야
 *  하기 때문이다(design 문서 §7.1: 섹션 0 "헤더" — 회사명·종목코드·업종·
 *  대표자·조회 시점). 이전에는 company_info도 다른 섹션과 똑같이
 *  renderSection()을 타서, SECTION_GROUPS에 없는 키라 "기타" 그룹으로
 *  밀려나 화면 맨 아래(약 18,000px 지점)에 나타났다.
 *
 *  값은 sectionBlocks()가 만드는 표를 그대로 쓴다 — 어떤 필드도 골라내거나
 *  숨기지 않는다(이 화면의 "데이터를 조용히 숨기지 않는다" 원칙과 동일).
 */
function renderCompanyInfo(value) {
  const box = document.getElementById("company-info");
  if (!box) return;
  while (box.firstChild) box.removeChild(box.firstChild);

  const h2 = document.createElement("h2");
  h2.textContent = label("company_info");
  box.appendChild(h2);

  const blocks = sectionBlocks(value, 0, "company_info");
  if (blocks.length === 0) {
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = "표시할 데이터가 없습니다.";
    box.appendChild(p);
  } else {
    for (const block of blocks) box.appendChild(blockEl(block));
  }

  // 그룹(groupHolder)을 거치지 않는 유일한 섹션이라 목차 항목도 여기서
  // 직접 추가한다. order=-1로 항상 그룹 목차(0 이상)보다 앞에 오게 해
  // 화면 맨 위 고정 위치와 목차 순서를 맞춘다. company_info는 폴링
  // 프로토콜상 한 번만 오지만(analyze() 쪽에서 fetched로 중복을 막는다),
  // 방어적으로 이미 이 박스를 가리키는 목차 항목이 있으면 다시 추가하지
  // 않는다 — 그러지 않으면 재호출 시 목차에 "기업 개요"가 중복된다.
  if (!TOC_ITEMS.some(function (it) { return it.el === box; })) {
    addTocEntry(label("company_info"), box, false, -1);
  }
}

/** 가져오지 못한 항목을 보여준다.
 *
 * 이 함수는 폴링마다(analyze()의 루프 한 바퀴마다) 불린다. **누적이 아니라
 * 교체**로 그린다 — 매번 새 노드를 append하면 같은 실패가 화면에 계속
 * 쌓인다(같은 섹션이 다음 폴링에서도 여전히 실패하면 특히 그렇다).
 * renderSection이 `sec-<key>` 고정 노드를 재사용해 교체하는 방식을
 * 그대로 따른다 — 고정 id(`sec-failures`)를 매번 비우고 다시 채운다.
 * 실패가 없어지면(다음 폴링에서 재시도 성공) 노드 자체를 지운다 — 빈
 * "0건" 문구가 남지 않게 한다.
 */
function renderFailures(failed) {
  // disclosures를 못 가져왔다는 사실은 실패 목록에만 있고 renderSection은
  // 영영 불리지 않는다 — 조달건 블록이 그 사실을 말할 수 있도록 여기서
  // 넘겨받는다(리뷰 지적 ②). 이미 목록을 받아 둔 뒤라면(다음 폴링에서
  // 재시도 성공) 덮어쓰지 않는다.
  const disclosuresFailed = (failed || []).some(function (f) {
    return f && f.key === "disclosures";
  });
  if (disclosuresFailed && !Array.isArray(DISCLOSURES_DATA)) {
    DISCLOSURES_FAILED = true;
    refreshFundChainForDisclosures();
  }

  const id = "sec-failures";
  let wrap = document.getElementById(id);
  if (!failed || failed.length === 0) {
    if (wrap) wrap.parentNode.removeChild(wrap);
    return;
  }
  if (!wrap) {
    wrap = document.createElement("div");
    wrap.id = id;
    wrap.className = "sec";
    document.getElementById("body").appendChild(wrap);
  }
  while (wrap.firstChild) wrap.removeChild(wrap.firstChild);
  const h = document.createElement("h2");
  h.textContent = "가져오지 못한 항목 " + formatCount(failed.length) + "건";
  wrap.appendChild(h);
  for (const f of failed) {
    const p = document.createElement("p");
    p.className = "note";
    // 서버가 이미 키를 스크럽해서 보낸다(runner._scrub).
    p.textContent = f.key + " — " + (f.error || "원인 미상");
    wrap.appendChild(p);
  }
}

// ── 작업 이어받기 — 상태는 서버(Postgres)에 있고, 브라우저는 job_id만 든다 ──
// LS_JOB 상수는 app.js에 있다(LS_DART_KEY·LS_SESSION과 같은 자리 —
// 브라우저 저장소 키는 한곳에 모아둔다).

/** 진행 중인 작업을 기억한다. 상태는 서버(Postgres)에 있으므로
 *  브라우저는 job_id만 들고 있으면 이어받을 수 있다. */
function rememberJob(jobId) {
  localStorage.setItem(LS_JOB, JSON.stringify({
    job_id: jobId, saved_at: Date.now(),
  }));
}

function forgetJob() {
  localStorage.removeItem(LS_JOB);
}

/** 분석이 성공적으로 끝났을 때 헤더 문구를 "N 분석을 시작합니다…"/
 *  "N 분석을 이어받는 중입니다…"에서 완료 문구로 바꾼다. 완료 상태가
 *  화면에 전혀 드러나지 않던 결함의 수정이다 — 호출부(analyze()·
 *  resumeIfAny())에서 자기 세대가 여전히 최신일 때만 부른다(아니면 더
 *  새 분석의 헤더를 덮어쓸 수 있다). */
function renderHeadDone(name) {
  const headEl = document.getElementById("head-name");
  if (headEl) headEl.textContent = name + " 분석 완료";
}

/** 작업 하나를 완료될 때까지 폴링한다. analyze()(막 시작한 작업)와
 *  resumeIfAny()(탭을 다시 연 뒤 이어받는 작업)가 이 하나의 루프를
 *  공유한다 — 폴링 로직이 두 곳에 따로 있으면 한쪽만 고치고 잊어버리는
 *  사고가 되풀이된다.
 *
 * 섹션은 한 번만 받는다 — 폴링 응답은 매번 완료된 키 전체를 주므로,
 * nextKeysToFetch로 아직 안 받은 키만 걸러 요청한다(SE-4a가 없앤
 * 737KB 재수신 문제가 여기서 되돌아올 수 있다). stalled가 true면
 * 즉시 멈춘다 — 계속 부르면 사용자의 DART 호출 한도만 태운다.
 *
 * fetched는 이 호출 하나에만 속하는 지역 상태다 — 모듈 전역에 두면
 * 같은 페이지에서 두 번째 작업을 폴링할 때 이전 작업에서 받은 키가
 * 그대로 남아 nextKeysToFetch가 []를 돌려주고 새 작업은 섹션이 하나도
 * 안 그려진다.
 *
 * gen은 호출자(analyze()/resumeIfAny())가 자기 시작 시점에 POLL_GEN에서
 * 찍어온 세대 번호다. 이어받기 루프가 도는 중에 사용자가 새 분석을
 * 시작하면(또는 그 반대) 두 루프가 동시에 돌면서 늦게 도착한 옛 루프의
 * 응답이 새 화면 위에 섞일 수 있다 — 매 확인 지점에서 gen이 여전히
 * POLL_GEN과 같은지 보고, 아니면(더 새 루프가 이미 시작됐으면) 그 자리에서
 * 조용히 멈춘다. 화면을 그리지도, 이어서 서버를 부르지도 않는다.
 *
 * 반환값 {resumable, done}은 호출자가 forgetJob()·renderHeadDone() 여부를
 * 정하는 데 쓴다 — resumable=true(네트워크 예외로 멈춘 경우)면 "새로고침
 * 하면 이어받습니다" 안내를 실제로 지킬 수 있도록 se_job을 지우지 않아야
 * 한다.
 */
async function pollUntilDone(jobId, dartKey, gen) {
  const fetched = new Set();

  for (;;) {
    try {
      // 이 루프를 시작한 이후 더 새 루프(analyze()·resumeIfAny()의 다른
      // 호출)가 시작됐으면 여기서 멈춘다 — 서버를 더 부르지도, 화면을
      // 더 그리지도 않는다.
      if (gen !== POLL_GEN) return { resumable: false, done: false };
      const step = await api("POST", "/api/se/analyze/" + jobId + "/step",
                             { token: await token(), dartKey: dartKey });
      if (gen !== POLL_GEN) return { resumable: false, done: false };
      const decision = pollDecision(step.body);

      const prog = await api("GET", "/api/se/analyze/" + jobId,
                             { token: await token() });
      if (gen !== POLL_GEN) return { resumable: false, done: false };
      if (prog.status === 200) {
        showProgress(prog.body);
        // 새로 완성된 섹션만 받는다. 요청이 실패한 키는 fetched에 넣지
        // 않는다 — FETCHED.add()를 요청 전에 해버리면 실패한 섹션이
        // 재시도되지도, 사용자에게 알려지지도 않고 조용히 사라진다.
        const sectionErrors = [];
        for (const key of nextKeysToFetch(prog.body.section_keys, [...fetched])) {
          const sec = await api(
            "GET",
            "/api/se/analyze/" + jobId + "/section/" + encodeURIComponent(key),
            { token: await token() }
          );
          if (gen !== POLL_GEN) return { resumable: false, done: false };
          // api()는 {status, body}를 준다. 섹션 키는 sec.body.key에 있다.
          if (sec.status === 200) {
            fetched.add(key);
            const secKey = sec.body.key || key;
            // company_info(헤더)는 그룹 정렬과 무관하게 항상 화면 맨
            // 위 고정이어야 한다(renderCompanyInfo 주석 참고) — 일반
            // renderSection(그룹별 정렬) 경로를 타지 않는다.
            const docRceptNo = docKeyRceptNo(secKey);
            if (secKey === "company_info") renderCompanyInfo(sec.body.value);
            // doc:<접수번호> 섹션은 각자 새 h2로 그리지 않고 하나의 목록
            // (addDocListEntry)에 모은다 — 34건이 34개 h2로 흩어지며 본문에
            // 원문 전체가 쏟아지던 문제의 수정(위 addDocListEntry 주석 참고).
            else if (docRceptNo) addDocListEntry(docRceptNo, sec.body.value);
            else renderSection(secKey, sec.body.value);
          } else {
            // 성공했을 때만 "받음"으로 친다 — 다음 폴링에서 자동 재시도된다.
            // 동시에 renderFailures로 넘겨 화면에도 보이게 한다(무한 재시도로
            // 사용자의 DART 호출 한도를 태우지 않도록, 재시도는 이미 도는
            // 폴링 루프에 얹을 뿐 별도로 더 부르지 않는다).
            sectionErrors.push({
              key: key,
              error: (sec.body && sec.body.error) || ("섹션 응답 오류(" + sec.status + ")"),
            });
          }
        }
        if (gen !== POLL_GEN) return { resumable: false, done: false };
        renderFailures((prog.body.failed || []).concat(sectionErrors));
      }
      if (decision.shouldStop) {
        if (decision.reason) showBar(decision.reason);
        // reason이 없으면 정상 완료(b.done===true)다 — stalled·서버 오류는
        // 항상 reason을 동반한다(pollDecision 계약).
        return { resumable: false, done: !decision.reason };
      }
    } catch (e) {
      // await token()이 갱신 실패로 던지면(세션 만료 등) token()이 이미
      // clearSession()+showGate()로 로그인 화면을 띄운 뒤다(e.userSafe가
      // true) — 여기서 또 안내할 필요가 없다. 그 외(fetch 자체가 던지는
      // 네트워크 예외 등)는 안내 없이 멈추면 진행률 바가 멈춘 채 남고
      // 사용자는 왜 멈췄는지 알 방법이 없다 — 최소한의 안내를 남긴다.
      // analyze()/resumeIfAny() 쪽으로 예외를 다시 던지지 않는다 — 그러면
      // 호출부마다 try/catch를 강제하게 되므로, 루프만 조용히 멈춘다.
      if (gen !== POLL_GEN) return { resumable: false, done: false };
      if (!(e && e.userSafe)) {
        showBar("연결이 끊겨 진행을 멈췄습니다. 새로고침하면 이어받습니다.");
        // 안내 문구가 실제로 이어받기를 약속하므로, 호출자가 se_job을
        // 지우지 않도록 resumable=true를 돌려준다 — 안 그러면 새로고침해도
        // 이어받지 못해 문구가 거짓말이 된다.
        return { resumable: true, done: false };
      }
      return { resumable: false, done: false };
    }
  }
}

/** 회사 입력 폼 핸들러 — 분석 버튼 클릭과 입력창 Enter가 공유한다.
 *
 * 연타 방지: 분석은 수 분이 걸린다. 진행 중에 또 누르면 작업이 중복
 * 생성돼 사용자의 DART 호출 한도를 태운다 — doLogin()의 LOGGING_IN과
 * 같은 방식으로 ANALYZING을 가드로 쓴다. 빈 입력은 서버로 보내지
 * 않는다. analyze()는 reject할 수 있으므로(token() 실패, 서버 오류 등)
 * 여기서 받아 화면 문구로 바꾼다 — 그러지 않으면 클릭 핸들러 밖에서
 * unhandled rejection으로 조용히 사라진다.
 */
async function doAnalyze() {
  if (ANALYZING) return;
  const msgEl = document.getElementById("analyze-msg");
  msgEl.textContent = "";
  const company = document.getElementById("company-input").value.trim();
  if (!company) {
    msgEl.textContent = "회사명 또는 종목코드를 입력하세요.";
    return;
  }
  // 서버 계약(se_server/api/handlers.py _clamp_years)은 1~5년이고 범위
  // 밖 값도 알아서 클램프하지만, select 옵션 자체를 1~5로만 두었으므로
  // 여기서는 숫자로만 안전하게 바꾼다(파싱 실패 시 기본 1년).
  const years = Number(document.getElementById("lookback-years").value) || 1;
  const btn = document.getElementById("analyze-btn");
  ANALYZING = true;
  if (btn) btn.disabled = true;
  try {
    await analyze(company, years);
  } catch (e) {
    msgEl.textContent = safeMessage(e, "분석을 시작하지 못했습니다.");
  } finally {
    ANALYZING = false;
    if (btn) btn.disabled = false;
  }
}

/** 분석 작업을 시작하고 완료될 때까지 진행률을 폴링한다. */
async function analyze(company, lookbackYears) {
  const tk = await token();
  const dartKey = localStorage.getItem(LS_DART_KEY) || "";
  const created = await api("POST", "/api/se/analyze", {
    token: tk, dartKey: dartKey,
    body: { company: company, lookback_years: lookbackYears },
  });
  if (created.status !== 201) {
    // renderHeadPlaceholder를 부르지 않으면 이전 회사의 본문(#body)·헤더
    // (#head-name)가 그대로 남은 채 오류 문구만 진행률 바에 얹힌다 —
    // renderHeadPlaceholder가 그 정리를 겸한다(#panel·#body를 비우는
    // 한 곳 정리 패턴, showGate()와 같은 이유).
    const msg = created.body.error || "분석을 시작하지 못했습니다";
    renderHeadPlaceholder(company, msg);
    showBar(msg);
    return;
  }
  const jobId = created.body.job_id;
  // 세대 토큰은 renderHeadPlaceholder·rememberJob 직전에 올린다 — 그
  // 사이에 await이 없으므로, 이어받기 루프 등 아직 돌고 있을 수 있는
  // 이전 루프가 그 틈에 한 번 더 그리거나 이 작업의 se_job을 지울 수
  // 없다(POLL_GEN 주석 참고).
  const gen = ++POLL_GEN;
  renderHeadPlaceholder(created.body.company);
  rememberJob(jobId);
  const result = await pollUntilDone(jobId, dartKey, gen);
  // gen이 여전히 최신일 때만 이 작업의 뒷정리를 한다 — 그 사이 더 새
  // 분석이 시작됐다면(gen !== POLL_GEN) 그 작업의 헤더·se_job을 건드리면
  // 안 된다.
  if (gen === POLL_GEN) {
    if (result.done) renderHeadDone(created.body.company);
    if (!result.resumable) forgetJob();
  }
}

/** 페이지를 열 때 이어받을 작업이 있으면 폴링을 재개한다.
 *
 * 저장된 job_id가 있어도 무조건 이어받지 않는다 — resumeTarget()이
 * RESUME_WINDOW_MS(12시간)보다 오래된 작업은 걸러낸다. 며칠 전 작업을
 * 조용히 이어받으면 사용자는 방금 새로 분석한 줄 오해한다.
 */
async function resumeIfAny() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(LS_JOB) || "null"); }
  catch (e) { saved = null; }
  const jobId = resumeTarget(saved, Date.now());
  if (!jobId) { forgetJob(); return false; }

  let prog;
  try {
    prog = await api("GET", "/api/se/analyze/" + jobId, { token: await token() });
  } catch (e) {
    // token() 갱신 실패는 이미 showGate()로 안내된 뒤다 — 조용히 포기한다.
    forgetJob();
    return false;
  }
  if (prog.status !== 200) { forgetJob(); return false; }   // 남의 것이거나 사라졌다

  // analyze()와 같은 이유로, 렌더와 rememberJob 격인 상태 표시 사이에
  // await 없이 세대를 올린다(POLL_GEN 주석 참고).
  const gen = ++POLL_GEN;
  renderHeadPlaceholder(prog.body.company, prog.body.company + " 분석을 이어받는 중입니다…");
  showBar("진행 중이던 분석을 이어받습니다 — " + prog.body.company);
  const result = await pollUntilDone(jobId, localStorage.getItem(LS_DART_KEY) || "", gen);
  if (gen === POLL_GEN) {
    if (result.done) renderHeadDone(prog.body.company);
    if (!result.resumable) forgetJob();
  }
  return true;
}

// ── 우측 슬라이드 패널 — 실명과 공시 원문 ──────────────────────────

/** 패널을 닫는다. 닫기 버튼과 Esc 키가 공유한다. */
function closePanel() {
  document.getElementById("panel").classList.remove("open");
}

/** 행위자(실명) 패널을 연다.
 *
 * actorLine()이 이름·status 라벨·동명이인 경고를 한 번에 만들어 준다 —
 * 여기서 셋을 따로 조립하면 한쪽만 그리는 경로가 생기고, 그 경로로
 * 실명이 경고 없이 나간다. 값은 전부 textContent로 넣는다.
 */
async function openActorPanel(company) {
  const box = document.getElementById("panel-body");
  const panel = document.getElementById("panel");
  while (box.firstChild) box.removeChild(box.firstChild);

  let r;
  try {
    r = await api("GET", "/api/se/actors?company=" + encodeURIComponent(company),
                  { token: await token() });
  } catch (e) {
    // await token()이 갱신 실패로 던지면(세션 만료 등) token()이 이미
    // clearSession()+showGate()로 로그인 화면을 띄운 뒤다. 여기서 예외를
    // 그냥 흘리면 이 함수는 클릭 핸들러에서 부른 것이라 아무도 catch하지
    // 않는다(unhandled rejection) — 패널이 열리지도 닫히지도 않은 채
    // 아무 일도 없었던 것처럼 보인다. 조용히 멈추는 대신 무언가 잘못됐다고
    // 알린다.
    box.textContent = safeMessage(e, "행위자 정보를 불러오지 못했습니다.");
    panel.classList.add("open");
    return;
  }

  const body = r.body || {};
  // actors가 배열이 아니면(null·문자열 등 예상 밖 응답) 그대로 순회하지
  // 않는다 — 문자열이면 글자 수만큼 빈 이름 카드가 그려지고, null이면
  // 예외가 나 패널이 열리지도 못한다. 조용히 넘어가지 않고 실패로 알린다.
  const actors = Array.isArray(body.actors) ? body.actors : null;
  if (r.status !== 200 || actors === null) {
    // pollDecision·openDocPanel과 같은 원칙 — 서버가 사용자에게 보여줘도
    // 되는 문구로 다듬어 보낸 body.error가 있으면 그대로 쓰고, 없을
    // 때만 일반 문구로 대체한다. 무조건 일반 문구로 덮으면 서버가 이미
    // 안내한 원인(예: "X-DART-Key 헤더가 필요합니다")이 사라진다.
    box.textContent = (typeof body.error === "string" && body.error)
      || "행위자 정보를 불러오지 못했습니다.";
    panel.classList.add("open");
    return;
  }

  for (const raw of actors) {
    const a = actorLine(raw);
    const d = document.createElement("div");
    const h = document.createElement("h3"); h.textContent = a.name; d.appendChild(h);
    const s = document.createElement("p"); s.className = "note";
    s.textContent = a.statusLabel; d.appendChild(s);
    const w = document.createElement("p"); w.className = "warn";
    w.textContent = a.warn; d.appendChild(w);
    const c = document.createElement("p");
    c.textContent = a.companies.join(", "); d.appendChild(c);
    box.appendChild(d);
  }
  if (actors.length === 0) {
    const empty = document.createElement("p");
    empty.className = "note";
    empty.textContent = "공개기록에 등재된 행위자가 없습니다.";
    box.appendChild(empty);
  }
  // 서버가 준 면책 문구를 그대로 붙인다. 서버가 빠뜨렸으면(예상 밖 응답)
  // 빈 문단만 남기지 않는다 — 아예 붙이지 않는다.
  if (body.disclaimer) {
    const dis = document.createElement("p");
    dis.className = "note";
    dis.textContent = body.disclaimer;
    box.appendChild(dis);
  }
  panel.classList.add("open");
}

// ── SE-6 Task 3 — 임원 명단 ↔ 레지스트리 대조 ───────────────────────

/** 임원 명단 전체를 레지스트리와 대조한다. 등기임원만 대상이라 보통
 *  7~16명(계획 문서 실측) — 순차로 이름마다 GET /api/se/actors?name=을
 *  부른다. 이름 하나가 실패해도 나머지는 계속 조회한다(브리프: "실패한
 *  이름은 건너뛰고 나머지는 그대로 렌더한다"). 세션 자체가 없거나
 *  네트워크가 통째로 죽어 **한 건도** 성공하지 못하면 EXEC_STATUS를
 *  "failed"로 남긴다 — 침묵하면 "대조했는데 없었다"로 읽힌다(브리프).
 *
 *  대조가 끝나면 renderSection(key, EXEC_ROSTER_SOURCE)을 **같은 값으로**
 *  다시 불러 강조(.mk)·안내문을 반영한다 — EXEC_ROSTER_SOURCE 참조가
 *  그대로이므로 renderSection 쪽 "새 값인가" 가드에 걸려 대조를 다시
 *  시작하지 않는다. 이 재호출 하나로 SE-4g 강조 파이프라인(cellMarks
 *  대신 executiveRosterMarks, app.js)을 그대로 재사용한다 — 표를 다시
 *  그리는 새 렌더 경로를 따로 만들지 않는다.
 *
 *  myGen(호출 시점의 EXEC_GEN)이 끝날 때 달라져 있으면(로그아웃·새 분석
 *  시작이 먼저 세대를 올렸으면) 결과를 버리고 조용히 멈춘다 — 안 그러면
 *  로그아웃 뒤 뒤늦게 돌아온 응답이 이미 비운 화면 위에 이전 사용자의
 *  실명을 다시 그릴 수 있다.
 */
async function enrichExecutiveRoster(records, myGen) {
  const names = [];
  const seen = new Set();
  (records || []).forEach(function (r) {
    const n = r && r["성명"];
    if (n && !seen.has(n)) { seen.add(n); names.push(n); }
  });

  let tok;
  try {
    tok = await token();
  } catch (e) {
    if (myGen === EXEC_GEN) {
      EXEC_STATUS = "failed";
      renderSection("executive_roster", EXEC_ROSTER_SOURCE);
    }
    return;
  }

  const lookups = {};
  let succeeded = 0;
  for (const name of names) {
    if (myGen !== EXEC_GEN) return;
    try {
      const r = await api("GET", "/api/se/actors?name=" + encodeURIComponent(name),
                          { token: tok });
      if (r.status === 200 && r.body && Array.isArray(r.body.actors)) {
        lookups[name] = r.body;
        succeeded++;
      }
    } catch (e) {
      // 이 이름만 건너뛴다 — 나머지는 계속 조회한다.
    }
  }
  if (myGen !== EXEC_GEN) return;

  EXEC_LOOKUPS = lookups;
  EXEC_MATCHES = executiveMatches(records, lookups);
  EXEC_STATUS = succeeded === 0 ? "failed" : (succeeded < names.length ? "partial" : "done");
  renderSection("executive_roster", EXEC_ROSTER_SOURCE);
}

// 패널에서 항상 보이는 자리에(접거나 숨기지 않고) 함께 적는 고정 문구
// 셋 — 계획 문서 "말할 수 있는 것과 없는 것"이 요구하는 그대로다.
const EXEC_NAMESAKE_WARN =
  "동명이인일 수 있습니다 — 이름 표기가 일치한다는 뜻이지 신원을 확인한 것이 아닙니다.";
const EXEC_VERIFY_STEPS =
  "확인 방법 — ① 근거 공시 원문을 직접 확인 ② 법인 등기 기록을 조회 ③ 회사 또는 본인에게 직접 문의";
const EXEC_NO_BIRTH_NOTE = "레지스트리에는 생년월이 없어 자동 대조가 불가능합니다.";

/** 임원 이름 클릭 → 우측 패널(SE-6 Task 3).
 *
 * openActorPanel(company)을 억지로 재사용하지 않고 별도 함수로 둔다 —
 * 쿼리 파라미터(company vs name)도, 패널에 보여줄 것(이 회사에서의
 * 직위·등기 여부·생년월 vs 없음)도 다르다. 다만 행위자 하나를 "이름·
 * status 라벨·경고"로 바꾸는 재료(actorLine, app.js)는 그대로 재사용한다
 * — 나눠 두면 한쪽만 그리는 경로가 생기고, 그 경로로 실명이 경고 없이
 * 나간다(openActorPanel 주석과 같은 이유).
 *
 * **동명이인 경고(EXEC_NAMESAKE_WARN)·확인 방법 3가지(EXEC_VERIFY_STEPS)·
 * 생년월 미보유 안내(EXEC_NO_BIRTH_NOTE)는 접거나 숨기지 않는다** — 매칭이
 * 하나라도 있을 때 항상 같은 자리에 렌더한다(계획 문서: "동명이인 경고 —
 * 접거나 툴팁에 숨기지 않는다").
 *
 * 근거 링크는 `url`로만 연다(`rcept_no`는 레지스트리 1,342건 중 3%뿐이라
 * 내부 원문 패널에 의존할 수 없다). dartDisclosureLink(app.js)가 호스트를
 * dart.fss.or.kr로 검증한 뒤에만 앵커를 만든다 — 그 외 호스트는 텍스트로만
 * 남겨(레지스트리는 외부 Notion 데이터라 그대로 링크를 신뢰하지 않는다)
 * 사용자가 실수로 임의 사이트로 이동하지 않게 한다.
 */
async function openExecutivePanel(row) {
  const box = document.getElementById("panel-body");
  const panel = document.getElementById("panel");
  while (box.firstChild) box.removeChild(box.firstChild);

  const r0 = row || {};
  const name = typeof r0["성명"] === "string" ? r0["성명"] : "";

  const h = document.createElement("h3");
  h.textContent = name;
  box.appendChild(h);

  // 이 회사에서의 직위·등기 여부·생년월 — 네트워크 없이 이미 갖고 있는
  // 값이다(exctvSttus 원문 필드, SE-6 Task 2b가 화면까지 보냈다). 아래
  // 조회가 실패해도 이 정보는 남는다.
  const role = document.createElement("p");
  role.className = "note";
  role.textContent = "이 회사에서: 직위 " + (r0.ofcps || "정보 없음")
    + " · 등기 여부 " + (r0.rgist_exctv_at || "정보 없음")
    + " · 생년월 " + (r0.birth_ym || "정보 없음");
  box.appendChild(role);

  let resp;
  try {
    resp = await api("GET", "/api/se/actors?name=" + encodeURIComponent(name),
                     { token: await token() });
  } catch (e) {
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = safeMessage(e, "레지스트리를 조회하지 못했습니다 — 대조를 시도하지 못한 상태입니다.");
    box.appendChild(p);
    panel.classList.add("open");
    return;
  }

  const body = resp.body || {};
  const actors = Array.isArray(body.actors) ? body.actors : null;
  if (resp.status !== 200 || actors === null) {
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = (typeof body.error === "string" && body.error)
      || "레지스트리를 조회하지 못했습니다 — 대조를 시도하지 못한 상태입니다.";
    box.appendChild(p);
    panel.classList.add("open");
    return;
  }

  if (actors.length === 0) {
    const empty = document.createElement("p");
    empty.className = "note";
    empty.textContent = "레지스트리에 같은 이름이 없습니다.";
    box.appendChild(empty);
  } else {
    for (const raw of actors) {
      const a = actorLine(raw);
      const d = document.createElement("div");
      const s = document.createElement("p"); s.className = "note";
      s.textContent = a.statusLabel; d.appendChild(s);
      const w = document.createElement("p"); w.className = "warn";
      w.textContent = a.warn; d.appendChild(w);
      const c = document.createElement("p"); c.className = "note";
      c.textContent = "레지스트리 등재 회사: " + a.companies.join(", ");
      d.appendChild(c);
      if (raw && typeof raw.evidence === "string" && raw.evidence) {
        const ev = document.createElement("p"); ev.className = "note";
        ev.textContent = "근거: " + raw.evidence;
        d.appendChild(ev);
      }
      const dartUrl = dartDisclosureLink(raw && raw.url);
      if (dartUrl) {
        const link = document.createElement("a");
        link.href = dartUrl;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = "근거 공시 원문 (DART)";
        d.appendChild(link);
      } else if (raw && typeof raw.url === "string" && raw.url) {
        // dart.fss.or.kr이 아닌 호스트는 앵커로 만들지 않는다 — 레지스트리는
        // 외부(Notion) 데이터라 그대로 링크를 신뢰하지 않는다(계획 문서).
        const up = document.createElement("p"); up.className = "note";
        up.textContent = "근거 링크(출처 미확인): " + raw.url;
        d.appendChild(up);
      }
      box.appendChild(d);
    }

    // 동명이인 경고 + 확인 방법 + 생년월 미보유 안내 — 매칭이 있을 때만,
    // 그러나 항상 보이는 자리에(접지도 숨기지도 않는다).
    const warnBox = document.createElement("div");
    warnBox.className = "warn";
    [EXEC_NAMESAKE_WARN, EXEC_VERIFY_STEPS, EXEC_NO_BIRTH_NOTE].forEach(function (t) {
      const p = document.createElement("p");
      p.textContent = t;
      warnBox.appendChild(p);
    });
    box.appendChild(warnBox);
  }

  if (body.disclaimer) {
    const dis = document.createElement("p");
    dis.className = "note";
    dis.textContent = body.disclaimer;
    box.appendChild(dis);
  }
  panel.classList.add("open");
}

/** documentBlocks()(app.js)가 만든 블록 하나를 DOM으로 그린다.
 *
 * 표 블록은 어떤 셀이 헤더인지 판정하지 않는다 — documentBlocks는 구조만
 * 복원할 뿐 요약·판정을 하지 않으므로(v0.8.5 원칙), <thead> 없이 모든
 * 행을 그대로 <tr><td>로 나열한다. 값은 전부 textContent로만 넣는다 —
 * 공시 원문은 사용자 데이터라 한 줄로 스크립트가 실행되면 안 된다.
 */
function docBlockEl(block) {
  if (block.kind === "table") {
    const table = document.createElement("table");
    const tbody = table.createTBody();
    block.rows.forEach(function (row) {
      const tr = tbody.insertRow();
      row.forEach(function (c) {
        const td = tr.insertCell();
        td.textContent = c;
      });
    });
    return table;
  }
  const p = document.createElement("p");
  p.textContent = block.text;
  return p;
}

/** 공시 원문 패널을 연다. DART 키는 X-DART-Key 헤더로만 보낸다. */
async function openDocPanel(rceptNo) {
  const box = document.getElementById("panel-body");
  const panel = document.getElementById("panel");
  box.innerHTML = "";

  let r;
  try {
    r = await api("GET", "/api/se/disclosure/" + encodeURIComponent(rceptNo),
                  { token: await token(),
                    dartKey: localStorage.getItem(LS_DART_KEY) || "" });
  } catch (e) {
    // openActorPanel과 같은 이유 — await token() 실패가 클릭 핸들러
    // 밖으로 조용히 새 나가는 것을 막는다.
    box.textContent = safeMessage(e, "공시 원문을 불러오지 못했습니다.");
    panel.classList.add("open");
    return;
  }

  const body = r.body || {};
  // 공시 원문 — 반드시 textContent다(docBlockEl 참고). 200인데 text가
  // 문자열이 아니면(예상 밖 응답) 리터럴 "undefined"를 그대로 보여주는
  // 대신 실패로 취급한다 — "원문 0자 중 일부입니다" 같은 앞뒤 안 맞는
  // 안내도 막는다.
  const text = typeof body.text === "string" ? body.text : "";
  if (r.status === 200 && text) {
    // 한 덩어리 <pre>는 원문에 담긴 파이프 구분 표를 사람이 읽을 수 없게
    // 만든다 — documentBlocks(app.js)가 복원한 문단·표 구조 그대로
    // 그린다(요약이 아니라 구조 복원만, v0.8.5 원칙).
    for (const block of documentBlocks(text)) {
      box.appendChild(docBlockEl(block));
    }
    if (body.truncated) {
      const n = document.createElement("p");
      n.className = "note";
      n.textContent = "원문 " + formatCount(body.char_count) + "자 중 일부입니다.";
      box.appendChild(n);
    }
  } else {
    // 오류 경로다 — 공시 원문(실명 아님)만 다루는 패널이라 여기엔 행위자
    // 면책 문구가 필요 없다.
    const p = document.createElement("p");
    p.textContent = (typeof body.error === "string" && body.error)
      || "원문을 불러오지 못했습니다.";
    box.appendChild(p);
  }
  panel.classList.add("open");
}

document.addEventListener("DOMContentLoaded", init);
