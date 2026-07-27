"use strict";

let CONFIG = null;      // {supabase_url, supabase_anon_key}
let SESSION = null;     // {access_token, refresh_token, expires_at}

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
  if (r.status !== 200) throw new Error("서버 설정을 불러오지 못했습니다");
  CONFIG = r.body;
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
    throw new Error("로그인에 실패했습니다. 이메일과 비밀번호를 확인하세요.");
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

/** 만료됐으면 갱신하고 유효한 access_token을 돌려준다. */
async function token() {
  if (!SESSION) throw new Error("로그인이 필요합니다");
  if (Date.now() < SESSION.expires_at) return SESSION.access_token;
  saveSession(await gotrue("refresh_token", { refresh_token: SESSION.refresh_token }));
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

function getDartKey() {
  return localStorage.getItem(LS_DART_KEY) || "";
}

function saveDartKey(key) {
  localStorage.setItem(LS_DART_KEY, key);
}

/** 로그인 버튼 핸들러 — 이메일·비밀번호로 GoTrue 인증 후 DART 키를 저장한다. */
async function doLogin() {
  const msgEl = document.getElementById("gate-msg");
  msgEl.textContent = "";
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;
  const dartKey = document.getElementById("dartkey").value.trim();
  if (!email || !password) {
    msgEl.textContent = "이메일과 비밀번호를 입력하세요.";
    return;
  }
  try {
    if (!CONFIG) await loadConfig();
    const tok = await gotrue("password", { email: email, password: password });
    saveSession(tok);
    if (dartKey) saveDartKey(dartKey);
    showMain();
  } catch (e) {
    msgEl.textContent = (e && e.message) || "로그인에 실패했습니다.";
  }
}

/** 로그아웃 — 로컬 세션만 지운다(서버에는 상태가 없다). DART 키는 유지한다. */
function doLogout() {
  SESSION = null;
  localStorage.removeItem(LS_SESSION);
  showGate();
}

/** 저장된 세션이 있으면 갱신을 시도해 자동 로그인, 없거나 실패하면 로그인 화면. */
async function init() {
  document.getElementById("login").addEventListener("click", doLogin);
  document.getElementById("logout").addEventListener("click", doLogout);

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
    localStorage.removeItem(LS_SESSION);
    SESSION = null;
    showGate();
  }
}

document.addEventListener("DOMContentLoaded", init);

if (typeof module !== "undefined" && module.exports) {
  module.exports = { api, loadConfig, gotrue, saveSession, token };
}
