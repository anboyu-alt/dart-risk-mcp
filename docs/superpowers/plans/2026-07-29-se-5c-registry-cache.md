# SE-5c 레지스트리 캐시 배선 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 행위자 조회가 콜드 호출마다 Notion을 15회 왕복하며 **14~15초**를 쓰는 것을 **1.4초**로 줄인다(실측 10.2배). 그리고 콜드일 때 조용히 죽지 않게 한다.

**Architecture:** core에 캐시 시임을 하나 더 판다 — `dart_client.set_http_cache`와 **같은 패턴**(`se_server`가 주입, core는 se_server를 모른다). `load_known_actors`가 Notion보다 먼저 그 캐시를 본다. 매일 도는 cron이 캐시를 미리 채워, 24시간 만료 직후 걸린 사용자가 15초를 물지 않게 한다.

**Tech Stack:** Python(core는 표준 라이브러리 + `requests`만), Supabase REST(기존 `SupabaseCache`), GitHub Actions.

## Global Constraints

- **core는 `se_server`를 import하지 않는다.** 주입 시임만 둔다. `dart_client.py:48~59`의 `_http_cache`/`set_http_cache`/`get_http_cache`가 정본 패턴이다.
- **캐시가 없거나 실패해도 동작이 지금과 같아야 한다.** 레지스트리 로딩은 예외를 전파하지 않는다(프로젝트 규칙). 캐시 미설정 = 지금의 파일 캐시 + Notion 경로 그대로.
- **캐시에 사용자 자격증명을 넣지 않는다.** `NOTION_TOKEN`은 키 계산에도 값에도 들어가지 않는다. `http_cache.py`가 `crtfc_key`를 제외한 것과 같은 이유다.
- **실명이 캐시에 들어간다.** 레지스트리 자체가 실명 데이터다. Supabase는 이미 SE의 비공개 저장소이고 RLS가 방어선이므로 새로운 노출은 아니지만, **캐시 키·로그·에러 메시지에 인물명이 새면 안 된다.**
- **`dart_risk_mcp/` 변경은 추가만.** MCP 도구 26개의 동작이 달라지면 안 된다 — 캐시 미설정이 기본값이므로 CLI·MCP 경로는 지금과 동일해야 한다.
- **외부 의존성 추가 금지.**
- **판정 금지 (v0.8.5)** — 이 계획은 성능만 다룬다. 출력 내용은 한 글자도 바뀌지 않아야 한다.

---

## 배경: 실측으로 확인한 것

2026-07-29, 실제 Notion 레지스트리와 실제 Supabase로 측정했다.

> ⚠️ 이 절의 값은 **실행해서 출력한 것**이다. 같은 저장소에서 계획 작성자가 재지 않은 값을 실측으로 적어 화면이 통째로 빈 사고가 있었다(SE-4h). 의심되면 다시 재라.

### 15.1초가 어디서 나오는가

`fetch_registry_from_notion`(`known_actors.py:453`)은 `page_size: 100`으로 페이지네이션한다. 1,270명 → **POST 15회, 페이지당 평균 1.00초**.

| 측정 | 값 |
|---|---:|
| Notion 콜드 로드 | **15.1초** (POST 15회) |
| 레지스트리 JSON | 542,211B (필터 후 1,258명) |
| gzip 압축 시 | 53,132B |

### Supabase 왕복 실측

| 연산 | 1회차 | 2회차 | 3회차 |
|---|---:|---:|---:|
| `put_json`(542KB) | 3.08초 | — | — |
| `get_json`(542KB) | 0.93초 | 0.52초 | 0.75초 |
| `put_blob`(gzip 53KB) | 0.76초 | — | — |
| `get_blob`(gzip 53KB) | 1.19초 | 0.48초 | — |

**왕복 무결성 확인:** `get_json` 결과가 원본과 완전히 같다(`got == reg`). `get_blob`도 gzip 해제 후 동일.

### 왜 `get_json`인가 (gzip blob이 10배 작은데도)

