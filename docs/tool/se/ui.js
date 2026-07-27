"use strict";

let CONFIG = null;      // {supabase_url, supabase_anon_key}
let SESSION = null;     // {access_token, refresh_token, expires_at}
let LOGGING_IN = false; // 로그인 버튼 연타로 중복 인증 요청이 나가는 것을 막는다
let CURRENT_COMPANY = null; // 지금 화면에 떠 있는 분석의 회사명 — 행위자
                             // 패널을 "이 회사"로 열 때 쓴다(누가 사람인지
                             // 추측하지 않고, 헤더 버튼 하나로만 연다).

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
  // 패널이 열린 채 남으면 로그인 화면 위로 이전 사용자의 실명이 계속
  // 보인다 — #panel은 #main 밖(형제 노드)이라 showGate()가 #main을
  // 숨겨도 안 가려진다. 내용까지 비워야 DOM에도 실명이 남지 않는다.
  closePanel();
  const panelBox = document.getElementById("panel-body");
  if (panelBox) panelBox.textContent = "";
  CURRENT_COMPANY = null;
  const actorBtn = document.getElementById("actor-btn");
  if (actorBtn) actorBtn.hidden = true;
  showGate();
}

/** 저장된 세션이 있으면 갱신을 시도해 자동 로그인, 없거나 실패하면 로그인 화면. */
async function init() {
  document.getElementById("login").addEventListener("click", doLogin);
  document.getElementById("logout").addEventListener("click", doLogout);
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
  } catch (e) {
    // token()이 자체 실패 경로에서 이미 정리·안내를 했을 수 있지만(같은 e가
    // 다시 올라옴), loadConfig() 자체가 실패하는 경우엔 여기가 유일한 안내
    // 지점이라 다시 한번 확실히 정리한다.
    clearSession();
    showGate(safeMessage(e, ""));
  }
}

// ── 분석 실행 + 진행률 폴링 ────────────────────────────────────────

// Task 5에서 실제 구현으로 대체된다. 지금은 루프가 돌아가게만 한다.
function showBar(msg) { document.getElementById("bar").textContent = msg; }
function showProgress(p) {
  showBar(p.company + " — " + formatCount(p.finished) + "/" + formatCount(p.total));
}
function renderHeadPlaceholder(name) {
  document.getElementById("head-name").textContent = name + " 분석을 시작합니다…";
  CURRENT_COMPANY = name;
  const btn = document.getElementById("actor-btn");
  if (btn) btn.hidden = false;
}

/** 표를 DOM으로 만든다. 값은 전부 textContent로 넣는다 —
 *  공시 원문과 실명이 그대로 들어오는 자리다.
 *
 *  `rcept_no` 열의 셀만 클릭 가능하게 만든다 — table.keys(toTable()이
 *  라벨과 나란히 남긴 원본 키)로 정확히 그 열을 찾는다. 어느 열이 공시
 *  제목인지, 어느 열이 사람 이름인지는 추측하지 않는다 — 확인되지 않은
 *  필드명을 코드에 박는 것이 이 프로젝트에서 반복해서 사고를 낸 방식이고,
 *  rcept_no만 LABELS·2단 섹션 키(`doc:<접수번호>`)로 이미 확인된 필드다. */
function tableEl(table) {
  const t = document.createElement("table");
  const thead = t.createTHead().insertRow();
  for (const c of table.columns) {
    const th = document.createElement("th");
    th.textContent = c;
    thead.appendChild(th);
  }
  const rceptCol = Array.isArray(table.keys) ? table.keys.indexOf("rcept_no") : -1;
  const tb = t.createTBody();
  for (const row of table.rows) {
    const tr = tb.insertRow();
    row.forEach(function (v, i) {
      const td = tr.insertCell();
      td.textContent = v;
      if (i === rceptCol && v) {
        td.className = "doc";
        td.addEventListener("click", function () { openDocPanel(v); });
      }
    });
  }
  return t;
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
  h2.textContent = key;
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

function renderFailures(failed) { /* Task 5 */ }

/** 분석 작업을 시작하고 완료될 때까지 진행률을 폴링한다.
 *
 * 섹션은 한 번만 받는다 — 폴링 응답은 매번 완료된 키 전체를 주므로,
 * nextKeysToFetch로 아직 안 받은 키만 걸러 요청한다(SE-4a가 없앤
 * 737KB 재수신 문제가 여기서 되돌아올 수 있다). stalled가 true면
 * 즉시 멈춘다 — 계속 부르면 사용자의 DART 호출 한도만 태운다.
 */
async function analyze(company, lookbackYears) {
  const tk = await token();
  const dartKey = localStorage.getItem(LS_DART_KEY) || "";
  const created = await api("POST", "/api/se/analyze", {
    token: tk, dartKey: dartKey,
    body: { company: company, lookback_years: lookbackYears },
  });
  if (created.status !== 201) {
    showBar(created.body.error || "분석을 시작하지 못했습니다");
    return;
  }
  const jobId = created.body.job_id;
  renderHeadPlaceholder(created.body.company);

  // 이 작업 하나에만 속하는 상태다 — 모듈 전역에 두면 같은 페이지에서
  // analyze()를 두 번째 부를 때 이전 작업에서 받은 키가 그대로 남아
  // nextKeysToFetch가 []를 돌려주고 새 작업은 섹션이 하나도 안 그려진다.
  const fetched = new Set();

  for (;;) {
    try {
      const step = await api("POST", "/api/se/analyze/" + jobId + "/step",
                             { token: await token(), dartKey: dartKey });
      const decision = pollDecision(step.body);

      const prog = await api("GET", "/api/se/analyze/" + jobId,
                             { token: await token() });
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
        renderFailures((prog.body.failed || []).concat(sectionErrors));
      }
      if (decision.shouldStop) {
        if (decision.reason) showBar(decision.reason);
        break;
      }
    } catch (e) {
      // await token()이 갱신 실패로 던지면(세션 만료 등) token()이 이미
      // clearSession()+showGate()로 로그인 화면을 띄운 뒤다. 여기서
      // analyze()를 reject시키면 호출부마다 try/catch를 강제하게 되므로,
      // 루프만 조용히 멈춘다.
      break;
    }
  }
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
    box.textContent = "행위자 정보를 불러오지 못했습니다.";
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
