# 공개 뷰어 접속 분석 대시보드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공개 리스크 뷰어 방문자의 IP·쿠키·기기·유입 경로와 조회한 회사를 수집해, 운영자만 토큰으로 접근하는 대시보드에서 본다.

**Architecture:** 뷰어가 `/api/track`으로 이벤트를 POST하면 서버가 요청 헤더의 IP·지역을 붙여 Supabase 단일 테이블에 저장한다. 대시보드는 `/api/stats`를 토큰 인증으로 호출해 SQL 집계 뷰를 읽는다. 기존 `api/doc.py`(껍데기) + `tool_server/doc.py`(몸통) 분리 패턴을 그대로 따라 로직을 단위 테스트한다.

**Tech Stack:** Python 3.11 표준 라이브러리 + `requests` (Vercel 서버리스), Supabase PostgREST, 무빌드 단일 파일 HTML/JS

## Global Constraints

- **외부 라이브러리 추가 금지** — `requests`와 표준 라이브러리만. UA 파싱도 정규식으로 직접 구현한다. 차트도 인라인 SVG로 그린다(외부 차트 라이브러리 없음).
- **`api/[endpoint].js`는 절대 수정하지 않는다** — "키·파라미터·응답을 저장하거나 로그로 남기지 않는 무상태 통과"가 명시된 신뢰 경계다.
- **사용자의 DART API 키는 어떤 경로로도 수집·저장하지 않는다.**
- **껍데기는 얇게** — `api/*.py`는 HTTP 파싱만. 로직은 전부 `tool_server/*.py`에 둔다.
- **import 실패를 삼키지 않는다** — `api/doc.py`의 `_IMPORT_ERROR` 패턴을 복제한다. 삼키면 Vercel이 `FUNCTION_INVOCATION_FAILED`만 돌려줘 진단이 막힌다.
- **`se_server`를 import하지 않는다** — SE는 인가제라 신뢰 모델이 다르다. 필요한 코드는 복제한다.
- 대시보드 파일명은 `ops-762b24e0.html` 고정.
- 커밋 메시지는 한국어, 끝에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## File Structure

| 파일 | 책임 |
|---|---|
| `tool_server/schema_analytics.sql` | 테이블·인덱스·집계 뷰 정의 (사람이 Supabase SQL 편집기에 1회 붙여넣음) |
| `tool_server/supa.py` | Supabase PostgREST insert/select 최소 래퍼. 주입 가능해야 테스트가 네트워크를 안 탄다 |
| `tool_server/track.py` | 이벤트 정규화·검증 (UA 파싱·referrer 정규화·IP 추출·화이트리스트) + `handle_track` |
| `tool_server/stats.py` | 토큰 검사 + 집계 조회 + `handle_stats` |
| `api/track.py` | `POST /api/track` HTTP 껍데기 |
| `api/stats.py` | `GET /api/stats` HTTP 껍데기 |
| `docs/tool/ops-762b24e0.html` | 대시보드 4개 탭 |
| `docs/tool/robots.txt` | 대시보드 경로 크롤 차단 |
| `docs/tool/index.html` | 수집 스니펫 + 면책 문구 정정 |
| `tests/test_tool_server_track.py` | track 몸통 단위 테스트 |
| `tests/test_tool_server_stats.py` | stats 몸통 단위 테스트 |

---

### Task 1: Supabase 스키마와 저장 어댑터

**Files:**
- Create: `tool_server/schema_analytics.sql`
- Create: `tool_server/supa.py`
- Test: `tests/test_tool_server_supa.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `supa_config() -> tuple[str, str]` — `(url, service_key)`, 환경변수 미설정 시 `("", "")`
  - `insert_row(table: str, row: dict, *, post=None) -> bool`
  - `select_rows(path: str, *, get=None) -> list[dict]` — `path`는 `"v_corp_ranking?order=views.desc&limit=50"` 형태

- [ ] **Step 1: 스키마 SQL 작성**

`tool_server/schema_analytics.sql`:

```sql
-- 공개 뷰어 접속 분석. se_cache와 같은 원칙으로 RLS를 켜고 정책을 두지 않는다
-- (service_role 키만 우회 → 서버 함수 외에는 읽기·쓰기 불가).

create table if not exists viewer_events (
  id          bigserial primary key,
  ts          timestamptz not null default now(),
  event       text not null,
  visitor_id  text,
  ip          inet,
  country     text,
  region      text,
  city        text,
  ua          text,
  browser     text,
  os          text,
  device      text,
  is_mobile   boolean,
  referrer    text,
  corp_name   text,
  stock_code  text,
  path        text,
  screen      text,
  lang        text
);

create index if not exists viewer_events_ts_idx on viewer_events (ts desc);
create index if not exists viewer_events_visitor_idx on viewer_events (visitor_id, ts desc);
create index if not exists viewer_events_corp_idx on viewer_events (corp_name);

alter table viewer_events enable row level security;

-- 회사별 조회수. 기간 필터는 조회 시 ts로 건다.
create or replace view v_corp_ranking as
select corp_name, stock_code, ts::date as day,
       count(*) as views, count(distinct visitor_id) as visitors
from viewer_events
where event = 'scan' and corp_name is not null
group by corp_name, stock_code, ts::date;

create or replace view v_traffic_daily as
select ts::date as day,
       count(*) filter (where event = 'pageview') as pageviews,
       count(*) filter (where event = 'scan') as scans,
       count(distinct visitor_id) as visitors
from viewer_events
group by ts::date;

create or replace view v_referrer_summary as
select coalesce(referrer, '(직접 유입)') as referrer,
       country, city, browser, os, device,
       ts::date as day, count(*) as hits