- **읽기 속도가 사실상 같다** — 0.5~0.9초 vs 0.5~1.2초. 542KB의 네트워크 시간이 지배적이지 않다.
- **`put_blob`에는 TTL이 없다.** `CacheBackend` 프로토콜(`se_server/cache/base.py:20~26`)에서 `put_blob(key, data)`는 만료를 받지 않고 `put_json(key, value, ttl_seconds)`만 받는다. `http_cache.py`가 blob을 "TTL 없이" 쓰는 것은 `rcept_no`가 불변이기 때문인데, **레지스트리는 매일 cron으로 바뀐다.** TTL이 필수다.
- blob에 TTL을 따로 얹으면 만료 로직이 두 벌이 된다.

**결론: `put_json`/`get_json`.** 쓰기 3.08초는 24시간에 한 번이라 무시할 수 있다.

### 선례 조사 — 이 저장소가 이미 겪은 것

**⚠️ 이 계획의 "20배" 주장은 아직 신뢰할 수 없다.** 커밋 `2fedf74`(2026-07-27) 「캐시 효과 주장을 라이브 실측으로 정정 (16.9배 → 2~4배)」가 같은 유형의 실수를 기록하고 있다:

> 인메모리로 잰 16.9배는 전송 비용이 0이라서 나온 값이며 실서비스에 적용되지 않는다.

위 15.1초 → 0.5~0.9초는 양쪽 다 실제 HTTP로 쟀으므로 그 함정은 아니다. **그러나 계획 작성자의 로컬에서 쟀다.** Vercel 함수는 `icn1`에서 돌고 Supabase 프로젝트 리전은 확인하지 않았다. **배포된 실물에서 재기 전까지 배수를 단정하지 마라.** Task 4가 그것을 확정한다.

**CLAUDE.md가 없는 캐시를 문서화하고 있다.** "공개기록 원격 캐시 | `~/.cache/dart-risk-mcp/known_actors_remote.json` (GitHub raw fetch) | 24시간"이라고 적혀 있으나 **코드에 구현이 없다**(`grep` 0건). 이 계획의 마지막에 CLAUDE.md 캐시 표를 실제 구현과 맞춰라 — 없는 것을 있는 것처럼 적어 둔 문서는 다음 사람을 잘못 인도한다.

**비공개 레포 패턴을 쓰지 않는 이유.** 이 저장소는 cron 실행 간 상태를 `anboyu-alt/dart-risk-mcp-sightings`(비공개 레포 + `SIGHTINGS_REPO_TOKEN`)로 유지한다 — `audit-registry-names.yml`·`backfill-exits.yml` 등이 그 방식이다. **그건 배치 경로의 해법이고 요청 시점 경로에는 맞지 않는다**: Vercel 함수가 GitHub 토큰을 들고 API를 왕복해야 하고, 자격증명이 하나 더 늘며, SE는 이미 Supabase가 배선돼 있다. Supabase를 쓰되 이 판단 근거를 코드 주석에 남겨라.

**공개 뷰어는 참고가 되지 않는다.** `docs/tool/index.html`은 정적 JSON(`signals-data.json` 23KB·`corp-map.json` 156KB)만 쓰고 레지스트리를 아예 다루지 않는다 — 무료 계층이라 행위자 데이터가 없다. **레지스트리를 정적 파일로 빼는 안은 불가능하다**: `docs/`는 public 레포이고 레지스트리는 실명이다.

### ⚠️ 더 나쁜 문제 — 콜드일 때 타임아웃일 가능성

**`vercel.json`에 `functions.maxDuration`이 없다.** SE-3 계획이 "배포 후 실측해 정한다"로 남긴 미결 항목이고(설계 §11), 아직 정해지지 않았다.

Vercel Hobby 기본 상한이 10초라면, **15.1초짜리 콜드 레지스트리 로드는 느린 게 아니라 함수가 죽는 것**이다. 화면에는 "레지스트리를 조회하지 못했습니다"(502)나 아무 응답 없음으로 나타난다.

**이 계획은 그 가정을 검증하지 않았다.** Task 4에서 프로덕션으로 확인한다. 결과에 따라:
- 타임아웃이 맞다면 → 이 계획은 성능 개선이 아니라 **결함 수정**이다
- 아니라면 → 성능 개선이고, `maxDuration` 결정은 별도 항목으로 남는다

