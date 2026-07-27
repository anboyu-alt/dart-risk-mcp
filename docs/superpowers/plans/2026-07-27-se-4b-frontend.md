# SE-4b: 프론트엔드 — 로그인부터 화면까지 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 인가된 사용자가 로그인해 회사를 입력하면, 분석이 진행되는 동안 화면이 위에서부터 채워지고, 인물 이름과 공시 제목을 클릭하면 우측 패널이 열리는 페이지를 만든다.

**Architecture:** 기존 공개 뷰어(`docs/tool/index.html`)와 같은 방식 — 빌드 스텝 없는 단일 페이지 + 순수 JS. 다른 점은 순수 로직을 `app.js`로 분리해 **node로 단위 테스트**한다는 것이다. `docs/tool/` 아래에 두므로 `/api/se/*`와 **같은 오리진**이고 CORS가 필요 없다.

**Tech Stack:** HTML + 순수 JS(프레임워크·빌드·CDN 없음), Supabase GoTrue REST 직접 호출, 테스트는 `unittest` + `node` 서브프로세스

## Global Constraints

- **외부 CDN·빌드 스텝·프레임워크·npm 의존성 금지.** 기존 뷰어와 동일하게 정적 파일만 올린다. `supabase-js`도 쓰지 않는다 — GoTrue REST를 직접 부른다.
- **`dart_risk_mcp/` core를 수정하지 않는다.**
- **`se_server/`의 API 계약을 바꾸지 않는다.** SE-4a가 확정한 7개 경로를 소비만 한다. 계약을 바꿔야 할 이유를 발견하면 **멈추고 보고한다** — 화면 편의로 서버를 고치면 SE-4a에서 없앤 문제가 되돌아온다.
- **service_role 키가 페이지에 들어가면 안 된다.** `/api/se/config`가 주는 **anon 키만** 쓴다.
- **DART 키는 브라우저 `localStorage`에만.** 서버에 저장하지 않고, `X-DART-Key` **헤더로만** 보낸다. 쿼리스트링 금지.
- **한 번 받은 섹션은 다시 받지 않는다.** SE-4a가 폴링 737KB를 없앤 이유가 이것이다. 되돌리면 안 된다.
- **실명에는 `status`와 동명이인 면책이 항상 동반된다.** 어떤 렌더 경로로도 빠지면 안 된다.
- **점수·등급을 만들지 않는다**(v0.8.5). "위험", "의심", "고위험" 같은 판정 어휘를 화면 문구로 쓰지 않는다.
- **사용자·API 데이터는 `textContent`로만 DOM에 넣는다.** 데이터가 섞인 `innerHTML` 금지 — 공시 원문과 실명이 그대로 들어오는 페이지다.
- 주석·UI 문구는 **한국어**. 테스트는 `unittest.TestCase`, 실제 네트워크 호출 없음.

## 선행 조건