from viewer_events
group by referrer, country, city, browser, os, device, ts::date;

create or replace view v_visitor_sessions as
select visitor_id,
       min(ts) as first_seen, max(ts) as last_seen,
       count(*) as events,
       count(*) filter (where event = 'scan') as scans,
       max(ip::text) as last_ip,
       max(country) as country, max(city) as city,
       max(browser) as browser, max(os) as os, max(device) as device
from viewer_events
where visitor_id is not null
group by visitor_id;
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_tool_server_supa.py`:

```python
"""tool_server.supa — Supabase REST 최소 래퍼의 단위 테스트.

네트워크는 타지 않는다. post/get을 주입해 호출 인자만 검증한다.
"""
import tool_server.supa as supa


class _Resp:
    def __init__(self, status=201, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else []

    def json(self):
        return self._payload


def test_insert_row_posts_to_rest_endpoint(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-key")
    seen = {}

    def fake_post(url, **kwargs):
        seen["url"] = url
        seen["json"] = kwargs.get("json")
        seen["headers"] = kwargs.get("headers")
        return _Resp(201)

    assert supa.insert_row("viewer_events", {"event": "scan"}, post=fake_post) is True
    assert seen["url"] == "https://x.supabase.co/rest/v1/viewer_events"
    assert seen["json"] == {"event": "scan"}
    assert seen["headers"]["apikey"] == "svc-key"
    assert seen["headers"]["Authorization"] == "Bearer svc-key"


def test_insert_row_returns_false_without_config(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)

    def fake_post(url, **kwargs):  # 호출되면 안 된다
        raise AssertionError("설정이 없으면 네트워크를 타면 안 된다")

    assert supa.insert_row("viewer_events", {"event": "scan"}, post=fake_post) is False


def test_insert_row_swallows_network_error(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-key")

    def fake_post(url, **kwargs):
        raise OSError("boom")

    assert supa.insert_row("viewer_events", {"event": "scan"}, post=fake_post) is False


def test_select_rows_returns_payload(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-key")
    rows = [{"corp_name": "셀트리온", "views": 3}]

    def fake_get(url, **kwargs):
        assert url == "https://x.supabase.co/rest/v1/v_corp_ranking?order=views.desc"
        return _Resp(200, rows)

    assert supa.select_rows("v_corp_ranking?order=views.desc", get=fake_get) == rows


def test_select_rows_returns_empty_on_error(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-key")

    def fake_get(url, **kwargs):
        return _Resp(500, {"message": "nope"})

    assert supa.select_rows("v_corp_ranking", get=fake_get) == []
```

- [ ] **Step 3: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/test_tool_server_supa.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tool_server.supa'`

- [ ] **Step 4: 구현**

`tool_server/supa.py`:

```python
"""Supabase PostgREST 최소 래퍼 — 접속 분석 저장·조회 전용.

se_server.supabase_rest를 import하지 않는다. SE는 인가제라 신뢰 모델이
다르고, 이쪽은 공개 뷰어 트래픽을 다룬다 — 두 경계를 코드로 묶으면
한쪽 사고가 다른 쪽으로 번진다.

post/get을 주입 가능하게 둔 이유: 테스트가 네트워크를 타지 않기 위해서다.
"""
from __future__ import annotations

import os

import requests

_TIMEOUT = 5


def supa_config() -> tuple[str, str]:
    """(url, service_key). 하나라도 없으면 ("", "")."""
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
    if not url or not key:
        return "", ""
    return url, key


def _headers(key: str) -> dict:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        # 응답 본문이 필요 없다 — 수집은 fire-and-forget이다.
        "Prefer": "return=minimal",
    }


def insert_row(table: str, row: dict, *, post=None) -> bool:
    """한 행 삽입. 실패는 False로 삼킨다 — 수집 실패가 뷰어를 깨면 안 된다."""
    url, key = supa_config()
    if not url:
        return False
    sender = post or requests.post
    try:
        resp = sender(
            f"{url}/rest/v1/{table}",
            json=row,
            headers=_headers(key),
            timeout=_TIMEOUT,
        )
    except Exception:
        return False
    return 200 <= getattr(resp, "status_code", 500) < 300


def select_rows(path: str, *, get=None) -> list[dict]:
    """PostgREST 조회. path 예: "v_corp_ranking?order=views.desc&limit=50"."""
    url, key = supa_config()
    if not url:
        return []
    fetcher = get or requests.get
    try:
        resp = fetcher(
            f"{url}/rest/v1/{path}",
            headers=_headers(key),
            timeout=_TIMEOUT,
        )
        if not (200 <= getattr(resp, "status_code", 500) < 300):
            return []
        payload = resp.json()
    except Exception:
        return []
    return payload if isinstance(payload, list) else []
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `python -m pytest tests/test_tool_server_supa.py -v`
Expected: 5 passed

- [ ] **Step 6: 커밋**

```bash
git add tool_server/schema_analytics.sql tool_server/supa.py tests/test_tool_server_supa.py
git commit -m "feat(analytics): viewer_events 스키마 + Supabase REST 래퍼"
```

---

### Task 2: 이벤트 정규화·검증 (track 몸통)

**Files:**
- Create: `tool_server/track.py`
- Test: `tests/test_tool_server_track.py`

**Interfaces:**
- Consumes: `tool_server.supa.insert_row(table, row, *, post=None) -> bool`
- Produces:
  - `parse_ua(ua: str) -> dict` — `{"browser","os","device","is_mobile"}`
  - `clean_referrer(raw: str, self_host: str) -> str | None`
  - `client_ip(headers: dict) -> str | None`
  - `handle_track(body: dict, headers: dict, origin_ok: bool) -> tuple[int, dict]`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_tool_server_track.py`:

```python
"""tool_server.track — 접속 이벤트 정규화·검증의 단위 테스트.

Supabase 저장은 monkeypatch로 가짜를 넣는다. 네트워크를 타지 않는다.
"""
import tool_server.track as track_mod
from tool_server.track import (
    MAX_BODY_BYTES,
    clean_referrer,
    client_ip,
    handle_track,
    parse_ua,
)

CHROME_WIN = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
SAFARI_IOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
EDGE_WIN = CHROME_WIN + " Edg/120.0.0.0"
BOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


def test_parse_ua_chrome_windows():
    got = parse_ua(CHROME_WIN)
    assert got["browser"] == "Chrome"
    assert got["os"] == "Windows"
    assert got["device"] == "desktop"
    assert got["is_mobile"] is False


def test_parse_ua_safari_ios_is_mobile():
    got = parse_ua(SAFARI_IOS)
    assert got["browser"] == "Safari"
    assert got["os"] == "iOS"
    assert got["device"] == "mobile"
    assert got["is_mobile"] is True


def test_parse_ua_edge_not_misread_as_chrome():
    # Edge UA는 Chrome 토큰을 포함한다 — 순서를 틀리면 전부 Chrome이 된다.
    assert parse_ua(EDGE_WIN)["browser"] == "Edge"


def test_parse_ua_bot():
    got = parse_ua(BOT)
    assert got["device"] == "bot"
    assert got["is_mobile"] is False


def test_parse_ua_empty():
    got = parse_ua("")
    assert got["browser"] is None and got["device"] is None


def test_clean_referrer_strips_query():
    assert clean_referrer(
        "https://cafe.naver.com/abc/12345?page=2&from=search", "dart.example.com"
    ) == "https://cafe.naver.com/abc/12345"


def test_clean_referrer_drops_self_host():
    assert clean_referrer("https://dart.example.com/#a=1", "dart.example.com") is None


def test_clean_referrer_empty_is_none():
    assert clean_referrer("", "dart.example.com") is None


def test_client_ip_takes_first_of_forwarded_chain():
    assert client_ip({"x-forwarded-for": "203.0.113.9, 70.41.3.18"}) == "203.0.113.9"


def test_client_ip_missing_is_none():
    assert client_ip({}) is None


def test_handle_track_rejects_bad_origin():
    status, body = handle_track({"event": "pageview"}, {}, origin_ok=False)
    assert status == 403


def test_handle_track_rejects_unknown_event():
    status, body = handle_track({"event": "steal"}, {}, origin_ok=True)
    assert status == 400


def test_handle_track_stores_whitelisted_fields(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        track_mod, "insert_row", lambda t, row, **kw: saved.update({"t": t, "row": row}) or True
    )
    status, body = handle_track(
        {
            "event": "scan",
            "visitor_id": "abc-123",
            "corp_name": "셀트리온",
            "stock_code": "068270",
            "referrer": "https://google.com/search?q=x",
            "screen": "1920x1080",
            "lang": "ko-KR",
            "path": "/",
            "evil": "무시돼야 한다",
        },
        {
            "x-forwarded-for": "203.0.113.9",
            "user-agent": CHROME_WIN,
            "x-vercel-ip-country": "KR",
            "x-vercel-ip-city": "Seoul",
            "host": "dart.example.com",
        },
        origin_ok=True,
    )
    assert status == 204
    row = saved["row"]
    assert saved["t"] == "viewer_events"
    assert row["event"] == "scan"
    assert row["corp_name"] == "셀트리온"
    assert row["ip"] == "203.0.113.9"
    assert row["country"] == "KR" and row["city"] == "Seoul"
    assert row["browser"] == "Chrome"
    assert row["referrer"] == "https://google.com/search"
    assert "evil" not in row


def test_handle_track_truncates_overlong_values(monkeypatch):
    saved = {}
    monkeypatch.setattr(
        track_mod, "insert_row", lambda t, row, **kw: saved.update({"row": row}) or True
    )
    handle_track(
        {"event": "scan", "corp_name": "가" * 5000}, {}, origin_ok=True
    )
    assert len(saved["row"]["corp_name"]) <= track_mod.MAX_FIELD_CHARS


def test_handle_track_returns_204_even_when_store_fails(monkeypatch):
    # 수집 실패를 클라이언트에 에러로 돌려주면 뷰어 콘솔이 빨개진다.
    monkeypatch.setattr(track_mod, "insert_row", lambda t, row, **kw: False)
    status, _ = handle_track({"event": "pageview"}, {}, origin_ok=True)
    assert status == 204


def test_max_body_bytes_is_small():
    assert MAX_BODY_BYTES <= 2048
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/test_tool_server_track.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tool_server.track'`

- [ ] **Step 3: 구현**

`tool_server/track.py`:

```python
"""접속 이벤트 수집 — 공개 뷰어의 /api/track 몸통.

브라우저가 보낸 값은 전부 신뢰하지 않는다. IP·지역은 요청 헤더에서만
읽고(클라이언트가 못 위조), 본문은 화이트리스트로 걸러 길이를 자른다.

api/[endpoint].js(릴레이)에는 어떤 로깅도 넣지 않는다 — 그쪽은 "저장하지
않는 무상태 통과"가 명시된 신뢰 경계다. 수집은 이 엔드포인트에서만 한다.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from tool_server.supa import insert_row

TABLE = "viewer_events"
MAX_BODY_BYTES = 1024
MAX_FIELD_CHARS = 300
MAX_UA_CHARS = 500

ALLOWED_EVENTS = {"pageview", "scan", "compare", "doc"}

# 클라이언트가 보낼 수 있는 필드는 이것뿐. 나머지는 조용히 버린다.
CLIENT_FIELDS = (
    "visitor_id", "corp_name", "stock_code", "referrer", "path", "screen", "lang",
)

_BOT_RE = re.compile(r"bot|crawler|spider|crawling|slurp|bingpreview", re.I)

# 순서가 곧 우선순위다. Edge·Opera·Samsung UA는 Chrome 토큰을 포함하므로
# Chrome보다 먼저 봐야 한다. Chrome UA도 Safari 토큰을 포함한다.
_BROWSERS = (
    ("Edge", re.compile(r"Edg[eA]?/")),
    ("Opera", re.compile(r"OPR/|Opera")),
    ("Samsung Internet", re.compile(r"SamsungBrowser/")),
    ("Whale", re.compile(r"Whale/")),
    ("Firefox", re.compile(r"Firefox/|FxiOS/")),
    ("Chrome", re.compile(r"Chrome/|CriOS/")),
    ("Safari", re.compile(r"Safari/")),
)

_OSES = (
    ("Android", re.compile(r"Android")),
    ("iOS", re.compile(r"iPhone|iPad|iPod")),
    ("Windows", re.compile(r"Windows NT")),
    ("macOS", re.compile(r"Mac OS X|Macintosh")),
    ("Linux", re.compile(r"Linux")),
)


def parse_ua(ua: str) -> dict:
    """UA 문자열 → 브라우저·OS·기기. 외부 라이브러리 없이 정규식으로 판별한다."""
    blank = {"browser": None, "os": None, "device": None, "is_mobile": False}
    if not ua:
        return blank
    if _BOT_RE.search(ua):
        return {"browser": None, "os": None, "device": "bot", "is_mobile": False}

    browser = next((name for name, rx in _BROWSERS if rx.search(ua)), None)
    os_name = next((name for name, rx in _OSES if rx.search(ua)), None)

    if re.search(r"iPad|Tablet", ua, re.I) or (
        "Android" in ua and "Mobile" not in ua
    ):
        device, is_mobile = "tablet", True
    elif re.search(r"Mobi|iPhone|iPod|Android", ua, re.I):
        device, is_mobile = "mobile", True
    else:
        device, is_mobile = "desktop", False

    return {"browser": browser, "os": os_name, "device": device, "is_mobile": is_mobile}


def clean_referrer(raw: str, self_host: str) -> str | None:
    """쿼리스트링·프래그먼트를 떼고 origin+path만 남긴다.

    쿼리를 남기면 유입 사이트가 URL에 실어 보낸 개인정보까지 우리 DB에
    들어온다. 자기 도메인 유입은 '유입 경로'가 아니므로 버린다.
    """
    if not raw:
        return None
    try:
        parts = urlsplit(raw.strip())
    except ValueError:
        return None
    if not parts.scheme or not parts.netloc:
        return None
    if self_host and parts.netloc.lower() == self_host.lower():
        return None
    return f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip("/") or None


def client_ip(headers: dict) -> str | None:
    """x-forwarded-for 체인의 첫 항목이 실제 클라이언트다."""
    chain = (headers.get("x-forwarded-for") or "").strip()
    if not chain:
        return None
    first = chain.split(",")[0].strip()
    return first or None


def _trim(value, limit: int = MAX_FIELD_CHARS) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def handle_track(body: dict, headers: dict, origin_ok: bool) -> tuple[int, dict]:
    """(status, body). 성공은 204 — 클라이언트는 응답을 쓰지 않는다."""
    if not origin_ok:
        return 403, {"error": "forbidden"}

    event = (body.get("event") or "").strip()
    if event not in ALLOWED_EVENTS:
        return 400, {"error": "unknown event"}

    ua = _trim(headers.get("user-agent"), MAX_UA_CHARS) or ""
    row = {"event": event, "ua": ua or None, **parse_ua(ua)}

    for field in CLIENT_FIELDS:
        row[field] = _trim(body.get(field))

    row["referrer"] = clean_referrer(
        body.get("referrer") or "", headers.get("host") or ""
    )
    row["ip"] = client_ip(headers)
    row["country"] = _trim(headers.get("x-vercel-ip-country"), 8)
    row["region"] = _trim(headers.get("x-vercel-ip-country-region"), 32)
    row["city"] = _trim(headers.get("x-vercel-ip-city"), 64)

    # 저장 실패해도 204. 수집 문제를 뷰어 콘솔의 에러로 만들지 않는다.
    insert_row(TABLE, row)
    return 204, {}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_tool_server_track.py -v`
Expected: 16 passed

- [ ] **Step 5: 커밋**

```bash
git add tool_server/track.py tests/test_tool_server_track.py
git commit -m "feat(analytics): 이벤트 정규화·검증 (UA 파싱·referrer 정제·화이트리스트)"
```

---

### Task 3: `/api/track` HTTP 껍데기

**Files:**
- Create: `api/track.py`

**Interfaces:**
- Consumes: `tool_server.track.handle_track(body, headers, origin_ok) -> tuple[int, dict]`, `tool_server.track.MAX_BODY_BYTES`
- Produces: `POST /api/track` (204 성공), `OPTIONS /api/track` (204)

- [ ] **Step 1: 구현**

`api/track.py` — `api/doc.py`의 `_IMPORT_ERROR` 패턴을 그대로 복제한다:

```python
"""Vercel Python 함수 진입점 — 공개 뷰어 접속 이벤트 수집(/api/track).

api/doc.py와 같은 원칙: 껍데기는 얇게, import 실패는 삼키지 않고 보고한다.

계약: POST /api/track, JSON 본문. 성공은 204(본문 없음).
클라이언트는 sendBeacon으로 보내고 응답을 읽지 않는다.
"""
import json
import os
import platform
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_IMPORT_ERROR = ""
try:
    from tool_server.track import MAX_BODY_BYTES, handle_track  # noqa: E402
except Exception as exc:  # noqa: BLE001 — 어떤 import 실패든 보고 대상이다
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

# 허용 Origin. 뷰어가 어디에 배포되든 자기 호스트에서만 수집한다.
# 로컬 개발(scripts/dev_relay.py)도 통과시킨다.
_ALLOWED_ORIGIN_SUFFIXES = (".vercel.app", "localhost", "127.0.0.1")


def _origin_ok(origin: str, host: str) -> bool:
    """Origin이 우리 호스트이거나 허용 접미사면 True. 없으면(동일 출처) True."""
    if not origin:
        return True
    try:
        netloc = urlsplit(origin).netloc.lower()
    except ValueError:
        return False
    if not netloc:
        return False
    if host and netloc == host.lower():
        return True
    bare = netloc.split(":")[0]
    return any(
        bare == suffix or bare.endswith(suffix)
        for suffix in _ALLOWED_ORIGIN_SUFFIXES
    )


_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
}


def _send(rh, status, body=None):
    payload = json.dumps(body or {}, ensure_ascii=False).encode("utf-8")
    rh.send_response(status)
    for k, v in _CORS_HEADERS.items():
        rh.send_header(k, v)
    rh.send_header("Cache-Control", "no-store")
    if status == 204:
        rh.send_header("Content-Length", "0")
        rh.end_headers()
        return
    rh.send_header("Content-Type", "application/json; charset=utf-8")
    rh.send_header("Content-Length", str(len(payload)))
    rh.end_headers()
    rh.wfile.write(payload)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):  # noqa: N802 - Vercel 규약
        self.send_response(204)
        for k, v in _CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_POST(self):  # noqa: N802 - Vercel 규약
        if _IMPORT_ERROR:
            _send(self, 500, {
                "error": "서버 초기화에 실패했습니다",
                "detail": _IMPORT_ERROR,
                "python": platform.python_version(),
            })
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                _send(self, 413, {"error": "payload too large"})
                return
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(body, dict):
                _send(self, 400, {"error": "bad body"})
                return
            headers = {k.lower(): v for k, v in self.headers.items()}
            ok = _origin_ok(headers.get("origin", ""), headers.get("host", ""))
            status, out = handle_track(body, headers, ok)
        except Exception:
            # 수집 실패가 원인을 노출하면 안 되고, 뷰어를 방해해도 안 된다.
            status, out = 204, {}
        _send(self, status, out)
```

- [ ] **Step 2: import 검증**

Run: `python -c "import ast,sys; ast.parse(open('api/track.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: 커밋**

```bash
git add api/track.py
git commit -m "feat(analytics): /api/track 수집 엔드포인트"
```

---

### Task 4: 집계 조회 (stats 몸통)

**Files:**
- Create: `tool_server/stats.py`
- Test: `tests/test_tool_server_stats.py`

**Interfaces:**
- Consumes: `tool_server.supa.select_rows(path, *, get=None) -> list[dict]`
- Produces:
  - `token_ok(supplied: str) -> bool`
  - `handle_stats(query: dict, token: str) -> tuple[int, dict]` — `query["view"]` ∈ `{"corps","sources","traffic","visitors","timeline"}`, `query["days"]` 정수 문자열, `query["visitor_id"]`(timeline 전용)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_tool_server_stats.py`:

```python
"""tool_server.stats — 대시보드 집계 조회의 단위 테스트.

토큰이 안 걸리면 접속 로그 전체가 공개된다. 인증 분기를 가장 먼저 고정한다.
"""
import tool_server.stats as stats_mod
from tool_server.stats import handle_stats, token_ok


def _stub_rows(rows):
    return lambda path, **kw: rows


def test_token_missing_env_denies(monkeypatch):
    monkeypatch.delenv("OPS_TOKEN", raising=False)
    assert token_ok("아무거나") is False


def test_token_empty_supplied_denies(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "s3cret")
    assert token_ok("") is False


def test_token_exact_match_allows(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "s3cret")
    assert token_ok("s3cret") is True


def test_token_wrong_denies(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "s3cret")
    assert token_ok("s3cre") is False


def test_handle_stats_503_when_token_unset(monkeypatch):
    # 토큰을 안 걸어둔 채 배포되면 열린 상태가 된다 — 그럴 바엔 닫는다.
    monkeypatch.delenv("OPS_TOKEN", raising=False)
    status, body = handle_stats({"view": "corps"}, "")
    assert status == 503


def test_handle_stats_401_on_bad_token(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "s3cret")
    status, _ = handle_stats({"view": "corps"}, "nope")
    assert status == 401


def test_handle_stats_400_on_unknown_view(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "s3cret")
    status, _ = handle_stats({"view": "everything"}, "s3cret")
    assert status == 400


def test_corps_view_aggregates_across_days(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "s3cret")
    monkeypatch.setattr(stats_mod, "select_rows", _stub_rows([
        {"corp_name": "셀트리온", "stock_code": "068270", "day": "2026-08-21",
         "views": 2, "visitors": 2},
        {"corp_name": "셀트리온", "stock_code": "068270", "day": "2026-08-22",
         "views": 3, "visitors": 1},
        {"corp_name": "두산", "stock_code": "000150", "day": "2026-08-22",
         "views": 4, "visitors": 4},
    ]))
    status, body = handle_stats({"view": "corps", "days": "30"}, "s3cret")
    assert status == 200
    rows = body["rows"]
    # 조회수 내림차순, 같은 회사는 날짜를 합산한다.
    assert rows[0]["corp_name"] == "셀트리온" and rows[0]["views"] == 5
    assert rows[1]["corp_name"] == "두산" and rows[1]["views"] == 4


def test_timeline_view_requires_visitor_id(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "s3cret")
    status, _ = handle_stats({"view": "timeline"}, "s3cret")
    assert status == 400


def test_timeline_view_returns_rows(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "s3cret")
    seen = {}

    def fake_select(path, **kw):
        seen["path"] = path
        return [{"ts": "2026-08-22T01:00:00Z", "event": "scan", "corp_name": "두산"}]

    monkeypatch.setattr(stats_mod, "select_rows", fake_select)
    status, body = handle_stats({"view": "timeline", "visitor_id": "abc"}, "s3cret")
    assert status == 200
    assert body["rows"][0]["corp_name"] == "두산"
    assert "visitor_id=eq.abc" in seen["path"]


def test_days_filter_is_clamped(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", "s3cret")
    seen = {}

    def fake_select(path, **kw):
        seen["path"] = path
        return []

    monkeypatch.setattr(stats_mod, "select_rows", fake_select)
    handle_stats({"view": "traffic", "days": "99999"}, "s3cret")
    # 상한을 안 걸면 전체 스캔이 된다.
    assert "day=gte." in seen["path"]
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `python -m pytest tests/test_tool_server_stats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tool_server.stats'`

- [ ] **Step 3: 구현**

`tool_server/stats.py`:

```python
"""대시보드 집계 조회 — 운영 전용 /api/stats 몸통.

인증은 단일 공유 토큰이다. SE의 인가 체계와 섞지 않는다 — 신뢰 모델이
다르고, 섞으면 한쪽 사고가 다른 쪽으로 번진다.
"""
from __future__ import annotations

import datetime as _dt
import hmac
import os

from tool_server.supa import select_rows

VIEWS = {"corps", "sources", "traffic", "visitors", "timeline"}
DAYS_DEFAULT = 30
DAYS_MAX = 365
ROW_LIMIT = 500


def token_ok(supplied: str) -> bool:
    """상수시간 비교. 문자열 == 는 첫 불일치에서 끊겨 길이가 새어 나간다."""
    expected = os.environ.get("OPS_TOKEN") or ""
    if not expected or not supplied:
        return False
    return hmac.compare_digest(supplied, expected)


def _days(raw) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DAYS_DEFAULT
    return max(1, min(DAYS_MAX, value))


def _since(days: int) -> str:
    return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)).date().isoformat()


def _merge_corps(rows: list[dict]) -> list[dict]:
    """뷰는 (회사, 날짜)로 쪼개져 있다. 회사 단위로 다시 합친다."""
    merged: dict[tuple, dict] = {}
    for row in rows:
        key = (row.get("corp_name"), row.get("stock_code"))
        slot = merged.setdefault(
            key, {"corp_name": key[0], "stock_code": key[1], "views": 0, "visitors": 0}
        )
        slot["views"] += int(row.get("views") or 0)
        # 날짜별 순방문자 합은 실제 순방문자의 상한이다. 그대로 쓰면 과대
        # 계상되므로 화면에 "연인원"으로 표기한다.
        slot["visitors"] += int(row.get("visitors") or 0)
    return sorted(merged.values(), key=lambda r: -r["views"])


def handle_stats(query: dict, token: str) -> tuple[int, dict]:
    """(status, body). 토큰 미설정 배포는 열린 상태가 되므로 503으로 닫는다."""
    if not (os.environ.get("OPS_TOKEN") or ""):
        return 503, {"error": "OPS_TOKEN이 설정되지 않았습니다"}
    if not token_ok(token):
        return 401, {"error": "unauthorized"}

    view = (query.get("view") or "corps").strip()
    if view not in VIEWS:
        return 400, {"error": "unknown view"}

    days = _days(query.get("days"))
    since = _since(days)

    if view == "corps":
        rows = select_rows(
            f"v_corp_ranking?day=gte.{since}&order=views.desc&limit={ROW_LIMIT}"
        )
        return 200, {"view": view, "days": days, "rows": _merge_corps(rows)}

    if view == "traffic":
        rows = select_rows(f"v_traffic_daily?day=gte.{since}&order=day.asc")
        return 200, {"view": view, "days": days, "rows": rows}

    if view == "sources":
        rows = select_rows(
            f"v_referrer_summary?day=gte.{since}&order=hits.desc&limit={ROW_LIMIT}"
        )
        return 200, {"view": view, "days": days, "rows": rows}

    if view == "visitors":
        rows = select_rows(
            f"v_visitor_sessions?last_seen=gte.{since}&order=last_seen.desc&limit={ROW_LIMIT}"
        )
        return 200, {"view": view, "days": days, "rows": rows}

    visitor_id = (query.get("visitor_id") or "").strip()
    if not visitor_id:
        return 400, {"error": "visitor_id가 필요합니다"}
    rows = select_rows(
        f"viewer_events?visitor_id=eq.{visitor_id}&order=ts.desc&limit={ROW_LIMIT}"
    )
    return 200, {"view": view, "visitor_id": visitor_id, "rows": rows}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `python -m pytest tests/test_tool_server_stats.py -v`
Expected: 11 passed

- [ ] **Step 5: 커밋**

```bash
git add tool_server/stats.py tests/test_tool_server_stats.py
git commit -m "feat(analytics): 집계 조회 + 상수시간 토큰 인증"
```

---

### Task 5: `/api/stats` HTTP 껍데기

**Files:**
- Create: `api/stats.py`

**Interfaces:**
- Consumes: `tool_server.stats.handle_stats(query, token) -> tuple[int, dict]`
- Produces: `GET /api/stats?view=&days=&visitor_id=`, 헤더 `X-Ops-Token`

- [ ] **Step 1: 구현**

`api/stats.py` — `api/doc.py` 구조를 그대로 따르되 캐시는 절대 걸지 않는다:

```python
"""Vercel Python 함수 진입점 — 운영 대시보드 집계(/api/stats).

계약: GET /api/stats?view=corps&days=30, 인증은 X-Ops-Token 헤더.
토큰을 쿼리에 넣지 않는다 — URL은 로그·리퍼러·CDN 캐시 키에 남는다.
응답은 절대 캐시하지 않는다(운영 데이터).
"""
import json
import os
import platform
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_IMPORT_ERROR = ""
try:
    from tool_server.stats import handle_stats  # noqa: E402
except Exception as exc:  # noqa: BLE001 — 어떤 import 실패든 보고 대상이다
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

_CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Ops-Token",
    "Access-Control-Max-Age": "86400",
}


def _send_json(rh, status, body):
    payload = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
    rh.send_response(status)
    rh.send_header("Content-Type", "application/json; charset=utf-8")
    rh.send_header("Content-Length", str(len(payload)))
    # 운영 데이터는 어떤 캐시에도 남기지 않는다.
    rh.send_header("Cache-Control", "no-store")
    rh.send_header("X-Robots-Tag", "noindex, nofollow")
    for k, v in _CORS_HEADERS.items():
        rh.send_header(k, v)
    rh.end_headers()
    rh.wfile.write(payload)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):  # noqa: N802 - Vercel 규약
        self.send_response(204)
        for k, v in _CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):  # noqa: N802 - Vercel 규약
        if _IMPORT_ERROR:
            _send_json(self, 500, {
                "error": "서버 초기화에 실패했습니다",
                "detail": _IMPORT_ERROR,
                "python": platform.python_version(),
            })
            return
        try:
            query = dict(parse_qsl(urlsplit(self.path).query))
            token = (self.headers.get("X-Ops-Token") or "").strip()
            status, body = handle_stats(query, token)
        except Exception:
            status, body = 500, {"error": "서버 오류가 발생했습니다"}
        _send_json(self, status, body)
```

- [ ] **Step 2: 문법 검증**

Run: `python -c "import ast; ast.parse(open('api/stats.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 3: 커밋**

```bash
git add api/stats.py
git commit -m "feat(analytics): /api/stats 집계 엔드포인트"
```

---

### Task 6: 뷰어 수집 스니펫 + 면책 문구 정정

**Files:**
- Modify: `docs/tool/index.html:411-418` (면책 문구)
- Modify: `docs/tool/index.html` (`</script>` 직전에 수집 스니펫 추가)
- Modify: `docs/tool/index.html:1146` 부근 (`pushRecent` 호출 뒤 `scan` 이벤트)

**Interfaces:**
- Consumes: `POST /api/track`
- Produces: 전역 `track(event, extra)` 함수

- [ ] **Step 1: 면책 문구 정정**

현재 414행은 `이 페이지는 어떤 데이터도 서버에 저장하지 않습니다.` 이다. 수집을 붙이는 순간 이 문장은 **거짓**이 되므로 반드시 고친다. 이 줄을 아래로 교체한다:

```html
      조회는 사용자의 API 키로 사용자가 시작하며, API 키는 서버에 저장되지 않습니다.
      서비스 개선을 위해 접속 기록·쿠키·기기 정보를 수집합니다.
```

- [ ] **Step 2: 수집 스니펫 추가**

`docs/tool/index.html`의 마지막 `</script>` 직전에 넣는다:

```javascript
/* ── 접속 분석 수집 ────────────────────────────────────────────────
   전체를 try/catch로 감싼다. 수집이 죽어도 뷰어는 그대로 동작해야 한다.
   이 블록은 뷰어 로직에 어떤 값도 되돌려주지 않는다. */
var DV_ID = (function () {
  try {
    var m = document.cookie.match(/(?:^|;\s*)dv_id=([^;]+)/);
    if (m) return m[1];
    var id = (crypto.randomUUID ? crypto.randomUUID()
      : String(Date.now()) + Math.random().toString(36).slice(2));
    document.cookie = "dv_id=" + id + ";max-age=31536000;path=/;SameSite=Lax";
    return id;
  } catch (e) { return ""; }
})();

function track(event, extra) {
  try {
    var payload = Object.assign({
      event: event,
      visitor_id: DV_ID,
      referrer: document.referrer || "",
      path: location.pathname,
      screen: (screen.width || 0) + "x" + (screen.height || 0),
      lang: navigator.language || "",
    }, extra || {});
    var blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
    if (navigator.sendBeacon && navigator.sendBeacon("/api/track", blob)) return;
    fetch("/api/track", {
      method: "POST", body: blob, keepalive: true,
      headers: { "Content-Type": "application/json" },
    }).catch(function () {});
  } catch (e) { /* 수집 실패는 삼킨다 */ }
}

track("pageview");
```

- [ ] **Step 3: 스캔 이벤트 배선**

`pushRecent({ n: name, s: stockCode, ... });` (약 1146행) 바로 다음 줄에 추가:

```javascript
  track("scan", { corp_name: name, stock_code: stockCode });
```

- [ ] **Step 4: robots.txt 작성**

`docs/tool/robots.txt` (Vercel `outputDirectory`가 `docs/tool`이라 `/robots.txt`로 서빙된다):

```
User-agent: *
Disallow: /ops-762b24e0.html
Disallow: /api/stats
```

- [ ] **Step 5: 문법 검증**

Run: `node --check <(sed -n '/<script>/,/<\/script>/p' docs/tool/index.html) 2>/dev/null || echo "수동 확인: 브라우저 콘솔에 에러 없는지"`
그리고 브라우저로 열어 콘솔 에러가 없는지, `document.cookie`에 `dv_id`가 생기는지 확인한다.

- [ ] **Step 6: 커밋**

```bash
git add docs/tool/index.html docs/tool/robots.txt
git commit -m "feat(analytics): 뷰어 수집 스니펫 + 면책 문구 정정

414행 '어떤 데이터도 서버에 저장하지 않습니다'는 수집 도입으로 거짓이 되므로
'API 키는 저장되지 않습니다' + 수집 고지로 교체."
```

---

### Task 7: 대시보드 화면

**Files:**
- Create: `docs/tool/ops-762b24e0.html`

**Interfaces:**
- Consumes: `GET /api/stats?view={corps|sources|traffic|visitors|timeline}&days=&visitor_id=`, 헤더 `X-Ops-Token`

- [ ] **Step 1: 구현**

`docs/tool/ops-762b24e0.html` — 단일 파일, 외부 의존 0. 뷰어(`index.html`)의 CSS 변수·다크 톤을 맞춘다.

구성:
- `<head>`에 `<meta name="robots" content="noindex, nofollow">`
- 토큰 입력창 → `localStorage.ops_token`에 보관, 이후 자동 사용. 401이면 다시 묻는다
- 기간 셀렉트(1/7/30/365일)는 모든 탭이 공유
- 탭 4개:
  1. **회사 순위** — `view=corps`. 표: 순위·회사명·종목코드·조회수·방문 연인원
  2. **유입·지역·기기** — `view=sources`. referrer별 합계 표 + 국가·도시 표 + 브라우저/OS/기기 표 (같은 응답을 클라이언트에서 세 번 접어 만든다)
  3. **트래픽 추이** — `view=traffic`. 인라인 SVG 꺾은선 2개(방문자·조회수) + 일별 표
  4. **방문자** — `view=visitors`. 표: 최종 접속·방문자ID·IP·지역·브라우저·기기·이벤트수·스캔수. IP/ID 검색 입력으로 클라이언트 필터. 행 클릭 → `view=timeline&visitor_id=`로 그 방문자의 이벤트 타임라인을 아래에 펼침

주의사항:
- 회사 순위의 `visitors`는 **날짜별 순방문자의 합**이라 실제 순방문자보다 클 수 있다. 열 이름을 "방문 연인원"으로 적고 표 아래 한 줄로 설명한다. 정확한 순방문자로 바꾸려면 뷰를 날짜 없이 다시 만들어야 하는데, 그러면 기간 필터가 불가능해진다 — 의도된 트레이드오프다.
- SVG 차트는 라이브러리 없이 `polyline`의 `points` 문자열을 직접 계산한다.
- 모든 셀은 `textContent`로 넣는다. referrer·UA는 외부 입력이라 `innerHTML`로 넣으면 XSS다.

- [ ] **Step 2: 로컬 확인**

Run: `python -m http.server 8899 --directory docs/tool`
브라우저에서 `http://localhost:8899/ops-762b24e0.html` — 토큰 입력창이 뜨고, 잘못된 토큰에 401 안내가 나오는지 확인.

- [ ] **Step 3: 커밋**

```bash
git add docs/tool/ops-762b24e0.html
git commit -m "feat(analytics): 운영 대시보드 4개 화면"
```

---

### Task 8: 배포 준비와 문서

**Files:**
- Create: `docs/tool/ANALYTICS.md`
- Modify: `.vercelignore` (필요 시)

- [ ] **Step 1: `.vercelignore` 확인**

Run: `cat .vercelignore`
`tool_server`가 제외되지 않는지 확인한다(`!tool_server` 필요). 이미 있으면 그대로 둔다.

- [ ] **Step 2: 운영 문서 작성**

`docs/tool/ANALYTICS.md`에 적을 것:
- Supabase SQL 편집기에 `tool_server/schema_analytics.sql`을 1회 실행
- Vercel 환경변수 3개: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `OPS_TOKEN`
- `OPS_TOKEN` 생성: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- 대시보드 주소와 토큰 입력 방법
- 수집 항목 목록과, 이것이 개인정보 처리에 해당한다는 사실
- 보관기간 자동 삭제는 없다는 사실 (필요 시 수동 `delete from viewer_events where ts < now() - interval '90 days'`)

- [ ] **Step 3: 전체 테스트**

Run: `python -m pytest tests/test_tool_server_supa.py tests/test_tool_server_track.py tests/test_tool_server_stats.py -v`
Expected: 32 passed

Run: `python -m pytest tests/test_golden_output_hygiene.py -v`
Expected: 기존과 동일 (이번 변경은 MCP 출력 경로를 건드리지 않는다)

- [ ] **Step 4: 커밋**

```bash
git add docs/tool/ANALYTICS.md .vercelignore
git commit -m "docs(analytics): 배포 절차와 수집 항목 문서"
```

---

## 회귀 영향

- `api/[endpoint].js` **미변경** — 무상태 통과 계약 유지
- `se_server/**` **미변경** — 별도 테이블·별도 인증
- `dart_risk_mcp/**` **미변경** — MCP 도구 출력 경로 무관, hygiene 테스트 영향 없음
- `docs/tool/index.html` — 면책 문구 1줄 교체 + 격리된 수집 스니펫. 기존 스캔·검색·겸직 비교 경로는 그대로
- 신규 의존성 **없음**
