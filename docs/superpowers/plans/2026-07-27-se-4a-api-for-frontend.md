# SE-4a: 프론트엔드용 API 보강 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SE-4 화면이 호출해야 하는데 지금 없는 API 5종을 만들고, 폴링이 매번 737KB를 받는 문제를 없앤다.

**Architecture:** SE-3가 세운 순수 핸들러 구조(`se_server/api/`)를 그대로 확장한다. 라우터에 경로를 추가하고 핸들러 함수를 늘리며, Vercel 어댑터는 건드리지 않는다.

**Tech Stack:** Python 3.11+, 표준 라이브러리, `requests`(기존), `unittest`

## Global Constraints

- `dart_risk_mcp/` core를 **수정하지 않는다.** 기존 공개 함수만 호출한다.
- 새 서드파티 의존성을 추가하지 않는다. **`supabase-py` 등 SDK 금지** — REST 직접 호출.
- **인증이 모든 데이터 경로보다 먼저다.** 유일한 예외는 `/api/se/config`이며, 그 응답에는 공개 정보만 담는다.
- **소유자 불일치는 404다.** 403이면 `job_id` 존재 여부가 샌다.
- **DART 키는 `X-DART-Key` 헤더로만** 받는다. 쿼리스트링 금지.
- **service_role 키를 브라우저에 노출하지 않는다.** `/api/se/config`가 내보내는 것은 **anon(publishable) 키뿐**이다.
- **행위자 실명은 인증된 요청에만** 준다. status와 동명이인 경고를 항상 동반한다.
- **점수·등급을 만들지 않는다**(v0.8.5).
- 주석·docstring은 **한국어**. 테스트는 `unittest.TestCase`, **실제 네트워크 호출 없음**.
- `.vercelignore`는 이미 `se_server`·`dart_risk_mcp`를 허용한다. 새 최상위 패키지를 만들면 **거기도 추가**해야 한다(`tests/se/test_vercel_bundle.py`가 강제).

## 선행 조건