**SE-4a가 머지되어 프로덕션에서 동작 중이다**(PR #111). 7개 경로가 모두 살아 있다.

---

## 확인된 사실 (추측이 아니라 실측·정독)

계획을 쓰기 전에 확인한 것들이다. 여기 적힌 값은 그대로 써도 된다.

| 항목 | 확인 결과 |
|---|---|
| 배포 루트 | `vercel.json`의 `outputDirectory: docs/tool` → `docs/tool/se/`는 `/se/`로 서빙된다 |
| CORS | 페이지와 `/api/se/*`가 **같은 오리진** → 프리플라이트 없음. SE-4a 최종 리뷰가 남긴 제약이 이 배치로 해소된다 |
| `.vercelignore` | `!docs` + `docs/*` + `!docs/tool` → `docs/tool` 하위는 배포에 포함된다. **새 최상위 디렉토리를 만들면 안 된다** |
| 기존 뷰어 | 단일 HTML 68,001자, 외부 스크립트 0개, CSS 변수 22개, `localStorage` 키 `dart_tool_key`/`dart_tool_relay`/`dart_tool_recent` |
| node | v24.14.0 사용 가능 → 순수 JS 함수를 pytest에서 검증할 수 있다 |
| 섹션 그룹 | `se_server/jobs/registry.py`의 `STAGE1_SPECS[*].section`이 이미 화면 그룹을 갖고 있다: `헤더`/`자금`/`재무`/`지배구조`/`감사부실` |

### 소비할 API 계약 (SE-4a 확정)

```
POST /api/se/analyze                       201 {job_id, company, total} | 400 404
POST /api/se/analyze/{id}/step             200 {done, processed, finished, total, stalled} | 400 404 500
GET  /api/se/analyze/{id}                  200 {job_id, company, status, finished, total,
                                                failed:[{key,error}], section_keys:[...]} | 404
GET  /api/se/analyze/{id}/section/{key}    200 {key, value} | 404
GET  /api/se/disclosure/{rcept_no}         200 {rcept_no, text, char_count, truncated} | 400 404 502
GET  /api/se/actors?company=               200 {company, actors:[{name,status,companies,evidence}],
                                                disclaimer} | 400 502
GET  /api/se/config                        200 {supabase_url, supabase_anon_key}   ← 인증 불필요
```

1단 섹션 키 13개: `company_info` `disclosures` `fund_usage` `affiliates` `financials` `indicators` `shareholders` `insider_timeline` `executive_roster` `audit_history` `debt_balance` `distress` `dividends`.
2단 섹션 키: `doc:<접수번호>` (공시 원문). **`encodeURIComponent`로 인코딩해도 동작한다**(SE-4a에서 고침).

---

## 범위 결정 — 무엇을 넣고 무엇을 미루는가

스펙 §7.1은 본문 섹션 8개를 정의한다. 이번 계획은 그중 **데이터가 이미 있는 것만** 만든다.

| 스펙 § | 이번 계획 | 근거 |
|---|---|---|
| 0 헤더 | ✅ | `company_info` 그대로 |
| ① 계획 vs 실제 요약 | ✅ | `fetch_fund_usage`가 이미 플래그(`FUND_DIVERSION`·`FUND_UNREPORTED`)를 계산해 돌려준다 — 렌더만 하면 된다 |
| ② **자금 체인** | ❌ **SE-4c로 미룸** | `fund_usage`↔`affiliates`↔`financials` 조인 + 금액 비례 폭 계산이 필요하다. 파생 로직이며, **파이썬에 두고 pytest로 검증해야 한다** |
| ③ **자금 시계열 레인** | ❌ **SE-4c로 미룸** | 같은 이유 |
| ④ 재무 이상 | ✅ | `financials`·`indicators` |
| ⑤ 지배구조 | ✅ | `shareholders`·`insider_timeline`·`executive_roster` |
| ⑥ 감사·부실 | ✅ | `audit_history`·`debt_balance`·`distress`·`dividends` |
| ⑦ 공시 원문 열람 | ✅ | `disclosures` + `/api/se/disclosure` |
| ⑧ 출처·면책 | ✅ | 고정 문구 |

**②③을 미루는 이유를 분명히 한다.** 이 둘만이 "가공"이고 나머지는 "표시"다. 가공 로직을 JS에 두면 이 저장소의 유일한 품질 장치인 pytest 밖으로 나간다. SE-4a에서 발견된 결함 4건은 **전부 테스트가 잡았다.** 가장 틀리기 쉬운 부분을 테스트가 닿지 않는 곳에 두는 것은 그 경험과 정면으로 어긋난다.

**대신 이번 계획은 열어서 쓸 수 있는 화면을 낸다.** SE-1~4a는 화면이 없었다. ②③이 빠져도 로그인·분석·13개 섹션·실명 패널·원문 열람이 동작하는 페이지가 나온다.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `docs/tool/se/index.html` | 페이지 골격·스타일·DOM. 로직은 두지 않는다 |
| `docs/tool/se/app.js` | **순수 로직** — 폴링 계획, 섹션 그룹핑, 레코드 표 변환, 라벨 맵. node로 테스트된다 |
| `docs/tool/se/ui.js` | DOM 조작·네트워크. 순수하지 않으므로 정적 검사만 받는다 |
| `tests/se/test_se_page_assets.py` | 정적 검사 — CDN 부재, 비밀 부재, `innerHTML` 금지, 판정 어휘 부재 |
| `tests/se/test_se_app_js.py` | node 서브프로세스로 `app.js` 순수 함수 검증 |

**`app.js`가 브라우저와 node 양쪽에서 로드되는 방식** (빌드 없이):

```js
// 파일 끝. 브라우저에는 module이 없으므로 이 줄은 무시된다.
// node는 테스트가 순수 함수를 부르기 위해 이 export를 쓴다.
if (typeof module !== "undefined" && module.exports) {
  module.exports = { SECTION_GROUPS, LABELS, nextKeysToFetch, toTable, actorLine, formatCount };
}
```

---

### Task 1: 페이지 골격 + 설정 로드 + 로그인

**Files:**
- Create: `docs/tool/se/index.html`, `docs/tool/se/app.js`, `docs/tool/se/ui.js`
- Test: `tests/se/test_se_page_assets.py`

**Interfaces:**
- Produces: `app.js`가 `LS_DART_KEY = "se_dart_key"`, `LS_SESSION = "se_session"` 상수를 export한다. Task 2~5가 쓴다.
- Produces: `ui.js`의 `api(method, path, {token, dartKey, body})` → `{status, body}`. 이후 모든 태스크가 이 하나만 쓴다.

**로그인 흐름 (GoTrue REST 직접 호출 — SDK 없이):**

```
1. GET /api/se/config              → {supabase_url, supabase_anon_key}   (인증 불필요)
2. POST {supabase_url}/auth/v1/token?grant_type=password
   헤더: apikey: <anon>, Content-Type: application/json
   본문: {"email": ..., "password": ...}
   → {access_token, refresh_token, expires_in, user:{id, email}}
3. 만료 전 갱신: POST {supabase_url}/auth/v1/token?grant_type=refresh_token
   본문: {"refresh_token": ...}
```

**회원가입은 이 페이지에 두지 않는다.** 인가된 사람만 받는 서비스이므로 계정은 제작자가 Supabase 콘솔에서 만든다. 가입 폼을 두면 인가 경계가 사라진다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_se_page_assets.py`:

```python
"""SE 페이지 정적 검사.

이 페이지는 실명과 공시 원문을 그대로 표시하고, 사용자의 DART 키를
보관한다. 브라우저에서만 돌아가므로 파이썬 테스트로는 동작을 볼 수 없다 —
대신 **소스를 정적으로 검사**해 되돌아오면 안 되는 것들을 막는다.

`tests/se/test_vercel_bundle.py`와 같은 계열이다: 로컬에서는 아무 문제가
없어 보이지만 배포하면 깨지거나 새는 부류를 소스 대조로 잡는다.
"""
import pathlib
import re
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_SE = _ROOT / "docs" / "tool" / "se"


def _sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in _SE.glob("*.*")}