**어느 쪽이든 캐시가 답이라는 것은 변하지 않는다.** 다만 PR 문구가 달라지므로 재보고 정직하게 쓴다.

### 24시간 만료 직후 문제

캐시를 깔아도 **TTL 만료 직후 첫 요청은 여전히 15.1초를 문다.** 매일 한 명이 그 비용을 낸다(그리고 위 타임아웃이 사실이면 실패한다).

레지스트리는 이미 **매일 cron으로 재구성된다**(`.github/workflows/refresh-known-actors.yml` → `scripts/refresh_known_actors.py`). 그 작업이 끝나면서 Supabase 캐시를 함께 채우면 사용자 요청이 만료된 캐시를 만날 일이 없다.

### Task 4 실측 결과 (2026-07-29 기록)

**단축은 10.2배다 — 계획 첫머리에 적은 "20배"는 틀렸다.**

| 경로 | 시간 |
|---|---:|
| A. 캐시 미설정 + 파일 캐시 없음 (MCP·CLI 현행) | **14.06초** |
| B. Supabase 캐시 적중 (Vercel 콜드 경로) | **1.38초** |
| C. 같은 프로세스 재호출 | 0.81초 |

**왜 20배가 아니었나:** 계획 작성자가 `get_json` 단독(0.52~0.93초)만 재고 `load_known_actors` **전체 경로**(응답 검증 `_valid`, `should_store` 필터 1,258건, 파일 캐시 쓰기)를 재지 않았다. `2fedf74`가 경고한 것과 같은 유형 — **부분을 재고 전체라고 말한 것**이다. 실제 개선은 여전히 크지만(14.06→1.38초) 배수는 정확히 적는다.

### ⚠️ 프로덕션 타임아웃 가정 — **확인하지 못했다**

배경 절의 미확인 가정(`maxDuration` 미설정 → 콜드 15초가 타임아웃인가)을 **확정하지 못했다.**

프로덕션 측정 결과:

| 엔드포인트 | 상태 | 시간 |
|---|---:|---:|
| `/api/se/config` | 200 | 1.21초 |
| `/api/se/actors?company=…` (토큰 없음) | 401 | 0.29초 |
| `/api/se/actors?company=…` (잘못된 토큰) | 401 | 0.55초 |

**인증 가드가 레지스트리 로드보다 앞에 있어, 로그인 토큰 없이는 그 경로를 측정할 수 없다.** 함수 자체는 살아 있다.

**따라서 이 계획이 "성능 개선"인지 "결함 수정"인지 확정하지 못했다.** PR에는 성능 개선으로만 쓰고, 타임아웃 가능성은 **미확인 항목**으로 남긴다. 로그인 토큰을 가진 사람이 배포 후 `/api/se/actors`를 한 번 호출해 보면 즉시 갈린다.

---

## File Structure

| 파일 | 책임 | 변경 |
|---|---|---|
| `dart_risk_mcp/core/known_actors.py` | 캐시 시임 + 로드 경로 우선순위 | 추가만 |
| `se_server/registry_cache.py` | 시임에 꽂는 정책 계층 + `install` | 신규 |
| `se_server/api/handlers.py` | `build_deps`에서 배선, 콜드 시 정직한 응답 | 수정 |
| `scripts/warm_registry_cache.py` | cron이 부르는 캐시 채우기 | 신규 |
| `.github/workflows/refresh-known-actors.yml` | 캐시 채우기 단계 추가 | 수정 |
| `tests/…` | 검증 | 수정 |

---

## Task 1: core 캐시 시임

**Files:**
- Modify(추가만): `dart_risk_mcp/core/known_actors.py`
- Test: 기존 `load_known_actors` 테스트가 있는 파일(먼저 찾아라)

**Interfaces:**
- Produces:
  ```python
  def set_registry_cache(cache) -> None: ...
  def get_registry_cache(): ...
  ```
  `dart_client.py:48~59`의 `_http_cache`/`set_http_cache`/`get_http_cache`를 **그대로 본떠라.** 새 패턴을 만들지 마라.