**SE-3가 머지되어 프로덕션에서 동작 중이다** (PR #107·#108·#109·#110). 종단 검증까지 통과했다.

---

## 왜 이 계획이 필요한가 — 실측 근거

`GET /api/se/analyze/{id}`가 완료된 섹션을 **통째로** 돌려준다. 프로덕션 실측(2026-07-27, 셀트리온 1년):

| 폴링 | 응답 크기 | 진행 |
|---|---|---|
| 1회 | 136 B | 0/13 |
| 2회 | 166,231 B | 9/13 |
| 3회 | 498,500 B | 12/13 |
| 4회 | **736,635 B** | 39/39 |

**4회 폴링에 1.4MB.** 화면은 진행 상황을 보여주려고 수 초 간격으로 폴링하므로, 실제로는 20회 이상이 되어 **10MB를 넘긴다.** 같은 데이터를 반복해서 받는 것이다.

섹션별 크기 상위:

| 섹션 | 크기 | 비중 |
|---|---|---|
| `insider_timeline` | 305,453 B | **41%** |
| `disclosures` | 49,549 B | 7% |
| `shareholders` | 41,759 B | 6% |
| `affiliates` | 31,697 B | 4% |

SE-3 최종 리뷰가 "미해결 위험"으로 남긴 항목이며, 이제 수치가 확인됐다.

---

## 없는 API 5종

| 엔드포인트 | 용도 | 없으면 |
|---|---|---|
| `GET /api/se/analyze/{id}` (경량화) | 진행률 폴링 | 폴링마다 737KB |
| `GET /api/se/analyze/{id}/section/{key}` | 섹션 하나 | 전체를 받아야 함 |
| `GET /api/se/config` | 브라우저 로그인용 공개 설정 | 로그인 불가 |
| `GET /api/se/disclosure/{rcept_no}` | 우측 패널 3단 원문 | 공시 클릭이 죽음 |
| `GET /api/se/actors?company=` | 행위자 대조 | **SE의 유일한 독점 자산이 화면에 안 나옴** |

---

## File Structure

| 파일 | 책임 |
|---|---|
| `se_server/api/router.py` | **수정** — 경로 4개 추가 |
| `se_server/api/handlers.py` | **수정** — 핸들러 4개 추가, `_get` 경량화 |
| `se_server/config.py` | **수정** — `supabase_anon_key` 추가 |
| `scripts/se_verify_api.py` | **수정** — 분리된 응답에 맞춰 갱신 |
| `tests/se/test_api_sections.py` | 진행률/섹션 분리 |
| `tests/se/test_api_config.py` | 공개 설정 |
| `tests/se/test_api_disclosure.py` | 원문 조회 |
| `tests/se/test_api_actors.py` | 행위자 조회 |

---

### Task 1: 진행률과 섹션 분리

**Files:**
- Modify: `se_server/api/router.py`, `se_server/api/handlers.py`
- Modify: `scripts/se_verify_api.py`
- Test: `tests/se/test_api_sections.py`

**Interfaces:**
- Produces:
  - `GET /api/se/analyze/{id}` → `200 {job_id, company, status, finished, total, failed, section_keys}` — **`sections` 본문을 더 이상 담지 않는다**
  - `GET /api/se/analyze/{id}/section/{key}` → `200 {key, value}` / `404` (미완료·미존재)

**호환성:** 기존 `sections` 필드를 없애는 **파괴적 변경**이다. 현재 소비자는 `scripts/se_verify_api.py` 하나뿐이며 같은 커밋에서 갱신한다. 브라우저 클라이언트는 아직 없다.

**왜 `?include=sections` 옵션이 아니라 분리인가:** 옵션으로 두면 화면이 편의상 전체를 받는 쪽으로 흐르고, 실측한 문제가 그대로 남는다. 섹션을 개별로만 받을 수 있게 하면 **한 번 받은 섹션을 다시 받지 않는 구조**가 강제된다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_api_sections.py`:

```python
"""진행률 폴링과 섹션 조회의 분리.

GET이 완료된 섹션을 통째로 돌려주면 폴링마다 같은 데이터를 다시 받는다.
프로덕션 실측: 최종 응답 737KB, 4회 폴링 누적 1.4MB.
"""
import unittest
from unittest import mock

from se_server.api.handlers import Deps, handle
from se_server.api.types import Request
from se_server.jobs.store import MemoryJobStore


class _Auth:
    def __init__(self, user_id="user-1"):
        self.user_id = user_id

    def verify(self, bearer):
        from se_server.api.auth import AuthError
        if not bearer:
            raise AuthError(401, "인증 토큰이 없습니다")
        return self.user_id


def _req(method, path, token="T", dart_key="DARTKEY123456", body=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if dart_key:
        headers["X-DART-Key"] = dart_key
    return Request(method, path, headers, body or {})


def _seeded_store(user_id="user-1"):
    """섹션 2개가 완료된 작업을 만들어 둔다."""
    from se_server.jobs import runner
    store = MemoryJobStore()
    with mock.patch("se_server.api.handlers.resolve_corp",
                    return_value=("회사", {"corp_code": "0"})):
        created = handle(_req("POST", "/api/se/analyze", body={"company": "회사"}),
                         Deps(store=store, auth=_Auth(user_id)))
    job_id = created.body["job_id"]
    job = store.load(job_id)
    job.items[0].status = "done"
    job.items[0].result = {"value": {"큰": "x" * 5000}}
    job.items[1].status = "done"
    job.items[1].result = {"value": [1, 2, 3]}
    store.save(job)
    return store, job_id, job.items[0].key, job.items[1].key


class TestProgressIsLightweight(unittest.TestCase):
    def test_get_omits_section_bodies(self):
        store, job_id, key0, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}"),
                      Deps(store=store, auth=_Auth()))
        self.assertEqual(resp.status, 200)
        self.assertNotIn("sections", resp.body)

    def test_get_lists_completed_section_keys(self):
        store, job_id, key0, key1 = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}"),
                      Deps(store=store, auth=_Auth()))
        self.assertIn(key0, resp.body["section_keys"])
        self.assertIn(key1, resp.body["section_keys"])

    def test_incomplete_sections_are_not_listed(self):
        store, job_id, key0, key1 = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}"),
                      Deps(store=store, auth=_Auth()))
        job = store.load(job_id)
        pending = [i.key for i in job.items if i.status == "pending"]
        for key in pending:
            self.assertNotIn(key, resp.body["section_keys"])

    def test_progress_response_stays_small(self):
        """5,000자짜리 섹션이 있어도 진행률 응답은 작아야 한다."""
        import json
        store, job_id, _, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}"),
                      Deps(store=store, auth=_Auth()))
        size = len(json.dumps(resp.body, ensure_ascii=False))
        self.assertLess(size, 2000, f"진행률 응답이 {size}B로 큽니다")

    def test_keeps_progress_fields(self):
        store, job_id, _, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}"),
                      Deps(store=store, auth=_Auth()))
        for field in ("job_id", "company", "status", "finished", "total", "failed"):
            self.assertIn(field, resp.body)


class TestSectionEndpoint(unittest.TestCase):
    def test_returns_single_section(self):
        store, job_id, key0, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}/section/{key0}"),
                      Deps(store=store, auth=_Auth()))
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["key"], key0)
        self.assertEqual(resp.body["value"], {"큰": "x" * 5000})

    def test_unknown_section_is_404(self):
        store, job_id, _, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}/section/없는섹션"),
                      Deps(store=store, auth=_Auth()))
        self.assertEqual(resp.status, 404)

    def test_incomplete_section_is_404(self):
        """미완료 섹션을 완성된 것처럼 주면 안 된다."""
        store, job_id, _, _ = _seeded_store()
        job = store.load(job_id)
        pending = [i.key for i in job.items if i.status == "pending"][0]
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}/section/{pending}"),
                      Deps(store=store, auth=_Auth()))
        self.assertEqual(resp.status, 404)

    def test_other_user_gets_404(self):
        store, job_id, key0, _ = _seeded_store(user_id="owner")
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}/section/{key0}"),
                      Deps(store=store, auth=_Auth("침입자")))
        self.assertEqual(resp.status, 404)

    def test_requires_auth(self):
        store, job_id, key0, _ = _seeded_store()
        resp = handle(_req("GET", f"/api/se/analyze/{job_id}/section/{key0}", token=""),
                      Deps(store=store, auth=_Auth()))
        self.assertEqual(resp.status, 401)

    def test_unauthenticated_never_touches_store(self):
        store = mock.Mock()
        handle(_req("GET", "/api/se/analyze/j1/section/k", token=""),
               Deps(store=store, auth=_Auth()))
        store.load.assert_not_called()