class TestPageExists(unittest.TestCase):
    """파일이 없으면 아래 정적 검사들이 전부 공허하게 통과한다.

    이 브랜치 계열에서 반복해서 나온 결함이 정확히 그 부류다 — 검사 대상에
    도달하지 못한 채 초록으로 보이는 것.
    """

    def test_expected_files_are_present(self):
        for name in ("index.html", "app.js", "ui.js"):
            self.assertTrue((_SE / name).exists(), f"{name}이 없습니다")


class TestNoExternalDependencies(unittest.TestCase):
    """빌드 스텝도 CDN도 없다 — 기존 공개 뷰어와 같은 방식이다."""

    def test_no_external_script_or_style(self):
        offenders = []
        for name, src in _sources().items():
            for m in re.finditer(r'<(?:script|link)[^>]*\b(?:src|href)="([^"]+)"', src):
                url = m.group(1)
                if url.startswith(("http://", "https://", "//")):
                    offenders.append(f"{name}: {url}")
        self.assertEqual(offenders, [],
                         "외부 스크립트·스타일을 불러오면 안 됩니다:\n  "
                         + "\n  ".join(offenders))

    def test_no_package_json_introduced(self):
        self.assertFalse((_ROOT / "package.json").exists(),
                         "npm 의존성을 도입하면 안 됩니다")


class TestNoSecretsInPage(unittest.TestCase):
    def test_no_service_key_or_jwt_literal(self):
        """service_role 키·JWT 리터럴이 소스에 박히면 안 된다.

        anon 키조차 하드코딩하지 않는다 — 런타임에 /api/se/config로 받는다.
        """
        for name, src in _sources().items():
            self.assertNotIn("service_role", src, f"{name}에 service_role 언급")
            self.assertNotIn("sb_secret_", src, f"{name}에 secret 키 접두어")
            self.assertNotRegex(src, r"eyJ[A-Za-z0-9_-]{20,}",
                                f"{name}에 JWT 리터럴로 보이는 문자열")

    def test_dart_key_is_sent_as_header_only(self):
        """쿼리스트링으로 보내면 URL 로그·리퍼러에 키가 남는다."""
        src = _sources()["ui.js"]
        self.assertIn("X-DART-Key", src)
        self.assertNotRegex(src, r"[?&](?:dart_key|crtfc_key|key)=",
                            "DART 키를 쿼리스트링에 실으면 안 됩니다")


class TestNoDataIntoInnerHtml(unittest.TestCase):
    """실명과 공시 원문이 그대로 들어오는 페이지다.

    데이터를 innerHTML에 넣으면 공시 원문 한 줄로 스크립트가 실행된다.
    정적 마크업을 넣는 innerHTML은 허용하되(리터럴만), 변수가 섞이면 막는다.
    """

    def test_no_variable_interpolation_into_inner_html(self):
        offenders = []
        for name, src in _sources().items():
            if not name.endswith(".js"):
                continue
            for m in re.finditer(r"\.innerHTML\s*=\s*(.+)", src):
                rhs = m.group(1).strip()
                literal = re.fullmatch(r'(""|\'\'|``);?', rhs)
                if not literal:
                    offenders.append(f"{name}: {rhs[:60]}")
        self.assertEqual(offenders, [],
                         "데이터를 innerHTML에 넣으면 안 됩니다 — textContent를 "
                         "쓰세요:\n  " + "\n  ".join(offenders))


class TestNoVerdictVocabulary(unittest.TestCase):
    """v0.8.5 원칙 — 점수·등급·판정 어휘를 화면 문구로 쓰지 않는다."""

    _BANNED = ("매우위험", "고위험", "위험도", "위험등급", "риск",
               "의심스", "종합점수", "리스크 점수", "등급 부여")

    def test_no_grade_words(self):
        for name, src in _sources().items():
            for word in self._BANNED:
                self.assertNotIn(word, src, f"{name}에 판정 어휘 '{word}'")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_se_page_assets.py -v`
Expected: FAIL — `docs/tool/se/`가 아직 없어 `_sources()`가 빈 dict이거나 `ui.js` KeyError

- [ ] **Step 3: `docs/tool/se/index.html` 작성**

기존 뷰어의 CSS 변수를 그대로 가져와 톤을 맞춘다(`--bg: #070a0f` 등 22개). 골격만 두고 내용은 JS가 채운다.