- 캐시 객체에 요구하는 것은 **두 메서드뿐**이다: `get_json(key) -> dict | None`, `put_json(key, value, ttl_seconds) -> None`. `CacheBackend` 전체를 요구하지 마라 — core가 se_server 타입을 알 필요가 없다.

**로드 우선순위 (기존 `load_known_actors`를 최소 변경)**

현재(`:563~`): `DART_KNOWN_ACTORS_PATH` > 신선한 파일 캐시 > Notion > 동봉.

바꿀 것: **Notion 직전에 주입된 캐시를 본다.**

```
DART_KNOWN_ACTORS_PATH > 신선한 파일 캐시 > [주입 캐시] > Notion > 동봉
```

- 주입 캐시가 **없으면**(기본값) 지금과 완전히 동일하게 동작한다. MCP·CLI 경로가 여기 해당한다.
- 주입 캐시에서 읽어 온 값도 **기존 `_valid()` 검증을 통과해야** 쓴다. 형태가 깨졌으면 없는 것처럼 넘어간다.
- Notion에서 새로 받아왔으면 **주입 캐시에도 쓴다**(파일 캐시에 쓰는 것과 나란히).
- 캐시 조회·쓰기에서 **어떤 예외도 밖으로 나가면 안 된다.** 프로젝트 규칙이자, 캐시 장애가 기능 장애가 되면 안 되기 때문이다.
- **필터를 어디에 적용하는지 확인하라.** SE-5b가 `load_known_actors`에 `should_store` 필터를 넣었다. 캐시에 저장하는 것이 필터 **전**인지 **후**인지 정하고 이유를 주석에 남겨라 — 필터 후를 저장하면 필터 규칙이 바뀌었을 때 캐시가 옛 규칙을 물고 있게 된다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`DART_KNOWN_ACTORS_PATH`가 최우선이므로(`:568`), 그 경로를 **비워** 캐시 경로를 타게 만들어야 한다. Notion 호출은 반드시 모킹한다(네트워크 금지).

검증할 것:

1. 캐시 미설정 시 동작이 **지금과 동일**하다(Notion 호출 횟수 포함)
2. 캐시에 유효한 레지스트리가 있으면 **Notion을 한 번도 부르지 않는다**
3. 캐시가 비어 있으면 Notion을 부르고, **그 결과를 캐시에 쓴다**
4. 캐시가 깨진 형태(`{"actors": "문자열"}`)를 돌려주면 **무시하고** Notion으로 간다
5. `get_json`이 예외를 던져도 **예외가 밖으로 안 나가고** Notion으로 폴백한다
6. `put_json`이 예외를 던져도 **로드는 성공한다**
7. `DART_KNOWN_ACTORS_PATH`가 설정돼 있으면 캐시를 **보지도 않는다**(우선순위 유지)
8. 캐시 키에 `NOTION_TOKEN` 값이 들어가지 않는다

- [ ] **Step 2: 실패 확인** → **Step 3: 구현** → **Step 4: 통과 확인**

- [ ] **Step 5: 전체 회귀 + 커밋**

```bash
python -m pytest tests/ -q
git add dart_risk_mcp/core/known_actors.py tests/
git commit -m "feat(actors): 레지스트리 캐시 시임 — core 는 주입만 받는다"
```

---

## Task 2: se_server 배선 + 콜드 시 정직한 응답

**Files:**
- Create: `se_server/registry_cache.py`
- Modify: `se_server/api/handlers.py`
- Test: 기존 `se_server` 핸들러 테스트 파일

**Interfaces:**
- Consumes: Task 1의 `set_registry_cache`, 기존 `SupabaseCache`(생성자는 **`SEConfig`를 받는다** — `SupabaseCache(config)`. `(url, key)`가 아니다. 실측으로 확인했다)
- Produces:
  ```python
  def install(backend, ttl_seconds: int = 24 * 3600): ...
  ```
  `se_server/http_cache.py:158`의 `install`을 본떠라.

**요구사항:**