class TestSectionKeyRouting(unittest.TestCase):
    """섹션 키는 registry 키와 `doc:<rcept_no>` 두 형태다."""

    def test_document_section_key_matches(self):
        from se_server.api.router import match
        name, vars_ = match("GET", "/api/se/analyze/abc/section/doc:20240301000001")
        self.assertEqual(name, "section")
        self.assertEqual(vars_["key"], "doc:20240301000001")

    def test_plain_section_key_matches(self):
        from se_server.api.router import match
        name, vars_ = match("GET", "/api/se/analyze/abc/section/insider_timeline")
        self.assertEqual(name, "section")
        self.assertEqual(vars_["key"], "insider_timeline")

    def test_path_traversal_in_key_is_rejected(self):
        from se_server.api.router import match
        self.assertIsNone(match("GET", "/api/se/analyze/abc/section/../../etc"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_api_sections.py -v`
Expected: FAIL — `section_keys`가 없고 section 라우트도 없다

- [ ] **Step 3: 라우터에 경로 추가**

`se_server/api/router.py`의 `_ROUTES`에 추가한다. 섹션 키는 `insider_timeline` 같은 이름과 `doc:20240301000001` 형태를 모두 포함하므로 **콜론을 허용**하되, 경로 순회 문자(`/`·`.`)는 계속 배제한다:

```python
# 섹션 키. registry 키(insider_timeline)와 원문 키(doc:<rcept_no>) 두 형태다.
# 콜론은 허용하되 `/`·`.`는 배제해 경로 순회를 구조적으로 막는다.
_SECTION_KEY = r"(?P<key>[A-Za-z0-9_:-]+)"
```

```python
    ("GET", re.compile(rf"/api/se/analyze/{_JOB_ID}/section/{_SECTION_KEY}"), "section"),
```

**`get` 라우트보다 먼저** 넣는다 — 아니면 `/section/...`이 `job_id`에 흡수되지 않는지 확인이 필요하다(`_JOB_ID`는 `/`를 포함하지 않으므로 실제로는 안전하지만, 순서를 명시해 의도를 드러낸다).

- [ ] **Step 4: 핸들러 수정**

`se_server/api/handlers.py`의 `_get`에서 섹션 본문을 빼고 키 목록만 남긴다:

```python
def _get(deps: Deps, user_id: str, job_id: str) -> Response:
    job = deps.store.load(job_id, user_id=user_id)
    if job is None:
        return Response.error(404, "작업을 찾을 수 없습니다")

    finished, total = job.progress()
    # 섹션 **본문은 담지 않는다.** 화면은 이 응답을 수 초 간격으로 폴링하는데,
    # 본문까지 담으면 같은 데이터를 반복 전송한다(실측 737KB × 폴링 횟수).
    # 완료된 키만 알려주고, 화면이 새로 생긴 키만 개별 조회한다.
    return Response(200, {
        "job_id": job.job_id,
        "company": job.company,
        "status": job.status,
        "finished": finished,
        "total": total,
        "failed": [
            {"key": i.key, "error": i.error} for i in job.items if i.status == "failed"
        ],
        "section_keys": [
            i.key for i in job.items if i.status == "done" and i.result is not None
        ],
    })


def _section(deps: Deps, user_id: str, job_id: str, key: str) -> Response:
    """완료된 섹션 하나를 돌려준다.

    미완료 섹션은 404다 — 부분 결과를 완성된 것처럼 보이게 하면 안 된다.
    """
    job = deps.store.load(job_id, user_id=user_id)
    if job is None:
        return Response.error(404, "작업을 찾을 수 없습니다")

    for item in job.items:
        if item.key == key and item.status == "done" and item.result is not None:
            return Response(200, {"key": key, "value": item.result.get("value")})
    return Response.error(404, "섹션을 찾을 수 없습니다")
```

`handle()`의 분기에 추가:

```python
    if name == "section":
        return _section(deps, user_id, path_vars["job_id"], path_vars["key"])
```

- [ ] **Step 5: 검증 스크립트 갱신**

`scripts/se_verify_api.py`의 `[5] 최종 상태`가 `sections`를 읽는다. `section_keys`로 바꾸고, 섹션 하나를 실제로 받아보는 확인을 추가한다:

```python
        print("\n[5] 최종 상태")
        code, body = api(session, args.base, "GET", f"/api/se/analyze/{job_id}",
                         alice.access_token)
        if code == 200:
            keys = body.get("section_keys") or []
            failed = body.get("failed") or []
            print(f"{INFO}{body.get('finished')}/{body.get('total')} 완료 "
                  f"· 섹션 {len(keys)}개 · 실패 {len(failed)}건")
            check("최종 조회 정상", True)
            check("진행률 응답이 경량", len(str(body)) < 20000,
                  f"{len(str(body)):,}자")
            if keys:
                c2, b2 = api(session, args.base, "GET",
                             f"/api/se/analyze/{job_id}/section/{keys[0]}",
                             alice.access_token)
                check("섹션 개별 조회", c2 == 200 and b2.get("key") == keys[0],
                      f"HTTP {c2}")
        else:
            check("최종 조회 정상", False, f"HTTP {code}")
```

- [ ] **Step 6: 테스트 통과 + 전체 회귀**

Run: `python -m pytest tests/se/test_api_sections.py -v`
Expected: PASS — 13 passed

Run: `python -m pytest tests/ -q`
Expected: 실패 0. **기존 `test_api_handlers.py`·`test_api_integration.py`가 `sections`를 단언하면 함께 갱신한다** — 단, "완료 섹션을 알 수 있다"는 검증 의도는 `section_keys`로 유지할 것.

- [ ] **Step 7: 커밋**

```bash
git add se_server/api/ scripts/se_verify_api.py tests/se/test_api_sections.py
git commit -m "feat(se): 진행률 폴링과 섹션 조회 분리 — 폴링당 737KB 제거"
```

---

### Task 2: 브라우저용 공개 설정

브라우저가 Supabase에 로그인하려면 **프로젝트 URL과 anon(publishable) 키**가 필요하다. 이 둘은 공개용이지만, HTML에 하드코딩하면 배포 환경마다 다른 값을 반영할 수 없다.

**Files:**
- Modify: `se_server/config.py`, `se_server/api/router.py`, `se_server/api/handlers.py`
- Test: `tests/se/test_api_config.py`

**Interfaces:**
- Produces:
  - `SEConfig.supabase_anon_key: str` — `SUPABASE_ANON_KEY` 환경변수. **필수 아님**(없으면 빈 문자열)
  - `GET /api/se/config` → `200 {supabase_url, supabase_anon_key}` — **인증 불필요**

**왜 인증이 없는가:** 이 엔드포인트가 없으면 로그인을 할 수 없으므로 인증을 요구하는 것이 논리적으로 불가능하다. 대신 **공개 정보만** 담는다 — anon 키는 브라우저에 노출되도록 설계된 값이고, RLS가 실제 방어선이다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_api_config.py`:

```python
"""브라우저용 공개 설정. service_role 키가 새면 안 된다."""
import json
import unittest
from unittest import mock

from se_server.api.handlers import Deps, handle
from se_server.api.types import Request
from se_server.config import SEConfig
from se_server.jobs.store import MemoryJobStore

CFG = SEConfig(
    supabase_url="https://proj.supabase.co",
    supabase_service_key="SERVICE_KEY_MUST_NOT_LEAK",
    cache_bucket="se-cache",
    supabase_anon_key="ANON_KEY_IS_PUBLIC",
)


class _Auth:
    def verify(self, bearer):
        raise AssertionError("config 엔드포인트는 인증을 호출하면 안 된다")


def _deps():
    return Deps(store=MemoryJobStore(), auth=_Auth(), config=CFG)


class TestConfigEndpoint(unittest.TestCase):
    def test_returns_public_config_without_auth(self):
        resp = handle(Request("GET", "/api/se/config", {}, {}), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["supabase_url"], "https://proj.supabase.co")
        self.assertEqual(resp.body["supabase_anon_key"], "ANON_KEY_IS_PUBLIC")

    def test_never_leaks_service_key(self):
        resp = handle(Request("GET", "/api/se/config", {}, {}), _deps())
        dumped = json.dumps(resp.body, ensure_ascii=False)
        self.assertNotIn("SERVICE_KEY_MUST_NOT_LEAK", dumped)
        self.assertNotIn("service", dumped.lower())

    def test_never_touches_store(self):
        store = mock.Mock()
        handle(Request("GET", "/api/se/config", {}, {}),
               Deps(store=store, auth=_Auth(), config=CFG))
        store.load.assert_not_called()
        store.save.assert_not_called()

    def test_missing_anon_key_is_empty_not_error(self):
        """anon 키 미설정은 설정 실수다. 500이 아니라 빈 값으로 알린다."""
        cfg = SEConfig(supabase_url="https://p.supabase.co",
                       supabase_service_key="K", cache_bucket="b")
        resp = handle(Request("GET", "/api/se/config", {}, {}),
                      Deps(store=MemoryJobStore(), auth=_Auth(), config=cfg))
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["supabase_anon_key"], "")


class TestConfigFromEnv(unittest.TestCase):
    def test_reads_anon_key(self):
        env = {"SUPABASE_URL": "https://x.supabase.co",
               "SUPABASE_SERVICE_KEY": "K", "SUPABASE_ANON_KEY": "A"}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertEqual(SEConfig.from_env().supabase_anon_key, "A")

    def test_anon_key_is_optional(self):
        env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": "K"}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertEqual(SEConfig.from_env().supabase_anon_key, "")

    def test_anon_key_is_not_in_repr(self):
        """공개 키지만 repr에 굳이 담을 이유가 없다."""
        self.assertNotIn("ANON_KEY_IS_PUBLIC", repr(CFG))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_api_config.py -v`
Expected: FAIL — `SEConfig`에 `supabase_anon_key`가 없고 `Deps`에 `config`가 없다

- [ ] **Step 3: 구현**

`se_server/config.py`의 `SEConfig`에 필드를 추가한다:

```python
    # 브라우저에 내보내는 공개 키(구 anon). RLS가 실제 방어선이므로 노출돼도
    # 되는 값이지만, repr에 담을 이유는 없어 service key와 같이 가린다.
    supabase_anon_key: str = field(default="", repr=False)
```

`from_env`에 `supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY") or ""`를 추가한다. **필수로 만들지 않는다** — 없으면 로그인만 안 되고 나머지 API는 동작해야 한다.

`Deps`에 `config` 필드를 추가한다:

```python
@dataclass
class Deps:
    store: JobStore
    auth: object
    budget_seconds: float = _DEFAULT_BUDGET
    config: object = None  # SEConfig. /api/se/config 응답에만 쓴다
```

`build_deps()`가 `config=config`를 넘기도록 수정한다.

라우터에 추가:

```python
    ("GET", re.compile(r"/api/se/config"), "config"),
```

`handle()`에서 **인증보다 먼저** 분기한다 — 이 엔드포인트는 인증 전에 필요하다:

```python
    name, path_vars = route

    # config는 로그인 전에 필요하므로 인증 앞에 둔다. 공개 정보만 담는다.
    if name == "config":
        return _config(deps)

    # 그 외에는 인증이 먼저다.
    try:
        user_id = deps.auth.verify(...)
```

```python
def _config(deps: Deps) -> Response:
    """브라우저 로그인에 필요한 공개 설정.

    **service_role 키를 절대 담지 않는다.** anon 키는 브라우저 노출을 전제로
    설계된 값이며 RLS가 실제 방어선이다.
    """
    config = deps.config
    return Response(200, {
        "supabase_url": getattr(config, "supabase_url", ""),
        "supabase_anon_key": getattr(config, "supabase_anon_key", ""),
    })
```

- [ ] **Step 4: 테스트 통과 + 회귀**

Run: `python -m pytest tests/se/test_api_config.py -v`
Expected: PASS — 7 passed

Run: `python -m pytest tests/ -q`
Expected: 실패 0. `Deps` 시그니처가 바뀌므로 기존 테스트가 깨지는지 확인한다(기본값 `None`이라 하위 호환이어야 한다).

- [ ] **Step 5: 커밋**

```bash
git add se_server/ tests/se/test_api_config.py
git commit -m "feat(se): 브라우저용 공개 설정 엔드포인트"
```

---

### Task 3: 원문 조회 (우측 패널 3단)

설계 §7.2의 우측 패널은 **공시 제목을 클릭하면 원문을 연다.** 그 시점에 로드하는 것이 3단 로딩이다.

**Files:**
- Modify: `se_server/api/router.py`, `se_server/api/handlers.py`
- Test: `tests/se/test_api_disclosure.py`

**Interfaces:**
- Produces:
  - `GET /api/se/disclosure/{rcept_no}` → `200 {rcept_no, text, truncated}` — 인증 필요, `X-DART-Key` 필요

**왜 작업(job)에 묶지 않는가:** 원문은 `rcept_no`만 있으면 되고 특정 작업에 속하지 않는다. 작업에 묶으면 화면이 "이 공시가 어느 작업에서 왔는지"를 추적해야 한다. 공시는 **공개 데이터**이므로 소유권 개념이 없다 — 인증만 요구한다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_api_disclosure.py`:

```python
"""원문 조회 — 우측 패널이 공시를 열 때 쓴다."""
import unittest
from unittest import mock

from se_server.api.auth import AuthError
from se_server.api.handlers import Deps, handle
from se_server.api.types import Request
from se_server.jobs.store import MemoryJobStore


class _Auth:
    def __init__(self, user_id="user-1"):
        self.user_id = user_id

    def verify(self, bearer):
        if not bearer:
            raise AuthError(401, "인증 토큰이 없습니다")
        return self.user_id


def _req(path, token="T", dart_key="DARTKEY123456"):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if dart_key:
        headers["X-DART-Key"] = dart_key
    return Request("GET", path, headers, {})


def _deps():
    return Deps(store=MemoryJobStore(), auth=_Auth())


class TestDisclosure(unittest.TestCase):
    def test_returns_text(self):
        with mock.patch("se_server.api.handlers.fetch_disclosure_full",
                        return_value={"text": "본문 내용", "truncated": False}) as f:
            resp = handle(_req("/api/se/disclosure/20240301000001"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["rcept_no"], "20240301000001")
        self.assertEqual(resp.body["text"], "본문 내용")
        self.assertEqual(f.call_args[0][0], "20240301000001")

    def test_requires_auth(self):
        with mock.patch("se_server.api.handlers.fetch_disclosure_full") as f:
            resp = handle(_req("/api/se/disclosure/20240301000001", token=""), _deps())
        self.assertEqual(resp.status, 401)
        f.assert_not_called()

    def test_requires_dart_key(self):
        with mock.patch("se_server.api.handlers.fetch_disclosure_full") as f:
            resp = handle(_req("/api/se/disclosure/20240301000001", dart_key=""),
                          _deps())
        self.assertEqual(resp.status, 400)
        f.assert_not_called()

    def test_empty_result_is_404(self):
        """원문을 못 받으면 빈 본문을 성공처럼 주지 않는다."""
        with mock.patch("se_server.api.handlers.fetch_disclosure_full",
                        return_value={"text": ""}):
            resp = handle(_req("/api/se/disclosure/20240301000001"), _deps())
        self.assertEqual(resp.status, 404)

    def test_dart_key_is_not_echoed(self):
        import json
        key = "SECRET_DART_KEY_9999"
        req = Request("GET", "/api/se/disclosure/20240301000001",
                      {"Authorization": "Bearer T", "X-DART-Key": key}, {})
        with mock.patch("se_server.api.handlers.fetch_disclosure_full",
                        return_value={"text": "본문"}):
            resp = handle(req, _deps())
        self.assertNotIn(key, json.dumps(resp.body, ensure_ascii=False))

    def test_fetch_failure_is_502_not_500(self):
        """DART 쪽 실패와 우리 쪽 오류를 구분한다."""
        with mock.patch("se_server.api.handlers.fetch_disclosure_full",
                        side_effect=RuntimeError("DART 오류")):
            resp = handle(_req("/api/se/disclosure/20240301000001"), _deps())
        self.assertEqual(resp.status, 502)


class TestRcptNoRouting(unittest.TestCase):
    def test_only_digits_match(self):
        from se_server.api.router import match
        name, vars_ = match("GET", "/api/se/disclosure/20240301000001")
        self.assertEqual(name, "disclosure")
        self.assertEqual(vars_["rcept_no"], "20240301000001")

    def test_non_numeric_is_rejected(self):
        from se_server.api.router import match
        self.assertIsNone(match("GET", "/api/se/disclosure/abc"))
        self.assertIsNone(match("GET", "/api/se/disclosure/../../etc/passwd"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2~5: 실패 확인 → 구현 → 통과 → 커밋**

라우터:

```python
# 접수번호는 숫자 14자리다. 숫자만 허용해 경로 순회를 구조적으로 막는다.
_RCEPT_NO = r"(?P<rcept_no>[0-9]{8,20})"
```

```python
    ("GET", re.compile(rf"/api/se/disclosure/{_RCEPT_NO}"), "disclosure"),
```

핸들러 (`handlers.py` 상단에 `from dart_risk_mcp.core.dart_client import fetch_disclosure_full` 추가):

```python
def _disclosure(request: Request, deps: Deps, rcept_no: str) -> Response:
    """공시 원문. 우측 패널이 클릭 시 호출한다(3단 로딩).

    작업에 묶지 않는다 — 공시는 공개 데이터라 소유권 개념이 없고, 작업에
    묶으면 화면이 "이 공시가 어느 작업에서 왔는지"를 추적해야 한다.
    """
    api_key = _dart_key(request)
    if not api_key:
        return Response.error(400, "X-DART-Key 헤더가 필요합니다")

    try:
        result = fetch_disclosure_full(rcept_no, api_key) or {}
    except Exception:
        # DART 쪽 실패를 500으로 보고하면 우리 버그로 오해된다.
        return Response.error(502, "공시 원문을 가져오지 못했습니다")

    text = result.get("text") or ""
    if not text:
        return Response.error(404, "공시 원문을 찾을 수 없습니다")
    return Response(200, {
        "rcept_no": rcept_no,
        "text": text,
        "truncated": bool(result.get("truncated")),
    })
```

Run: `python -m pytest tests/se/test_api_disclosure.py -v` → 8 passed
Run: `python -m pytest tests/ -q` → 실패 0

```bash
git commit -m "feat(se): 공시 원문 조회 엔드포인트 (우측 패널 3단)"
```

---

### Task 4: 행위자 대조

**SE의 유일한 독점 자산**이다. 이 엔드포인트가 없으면 화면에 행위자가 나오지 않고, SE는 "공시를 좀 더 보여주는 도구"에 그친다.

**Files:**
- Modify: `se_server/api/router.py`, `se_server/api/handlers.py`
- Test: `tests/se/test_api_actors.py`

**Interfaces:**
- Produces:
  - `GET /api/se/actors?company=<이름>` → `200 {company, actors: [...], disclaimer}` — 인증 필요

**반환 형태:** 각 행위자에 `name`·`status`·`companies`·`evidence`를 담고, **`status`와 면책 문구를 항상 동반**한다. `auto_matched`는 동명이인 미확인이므로 화면이 반드시 그 사실을 표시해야 한다.

**레지스트리 미설정 시:** `load_known_actors()`가 빈 스켈레톤을 돌려주므로 `actors: []`가 된다. **500이 아니다** — opt-in 기능이라 미설정이 정상 상태다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_api_actors.py`:

```python
"""행위자 대조 — SE의 독점 자산. 실명을 다루므로 가장 조심스럽다."""
import json
import unittest
from unittest import mock

from se_server.api.auth import AuthError
from se_server.api.handlers import Deps, handle
from se_server.api.types import Request
from se_server.jobs.store import MemoryJobStore


class _Auth:
    def verify(self, bearer):
        if not bearer:
            raise AuthError(401, "인증 토큰이 없습니다")
        return "user-1"


def _req(path, token="T"):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return Request("GET", path, headers, {})


def _deps():
    return Deps(store=MemoryJobStore(), auth=_Auth())


_SAMPLE = [
    ("김OO", {"status": "verified", "companies": ["A사"], "evidence": "2024 CB 인수"}),
    ("이OO", {"status": "auto_matched", "companies": ["B사"], "evidence": "자동 발굴"}),
]


class TestActors(unittest.TestCase):
    def test_returns_actors_for_company(self):
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=_SAMPLE) as f:
            resp = handle(_req("/api/se/actors?company=테스트회사"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(f.call_args[0][0], "테스트회사")
        self.assertEqual(len(resp.body["actors"]), 2)

    def test_status_is_always_present(self):
        """auto_matched는 동명이인 미확인이다. 화면이 반드시 알아야 한다."""
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=_SAMPLE):
            resp = handle(_req("/api/se/actors?company=테스트회사"), _deps())
        for actor in resp.body["actors"]:
            self.assertIn("status", actor)
            self.assertIn(actor["status"], ("verified", "maintainer_seed", "auto_matched"))

    def test_disclaimer_is_always_present(self):
        """실명을 내보내면서 면책을 빼면 안 된다."""
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=_SAMPLE):
            resp = handle(_req("/api/se/actors?company=테스트회사"), _deps())
        self.assertIn("disclaimer", resp.body)
        self.assertTrue(resp.body["disclaimer"])

    def test_requires_auth(self):
        with mock.patch("se_server.api.handlers.lookup_actors_by_company") as f:
            resp = handle(_req("/api/se/actors?company=회사", token=""), _deps())
        self.assertEqual(resp.status, 401)
        f.assert_not_called()

    def test_missing_company_is_400(self):
        with mock.patch("se_server.api.handlers.lookup_actors_by_company") as f:
            resp = handle(_req("/api/se/actors"), _deps())
        self.assertEqual(resp.status, 400)
        f.assert_not_called()

    def test_registry_unavailable_is_empty_not_error(self):
        """레지스트리는 opt-in이다. 미설정이 정상 상태다."""
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=[]):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.body["actors"], [])

    def test_lookup_failure_is_502(self):
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        side_effect=RuntimeError("Notion 오류")):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        self.assertEqual(resp.status, 502)

    def test_no_score_or_grade_in_response(self):
        """v0.8.5: 위험도를 정량화하지 않는다."""
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=_SAMPLE):
            resp = handle(_req("/api/se/actors?company=회사"), _deps())
        dumped = json.dumps(resp.body, ensure_ascii=False)
        for banned in ("점수", "등급", "score", "grade", "위험도"):
            self.assertNotIn(banned, dumped)