```html
<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>리스크 뷰어 SE</title>
<style>
:root{
  --bg:#070a0f; --rail:#0b0e14; --panel:#11151d; --cell:#0d1118;
  --line:#1e2530; --line2:#2a333f; --tx:#d7dde6; --dim:#7c8797;
  --dim2:#9fb0c0; --faint:#4a5566; --amber:#e8a33d; --amber2:#f2bc63;
  --red:#e0564a; --green:#4ad295;
  --mono:Consolas,"Cascadia Code","SF Mono",monospace;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);
     font:14px/1.6 -apple-system,"Segoe UI","Malgun Gothic",sans-serif}
#gate,#main{max-width:960px;margin:0 auto;padding:24px}
#main[hidden],#gate[hidden]{display:none}
input,button{font:inherit;background:var(--cell);color:var(--tx);
             border:1px solid var(--line2);border-radius:4px;padding:8px 10px}
button{cursor:pointer}
.sec{border-top:1px solid var(--line);padding:20px 0}
.sec h2{font-size:15px;color:var(--amber2);margin:0 0 12px}
table{border-collapse:collapse;width:100%;font-family:var(--mono);font-size:12px}
th,td{border:1px solid var(--line);padding:4px 8px;text-align:left;
      vertical-align:top;max-width:280px;overflow-wrap:anywhere}
th{color:var(--dim2);background:var(--rail);font-weight:normal}
.person,.doc{color:var(--amber);cursor:pointer;text-decoration:underline dotted}
#bar{position:sticky;top:0;background:var(--rail);border-bottom:1px solid var(--line);
     padding:8px 12px;font-family:var(--mono);font-size:12px;color:var(--dim2);z-index:5}
#panel{position:fixed;top:0;right:0;height:100%;width:min(560px,92vw);
       background:var(--panel);border-left:1px solid var(--line2);
       transform:translateX(100%);transition:transform .18s ease;
       overflow:auto;padding:20px;z-index:10}
#panel.open{transform:none}
.note{color:var(--dim);font-size:12px}
.warn{color:var(--amber);font-size:12px}
</style>
</head>
<body>
<section id="gate">
  <h1>리스크 뷰어 SE</h1>
  <p class="note">인가된 사용자 전용입니다. 계정은 제작자가 발급합니다.</p>
  <div><input id="email" type="email" placeholder="이메일" autocomplete="username"></div>
  <div><input id="password" type="password" placeholder="비밀번호"
              autocomplete="current-password"></div>
  <div><input id="dartkey" type="password" placeholder="DART API 키"
              autocomplete="off"></div>
  <p class="note">DART 키는 이 브라우저에만 저장되며 서버로 보관되지 않습니다.</p>
  <button id="login">로그인</button>
  <p id="gate-msg" class="warn"></p>
</section>

<main id="main" hidden>
  <div id="bar"></div>
  <div id="head" class="sec"></div>
  <div id="body"></div>
  <div class="sec">
    <h2>출처·면책</h2>
    <p class="note">
      모든 수치와 이름은 금융감독원 전자공시(DART) 공개 자료입니다.
      이 화면은 사실을 표기할 뿐 위험을 판정하거나 등급을 매기지 않으며,
      투자 판단의 근거가 아닙니다. 동명이인이 있을 수 있습니다.
    </p>
    <button id="logout">로그아웃</button>
  </div>
</main>

<aside id="panel"><div id="panel-body"></div></aside>

<script src="app.js"></script>
<script src="ui.js"></script>
</body>
</html>
```

- [ ] **Step 4: `docs/tool/se/app.js` 초안 — 상수와 순수 함수 자리**

```js
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
```

- [ ] **Step 5: `docs/tool/se/ui.js` — 설정 로드·로그인·`api()`**

```js
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
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `python -m pytest tests/se/test_se_page_assets.py -v`
Expected: PASS (5개)

- [ ] **Step 7: 전체 스위트 회귀 확인**

Run: `python -m pytest tests/ -q`
Expected: 기준선 + 5

- [ ] **Step 8: 커밋**

```bash
git add docs/tool/se tests/se/test_se_page_assets.py
git commit -m "feat(se): SE 페이지 골격 + 공개 설정 로드 + GoTrue 직접 로그인"
```

---

### Task 2: 분석 실행과 진행률 폴링

**Files:**
- Modify: `docs/tool/se/app.js`, `docs/tool/se/ui.js`
- Test: `tests/se/test_se_app_js.py`

**Interfaces:**
- Consumes: Task 1의 `api()`, `token()`
- Produces: `nextKeysToFetch(sectionKeys, fetched)` → 아직 안 받은 키 배열. Task 3이 쓴다.
- Produces: `pollDecision(stepBody)` → `{shouldStop, reason}`

**핵심 규칙:** 섹션은 **한 번만** 받는다. SE-4a가 폴링 응답에서 737KB를 걷어낸 이유가 이것이므로, 여기서 매번 다시 받으면 원위치다.

**`stalled` 처리:** `step` 응답의 `stalled`가 참이면 진행이 멈춘 것이다. 무한 루프를 돌면 사용자 DART 호출 한도만 태운다 — 멈추고 사실을 표시한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_se_app_js.py`:

```python
"""app.js 순수 함수 검증 — node 서브프로세스로 실제 실행한다.

브라우저 로직을 테스트 밖에 두면 이 저장소의 유일한 품질 장치인 pytest가
닿지 않는다. app.js는 DOM도 네트워크도 만지지 않는 순수 함수만 담으므로
node로 그대로 부를 수 있다.
"""
import json
import pathlib
import shutil
import subprocess
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_APP = _ROOT / "docs" / "tool" / "se" / "app.js"
_NODE = shutil.which("node")


def run_js(expression: str):
    """app.js를 로드해 표현식을 평가하고 결과를 JSON으로 받는다."""
    # export를 전역에 통째로 얹는다. 고정 목록을 두면 함수가 늘 때마다
    # 목록을 고쳐야 하고, 빠뜨리면 "정의되지 않음"으로 엉뚱하게 실패한다.
    script = (
        f"Object.assign(globalThis, require({json.dumps(str(_APP))}));\n"
        f"process.stdout.write(JSON.stringify({expression}));\n"
    )
    out = subprocess.run([_NODE, "-e", script], capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestNextKeysToFetch(unittest.TestCase):
    def test_returns_keys_not_yet_fetched(self):
        got = run_js('nextKeysToFetch(["a","b","c"], ["a"])')
        self.assertEqual(got, ["b", "c"])

    def test_returns_empty_when_all_fetched(self):
        self.assertEqual(run_js('nextKeysToFetch(["a","b"], ["a","b"])'), [])

    def test_never_refetches_across_polls(self):
        """폴링이 반복돼도 같은 키를 두 번 주지 않아야 한다.

        SE-4a가 없앤 737KB 문제가 되돌아오는 경로가 정확히 여기다.
        """
        got = run_js(
            '(() => { const seen=[]; let out=[];'
            ' for (const poll of [["a"],["a","b"],["a","b","c"]]) {'
            '   const n = nextKeysToFetch(poll, seen); out = out.concat(n);'
            '   for (const k of n) seen.push(k); }'
            ' return out; })()'
        )
        self.assertEqual(got, ["a", "b", "c"], "같은 섹션을 다시 받고 있습니다")

    def test_ignores_unknown_extra_keys_in_fetched(self):
        self.assertEqual(run_js('nextKeysToFetch(["a"], ["zzz"])'), ["a"])


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestPollDecision(unittest.TestCase):
    def test_stops_when_done(self):
        got = run_js('pollDecision({done: true, stalled: false, processed: 3})')
        self.assertTrue(got["shouldStop"])

    def test_stops_when_stalled(self):
        """진행이 멈췄는데 계속 부르면 DART 호출 한도만 태운다."""
        got = run_js('pollDecision({done: false, stalled: true, processed: 0})')
        self.assertTrue(got["shouldStop"])
        self.assertTrue(got["reason"], "멈춘 이유를 사용자에게 말해야 합니다")

    def test_continues_while_progressing(self):
        got = run_js('pollDecision({done: false, stalled: false, processed: 2})')
        self.assertFalse(got["shouldStop"])

    def test_missing_fields_do_not_loop_forever(self):
        """응답이 예상과 달라도 무한 루프에 빠지면 안 된다."""
        got = run_js("pollDecision({})")
        self.assertTrue(got["shouldStop"])


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestSectionGroups(unittest.TestCase):
    def test_covers_all_stage1_keys_except_header(self):
        """registry의 1단 키 13개가 화면 어딘가에는 나와야 한다.

        빠지면 데이터를 받아놓고 보여주지 않는 것이다.
        """
        from se_server.jobs.registry import STAGE1_SPECS

        groups = run_js("SECTION_GROUPS")
        shown = {k for g in groups for k in g["keys"]}
        expected = {s.key for s in STAGE1_SPECS} - {"company_info"}  # 헤더는 별도
        self.assertEqual(expected - shown, set(),
                         "화면에 안 나오는 섹션이 있습니다")
        self.assertEqual(shown - expected, set(),
                         "registry에 없는 섹션 키를 그리려 합니다")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_se_app_js.py -v`
Expected: FAIL — `nextKeysToFetch is not defined`

- [ ] **Step 3: `app.js`에 순수 함수 추가**

```js
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
```

export 목록에 `nextKeysToFetch`, `pollDecision`을 추가한다.

- [ ] **Step 4: `ui.js`에 실행 루프 추가**