- TTL은 **24시간** — 기존 파일 캐시(`_CACHE_TTL`)와 같은 값이다. 두 캐시가 다른 주기로 만료되면 어느 쪽이 최신인지 추론할 수 없다.
- 캐시 키는 **고정 문자열 하나**면 된다(레지스트리는 전역 단일 자산이다). `NOTION_TOKEN`이나 DB id를 키에 넣지 마라 — 자격증명이 저장소에 남는다. **DB id를 넣고 싶다면 그 이유를 적어라**(여러 DB를 쓰는 계획이 없다면 넣지 마라).
- `build_deps()`에서 기존 `http_cache.install(...)` 옆에 나란히 배선한다.
- **콜드일 때 정직하게 응답한다.** `_actors` 핸들러는 지금 실패 시 `502 "레지스트리를 조회하지 못했습니다"`를 낸다. 그것과 **"레지스트리에 이 회사 관련 인물이 없다"(200, 빈 목록)** 는 다른 사실이다. 지금 코드가 둘을 구분하는지 확인하고, 안 하면 구분하라 — 이 저장소는 "없음"과 "못 가져옴"을 뭉개서 사용자를 오도한 전례가 있다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

1. `install`이 core 시임에 실제로 꽂힌다(`get_registry_cache()`가 비어 있지 않다)
2. 캐시 적중 시 핸들러가 Notion을 부르지 않는다
3. 캐시·Notion 모두 실패하면 **502**가 나오고, 그 문구가 "없음"이 아니라 "조회 실패"다
4. 레지스트리는 정상인데 그 회사에 인물이 없으면 **200 + 빈 목록**이다
5. Supabase 미설정 환경에서 `build_deps()`가 죽지 않는다

- [ ] **Step 2~4: 실패 확인 → 구현 → 통과 확인**

- [ ] **Step 5: 전체 회귀 + 커밋**

---

## Task 3: cron이 캐시를 미리 채운다

**Files:**
- Create: `scripts/warm_registry_cache.py`
- Modify: `.github/workflows/refresh-known-actors.yml`

**요구사항:**

- 스크립트는 Notion에서 레지스트리를 받아 Supabase 캐시에 **쓴다**. 읽기 검증까지 하고 결과를 표준출력으로 요약한다(인물 수·바이트 수·소요 시간).
- **실명을 출력하지 않는다.** 워크플로 로그는 GitHub에 남고, 이 저장소는 public이다. 인물 수만 찍는다.
- 실패해도 **워크플로 전체를 깨뜨리지 않는다**(레지스트리 갱신 자체는 이미 끝난 뒤다). 실패를 로그에 남기고 0으로 끝낸다. 다만 **성공/실패를 구분해 찍어야** 사람이 알아챈다.
- 워크플로에 **Supabase Secrets**(`SUPABASE_URL`·`SUPABASE_SERVICE_KEY`)를 추가해야 한다. **이 계획으로 Secrets를 설정할 수는 없다** — 제작자가 GitHub에서 넣어야 한다. 워크플로에는 넣되, 미설정 시 스크립트가 조용히 건너뛰게 하고 그 사실을 로그에 남긴다.
- 기존 워크플로의 액션 버전 정책을 따른다(`checkout@v5`·`setup-python@v6+` — 2026-06-16부터 Node 20 액션이 강제 마이그레이션됐다).

- [ ] **Step 1: 스크립트 작성 + 워크플로 수정**

- [ ] **Step 2: 실측 실행**

`.env.local`에서 자격증명을 **런타임에 읽어**(파일에 키를 박지 마라 — 이 저장소에서 실제로 있었던 사고다) 로컬에서 실행하고, 캐시가 채워졌는지 별도 프로세스로 확인한다.

- [ ] **Step 3: 커밋**

---

## Task 4: 실측 검증 — 콜드/웜, 그리고 프로덕션 타임아웃 확인

**Files:** 없음(검증 전용). 결함이 나오면 해당 파일 수정.

- [ ] **Step 1: 로컬 콜드/웜 실측**

파일 캐시(`~/.cache/dart-risk-mcp/known_actors_notion.json`)를 지우고 Supabase 캐시만 남긴 상태에서 `load_known_actors()` 시간을 잰다.

