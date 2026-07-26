# SE-1: 캐시 계층 + core HTTP 시임 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `se_server` 패키지의 기반을 세우고, DART HTTP 응답(구조화 JSON + 원문 ZIP)을 외부 저장소에 캐시해 같은 회사 2회차 조회를 8–15분에서 30초~1분으로 줄인다.

**Architecture:** `dart_risk_mcp/core/dart_client.py`의 `_retry()`가 모든 DART 트래픽의 단일 진입점이므로, 여기에 **선택적 캐시 훅**을 하나 추가한다(기본 `None` = 현행 동작). `se_server`가 그 훅에 캐싱 계층을 꽂고, 캐싱 계층은 교체 가능한 백엔드(테스트용 인메모리 / 운영용 Supabase)를 사용한다. HTTP 서버·인증·화면은 이 계획의 범위가 아니며, 산출물은 CLI로 단독 검증한다.

**Tech Stack:** Python 3.11+, `requests`(기존 의존성), Supabase Storage + PostgREST(REST 직접 호출, SDK 없음), `unittest`(기존 테스트 관행)

## Global Constraints

- `dart_risk_mcp/` core의 런타임 의존성은 `mcp>=1.0.0`, `requests>=2.28.0`만 유지한다. **core에 새 의존성을 추가하지 않는다.**
- `se_server/`는 별도 최상위 패키지다. core는 `se_server`를 import하지 않는다 (의존 방향은 `se_server` → `core` 단방향).
- Supabase 접근은 REST(`requests`)로 한다. `supabase-py`·`gotrue`·`postgrest`·`storage3`를 설치하지 않는다.
- **캐시 키에 사용자 식별자를 넣지 않는다.** DART API 키(`crtfc_key`)는 사실상 사용자 식별자이므로 캐시 키 계산에서 반드시 제외한다. 원문은 공개 데이터이므로 전 사용자가 캐시를 공유한다.
- 원문 ZIP은 `rcept_no`가 불변이므로 **TTL 없이 영구** 보관한다. 구조화 JSON 응답은 **7일** TTL.
- 기존 MCP 서버 동작은 바뀌면 안 된다. 캐시 미설정(`None`)이 기본이며, 이 경우 `_retry`는 현행과 동일하게 동작한다.
- 테스트는 기존 관행을 따른다: `unittest.TestCase` 클래스, `tests/` 하위, 네트워크 호출 없음(전부 스텁).
- 사용자 출력 경로가 아니므로 v0.8.5 무점수 원칙 검사 대상은 아니지만, 로그·예외 메시지에 점수·등급 표현을 쓰지 않는다.

---

## File Structure

| 파일 | 책임 |
|---|---|
| `se_server/__init__.py` | 패키지 선언. 버전 상수만 |
| `se_server/cache/__init__.py` | 캐시 서브패키지 공개 API |
| `se_server/cache/base.py` | `CacheBackend` 프로토콜 + `MemoryCache`(테스트·로컬용) |
| `se_server/cache/supabase.py` | `SupabaseCache` — Storage(blob) + PostgREST(json) |
| `se_server/http_cache.py` | `CachingHttp` — core 시임에 꽂히는 캐시 정책 계층 |
| `se_server/config.py` | 환경변수 로드 |
| `dart_risk_mcp/core/dart_client.py` | **수정** — `set_http_cache()` 훅 추가 |
| `tests/se/test_cache_base.py` | `MemoryCache` 동작 |
| `tests/se/test_http_cache.py` | 캐시 키 계산·정책 분기 |
| `tests/se/test_supabase_cache.py` | `SupabaseCache` HTTP 계약 (요청 스텁) |
| `tests/test_core_http_seam.py` | core 시임 계약 + 기본값 무캐시 회귀 |
| `scripts/se_cache_bench.py` | 콜드/웜 실측 CLI |

`cache/base.py`와 `cache/supabase.py`를 나눈 이유: 백엔드 교체가 이 설계의 핵심이라 인터페이스와 구현이 같은 파일에 있으면 테스트가 Supabase를 끌고 온다.

---

### Task 1: se_server 패키지 골격 + 캐시 백엔드 인터페이스

**Files:**
- Create: `se_server/__init__.py`
- Create: `se_server/cache/__init__.py`
- Create: `se_server/cache/base.py`
- Create: `tests/se/__init__.py`
- Test: `tests/se/test_cache_base.py`

**Interfaces:**
- Consumes: 없음 (첫 태스크)
- Produces:
  - `se_server.cache.base.CacheBackend` — 프로토콜. 메서드 4개:
    - `get_blob(key: str) -> bytes | None`
    - `put_blob(key: str, data: bytes) -> None`
    - `get_json(key: str) -> dict | None`
    - `put_json(key: str, value: dict, ttl_seconds: int | None) -> None`
  - `se_server.cache.base.MemoryCache` — 위 프로토콜의 인메모리 구현. 생성자 `MemoryCache(now: Callable[[], float] = time.time)`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_cache_base.py`:

```python
"""SE 캐시 백엔드 기본 동작."""
import unittest

from se_server.cache.base import MemoryCache


class TestMemoryCacheBlob(unittest.TestCase):
    def test_miss_returns_none(self):
        cache = MemoryCache()
        self.assertIsNone(cache.get_blob("없는키"))

    def test_put_then_get(self):
        cache = MemoryCache()
        cache.put_blob("20240301000001", b"ZIP-BYTES")
        self.assertEqual(cache.get_blob("20240301000001"), b"ZIP-BYTES")

    def test_blob_never_expires(self):
        """원문 ZIP은 rcept_no가 불변이므로 시간이 흘러도 유효하다."""
        clock = {"t": 100.0}
        cache = MemoryCache(now=lambda: clock["t"])
        cache.put_blob("k", b"data")
        clock["t"] = 100.0 + 86400 * 3650
        self.assertEqual(cache.get_blob("k"), b"data")


class TestMemoryCacheJson(unittest.TestCase):
    def test_miss_returns_none(self):
        self.assertIsNone(MemoryCache().get_json("없는키"))

    def test_roundtrip_without_ttl(self):
        cache = MemoryCache()
        cache.put_json("k", {"status": "000"}, ttl_seconds=None)
        self.assertEqual(cache.get_json("k"), {"status": "000"})

    def test_expires_after_ttl(self):
        clock = {"t": 100.0}
        cache = MemoryCache(now=lambda: clock["t"])
        cache.put_json("k", {"status": "000"}, ttl_seconds=10)
        clock["t"] = 111.0
        self.assertIsNone(cache.get_json("k"))

    def test_valid_just_before_ttl(self):
        clock = {"t": 100.0}
        cache = MemoryCache(now=lambda: clock["t"])
        cache.put_json("k", {"status": "000"}, ttl_seconds=10)
        clock["t"] = 109.0
        self.assertEqual(cache.get_json("k"), {"status": "000"})

    def test_blob_and_json_namespaces_are_separate(self):
        """같은 키라도 blob과 json은 서로 덮어쓰지 않는다."""
        cache = MemoryCache()
        cache.put_blob("k", b"blob")
        cache.put_json("k", {"a": 1}, ttl_seconds=None)
        self.assertEqual(cache.get_blob("k"), b"blob")
        self.assertEqual(cache.get_json("k"), {"a": 1})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_cache_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'se_server'`

- [ ] **Step 3: 패키지 골격 생성**

`se_server/__init__.py`:

```python
"""SE(스페셜 에디션) 서버 패키지.

dart_risk_mcp.core를 import해서 사용하되, core를 수정하거나 core가
이 패키지를 참조하게 하지 않는다. 의존 방향은 se_server → core 단방향이다.

설계: docs/superpowers/specs/2026-07-26-risk-viewer-se-design.md
"""

__version__ = "0.1.0"
```

`se_server/cache/__init__.py`:

```python
"""SE 캐시 계층."""
from se_server.cache.base import CacheBackend, MemoryCache

__all__ = ["CacheBackend", "MemoryCache"]
```

`tests/se/__init__.py`:

```python
```

(빈 파일)

- [ ] **Step 4: MemoryCache 구현**

`se_server/cache/base.py`:

```python
"""캐시 백엔드 인터페이스와 인메모리 구현.

두 종류를 나눠 다룬다:
- blob: 공시 원문 ZIP. rcept_no가 불변 식별자이고 정정공시는 새 번호를
  발급받으므로 stale이 발생하지 않는다. TTL 없이 영구 보관한다.
- json: 구조화 API 응답. 확정 연도는 불변이나 최근 연도는 정정될 수
  있으므로 TTL을 둔다.

근거: docs/superpowers/specs/2026-07-26-risk-viewer-se-design.md §6.2
"""
from __future__ import annotations