```js
const FETCHED = new Set();   // 이미 받은 섹션 키

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

  for (;;) {
    const step = await api("POST", "/api/se/analyze/" + jobId + "/step",
                           { token: await token(), dartKey: dartKey });
    const decision = pollDecision(step.body);

    const prog = await api("GET", "/api/se/analyze/" + jobId,
                           { token: await token() });
    if (prog.status === 200) {
      showProgress(prog.body);
      // 새로 완성된 섹션만 받는다.
      for (const key of nextKeysToFetch(prog.body.section_keys, [...FETCHED])) {
        FETCHED.add(key);
        const sec = await api(
          "GET",
          "/api/se/analyze/" + jobId + "/section/" + encodeURIComponent(key),
          { token: await token() }
        );
        // api()는 {status, body}를 준다. 섹션 키는 sec.body.key에 있다.
        if (sec.status === 200) renderSection(sec.body.key || key, sec.body.value);
      }
      renderFailures(prog.body.failed);
    }
    if (decision.shouldStop) {
      if (decision.reason) showBar(decision.reason);
      break;
    }
  }
}
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/se/test_se_app_js.py tests/se/test_se_page_assets.py -v`
Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add docs/tool/se tests/se/test_se_app_js.py
git commit -m "feat(se): 분석 실행·진행률 폴링 — 섹션은 한 번만 받는다"
```

---

### Task 3: 섹션 렌더 — 범용 레코드 표 + 라벨 맵

**Files:**
- Modify: `docs/tool/se/app.js`, `docs/tool/se/ui.js`
- Modify: `tests/se/test_se_app_js.py`

**Interfaces:**
- Consumes: Task 2의 `SECTION_GROUPS`
- Produces: `toTable(value)` → `{columns: [...], rows: [[...]]} | null`
- Produces: `LABELS` — DART 필드명 → 한국어 라벨

**설계 판단 — 왜 범용 렌더인가:** 13개 섹션의 값은 대부분 **DART 원본 레코드 리스트**이고 필드는 엔드포인트마다 다르다. 섹션마다 전용 렌더를 쓰려면 필드명을 알아야 하는데, **확인하지 않은 필드명을 코드에 박는 것이 SE-4a에서 세 번 사고를 낸 방식이다.** 대신 레코드가 가진 키를 그대로 열로 삼고, **확신하는 것만** 한국어 라벨로 바꾼다.

**모르는 필드를 숨기지 않는다.** 라벨이 없으면 원본 키를 그대로 열 이름으로 쓴다. 숨기면 데이터가 조용히 사라지고, 사용자는 없는 줄 안다.

- [ ] **Step 1: 실패하는 테스트 작성 (`tests/se/test_se_app_js.py`에 추가)**

```python
@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestToTable(unittest.TestCase):
    def test_list_of_records_becomes_rows(self):
        got = run_js('toTable([{a:1,b:2},{a:3,b:4}])')
        self.assertEqual(got["rows"], [["1", "2"], ["3", "4"]])

    def test_columns_union_covers_ragged_records(self):
        """레코드마다 필드가 다를 수 있다. 어느 것도 사라지면 안 된다."""
        got = run_js('toTable([{a:1},{b:2}])')
        self.assertEqual(sorted(got["columns"]), ["a", "b"])

    def test_unknown_field_keeps_raw_key_as_header(self):
        """라벨이 없다고 열을 숨기면 데이터가 조용히 사라진다."""
        got = run_js('toTable([{wholly_unknown_field: "x"}])')
        self.assertIn("wholly_unknown_field", got["columns"])

    def test_known_field_uses_korean_label(self):
        got = run_js('toTable([{rcept_no: "20240301000001"}])')
        self.assertIn("접수번호", got["columns"])

    def test_single_dict_becomes_one_row(self):
        got = run_js('toTable({a:1})')
        self.assertEqual(got["rows"], [["1"]])

    def test_empty_value_is_null(self):
        for expr in ("toTable([])", "toTable(null)", "toTable({})"):
            self.assertIsNone(run_js(expr), f"{expr}가 표를 만들었습니다")

    def test_nested_value_is_stringified_not_dropped(self):
        got = run_js('toTable([{x: {deep: 1}}])')
        self.assertNotEqual(got["rows"][0][0], "")

    def test_null_cell_becomes_empty_string_not_the_word_null(self):
        got = run_js('toTable([{a: null}])')
        self.assertEqual(got["rows"][0][0], "")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/se/test_se_app_js.py -k ToTable -v`
Expected: FAIL — `toTable is not defined`

- [ ] **Step 3: `app.js`에 구현 추가**

```js
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
```

export 목록에 `toTable`, `LABELS`를 추가한다.

- [ ] **Step 4: `ui.js`에 DOM 렌더 추가 — `textContent`만 쓴다**

```js
/** 표를 DOM으로 만든다. 값은 전부 textContent로 넣는다 —
 *  공시 원문과 실명이 그대로 들어오는 자리다. */
function tableEl(table) {
  const t = document.createElement("table");
  const thead = t.createTHead().insertRow();
  for (const c of table.columns) {
    const th = document.createElement("th");
    th.textContent = c;
    thead.appendChild(th);
  }
  const tb = t.createTBody();
  for (const row of table.rows) {
    const tr = tb.insertRow();
    for (const v of row) tr.insertCell().textContent = v;
  }
  return t;
}
```

- [ ] **Step 5: 통과 확인 후 커밋**

Run: `python -m pytest tests/se/ -q`

```bash
git add docs/tool/se tests/se/test_se_app_js.py
git commit -m "feat(se): 섹션 범용 렌더 — 모르는 필드도 숨기지 않는다"
```

---

### Task 4: 우측 슬라이드 패널 — 실명과 공시 원문

**Files:**
- Modify: `docs/tool/se/app.js`, `docs/tool/se/ui.js`, `docs/tool/se/index.html`
- Modify: `tests/se/test_se_app_js.py`, `tests/se/test_se_page_assets.py`

**Interfaces:**
- Consumes: `GET /api/se/actors?company=`, `GET /api/se/disclosure/{rcept_no}`
- Produces: `actorLine(actor)` → `{name, statusLabel, warn, companies}`

**이 태스크가 SE의 핵심이다.** 행위자 실명이 없으면 SE는 "공시를 좀 더 보여주는 도구"에 그친다. 동시에 **가장 조심해야 할 곳**이다.

**status 라벨과 경고는 분리하지 않는다.** 하나의 함수가 둘 다 만들어야 화면 어디서 렌더하든 함께 나간다. 따로 두면 한쪽만 그리는 경로가 생긴다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestActorLine(unittest.TestCase):
    def test_verified_has_label(self):
        got = run_js('actorLine({name:"홍길동", status:"verified", companies:["A"]})')
        self.assertEqual(got["name"], "홍길동")
        self.assertTrue(got["statusLabel"])

    def test_auto_matched_carries_namesake_warning(self):
        """자동 매칭은 동명이인이 확인되지 않았다. 경고 없이 실명을
        보여주면 안 된다."""
        got = run_js('actorLine({name:"홍길동", status:"auto_matched", companies:[]})')
        self.assertIn("동명이인", got["warn"])

    def test_unknown_status_is_treated_as_weakest(self):
        """모르는 값을 강한 쪽으로 보여주는 실수는 허용되지 않는다."""
        for bad in ('""', '"확인됨"', "null", "123", '["verified"]'):
            got = run_js(f'actorLine({{name:"홍길동", status:{bad}, companies:[]}})')
            self.assertIn("동명이인", got["warn"],
                          f"status={bad} 인데 경고가 없습니다")

    def test_every_status_produces_a_label(self):
        """라벨이 빈 채로 실명만 나가는 경로가 있으면 안 된다."""
        for st in ('"verified"', '"maintainer_seed"', '"auto_matched"', '""'):
            got = run_js(f'actorLine({{name:"홍길동", status:{st}, companies:[]}})')
            self.assertTrue(got["statusLabel"], f"status={st}에 라벨이 없습니다")

    def test_missing_name_does_not_crash(self):
        got = run_js("actorLine({})")
        self.assertEqual(got["name"], "")
```