**기대: 15.1초 → 0.5~0.9초.** 다르면 멈추고 보고하라. 숫자를 맞추려고 캐시를 조작하지 마라.

**⚠️ 이 로컬 수치를 PR에 배수로 쓰지 마라.** 선례 조사 절 참고 — 이 저장소는 로컬/인메모리 수치를 실서비스 개선으로 발표했다가 정정한 이력이 있다(`2fedf74`). 배포 환경에서 잰 값만 배수로 말한다.

Supabase 캐시까지 비운 완전 콜드도 재서, 그때 Notion 15회 왕복이 그대로 일어나는지 확인한다(폴백이 살아 있어야 한다).

- [ ] **Step 2: 프로덕션에서 `maxDuration` 가정을 확인한다**

**배경 절의 ⚠ 항목이다.** 지금 프로덕션에서 콜드 레지스트리 조회가 **타임아웃인지 단지 느린 것인지 아무도 모른다.**

`https://dart-risk-mcp.vercel.app/api/se/actors?company=<회사명>`을 호출해 확인한다. 인증이 필요하므로 로그인 토큰이 있어야 한다 — **없으면 그 사실을 보고하고, 401 응답 시간만이라도 측정해 함수가 살아 있는지 확인하라.**

확인할 것:
- 콜드 상태에서 응답이 오는가, 얼마나 걸리는가, 아니면 죽는가
- 죽는다면 상태 코드·본문이 무엇인가(사용자가 무엇을 보는가)

**결과를 그대로 기록하라.** 이 계획이 성능 개선인지 결함 수정인지가 여기서 갈린다.

- [ ] **Step 3: `maxDuration` 판단 재료 정리**

Step 2 결과와 함께, 이 저장소의 다른 미결 항목(`_DEFAULT_BUDGET` 25초 > Hobby 10초)을 묶어 **무엇을 정해야 하는지** 한 문단으로 정리해 보고한다. **값을 임의로 정해서 `vercel.json`에 넣지 마라** — 요금제가 무엇인지 모르는 상태에서 상한을 올리면 조용히 요금이 발생할 수 있다. 제작자가 결정할 문제다.

- [ ] **Step 4: CLAUDE.md 캐시 표를 실제와 맞춘다**

CLAUDE.md의 캐시 표에 **구현이 없는 항목**이 있다: `~/.cache/dart-risk-mcp/known_actors_remote.json` (GitHub raw fetch, 24시간). 코드에 존재하지 않는다.

이 계획이 추가하는 레지스트리 캐시를 표에 넣으면서, **그 유령 항목을 지워라.** 없는 캐시를 문서에 남겨 두면 다음 사람이 그것이 동작한다고 믿는다.

- [ ] **Step 5: 전체 회귀 + 커밋**

---

## Self-Review 결과

- **가장 큰 위험은 캐시가 조용히 옛 데이터를 물고 있는 것.** TTL 24시간을 파일 캐시와 맞췄고, cron이 매일 덮어쓴다. Task 1의 검증 4·5·6번이 깨진 캐시·예외 상황에서 폴백을 확인한다.
- **두 번째 위험은 필터 적용 시점**이다(SE-5b의 `should_store`). 필터 전을 캐시하면 규칙 변경이 즉시 반영되고, 필터 후를 캐시하면 24시간 지연된다. Task 1에서 명시적으로 정하게 했다.
- **검증되지 않은 가정 하나를 남긴 채 계획을 쓴다** — 프로덕션 콜드 조회가 타임아웃인지 여부. 확인 없이 "결함 수정"이라 쓰면 그것도 재지 않은 것을 실측이라 적는 일이다. Task 4 Step 2가 그걸 확정한다.
- **`maxDuration`은 이 계획에서 정하지 않는다.** 요금제를 모르고, 상한을 올리는 것은 비용이 따르는 결정이다.
- **cron Secrets는 제작자가 넣어야 한다.** 미설정이면 스크립트가 건너뛰고 로그에 남긴다 — 조용히 실패하지 않는다.