import time
from typing import Callable, Protocol


class CacheBackend(Protocol):
    """SE 캐시 백엔드가 제공해야 하는 최소 인터페이스."""

    def get_blob(self, key: str) -> bytes | None: ...

    def put_blob(self, key: str, data: bytes) -> None: ...

    def get_json(self, key: str) -> dict | None: ...

    def put_json(self, key: str, value: dict, ttl_seconds: int | None) -> None: ...


class MemoryCache:
    """프로세스 메모리 백엔드. 테스트와 로컬 개발용.

    Vercel 함수는 파일시스템·메모리가 비영속이므로 운영에서는 쓰지 않는다.
    """

    def __init__(self, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._blobs: dict[str, bytes] = {}
        self._json: dict[str, tuple[float | None, dict]] = {}

    def get_blob(self, key: str) -> bytes | None:
        return self._blobs.get(key)

    def put_blob(self, key: str, data: bytes) -> None:
        self._blobs[key] = data

    def get_json(self, key: str) -> dict | None:
        entry = self._json.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at is not None and self._now() >= expires_at:
            del self._json[key]
            return None
        return value

    def put_json(self, key: str, value: dict, ttl_seconds: int | None) -> None:
        expires_at = None if ttl_seconds is None else self._now() + ttl_seconds
        self._json[key] = (expires_at, value)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/se/test_cache_base.py -v`
Expected: PASS — 8 passed

- [ ] **Step 6: 커밋**

```bash
git add se_server/ tests/se/
git commit -m "feat(se): 캐시 백엔드 인터페이스와 인메모리 구현 추가"
```

---

### Task 2: core에 선택적 HTTP 캐시 시임 추가

`_retry()`는 DART의 모든 트래픽(구조화 JSON·원문 ZIP)이 지나는 단일 진입점이다. 여기에 훅을 하나 두면 엔드포인트별 개별 캐싱이 필요 없다.

이 태스크만이 core를 수정한다. 스펙 §3.1의 예외 조건("MCP 도구에도 독립적으로 유용한가")을 통과한다 — MCP 서버 역시 같은 ZIP을 반복 내려받고 있으며, 이 훅으로 동일하게 이득을 볼 수 있다. 기본값이 `None`이므로 미설정 시 동작은 완전히 동일하다.

**Files:**
- Modify: `dart_risk_mcp/core/dart_client.py` (`_retry` 정의부 주변)
- Test: `tests/test_core_http_seam.py`

**Interfaces:**
- Consumes: 없음 (core 단독)
- Produces:
  - `dart_risk_mcp.core.dart_client.set_http_cache(cache: HttpCache | None) -> None`
  - `dart_risk_mcp.core.dart_client.get_http_cache() -> HttpCache | None`
  - `HttpCache` 계약 (덕 타이핑, 프로토콜 클래스는 core에 두지 않는다):
    - `get(url: str, params: dict) -> tuple[int, dict, bytes] | None` — `(status_code, headers, body)`
    - `put(url: str, params: dict, status: int, headers: dict, body: bytes) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_core_http_seam.py`:

```python
"""core _retry의 선택적 HTTP 캐시 시임 계약.

이 시임은 se_server가 캐시를 주입하는 유일한 지점이다. 기본값은 None이며
MCP 서버는 이를 설정하지 않으므로 기존 동작이 그대로 유지되어야 한다.
"""
import unittest
from unittest import mock

from dart_risk_mcp.core import dart_client


class FakeCache:
    def __init__(self, preload=None):
        self.preload = preload
        self.puts = []
        self.gets = []

    def get(self, url, params):
        self.gets.append((url, params))
        return self.preload

    def put(self, url, params, status, headers, body):
        self.puts.append((url, params, status, headers, body))


def _fake_response(status=200, body=b"{}", headers=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.content = body
    resp.headers = headers or {"Content-Type": "application/json"}
    return resp


class TestHttpSeamDefault(unittest.TestCase):
    def tearDown(self):
        dart_client.set_http_cache(None)

    def test_default_cache_is_none(self):
        self.assertIsNone(dart_client.get_http_cache())

    def test_without_cache_calls_network(self):
        with mock.patch.object(
            dart_client.requests, "request", return_value=_fake_response()
        ) as req:
            dart_client._retry("GET", "https://example.test/api/list.json",
                               params={"crtfc_key": "K"})
        self.assertEqual(req.call_count, 1)


class TestRetrySemanticsUnchanged(unittest.TestCase):
    """캐시 훅을 달면서 기존 재시도·예외 동작이 바뀌지 않았는지 고정한다.

    _retry는 거의 모든 core 함수가 쓰므로 이 계약이 깨지면 광범위한 회귀가 난다.
    """

    def tearDown(self):
        dart_client.set_http_cache(None)

    def test_4xx_is_returned_not_raised(self):
        """404 등 비재시도 4xx는 예외 없이 그대로 반환된다.

        _fetch_document_zip을 비롯한 호출자들이 `resp.status_code != 200`으로
        분기하므로, 여기서 raise하면 그 분기가 죽는다.
        """
        resp404 = _fake_response(status=404)
        with mock.patch.object(dart_client.requests, "request", return_value=resp404) as req:
            result = dart_client._retry("GET", "https://example.test/api/list.json", params={})
        self.assertEqual(result.status_code, 404)
        self.assertEqual(req.call_count, 1)  # 4xx는 재시도하지 않는다
        resp404.raise_for_status.assert_not_called()

    def test_4xx_not_retried_with_cache_enabled(self):
        """캐시가 켜져 있어도 4xx 동작은 같아야 한다."""
        dart_client.set_http_cache(FakeCache(preload=None))
        resp403 = _fake_response(status=403)
        with mock.patch.object(dart_client.requests, "request", return_value=resp403):
            result = dart_client._retry("GET", "https://example.test/api/list.json", params={})
        self.assertEqual(result.status_code, 403)
        resp403.raise_for_status.assert_not_called()

    def test_persistent_5xx_exhausts_retries_then_raises(self):
        """재시도를 모두 소진한 5xx는 기존대로 raise_for_status를 호출한다."""
        resp500 = _fake_response(status=500)
        resp500.raise_for_status.side_effect = RuntimeError("500")
        with mock.patch.object(dart_client.requests, "request", return_value=resp500) as req, \
                mock.patch.object(dart_client.time, "sleep"):
            with self.assertRaises(RuntimeError):
                dart_client._retry("GET", "https://example.test/api/list.json", params={})
        self.assertEqual(req.call_count, 3)

    def test_429_is_retried_then_succeeds(self):
        """429 후 200이 오면 재시도해서 성공 응답을 반환한다."""
        responses = [_fake_response(status=429), _fake_response(status=200, body=b'{"ok":1}')]
        with mock.patch.object(
            dart_client.requests, "request", side_effect=responses
        ) as req, mock.patch.object(dart_client.time, "sleep"):
            result = dart_client._retry("GET", "https://example.test/api/list.json", params={})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(req.call_count, 2)


class TestHttpSeamWithCache(unittest.TestCase):
    def tearDown(self):
        dart_client.set_http_cache(None)

    def test_hit_skips_network(self):
        cache = FakeCache(preload=(200, {"Content-Type": "application/json"}, b'{"status":"000"}'))
        dart_client.set_http_cache(cache)
        with mock.patch.object(dart_client.requests, "request") as req:
            resp = dart_client._retry("GET", "https://example.test/api/list.json",
                                      params={"corp_code": "001"})
        req.assert_not_called()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b'{"status":"000"}')
        self.assertEqual(resp.json(), {"status": "000"})

    def test_miss_calls_network_then_stores(self):
        cache = FakeCache(preload=None)
        dart_client.set_http_cache(cache)
        with mock.patch.object(
            dart_client.requests, "request",
            return_value=_fake_response(body=b'{"status":"000"}')
        ):
            dart_client._retry("GET", "https://example.test/api/list.json",
                               params={"corp_code": "001"})
        self.assertEqual(len(cache.puts), 1)
        url, params, status, headers, body = cache.puts[0]
        self.assertEqual(url, "https://example.test/api/list.json")
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"status":"000"}')

    def test_non_200_is_not_stored(self):
        cache = FakeCache(preload=None)
        dart_client.set_http_cache(cache)
        with mock.patch.object(
            dart_client.requests, "request", return_value=_fake_response(status=404)
        ):
            dart_client._retry("GET", "https://example.test/api/list.json", params={})
        self.assertEqual(cache.puts, [])

    def test_non_get_is_not_cached(self):
        cache = FakeCache(preload=None)
        dart_client.set_http_cache(cache)
        with mock.patch.object(
            dart_client.requests, "request", return_value=_fake_response()
        ):
            dart_client._retry("POST", "https://example.test/api/list.json", params={})
        self.assertEqual(cache.gets, [])
        self.assertEqual(cache.puts, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/test_core_http_seam.py -v`
Expected: FAIL — `AttributeError: module 'dart_risk_mcp.core.dart_client' has no attribute 'set_http_cache'`

- [ ] **Step 3: 시임 구현**

`dart_risk_mcp/core/dart_client.py`의 기존 `_retry` 정의를 아래로 교체한다. 기존 재시도 루프는 그대로 두고 앞뒤만 감싼다.

```python
# ── 선택적 HTTP 캐시 시임 ─────────────────────────────
# se_server 등 외부 소비자가 DART 응답 캐시를 주입하는 유일한 지점.
# 기본값 None이면 캐시 없이 직접 호출한다(MCP 서버의 기존 동작).
#
# 주입 객체는 아래 두 메서드를 제공해야 한다:
#   get(url, params) -> (status_code, headers, body) | None
#   put(url, params, status, headers, body) -> None
#
# 캐시 키 계산은 주입 측 책임이다. 특히 params의 crtfc_key(사용자 API 키)를
# 키에서 제외하는 것은 주입 측에서 처리한다.
_http_cache = None


def set_http_cache(cache) -> None:
    """DART HTTP 응답 캐시를 주입한다. None이면 캐시를 사용하지 않는다."""
    global _http_cache
    _http_cache = cache


def get_http_cache():
    """현재 주입된 HTTP 캐시를 반환한다 (미설정 시 None)."""
    return _http_cache


def _response_from_cache(status: int, headers: dict, body: bytes) -> requests.Response:
    """캐시된 (status, headers, body)로 requests.Response를 합성한다."""
    resp = requests.Response()
    resp.status_code = status
    resp._content = body
    resp.headers.update(headers or {})
    return resp


def _retry(method: str, url: str, **kwargs) -> requests.Response:
    """429/5xx 지수 백오프 재시도 (최대 3회). 3회 후에도 4xx/5xx면 raise_for_status.

    _http_cache가 설정돼 있으면 GET 요청에 한해 캐시를 먼저 조회하고,
    200 응답만 캐시에 저장한다.
    """
    kwargs.setdefault("timeout", 15)

    cache = _http_cache
    cacheable = cache is not None and method.upper() == "GET"
    params = kwargs.get("params") or {}

    if cacheable:
        hit = cache.get(url, params)
        if hit is not None:
            status, headers, body = hit
            return _response_from_cache(status, headers, body)

    last: requests.Response | None = None
    exhausted = True  # 재시도를 모두 소진했는가 (아래 raise_for_status 조건)
    for i in range(3):
        try:
            last = requests.request(method, url, **kwargs)
            if last.status_code not in (429, 500, 502, 503, 504):
                exhausted = False
                break
            if i < 2:
                time.sleep(min(2 ** i, 10))
        except requests.RequestException:
            if i == 2:
                raise
            time.sleep(min(2 ** i, 10))

    if cacheable and last is not None and last.status_code == 200:
        cache.put(url, params, last.status_code, dict(last.headers), last.content)

    # 기존 동작 보존: 비재시도 응답(404 등)은 그대로 반환하고, 재시도를 모두
    # 소진한 429/5xx일 때만 예외를 던진다. `exhausted` 없이 상태 코드만 보면
    # 404가 raise_for_status로 흘러가 호출자의 `status_code != 200` 분기가
    # 죽는다 (_fetch_document_zip 등이 이 분기에 의존한다).
    if exhausted and last is not None and last.status_code >= 400:
        last.raise_for_status()
    return last  # type: ignore
```

> 주의: 기존 구현은 비재시도 응답을 만나면 루프 안에서 곧바로 `return last` 했고, 말미의 `raise_for_status`는 **재시도 소진 시에만** 도달했다. 캐시 저장 훅을 달려면 루프 밖으로 나와야 하므로 `break`로 바꾸되, `exhausted` 플래그로 원래의 예외 조건을 그대로 재현해야 한다. 이 플래그를 빠뜨리면 모든 4xx가 예외로 바뀌는 광범위한 회귀가 난다.

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_core_http_seam.py -v`
Expected: PASS — 10 passed

- [ ] **Step 5: 기존 테스트 전체 회귀 확인**

`_retry`는 거의 모든 core 함수가 쓰므로 전체 스위트를 돌린다.

Run: `python -m pytest tests/ -q`
Expected: 기존과 동일한 통과 수. 실패가 하나라도 늘면 Step 3의 `break` 전환이 원인이므로 되짚는다.

- [ ] **Step 6: 커밋**

```bash
git add dart_risk_mcp/core/dart_client.py tests/test_core_http_seam.py
git commit -m "feat(core): _retry에 선택적 HTTP 캐시 시임 추가 (기본 비활성)"
```

---

### Task 3: CachingHttp — 캐시 키 계산과 정책 분기

**Files:**
- Create: `se_server/http_cache.py`
- Test: `tests/se/test_http_cache.py`

**Interfaces:**
- Consumes: `se_server.cache.base.CacheBackend` (Task 1), `dart_client.set_http_cache` (Task 2)
- Produces:
  - `se_server.http_cache.CachingHttp(backend: CacheBackend, json_ttl_seconds: int = 604800)`
    - `get(url, params) -> tuple[int, dict, bytes] | None`
    - `put(url, params, status, headers, body) -> None`
    - `cache_key(url: str, params: dict) -> str` (공개 — 테스트·디버깅용)
  - `se_server.http_cache.install(backend: CacheBackend) -> CachingHttp` — 생성 후 core에 주입까지 수행

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_http_cache.py`:

```python
"""CachingHttp의 키 계산과 blob/json 정책 분기."""
import unittest

from se_server.cache.base import MemoryCache
from se_server.http_cache import CachingHttp

DOC_URL = "https://opendart.fss.or.kr/api/document.xml"
LIST_URL = "https://opendart.fss.or.kr/api/list.json"


class TestCacheKey(unittest.TestCase):
    def test_api_key_excluded(self):
        """crtfc_key는 사용자 식별자이므로 키에서 제외한다 — 전 사용자가 캐시를 공유한다."""
        http = CachingHttp(MemoryCache())
        a = http.cache_key(LIST_URL, {"crtfc_key": "AAA", "corp_code": "001"})
        b = http.cache_key(LIST_URL, {"crtfc_key": "BBB", "corp_code": "001"})
        self.assertEqual(a, b)

    def test_api_key_value_not_in_key(self):
        http = CachingHttp(MemoryCache())
        key = http.cache_key(LIST_URL, {"crtfc_key": "SECRET123", "corp_code": "001"})
        self.assertNotIn("SECRET123", key)

    def test_param_order_does_not_matter(self):
        http = CachingHttp(MemoryCache())
        a = http.cache_key(LIST_URL, {"corp_code": "001", "bgn_de": "20240101"})
        b = http.cache_key(LIST_URL, {"bgn_de": "20240101", "corp_code": "001"})
        self.assertEqual(a, b)

    def test_different_params_differ(self):
        http = CachingHttp(MemoryCache())
        a = http.cache_key(LIST_URL, {"corp_code": "001"})
        b = http.cache_key(LIST_URL, {"corp_code": "002"})
        self.assertNotEqual(a, b)

    def test_different_endpoint_differs(self):
        http = CachingHttp(MemoryCache())
        a = http.cache_key(LIST_URL, {"corp_code": "001"})
        b = http.cache_key(DOC_URL, {"corp_code": "001"})
        self.assertNotEqual(a, b)

    def test_delimiters_in_values_do_not_collide(self):
        """값에 `&`나 `=`가 섞여도 다른 파라미터 조합은 다른 키를 낳는다.

        단순 문자열 결합이면 아래 둘이 모두 "...?a=b&c=d"로 축약돼 충돌한다.
        """
        http = CachingHttp(MemoryCache())
        a = http.cache_key(LIST_URL, {"a": "b&c=d"})
        b = http.cache_key(LIST_URL, {"a": "b", "c": "d"})
        self.assertNotEqual(a, b)


class TestBlobPoisoningGuard(unittest.TestCase):
    """DART는 오류 시에도 HTTP 200 + JSON/텍스트 바디로 응답할 수 있다.

    blob은 TTL 없이 영구 보관되고 캐시 키가 crtfc_key를 제외해 전 사용자가
    공유하므로, 오류 바디가 한 번 저장되면 해당 rcept_no가 모두에게 영구히
    조회 불가가 된다. 실제 ZIP만 저장해야 한다.
    """

    def test_json_error_body_is_not_stored_as_blob(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"rcept_no": "2024030100001"}
        http.put(DOC_URL, params, 200,
                 {"Content-Type": "application/json"},
                 b'{"status":"013","message":"\xec\xa1\xb0\xed\x9a\x8c\xeb\x90\x9c \xeb\x8d\xb0\xec\x9d\xb4\xed\x84\xb0 \xec\x97\x86\xec\x9d\x8c"}')
        self.assertIsNone(backend.get_blob(http.cache_key(DOC_URL, params)))
        self.assertIsNone(http.get(DOC_URL, params))

    def test_text_error_body_is_not_stored_as_blob(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"rcept_no": "2024030100002"}
        http.put(DOC_URL, params, 200, {"Content-Type": "text/html"}, b"<html>error</html>")
        self.assertIsNone(backend.get_blob(http.cache_key(DOC_URL, params)))

    def test_real_zip_is_still_stored(self):
        """가드가 정상 ZIP까지 막아서는 안 된다."""
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"rcept_no": "2024030100003"}
        http.put(DOC_URL, params, 200, {"Content-Type": "application/zip"}, b"PK\x03\x04REAL")
        self.assertEqual(backend.get_blob(http.cache_key(DOC_URL, params)), b"PK\x03\x04REAL")

    def test_xbrl_endpoint_gets_same_guard(self):
        xbrl_url = "https://opendart.fss.or.kr/api/fnlttXbrl.xml"
        backend = MemoryCache()
        http = CachingHttp(backend)
        params = {"rcept_no": "2024030100004"}
        http.put(xbrl_url, params, 200, {"Content-Type": "application/json"}, b'{"status":"013"}')
        self.assertIsNone(backend.get_blob(http.cache_key(xbrl_url, params)))