`tests/se/test_se_page_assets.py`에 추가:

```python
class TestDisclaimerAlwaysRendered(unittest.TestCase):
    def test_panel_renders_server_disclaimer(self):
        """서버가 주는 면책 문구를 화면이 실제로 그려야 한다.

        서버만 보내고 화면이 버리면 사용자는 못 본다.
        """
        src = _sources()["ui.js"]
        self.assertIn("disclaimer", src,
                      "actors 응답의 disclaimer를 화면이 쓰지 않습니다")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/se/test_se_app_js.py -k ActorLine -v`
Expected: FAIL — `actorLine is not defined`

- [ ] **Step 3: `app.js`에 구현 추가**

```js
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
```

**세 단계 모두 동명이인 경고를 갖는다.** 레지스트리 대조는 **표기 일치**이지 신원 확인이 아니기 때문이다. 단계 차이는 `label`이 나타낸다. 경고를 폴백(`meta.warn || ...`)으로 채우지 않고 각 단계에 직접 적어 둔 이유는, 폴백은 "빠뜨렸는데 우연히 메워진 것"과 구분되지 않기 때문이다.

export 목록에 `actorLine`, `ACTOR_STATUS`를 추가한다.

- [ ] **Step 4: `ui.js`에 패널 열기 추가**

```js
async function openActorPanel(company) {
  const r = await api("GET", "/api/se/actors?company=" + encodeURIComponent(company),
                      { token: await token() });
  const box = document.getElementById("panel-body");
  box.innerHTML = "";
  const panel = document.getElementById("panel");
  if (r.status !== 200) {
    box.textContent = "행위자 정보를 불러오지 못했습니다.";
    panel.classList.add("open");
    return;
  }

  for (const raw of (r.body.actors || [])) {
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
  // 서버가 준 면책 문구를 그대로 붙인다.
  const dis = document.createElement("p");
  dis.className = "note";
  dis.textContent = r.body.disclaimer || "";
  box.appendChild(dis);
  document.getElementById("panel").classList.add("open");
}

async function openDocPanel(rceptNo) {
  const r = await api("GET", "/api/se/disclosure/" + encodeURIComponent(rceptNo),
                      { token: await token(),
                        dartKey: localStorage.getItem(LS_DART_KEY) || "" });
  const box = document.getElementById("panel-body");
  box.innerHTML = "";
  const p = document.createElement("pre");
  p.style.whiteSpace = "pre-wrap";
  // 공시 원문 — 반드시 textContent다.
  p.textContent = r.status === 200
    ? r.body.text
    : (r.body.error || "원문을 불러오지 못했습니다.");
  box.appendChild(p);
  if (r.status === 200 && r.body.truncated) {
    const n = document.createElement("p");
    n.className = "note";
    n.textContent = "원문 " + formatCount(r.body.char_count) + "자 중 일부입니다.";
    box.appendChild(n);
  }
  document.getElementById("panel").classList.add("open");
}
```

- [ ] **Step 5: 통과 확인 후 커밋**

Run: `python -m pytest tests/se/ -q`

```bash
git add docs/tool/se tests/se
git commit -m "feat(se): 우측 패널 — 실명은 status·동명이인 경고와 함께만 나간다"
```

---

### Task 5: 오류·중단·재개 + 종단 검증

**Files:**
- Modify: `docs/tool/se/ui.js`, `docs/tool/se/app.js`
- Modify: `tests/se/test_se_app_js.py`
- Create: `docs/tool/se/README.md`

**Interfaces:**
- Produces: `resumeTarget(saved, now)` → 이어받을 `job_id` 또는 `null`