class TestQueryParsing(unittest.TestCase):
    def test_company_is_url_decoded(self):
        with mock.patch("se_server.api.handlers.lookup_actors_by_company",
                        return_value=[]) as f:
            handle(_req("/api/se/actors?company=%EC%85%80%ED%8A%B8%EB%A6%AC%EC%98%A8"),
                   _deps())
        self.assertEqual(f.call_args[0][0], "셀트리온")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2~5: 실패 확인 → 구현 → 통과 → 커밋**

`Request`에 쿼리 파싱이 없으므로 핸들러에서 처리한다(라우터는 이미 `?` 앞만 매칭한다):

```python
from urllib.parse import parse_qs, unquote, urlsplit  # handlers.py 상단
from dart_risk_mcp.core.known_actors import lookup_actors_by_company

_ACTOR_DISCLAIMER = (
    "공개기록에 근거한 사실 표기입니다. 위험 판정이 아니며, 동명이인일 수 "
    "있습니다. status가 auto_matched인 항목은 동명이인 확인이 되지 않았습니다."
)


def _query(request: Request, name: str) -> str:
    values = parse_qs(urlsplit(request.path).query).get(name) or []
    return unquote(values[0]).strip() if values else ""


def _actors(request: Request, deps: Deps) -> Response:
    """회사에 등장한 공개기록 행위자.

    실명을 내보내므로 status와 면책을 **항상** 동반한다. 판정·점수는 없다.
    """
    company = _query(request, "company")
    if not company:
        return Response.error(400, "company 파라미터가 필요합니다")

    try:
        found = lookup_actors_by_company(company) or []
    except Exception:
        return Response.error(502, "레지스트리를 조회하지 못했습니다")

    return Response(200, {
        "company": company,
        "actors": [
            {
                "name": name,
                "status": (rec or {}).get("status", "auto_matched"),
                "companies": (rec or {}).get("companies", []),
                "evidence": (rec or {}).get("evidence", ""),
            }
            for name, rec in found
        ],
        "disclaimer": _ACTOR_DISCLAIMER,
    })
```