class TestPolicyRouting(unittest.TestCase):
    def test_document_xml_stored_as_blob(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        http.put(DOC_URL, {"rcept_no": "2024030100001"}, 200,
                 {"Content-Type": "application/zip"}, b"PK\x03\x04ZIP")
        key = http.cache_key(DOC_URL, {"rcept_no": "2024030100001"})
        self.assertEqual(backend.get_blob(key), b"PK\x03\x04ZIP")
        self.assertIsNone(backend.get_json(key))

    def test_json_endpoint_stored_as_json_with_ttl(self):
        backend = MemoryCache()
        http = CachingHttp(backend, json_ttl_seconds=100)
        http.put(LIST_URL, {"corp_code": "001"}, 200,
                 {"Content-Type": "application/json"}, b'{"status":"000"}')
        key = http.cache_key(LIST_URL, {"corp_code": "001"})
        stored = backend.get_json(key)
        self.assertIsNotNone(stored)
        self.assertEqual(stored["body_b64"], "eyJzdGF0dXMiOiIwMDAifQ==")

    def test_blob_roundtrip_through_get(self):
        http = CachingHttp(MemoryCache())
        params = {"rcept_no": "2024030100001"}
        http.put(DOC_URL, params, 200, {"Content-Type": "application/zip"}, b"PK\x03\x04ZIP")
        hit = http.get(DOC_URL, params)
        self.assertIsNotNone(hit)
        status, headers, body = hit
        self.assertEqual(status, 200)
        self.assertEqual(body, b"PK\x03\x04ZIP")
        self.assertEqual(headers.get("Content-Type"), "application/zip")

    def test_json_roundtrip_through_get(self):
        http = CachingHttp(MemoryCache())
        params = {"corp_code": "001"}
        http.put(LIST_URL, params, 200, {"Content-Type": "application/json"}, b'{"status":"000"}')
        hit = http.get(LIST_URL, params)
        self.assertIsNotNone(hit)
        status, headers, body = hit
        self.assertEqual(status, 200)
        self.assertEqual(body, b'{"status":"000"}')

    def test_miss_returns_none(self):
        http = CachingHttp(MemoryCache())
        self.assertIsNone(http.get(LIST_URL, {"corp_code": "999"}))

    def test_json_expiry_is_a_miss(self):
        clock = {"t": 0.0}
        backend = MemoryCache(now=lambda: clock["t"])
        http = CachingHttp(backend, json_ttl_seconds=10)
        params = {"corp_code": "001"}
        http.put(LIST_URL, params, 200, {"Content-Type": "application/json"}, b'{"status":"000"}')
        clock["t"] = 20.0
        self.assertIsNone(http.get(LIST_URL, params))


class TestNeverCache(unittest.TestCase):
    """corpCode.xml은 신규 상장으로 계속 바뀌므로 캐시 대상이 아니다.

    core의 _load_corp_codes가 24시간 파일 캐시를 이미 두고 있어, 여기서 다시
    캐시하면 그 갱신 주기가 무력화되고 기업 목록이 고정된다.
    """

    CORP_URL = "https://opendart.fss.or.kr/api/corpCode.xml"

    def test_put_stores_nothing(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        http.put(self.CORP_URL, {}, 200, {"Content-Type": "application/zip"}, b"PK\x03\x04")
        key = http.cache_key(self.CORP_URL, {})
        self.assertIsNone(backend.get_blob(key))
        self.assertIsNone(backend.get_json(key))

    def test_get_always_misses(self):
        backend = MemoryCache()
        http = CachingHttp(backend)
        # 백엔드에 직접 심어두더라도 조회 경로에서 걸러져야 한다.
        backend.put_blob(http.cache_key(self.CORP_URL, {}), b"STALE")
        self.assertIsNone(http.get(self.CORP_URL, {}))


class TestInstall(unittest.TestCase):
    def tearDown(self):
        from dart_risk_mcp.core import dart_client
        dart_client.set_http_cache(None)

    def test_install_injects_into_core(self):
        from dart_risk_mcp.core import dart_client
        from se_server.http_cache import install

        http = install(MemoryCache())
        self.assertIs(dart_client.get_http_cache(), http)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_http_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'se_server.http_cache'`

- [ ] **Step 3: CachingHttp 구현**

`se_server/http_cache.py`:

```python
"""core _retry 시임에 꽂히는 캐시 정책 계층.

두 갈래로 나눈다:
- 원문 ZIP(document.xml, fnlttXbrl.xml): 바이너리이고 rcept_no가 불변이므로
  blob 네임스페이스에 TTL 없이 저장한다.
- 그 외 JSON 엔드포인트: json 네임스페이스에 TTL을 두고 저장한다.

캐시 키에서 crtfc_key(사용자 DART API 키)를 반드시 제외한다. 원문과 공시
데이터는 공개 데이터이므로 전 사용자가 캐시를 공유하며, 키를 키 계산에
포함하면 공유 이점이 사라지고 사용자 자격증명이 저장소에 남는다.

근거: docs/superpowers/specs/2026-07-26-risk-viewer-se-design.md §6.2
"""
from __future__ import annotations

import base64
import hashlib
from urllib.parse import urlencode, urlsplit

from dart_risk_mcp.core import dart_client
from se_server.cache.base import CacheBackend

# ZIP 파일 매직 바이트. blob 저장 전 실제 ZIP인지 확인하는 데 쓴다.
_ZIP_MAGIC = b"PK\x03\x04"

# 캐시 키에서 제외할 파라미터 — 사용자 식별자에 해당한다.
_EXCLUDED_PARAMS = frozenset({"crtfc_key"})

# 바이너리(ZIP)로 응답하는 엔드포인트. blob 네임스페이스에 영구 저장한다.
# rcept_no가 불변 식별자이므로 stale이 발생하지 않는 것들만 넣는다.
_BLOB_ENDPOINTS = frozenset({"document.xml", "fnlttXbrl.xml"})

# 캐시하지 않는 엔드포인트.
# corpCode.xml(전체 기업 코드 목록)은 신규 상장으로 계속 바뀌므로 불변이 아니다.
# core의 _load_corp_codes가 이미 24시간 파일 캐시를 두고 있으며, 여기서 다시
# 캐시하면 그 갱신 주기를 무력화한다.
_NEVER_CACHE = frozenset({"corpCode.xml"})

_DEFAULT_JSON_TTL = 7 * 24 * 3600  # 7일


def _endpoint_of(url: str) -> str:
    """URL 경로의 마지막 조각(엔드포인트 파일명)을 반환한다."""
    return urlsplit(url).path.rsplit("/", 1)[-1]


class CachingHttp:
    """dart_client.set_http_cache()에 주입되는 캐시 어댑터."""

    def __init__(self, backend: CacheBackend, json_ttl_seconds: int = _DEFAULT_JSON_TTL) -> None:
        self.backend = backend
        self.json_ttl_seconds = json_ttl_seconds

    def cache_key(self, url: str, params: dict) -> str:
        """(엔드포인트, 사용자 키를 제외한 파라미터)로 안정적인 키를 만든다.

        값을 URL 인코딩해 정규화한다. 단순 문자열 결합은 값에 `&`나 `=`가
        섞이면 서로 다른 파라미터 조합이 같은 문자열로 축약돼 키가 충돌한다
        (예: {"a": "b&c=d"} 와 {"a": "b", "c": "d"}).
        """
        endpoint = _endpoint_of(url)
        items = sorted(
            (str(k), str(v))
            for k, v in (params or {}).items()
            if k not in _EXCLUDED_PARAMS
        )
        canonical = endpoint + "?" + urlencode(items)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
        return f"{endpoint}/{digest}"

    def _is_blob(self, url: str) -> bool:
        return _endpoint_of(url) in _BLOB_ENDPOINTS

    def _is_cacheable(self, url: str) -> bool:
        return _endpoint_of(url) not in _NEVER_CACHE

    def get(self, url: str, params: dict) -> tuple[int, dict, bytes] | None:
        if not self._is_cacheable(url):
            return None
        key = self.cache_key(url, params)
        if self._is_blob(url):
            body = self.backend.get_blob(key)
            if body is None:
                return None
            return 200, {"Content-Type": "application/zip"}, body

        entry = self.backend.get_json(key)
        if entry is None:
            return None
        body = base64.b64decode(entry["body_b64"])
        return int(entry["status"]), dict(entry.get("headers") or {}), body

    def put(self, url: str, params: dict, status: int, headers: dict, body: bytes) -> None:
        if status != 200 or not self._is_cacheable(url):
            return
        key = self.cache_key(url, params)
        if self._is_blob(url):
            # DART /document.xml은 키 오류·조회 실패 시에도 HTTP 200으로
            # 응답하면서 바디에 JSON/텍스트 오류 메시지를 담는다(core의
            # _fetch_document_zip이 같은 이유로 Content-Type을 검사한다).
            # blob은 TTL 없이 영구 보관되고 캐시 키가 crtfc_key를 제외해
            # 전 사용자가 공유하므로, 오류 바디가 한 번 들어가면 해당
            # rcept_no가 모두에게 영구히 조회 불가가 된다. 실제 ZIP인지
            # 확인한 뒤에만 저장한다.
            if not body.startswith(_ZIP_MAGIC):
                return
            self.backend.put_blob(key, body)
            return
        self.backend.put_json(
            key,
            {
                "status": status,
                "headers": {"Content-Type": (headers or {}).get("Content-Type", "application/json")},
                "body_b64": base64.b64encode(body).decode("ascii"),
            },
            ttl_seconds=self.json_ttl_seconds,
        )


def install(backend: CacheBackend, json_ttl_seconds: int = _DEFAULT_JSON_TTL) -> CachingHttp:
    """CachingHttp를 만들어 core 시임에 주입하고 반환한다."""
    http = CachingHttp(backend, json_ttl_seconds=json_ttl_seconds)
    dart_client.set_http_cache(http)
    return http
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/se/test_http_cache.py -v`
Expected: PASS — 19 passed

- [ ] **Step 5: 커밋**

```bash
git add se_server/http_cache.py tests/se/test_http_cache.py
git commit -m "feat(se): CachingHttp — 캐시 키 계산과 blob/json 정책 분기"
```

---

### Task 4: Supabase 백엔드

**Files:**
- Create: `se_server/config.py`
- Create: `se_server/cache/supabase.py`
- Modify: `se_server/cache/__init__.py`
- Create: `se_server/schema.sql`
- Test: `tests/se/test_supabase_cache.py`

**Interfaces:**
- Consumes: `se_server.cache.base.CacheBackend` (Task 1)
- Produces:
  - `se_server.config.SEConfig` — `from_env()` 클래스메서드. 필드: `supabase_url: str`, `supabase_service_key: str`, `cache_bucket: str`
  - `se_server.cache.supabase.SupabaseCache(config: SEConfig, session=None)` — `CacheBackend` 구현

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_supabase_cache.py`:

```python
"""SupabaseCache의 HTTP 계약. 실제 네트워크는 타지 않는다."""
import datetime as _dt
import unittest
from unittest import mock

from se_server.cache.supabase import SupabaseCache
from se_server.config import SEConfig

CFG = SEConfig(
    supabase_url="https://proj.supabase.co",
    supabase_service_key="SERVICE_KEY",
    cache_bucket="se-cache",
)


def _resp(status=200, content=b"", json_body=None):
    r = mock.Mock()
    r.status_code = status
    r.content = content
    r.json.return_value = json_body if json_body is not None else []
    return r


class TestBlob(unittest.TestCase):
    def test_get_blob_hit(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, b"ZIPDATA")
        cache = SupabaseCache(CFG, session=session)
        self.assertEqual(cache.get_blob("document.xml/abc"), b"ZIPDATA")
        url = session.get.call_args[0][0]
        self.assertEqual(
            url, "https://proj.supabase.co/storage/v1/object/se-cache/document.xml/abc"
        )

    def test_get_blob_miss_returns_none(self):
        session = mock.Mock()
        session.get.return_value = _resp(404)
        cache = SupabaseCache(CFG, session=session)
        self.assertIsNone(cache.get_blob("document.xml/abc"))

    def test_put_blob_uses_upsert_header(self):
        session = mock.Mock()
        session.post.return_value = _resp(200)
        cache = SupabaseCache(CFG, session=session)
        cache.put_blob("document.xml/abc", b"ZIPDATA")
        headers = session.post.call_args[1]["headers"]
        self.assertEqual(headers["x-upsert"], "true")
        self.assertEqual(headers["Authorization"], "Bearer SERVICE_KEY")

    def test_blob_write_failure_does_not_propagate(self):
        """캐시 쓰기 실패가 분석 전체를 중단시키면 안 된다.

        캐시는 성능 최적화이지 정확성의 일부가 아니다. 저장에 실패하면
        조용히 포기하고 호출자는 계속 진행해야 한다.
        """
        session = mock.Mock()
        session.post.side_effect = RuntimeError("네트워크 오류")
        cache = SupabaseCache(CFG, session=session)

        try:
            cache.put_blob("k", b"x")
        except Exception as exc:  # pragma: no cover - 실패 시 진단용
            self.fail(f"put_blob이 예외를 전파했습니다: {exc!r}")

        self.assertEqual(session.post.call_count, 1)

    def test_blob_read_failure_is_a_miss(self):
        session = mock.Mock()
        session.get.side_effect = RuntimeError("네트워크 오류")
        cache = SupabaseCache(CFG, session=session)
        self.assertIsNone(cache.get_blob("k"))


class TestJson(unittest.TestCase):
    def test_get_json_hit(self):
        session = mock.Mock()
        session.get.return_value = _resp(
            200, json_body=[{"key": "k", "value": {"status": 200}, "expires_at": None}]
        )
        cache = SupabaseCache(CFG, session=session)
        self.assertEqual(cache.get_json("k"), {"status": 200})

    def test_get_json_empty_result_is_miss(self):
        session = mock.Mock()
        session.get.return_value = _resp(200, json_body=[])
        cache = SupabaseCache(CFG, session=session)
        self.assertIsNone(cache.get_json("k"))

    def test_put_json_sends_merge_duplicates(self):
        session = mock.Mock()
        session.post.return_value = _resp(201)
        cache = SupabaseCache(CFG, session=session)
        cache.put_json("k", {"status": 200}, ttl_seconds=60)
        headers = session.post.call_args[1]["headers"]
        self.assertIn("resolution=merge-duplicates", headers["Prefer"])

    def test_put_json_without_ttl_sends_null_expiry(self):
        session = mock.Mock()
        session.post.return_value = _resp(201)
        cache = SupabaseCache(CFG, session=session)
        cache.put_json("k", {"a": 1}, ttl_seconds=None)
        payload = session.post.call_args[1]["json"]
        self.assertIsNone(payload["expires_at"])


class TestJsonExpiryParsing(unittest.TestCase):
    """만료 시각 해석은 어떤 입력에도 예외를 밖으로 내보내지 않아야 한다.

    이 함수의 계약은 "읽기 실패는 미스로 처리"이므로, 형식이 깨졌거나
    시간대 정보가 없는 값이 와도 호출자에게 예외가 전파되면 안 된다.
    """

    def _cache_returning(self, expires_at):
        session = mock.Mock()
        session.get.return_value = _resp(
            200, json_body=[{"key": "k", "value": {"a": 1}, "expires_at": expires_at}]
        )
        return SupabaseCache(CFG, session=session)

    def test_naive_future_timestamp_is_treated_as_utc_and_valid(self):
        future = (
            _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=1)
        ).replace(tzinfo=None).isoformat()
        self.assertEqual(self._cache_returning(future).get_json("k"), {"a": 1})

    def test_naive_past_timestamp_is_expired(self):
        past = (
            _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=1)
        ).replace(tzinfo=None).isoformat()
        self.assertIsNone(self._cache_returning(past).get_json("k"))

    def test_unparseable_timestamp_is_a_miss(self):
        self.assertIsNone(self._cache_returning("쓰레기값").get_json("k"))

    def test_non_string_timestamp_is_a_miss(self):
        self.assertIsNone(self._cache_returning(12345).get_json("k"))


class TestConfig(unittest.TestCase):
    def test_from_env_reads_variables(self):
        env = {
            "SUPABASE_URL": "https://x.supabase.co",
            "SUPABASE_SERVICE_KEY": "KEY",
            "SE_CACHE_BUCKET": "bucket",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = SEConfig.from_env()
        self.assertEqual(cfg.supabase_url, "https://x.supabase.co")
        self.assertEqual(cfg.cache_bucket, "bucket")

    def test_from_env_missing_required_raises(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                SEConfig.from_env()

    def test_trailing_slash_stripped(self):
        env = {"SUPABASE_URL": "https://x.supabase.co/", "SUPABASE_SERVICE_KEY": "K"}
        with mock.patch.dict("os.environ", env, clear=True):
            cfg = SEConfig.from_env()
        self.assertEqual(cfg.supabase_url, "https://x.supabase.co")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_supabase_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'se_server.config'`

- [ ] **Step 3: config 구현**

`se_server/config.py`:

```python
"""SE 서버 환경 설정.

Vercel 환경변수에서 읽는다. DART API 키는 여기에 없다 — 사용자 브라우저가
요청마다 동봉하며 서버는 저장하지 않는다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SEConfig:
    supabase_url: str
    supabase_service_key: str
    cache_bucket: str = "se-cache"

    @classmethod
    def from_env(cls) -> "SEConfig":
        url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
        service_key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
        if not url or not service_key:
            raise ValueError(
                "SUPABASE_URL과 SUPABASE_SERVICE_KEY 환경변수가 필요합니다"
            )
        return cls(
            supabase_url=url,
            supabase_service_key=service_key,
            cache_bucket=os.environ.get("SE_CACHE_BUCKET") or "se-cache",
        )
```

- [ ] **Step 4: Supabase 백엔드 구현**

`se_server/cache/supabase.py`:

```python
"""Supabase Storage(blob) + PostgREST(json) 캐시 백엔드.

Vercel 함수는 파일시스템이 비영속이므로 캐시는 외부 저장소여야 한다.
인증에 이미 Supabase를 쓰므로 신규 벤더를 늘리지 않는다.

SDK를 쓰지 않고 REST를 직접 호출한다 — supabase-py는 gotrue/postgrest/
storage3/realtime을 함께 끌고 오는데 우리가 쓰는 건 오브젝트 GET/POST와
테이블 조회뿐이다.

캐시 쓰기 실패는 삼킨다. 캐시는 성능 최적화이지 정확성의 일부가 아니며,
저장 실패로 분석 전체를 중단시키면 안 된다. 읽기 실패도 미스로 처리한다.
"""
from __future__ import annotations

import datetime as _dt

import requests

from se_server.config import SEConfig

_TABLE = "se_cache"


class SupabaseCache:
    def __init__(self, config: SEConfig, session=None) -> None:
        self.config = config
        self.session = session or requests.Session()

    # ── 공통 ──────────────────────────────────────
    def _headers(self) -> dict:
        key = self.config.supabase_service_key
        return {"Authorization": f"Bearer {key}", "apikey": key}

    def _object_url(self, key: str) -> str:
        return (
            f"{self.config.supabase_url}/storage/v1/object/"
            f"{self.config.cache_bucket}/{key}"
        )

    def _table_url(self) -> str:
        return f"{self.config.supabase_url}/rest/v1/{_TABLE}"

    # ── blob (원문 ZIP, 영구) ─────────────────────
    def get_blob(self, key: str) -> bytes | None:
        try:
            resp = self.session.get(self._object_url(key), headers=self._headers(), timeout=30)
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        return resp.content

    def put_blob(self, key: str, data: bytes) -> None:
        headers = self._headers()
        headers["x-upsert"] = "true"
        headers["Content-Type"] = "application/zip"
        try:
            self.session.post(
                self._object_url(key), headers=headers, data=data, timeout=60
            )
        except Exception:
            return

    # ── json (구조화 응답, TTL) ────────────────────
    def get_json(self, key: str) -> dict | None:
        params = {"key": f"eq.{key}", "select": "value,expires_at"}
        try:
            resp = self.session.get(
                self._table_url(), headers=self._headers(), params=params, timeout=15
            )
        except Exception:
            return None
        if resp.status_code != 200:
            return None
        try:
            rows = resp.json()
        except ValueError:
            return None
        if not rows:
            return None
        row = rows[0]
        expires_at = row.get("expires_at")
        if expires_at:
            try:
                deadline = _dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if deadline.tzinfo is None:
                    # PostgREST가 offset 없이 직렬화한 경우 UTC로 간주한다.
                    # 이 보정이 없으면 aware/naive 비교가 TypeError를 던진다.
                    deadline = deadline.replace(tzinfo=_dt.timezone.utc)
                if _dt.datetime.now(_dt.timezone.utc) >= deadline:
                    return None
            except (ValueError, TypeError, AttributeError):
                # 만료 시각을 해석할 수 없으면 보수적으로 미스 처리한다.
                # 비교까지 try 안에 두는 이유: 이 함수는 "읽기 실패는 미스"를
                # 계약으로 삼으므로 어떤 예외도 호출자로 새면 안 된다.
                # AttributeError는 expires_at이 문자열이 아닐 때(.replace 없음),
                # TypeError는 aware/naive 비교, ValueError는 형식 오류에 대응한다.
                return None
        return row.get("value")

    def put_json(self, key: str, value: dict, ttl_seconds: int | None) -> None:
        expires_at = None
        if ttl_seconds is not None:
            deadline = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=ttl_seconds)
            expires_at = deadline.isoformat()
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        headers["Prefer"] = "resolution=merge-duplicates"
        try:
            self.session.post(
                self._table_url(),
                headers=headers,
                json={"key": key, "value": value, "expires_at": expires_at},
                timeout=15,
            )
        except Exception:
            return
```

`se_server/cache/__init__.py`를 아래로 교체:

```python
"""SE 캐시 계층."""
from se_server.cache.base import CacheBackend, MemoryCache
from se_server.cache.supabase import SupabaseCache

__all__ = ["CacheBackend", "MemoryCache", "SupabaseCache"]
```

- [ ] **Step 5: 스키마 파일 작성**

`se_server/schema.sql`:

```sql
-- SE 캐시 테이블. Supabase SQL 에디터에서 1회 실행한다.
-- 원문 ZIP은 Storage 버킷(기본 이름 se-cache)에 저장하므로 여기 없다.

create table if not exists se_cache (
  key        text primary key,
  value      jsonb not null,
  expires_at timestamptz
);

-- 만료 행 정리를 위한 인덱스
create index if not exists se_cache_expires_at_idx
  on se_cache (expires_at)
  where expires_at is not null;

-- service_role만 접근한다. 브라우저는 이 테이블을 직접 읽지 않는다.
alter table se_cache enable row level security;
```

- [ ] **Step 6: 테스트 통과 확인**

Run: `python -m pytest tests/se/test_supabase_cache.py -v`
Expected: PASS — 16 passed

- [ ] **Step 7: 커밋**

```bash
git add se_server/config.py se_server/cache/ se_server/schema.sql tests/se/test_supabase_cache.py
git commit -m "feat(se): Supabase Storage/PostgREST 캐시 백엔드"
```

---

### Task 5: 콜드/웜 실측 CLI

계획 전체의 목표(2회차 8–15분 → 30초~1분)를 실제로 검증하는 유일한 태스크다. 스펙 §11의 "Vercel 요금제별 `maxDuration` 실측"도 여기서 나온 수치를 기준으로 판단한다.

**Files:**
- Create: `scripts/se_cache_bench.py`
- Test: `tests/se/test_cache_bench.py`

**Interfaces:**
- Consumes: `se_server.cache.MemoryCache`·`SupabaseCache` (Task 1·4), `se_server.http_cache.install` (Task 3)
- Produces:
  - `scripts.se_cache_bench.run_once(company: str, api_key: str, lookback_years: int) -> dict` — `{"seconds": float, "disclosures": int, "documents": int}`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/se/test_cache_bench.py`:

```python
"""벤치 CLI의 순수 로직. DART 호출은 스텁한다."""
import unittest
from unittest import mock

from scripts import se_cache_bench


class TestRunOnce(unittest.TestCase):
    def test_counts_disclosures_and_measures_time(self):
        clock = {"t": 0.0}

        def fake_monotonic():
            clock["t"] += 2.5
            return clock["t"]

        with mock.patch.object(
            se_cache_bench, "resolve_corp",
            return_value=("테스트회사", {"corp_code": "00000000", "stock_code": "000000"}),
        ), mock.patch.object(
            se_cache_bench, "fetch_company_disclosures",
            return_value=[{"rcept_no": "1", "report_nm": "전환사채권 발행결정"}],
        ), mock.patch.object(
            se_cache_bench, "fetch_disclosure_full", return_value={"text": "본문"}
        ), mock.patch.object(se_cache_bench.time, "monotonic", fake_monotonic):
            result = se_cache_bench.run_once("테스트회사", "KEY", 1)

        self.assertEqual(result["disclosures"], 1)
        self.assertEqual(result["documents"], 1)
        self.assertGreater(result["seconds"], 0)

    def test_unresolved_company_raises(self):
        with mock.patch.object(se_cache_bench, "resolve_corp", return_value=(None, None)):
            with self.assertRaises(ValueError):
                se_cache_bench.run_once("없는회사", "KEY", 1)

    def test_only_signal_matched_documents_fetched(self):
        """신호 매칭된 공시만 원문을 연다 (스펙 §6.1 2단)."""
        with mock.patch.object(
            se_cache_bench, "resolve_corp",
            return_value=("회사", {"corp_code": "0", "stock_code": "0"}),
        ), mock.patch.object(
            se_cache_bench, "fetch_company_disclosures",
            return_value=[
                {"rcept_no": "1", "report_nm": "전환사채권 발행결정"},
                {"rcept_no": "2", "report_nm": "임원ㆍ주요주주특정증권등소유상황보고서"},
            ],
        ), mock.patch.object(
            se_cache_bench, "fetch_disclosure_full", return_value={"text": ""}
        ) as full:
            result = se_cache_bench.run_once("회사", "KEY", 1)

        # CB 공시 1건만 매칭되고 임원 보고서는 매칭되지 않는다.
        # documents == full.call_count 는 구현이 호출할 때마다 세는 값이라
        # 동어반복이므로, 기대 건수를 직접 못박는다.
        self.assertEqual(result["disclosures"], 2)
        self.assertEqual(full.call_count, 1)
        self.assertEqual(result["documents"], 1)
        self.assertEqual(full.call_args[0][0], "1")  # CB 공시의 rcept_no


class TestMeasurementIsolation(unittest.TestCase):
    """측정이 SE 캐시 효과만 반영하도록 core의 프로세스 내 캐시를 비운다.

    같은 프로세스에서 콜드/웜을 재면 core의 _corp_cache·_zip_cache가
    웜 실행을 앞당겨 단축 배수를 부풀린다. 특히 corpCode.xml은 SE 캐시의
    _NEVER_CACHE 대상이라 그 단축분은 SE와 무관하다.
    """

    def test_reset_clears_both_core_caches(self):
        dart_client = se_cache_bench.dart_client
        dart_client._corp_cache["더미"] = {"corp_code": "0"}
        dart_client._zip_cache["더미"] = (0.0, b"x")

        se_cache_bench.reset_core_process_caches()

        self.assertEqual(dart_client._corp_cache, {})
        self.assertEqual(dart_client._zip_cache, {})


class TestCountingHttp(unittest.TestCase):
    """적중 수가 0인데 빨라졌다면 그 단축은 SE 캐시 효과가 아니다."""

    class _Inner:
        def __init__(self, result):
            self.result = result
            self.puts = 0

        def get(self, url, params):
            return self.result

        def put(self, url, params, status, headers, body):
            self.puts += 1

    def test_counts_hits_and_misses(self):
        counter = se_cache_bench.CountingHttp(self._Inner((200, {}, b"x")))
        counter.get("u", {})
        counter.get("u", {})
        self.assertEqual((counter.hits, counter.misses), (2, 0))

    def test_none_counts_as_miss(self):
        counter = se_cache_bench.CountingHttp(self._Inner(None))
        counter.get("u", {})
        self.assertEqual((counter.hits, counter.misses), (0, 1))

    def test_put_delegates_to_inner(self):
        inner = self._Inner(None)
        counter = se_cache_bench.CountingHttp(inner)
        counter.put("u", {}, 200, {}, b"x")
        self.assertEqual(inner.puts, 1)

    def test_reset_counts_zeroes_both(self):
        counter = se_cache_bench.CountingHttp(self._Inner(None))
        counter.get("u", {})
        counter.reset_counts()
        self.assertEqual((counter.hits, counter.misses), (0, 0))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/se/test_cache_bench.py -v`
Expected: FAIL — `ImportError: cannot import name 'se_cache_bench' from 'scripts'`

- [ ] **Step 3: 벤치 CLI 구현**

`scripts/se_cache_bench.py`:

```python
"""SE 캐시 효과 실측 — 같은 회사를 두 번 조회해 콜드/웜 시간을 비교한다.

사용:
    # 인메모리(같은 프로세스 내 2회차만 확인)
    python scripts/se_cache_bench.py 셀트리온

    # Supabase 백엔드 (SUPABASE_URL·SUPABASE_SERVICE_KEY 필요)
    python scripts/se_cache_bench.py 셀트리온 --backend supabase

API 키는 환경변수 DART_API_KEY 또는 tmp/_apikey.txt에서 읽는다.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dart_risk_mcp.core import dart_client  # noqa: E402
from dart_risk_mcp.core.dart_client import (  # noqa: E402
    fetch_company_disclosures,
    fetch_disclosure_full,
    resolve_corp,
)
from dart_risk_mcp.core.signals import match_signals  # noqa: E402
from se_server.cache import MemoryCache, SupabaseCache  # noqa: E402
from se_server.config import SEConfig  # noqa: E402
from se_server.http_cache import CachingHttp, install  # noqa: E402


def reset_core_process_caches() -> None:
    """core의 프로세스 내 캐시를 비운다.

    콜드/웜을 같은 프로세스에서 재면 SE 캐시와 무관한 두 캐시가 웜 실행을
    앞당겨 측정을 과대평가한다:

    - `_corp_cache`: 한 번 채워지면 `resolve_corp`가 재조회를 아예 건너뛴다.
      게다가 corpCode.xml은 SE 캐시의 `_NEVER_CACHE` 대상이라 이 단축분은
      SE와 전혀 무관하다.
    - `_zip_cache`: `_fetch_document_zip`이 `_retry`(SE 캐시 진입점)를
      호출하기 **전에** 확인하므로, 최근 5건은 SE 캐시에 닿지도 않는다.

    실서비스(Vercel)는 요청마다 새 프로세스라 두 캐시가 존재하지 않는다.
    비워야 측정이 배포 환경에 가까워진다.
    """
    dart_client._corp_cache.clear()
    dart_client._zip_cache.clear()


class CountingHttp:
    """SE 캐시 적중·미스를 세어 단축분의 귀속을 명시한다.

    "몇 배 빨라졌다"만으로는 그 단축이 SE 캐시 덕분인지 알 수 없다.
    적중 수가 0인데 빨라졌다면 그 측정은 SE 캐시 효과가 아니다.
    """

    def __init__(self, inner: CachingHttp) -> None:
        self.inner = inner
        self.hits = 0
        self.misses = 0

    def get(self, url: str, params: dict):
        result = self.inner.get(url, params)
        if result is None:
            self.misses += 1
        else:
            self.hits += 1
        return result

    def put(self, url: str, params: dict, status: int, headers: dict, body: bytes) -> None:
        self.inner.put(url, params, status, headers, body)

    def reset_counts(self) -> None:
        self.hits = 0
        self.misses = 0


def _load_api_key() -> str:
    key = os.environ.get("DART_API_KEY", "").strip()
    if key:
        return key
    path = os.path.join(os.path.dirname(__file__), "..", "tmp", "_apikey.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    raise ValueError("DART_API_KEY 환경변수 또는 tmp/_apikey.txt가 필요합니다")


def run_once(company: str, api_key: str, lookback_years: int) -> dict:
    """회사 하나를 스펙 §6.1의 1·2단 범위로 조회하고 소요 시간을 잰다."""
    started = time.monotonic()
    corp_name, info = resolve_corp(company, api_key)
    if not info:
        raise ValueError(f"기업을 찾지 못했습니다: {company}")

    items = fetch_company_disclosures(
        info["corp_code"], api_key, lookback_days=365 * lookback_years
    )
    documents = 0
    for item in items:
        if not match_signals(item.get("report_nm", "")):
            continue
        fetch_disclosure_full(item["rcept_no"], api_key)
        documents += 1

    return {
        "seconds": time.monotonic() - started,
        "disclosures": len(items),
        "documents": documents,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SE 캐시 효과 실측")
    parser.add_argument("company", help="기업명 또는 종목코드")
    parser.add_argument("--years", type=int, default=1, help="조회 연수 (기본 1)")
    parser.add_argument(
        "--backend", choices=["memory", "supabase"], default="memory",
        help="캐시 백엔드 (기본 memory)",
    )
    args = parser.parse_args()

    api_key = _load_api_key()
    backend = (
        SupabaseCache(SEConfig.from_env())
        if args.backend == "supabase"
        else MemoryCache()
    )
    counter = CountingHttp(install(backend))
    dart_client.set_http_cache(counter)

    # core의 프로세스 내 캐시를 비워야 SE 캐시 효과만 남는다.
    reset_core_process_caches()
    cold = run_once(args.company, api_key, args.years)
    cold_hits, cold_misses = counter.hits, counter.misses
    print(
        f"콜드: {cold['seconds']:.1f}초 "
        f"(공시 {cold['disclosures']}건 · 원문 {cold['documents']}건 · "
        f"SE 캐시 적중 {cold_hits}/{cold_hits + cold_misses})"
    )

    reset_core_process_caches()
    counter.reset_counts()
    warm = run_once(args.company, api_key, args.years)
    warm_hits, warm_misses = counter.hits, counter.misses
    print(
        f"웜  : {warm['seconds']:.1f}초 "
        f"(SE 캐시 적중 {warm_hits}/{warm_hits + warm_misses})"
    )

    if warm["seconds"] > 0:
        print(f"단축 배수: {cold['seconds'] / warm['seconds']:.1f}배")

    # 적중 수가 0이면 단축은 SE 캐시 때문이 아니다 — 수치를 그대로 믿으면 안 된다.
    if warm_hits == 0:
        print("⚠ 웜 실행의 SE 캐시 적중이 0건입니다 — 단축분은 SE 캐시 효과가 아닙니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/se/test_cache_bench.py -v`
Expected: PASS — 3 passed

- [ ] **Step 5: 전체 스위트 회귀 확인**

Run: `python -m pytest tests/ -q`
Expected: 기존 통과 수 + 이 계획에서 추가한 40건. 실패 0

- [ ] **Step 6: 라이브 실측 (API 키 필요)**

Run: `python scripts/se_cache_bench.py 셀트리온 --years 1`

Expected: 콜드/웜 시간이 출력되고 **웜이 콜드보다 뚜렷하게 짧다.** 단축 배수가 2배 미만이면 캐시가 실제로 안 걸린 것이므로, `install()`이 `resolve_corp` 호출 **전에** 실행됐는지와 `cache_key`가 매 호출 동일한지를 확인한다.

기록: 이 수치가 스펙 §6.2의 "2회차 30초~1분" 주장을 검증하는 유일한 근거다. 결과를 커밋 메시지에 남긴다.

- [ ] **Step 7: 커밋**

```bash
git add scripts/se_cache_bench.py tests/se/test_cache_bench.py
git commit -m "feat(se): 캐시 콜드/웜 실측 CLI 추가"
```

---

## 이 계획이 다루지 않는 것

스펙은 독립적인 하위 시스템 여럿을 담고 있어 계획 하나로 묶을 수 없다. SE-1은 그중 **기반**만 다룬다. 나머지는 별도 계획으로 작성한다.

| 계획 | 범위 | 선행 |
|---|---|---|
| **SE-1 (이 문서)** | 캐시 계층 + core HTTP 시임 | — |
| SE-2 | 청크 오케스트레이터 + 작업 상태(Postgres). 스펙 §6.1·§7.3 | SE-1 |
| SE-3 | Vercel HTTP API + Supabase Auth 가드. 스펙 §4·§3.3 | SE-2 |
| SE-4 | 프론트엔드 — 롱스크롤 본문 + 우측 슬라이드 패널. 스펙 §7.1·§7.2 | SE-3 |

SE-1을 먼저 하는 이유는 스펙 §6.2가 명시한다 — 캐시를 나중에 붙이면 캐시 키 설계 때문에 오케스트레이터를 다시 뜯게 된다.

## 자체 검토 결과

- **스펙 커버리지:** §3.1(패키지 경계) → Global Constraints + Task 1. §3.3(Vercel 비영속) → Task 4. §6.2(캐시 정책·키에서 사용자 식별자 제외) → Task 3·4. §10(테스트 전략의 캐시 계층 항목) → Task 1·3·4. 나머지 절은 SE-2~4 소관으로 위 표에 명시.
- **스펙과의 의도적 차이 1건:** §3.1은 "core 수정 없이 감싼다"고 적었으나, 원문을 쓰는 공개 함수들이 `(rcept_no, api_key)`만 받아 ZIP 주입 구멍이 없다. Task 2에서 core에 훅을 추가하며, 이는 §3.1이 정한 예외 조건("MCP 도구에도 독립적으로 유용한가")을 통과한다. **스펙 §3.1 본문에 이 결정을 반영해야 한다.**
- **타입 일관성:** `CacheBackend` 4개 메서드 시그니처가 Task 1 정의와 Task 4 구현에서 일치. `HttpCache`의 `get`/`put` 시그니처가 Task 2(core)와 Task 3(구현)에서 일치. `install()` 반환 타입 `CachingHttp` 일치.
- **미해결 위험:** Task 2가 `_retry`의 반환 구조를 `return`에서 `break`로 바꾼다. `_retry`는 거의 모든 core 함수가 쓰므로 Step 5의 전체 회귀 실행이 필수다.