**중단·재개는 공짜로 따라온다.** 작업 상태가 Postgres에 있으므로(스펙 §7.3), `job_id`만 `localStorage`에 남기면 탭을 닫았다 열어도 이어받는다. 다만 **오래된 `job_id`를 무한정 이어받으면 안 된다** — 며칠 전 작업을 재개하면 사용자는 새 분석을 받았다고 오해한다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestResumeTarget(unittest.TestCase):
    _HOUR = 3600 * 1000

    def test_recent_job_is_resumed(self):
        got = run_js(f'resumeTarget({{job_id:"j1", saved_at: {10 * self._HOUR}}},'
                     f' {10 * self._HOUR + 60000})')
        self.assertEqual(got, "j1")

    def test_stale_job_is_not_resumed(self):
        """며칠 전 작업을 조용히 이어받으면 새 분석으로 오해한다."""
        got = run_js(f'resumeTarget({{job_id:"j1", saved_at: 0}}, {72 * self._HOUR})')
        self.assertIsNone(got)

    def test_missing_or_malformed_is_null(self):
        for expr in ("resumeTarget(null, 1)", "resumeTarget({}, 1)",
                     'resumeTarget({job_id:"j"}, 1)'):
            self.assertIsNone(run_js(expr), f"{expr}가 이어받으려 합니다")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/se/test_se_app_js.py -k ResumeTarget -v`
Expected: FAIL — `resumeTarget is not defined`

- [ ] **Step 3: `app.js`에 구현 추가**

```js
// 이어받기 유효 시간. 이보다 오래된 작업은 새로 시작한다 —
// 며칠 전 작업을 조용히 재개하면 사용자는 새 분석을 받았다고 오해한다.
const RESUME_WINDOW_MS = 12 * 3600 * 1000;

function resumeTarget(saved, now) {
  const s = saved || {};
  if (typeof s.job_id !== "string" || !s.job_id) return null;
  if (typeof s.saved_at !== "number") return null;
  return (now - s.saved_at) <= RESUME_WINDOW_MS ? s.job_id : null;
}
```

export 목록에 `resumeTarget`을 추가한다.

- [ ] **Step 4: `ui.js`에 오류 표시와 재개 연결**

```js
const LS_JOB = "se_job";

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

/** 페이지를 열 때 이어받을 작업이 있으면 폴링을 재개한다. */
async function resumeIfAny() {
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(LS_JOB) || "null"); }
  catch (e) { saved = null; }
  const jobId = resumeTarget(saved, Date.now());
  if (!jobId) { forgetJob(); return false; }

  const prog = await api("GET", "/api/se/analyze/" + jobId, { token: await token() });
  if (prog.status !== 200) { forgetJob(); return false; }   // 남의 것이거나 사라졌다
  showBar("진행 중이던 분석을 이어받습니다 — " + prog.body.company);
  await pollUntilDone(jobId);
  return true;
}
```

`analyze()`는 `job_id`를 받은 직후 `rememberJob(jobId)`를 부르고, Task 2의 폴링 루프를 `pollUntilDone(jobId)`로 떼어내 `analyze()`와 `resumeIfAny()`가 함께 쓴다. 루프가 끝나면 `forgetJob()`을 부른다.

실패 섹션은 숨기지 않는다:

```js
function renderFailures(failed) {
  if (!failed || failed.length === 0) return;
  const box = document.getElementById("body");
  const d = document.createElement("div");
  d.className = "sec";
  const h = document.createElement("h2");
  h.textContent = "가져오지 못한 항목 " + formatCount(failed.length) + "건";
  d.appendChild(h);
  for (const f of failed) {
    const p = document.createElement("p");
    p.className = "note";
    // 서버가 이미 키를 스크럽해서 보낸다(runner._scrub).
    p.textContent = f.key + " — " + (f.error || "원인 미상");
    d.appendChild(p);
  }
  box.appendChild(d);
}
```

- [ ] **Step 5: `docs/tool/se/README.md` 작성**

계정 발급 절차(제작자가 Supabase 콘솔에서 생성), DART 키 보관 위치, ②③이 SE-4c로 미뤄졌다는 사실, 그리고 프로덕션 확인 절차를 적는다.

- [ ] **Step 6: 전체 스위트 + 커밋**

Run: `python -m pytest tests/ -q`

```bash
git add docs/tool/se tests/se
git commit -m "feat(se): 오류 표시·중단 재개 + 사용 안내"
```

- [ ] **Step 7: 프로덕션 종단 확인 (사람이 실행)**

배포 후 브라우저에서 확인한다. 자동화하지 않는 이유는 화면 거동이 사람 눈으로만 판정되기 때문이다.

| 확인 | 통과 기준 |
|---|---|
| `/se/` 접속 | 로그인 화면이 뜬다 |
| 잘못된 비밀번호 | 계정 존재 여부가 드러나지 않는 문구 |
| 로그인 후 회사 입력 | 헤더가 먼저 뜨고 섹션이 위에서부터 채워진다 |
| 개발자도구 Network | 같은 섹션 키를 두 번 받지 않는다 |
| 개발자도구 Network | 진행률 응답이 수 KB대다 |
| 인물 이름 클릭 | 패널에 status·동명이인 경고·면책이 함께 뜬다 |
| 공시 제목 클릭 | 원문이 뜨고 본문 스크롤 위치가 유지된다 |
| 탭 닫았다 열기 | 12시간 내면 이어받는다 |
| 로그아웃 후 | DART 키와 세션이 지워진다 |

---

## 이 계획이 남기는 것

**SE-4c로 넘어가는 것:**
- ② 자금 체인, ③ 자금 시계열 레인 — 파생 로직을 `se_server/view/`에 두고 pytest로 검증한 뒤 화면에 얹는다
- 라벨 맵 보강 — 실제 응답을 보고 확신이 선 필드만 `LABELS`에 추가한다

**의도적으로 하지 않는 것:**
- 회원가입 폼 (인가 경계가 사라진다)
- 워터마크·유출 방지 (사용자 결정 — 걱정하지 않기로 했다)
- 서버 주도 자동 완주 (별도 워커 호스트가 필요하며 1차 범위 밖)
