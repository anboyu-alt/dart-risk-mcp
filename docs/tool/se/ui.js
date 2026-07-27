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
let POLL_GEN = 0; // 폴링 세대 토큰. analyze()·resumeIfAny()가 폴링을 새로
                   // 시작할 때마다 올린다. pollUntilDone()은 매 확인 지점에서
                   // 자기 세대를 이 값과 비교해, 더 새 루프가 시작된 뒤에는
                   // 스스로 멈춘다 — 렌더도 하지 않고 forgetJob()도 부르지
                   // 않는다. 이어받기 루프가 도는 중 새 분석이 시작되면
                   // (또는 그 반대) 늦게 도착한 옛 루프의 응답이 새 화면
                   // 위에 섞이거나, 옛 루프가 새 작업의 se_job을 지워버리는
                   // 사고를 막기 위해서다.

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
  CURRENT_COMPANY = null;
  const actorBtn = document.getElementById("actor-btn");
  if (actorBtn) actorBtn.hidden = true;
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
 *  있다" 두 성질을 함께 지킨다. */
function tableEl(table) {
  const frag = document.createDocumentFragment();

  if (Array.isArray(table.caption) && table.caption.length > 0) {
    const cap = document.createElement("div");
    cap.className = "cap";
    table.caption.forEach(function (c, i) {
      if (i > 0) cap.appendChild(document.createTextNode(" · "));
      const b = document.createElement("b");
      b.textContent = c.label;
      cap.appendChild(b);
      cap.appendChild(document.createTextNode(": "));
      if (c.key === "rcept_no" && c.value) {
        const span = document.createElement("span");
        span.className = "doc";
        span.textContent = c.value;
        span.addEventListener("click", function () { openDocPanel(c.value); });
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
        detailTd.appendChild(document.createTextNode(": " + pair[1]));
      });

      btn.addEventListener("click", function () {
        detailTr.hidden = !detailTr.hidden;
      });
    }
  });
  frag.appendChild(t);
  return frag;
}

/** 그룹 제목에 해당하는 컨테이너를 찾거나 만든다. SECTION_GROUPS 정의
 *  순서를 따라 DOM 위치를 정한다 — 그룹은 섹션이 도착하는 순서(=완료
 *  순서)와 무관하게 항상 같은 자리에 나와야 한다. 목록에 없는 제목
 *  ("기타" 등, groupOrderIndex가 맨 뒤로 보낸다)은 이미 자리 잡은
 *  그룹들 뒤에 붙는다. */
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
  wrap.appendChild(holder);

  const body = document.getElementById("body");
  const idx = groupOrderIndex(title);
  let before = null;
  for (const child of body.children) {
    if (groupOrderIndex(child.dataset.title) > idx) { before = child; break; }
  }
  body.insertBefore(wrap, before);
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
function sectionHolder(key) {
  const id = "sec-" + key;
  let holder = document.getElementById(id);
  if (holder) return holder;

  const group = groupHolder(groupTitleFor(key));

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
  return holder;
}

/** 블록 하나(소제목 + 표, 또는 소제목 + 원문 텍스트)를 DOM으로 만든다. */
function blockEl(block) {
  const wrap = document.createElement("div");
  if (block.title) {
    const h3 = document.createElement("h3");
    h3.textContent = block.title;
    wrap.appendChild(h3);
  }
  if (block.table) {
    wrap.appendChild(tableEl(block.table));
  } else if (typeof block.text === "string") {
    // 표 셀(max-width:280px)에 욱여넣기엔 너무 긴 문자열 — 별도 문단으로
    // 그대로 보여준다. textContent만 쓴다.
    const p = document.createElement("p");
    p.textContent = block.text;
    wrap.appendChild(p);
  } else {
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = "표시할 데이터가 없습니다.";
    wrap.appendChild(p);
  }
  return wrap;
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
  while (holder.firstChild) holder.removeChild(holder.firstChild);

  const blocks = sectionBlocks(value);
  if (blocks.length === 0) {
    const p = document.createElement("p");
    p.className = "note";
    p.textContent = "표시할 데이터가 없습니다.";
    holder.appendChild(p);
    return;
  }
  for (const block of blocks) holder.appendChild(blockEl(block));
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
            renderSection(sec.body.key || key, sec.body.value);
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
  box.innerHTML = "";

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
  const p = document.createElement("pre");
  p.style.whiteSpace = "pre-wrap";
  // 공시 원문 — 반드시 textContent다. 200인데 text가 문자열이 아니면
  // (예상 밖 응답) 리터럴 "undefined"를 그대로 보여주는 대신 실패로
  // 취급한다 — "원문 0자 중 일부입니다" 같은 앞뒤 안 맞는 안내도 막는다.
  const text = typeof body.text === "string" ? body.text : "";
  if (r.status === 200 && text) {
    p.textContent = text;
    box.appendChild(p);
    if (body.truncated) {
      const n = document.createElement("p");
      n.className = "note";
      n.textContent = "원문 " + formatCount(body.char_count) + "자 중 일부입니다.";
      box.appendChild(n);
    }
  } else {
    // 오류 경로다 — 공시 원문(실명 아님)만 다루는 패널이라 여기엔 행위자
    // 면책 문구가 필요 없다.
    p.textContent = (typeof body.error === "string" && body.error)
      || "원문을 불러오지 못했습니다.";
    box.appendChild(p);
  }
  panel.classList.add("open");
}

document.addEventListener("DOMContentLoaded", init);