> `status` 기본값을 `auto_matched`(가장 약한 등급)로 두는 이유: 레코드에 status가 없을 때 `verified`로 보이면 **확인되지 않은 정보를 확인된 것처럼** 표시하게 된다.

라우터:

```python
    ("GET", re.compile(r"/api/se/actors"), "actors"),
```

Run: `python -m pytest tests/se/test_api_actors.py -v` → 9 passed
Run: `python -m pytest tests/ -q` → 실패 0

```bash
git commit -m "feat(se): 행위자 대조 엔드포인트 — status·면책 항상 동반"
```

---

### Task 5: 배포 검증 갱신

**Files:**
- Modify: `scripts/se_verify_api.py`
- Test: 없음 (검증 스크립트 자체)

새 엔드포인트 4종을 배포 검증에 넣는다. `[6] 신규 엔드포인트` 절을 추가한다:

- `GET /api/se/config` — 인증 없이 200, **service key가 응답에 없음**
- `GET /api/se/analyze/{id}/section/{key}` — 소유자 200, 타인 404
- `GET /api/se/disclosure/{rcept_no}` — 인증 필요, 실제 공시로 200
- `GET /api/se/actors?company=` — 인증 필요, 면책 포함

**진행률 응답 크기를 반드시 출력한다.** 이 계획의 목적이 그것이므로, 실측값이 안 보이면 검증이 아니다.

