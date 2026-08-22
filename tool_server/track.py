"""접속 이벤트 수집 — 공개 뷰어의 /api/track 몸통.

브라우저가 보낸 값은 신뢰하지 않는다. IP·지역은 요청 헤더에서만 읽고
(클라이언트가 위조할 수 없다), 본문은 화이트리스트로 걸러 길이를 자른다.

`api/[endpoint].js`(DART 릴레이)에는 어떤 로깅도 넣지 않는다 — 그쪽은
"키·파라미터·응답을 저장하거나 로그로 남기지 않는 무상태 통과"가 명시된
신뢰 경계다. 수집은 이 엔드포인트에서만 한다.

사용자의 DART API 키는 어떤 필드로도 받지 않는다(화이트리스트에 없다).

HTTP 껍데기(api/track.py)와 분리된 순수 함수라 단위 테스트가 가능하다.
"""
from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from tool_server.supa import insert_row

TABLE = "viewer_events"

# 정상 이벤트는 수백 바이트다. 상한을 두지 않으면 공개 엔드포인트가
# 임의 크기 쓰레기 저장소가 된다.
MAX_BODY_BYTES = 1024
MAX_FIELD_CHARS = 300
MAX_UA_CHARS = 500

ALLOWED_EVENTS = {"pageview", "scan", "compare", "doc"}

# 클라이언트가 보낼 수 있는 필드는 이것뿐. 나머지는 조용히 버린다.
CLIENT_FIELDS = (
    "visitor_id",
    "corp_name",
    "stock_code",
    "path",
    "screen",
    "lang",
)

# headless·자동화 클라이언트를 함께 잡는다. HeadlessChrome은 UA가 일반
# Chrome과 거의 같아 이걸 안 넣으면 스캐너가 데스크톱 방문자로 집계된다
# (프로덕션 실측 2026-08-22 — AWS us-west에서 HeadlessChrome/141 2건).
_BOT_RE = re.compile(
    r"bot|crawler|spider|crawling|slurp|bingpreview|headless|phantomjs"
    r"|puppeteer|playwright|scrapy|curl/|wget/|python-requests|go-http-client"
    r"|okhttp|node-fetch|axios/",
    re.I,
)

# 순서가 곧 우선순위다. Edge·Opera·Samsung·Whale UA는 Chrome 토큰을 포함하고
# Chrome UA는 Safari 토큰을 포함한다 — 순서를 틀리면 전부 Chrome/Safari가 된다.
_BROWSERS = (
    ("Edge", re.compile(r"Edg[eiA]?/")),
    ("Opera", re.compile(r"OPR/|Opera")),
    ("Samsung Internet", re.compile(r"SamsungBrowser/")),
    ("Whale", re.compile(r"Whale/")),
    ("Firefox", re.compile(r"Firefox/|FxiOS/")),
    ("Chrome", re.compile(r"Chrome/|CriOS/")),
    ("Safari", re.compile(r"Safari/")),
)

# iOS 판정은 Windows보다 먼저 와야 한다("like Mac OS X"가 섞여 있다).
_OSES = (
    ("Android", re.compile(r"Android")),
    ("iOS", re.compile(r"iPhone|iPad|iPod")),
    ("Windows", re.compile(r"Windows NT")),
    ("macOS", re.compile(r"Mac OS X|Macintosh")),
    ("Linux", re.compile(r"Linux")),
)


def parse_ua(ua: str) -> dict:
    """UA 문자열 → {browser, os, device, is_mobile}.

    외부 라이브러리를 쓰지 않는 프로젝트 규칙에 맞춰 정규식으로 판별한다.
    정밀한 기기 식별이 목적이 아니라 대략의 분포를 보는 용도다.
    """
    blank = {"browser": None, "os": None, "device": None, "is_mobile": False}
    if not ua:
        return blank
    if _BOT_RE.search(ua):
        # 봇은 브라우저·OS를 따져도 의미가 없다. 구분만 남긴다.
        return {"browser": None, "os": None, "device": "bot", "is_mobile": False}

    browser = next((name for name, rx in _BROWSERS if rx.search(ua)), None)
    os_name = next((name for name, rx in _OSES if rx.search(ua)), None)

    # Android 태블릿은 "Mobile" 토큰이 빠진다 — 이것이 유일한 구분 단서다.
    if re.search(r"iPad|Tablet", ua, re.I) or ("Android" in ua and "Mobile" not in ua):
        device, is_mobile = "tablet", True
    elif re.search(r"Mobi|iPhone|iPod|Android", ua, re.I):
        device, is_mobile = "mobile", True
    else:
        device, is_mobile = "desktop", False

    return {"browser": browser, "os": os_name, "device": device, "is_mobile": is_mobile}


def clean_referrer(raw: str, self_host: str) -> str | None:
    """쿼리스트링·프래그먼트를 떼고 origin+path만 남긴다.

    쿼리를 남기면 유입 사이트가 URL에 실어 보낸 값까지 우리 DB에 들어온다.
    자기 도메인 유입은 '유입 경로'가 아니므로 버린다(뷰어 내부 이동).
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
    cleaned = f"{parts.scheme}://{parts.netloc}{parts.path}".rstrip("/")
    return cleaned[:MAX_FIELD_CHARS] if cleaned else None


def client_ip(headers: dict) -> str | None:
    """x-forwarded-for 체인의 첫 항목이 실제 클라이언트다.

    뒤쪽 항목은 경유한 프록시다. 체인 전체를 저장하면 inet 컬럼이 거부한다.
    """
    chain = (headers.get("x-forwarded-for") or "").strip()
    if not chain:
        return None
    first = chain.split(",")[0].strip()
    return first or None


def _geo(value, limit: int) -> str | None:
    """Vercel geo 헤더는 퍼센트 인코딩돼 온다 — "San%20Jose", 한글 도시명 등.

    그대로 저장하면 대시보드에 인코딩 문자열이 그대로 보인다(프로덕션 실측).
    """
    text = _trim(value, limit)
    if text is None:
        return None
    try:
        return unquote(text)
    except Exception:  # noqa: BLE001 — 디코딩 실패 시 원문을 그대로 쓴다
        return text


def _trim(value, limit: int = MAX_FIELD_CHARS) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def handle_track(body: dict, headers: dict, origin_ok: bool) -> tuple[int, dict]:
    """(status, body). 성공은 204 — 클라이언트는 응답을 읽지 않는다."""
    if not origin_ok:
        return 403, {"error": "forbidden"}

    event = _trim(body.get("event"), 32) or ""
    if event not in ALLOWED_EVENTS:
        return 400, {"error": "unknown event"}

    ua = _trim(headers.get("user-agent"), MAX_UA_CHARS)
    row = {"event": event, "ua": ua, **parse_ua(ua or "")}

    for field in CLIENT_FIELDS:
        row[field] = _trim(body.get(field))

    row["referrer"] = clean_referrer(
        body.get("referrer") or "", headers.get("host") or ""
    )
    row["ip"] = client_ip(headers)
    row["country"] = _geo(headers.get("x-vercel-ip-country"), 8)
    row["region"] = _geo(headers.get("x-vercel-ip-country-region"), 32)
    row["city"] = _geo(headers.get("x-vercel-ip-city"), 64)

    # 저장 실패해도 204. 수집 문제를 뷰어 콘솔의 빨간 에러로 만들지 않는다.
    insert_row(TABLE, row)
    return 204, {}