- [ ] **Step 1~3: 갱신 → 로컬 실행 → 커밋**

Run: `python scripts/se_verify_api.py --steps 12`
Expected: 전부 통과. **진행률 응답이 이전 737KB에서 수 KB로 줄어야 한다** — 줄지 않았으면 Task 1이 실제로 적용되지 않은 것이다.

```bash
git commit -m "test(se): 신규 엔드포인트 4종을 배포 검증에 추가"
```

---

## 이 계획이 다루지 않는 것 — SE-4b

| 항목 | 내용 |
|---|---|
| **로그인 화면** | Supabase Auth REST(`POST /auth/v1/token`)를 fetch로 직접 호출. SDK·CDN 없음 |
| **롱스크롤 본문** | 헤더 → ①계획vs실제 → ②자금 체인 → ③시계열 레인 → ④재무이상 → ⑤지배구조 → ⑥감사·부실 → ⑦원문 → ⑧출처·면책 |
| **우측 슬라이드 패널** | 인물 클릭 → 행위자, 공시 클릭 → 원문, 피출자 법인 클릭 → 상세 |
| **점진 렌더** | `GET`으로 `section_keys`를 폴링하고, **새로 생긴 키만** 개별 조회 |
| **DART 키 입력 UI** | `localStorage` 보관 |

SE-4b는 이 계획이 만든 API 위에서만 성립한다. 화면부터 만들면 곧바로 막힌다.

## 자체 검토 결과

- **스펙 커버리지:** §7.2(우측 패널) → Task 3·4. §7.3(점진 렌더) → Task 1. §4(브라우저 로그인) → Task 2.
- **스펙 갱신 필요:** §7.3의 엔드포인트 표에 `section`·`config`·`disclosure`·`actors`가 없다. Task 5 완료 후 갱신할 것.
- **파괴적 변경 1건:** `GET /api/se/analyze/{id}`에서 `sections`를 제거한다. 소비자는 `scripts/se_verify_api.py` 하나뿐이며 Task 1에서 함께 갱신한다.
- **미해결 위험 2건:**
  1. **`insider_timeline` 단일 섹션이 305KB다.** 섹션을 분리해도 이 하나는 여전히 크다. SE-4b가 이걸 어떻게 그릴지 정할 때, 서버에서 요약해 내려보내는 편이 나을 수 있다 — 다만 그건 화면 요구가 확정된 뒤의 판단이다.
  2. **`/api/se/config`가 인증 없이 열린다.** anon 키는 공개 전제 값이지만, 이 엔드포인트로 **Supabase 프로젝트 URL이 공개**된다. 이미 브라우저 로그인에 필요한 정보라 불가피하며, RLS가 실제 방어선이다.
