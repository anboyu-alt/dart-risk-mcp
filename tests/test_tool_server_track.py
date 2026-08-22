"""tool_server.track — 접속 이벤트 정규화·검증의 단위 테스트.

Supabase 저장은 monkeypatch로 가짜를 넣는다. 네트워크를 타지 않는다.
"""
import tool_server.track as track_mod
from tool_server.track import (
    MAX_BODY_BYTES,
    MAX_FIELD_CHARS,
    clean_referrer,
    client_ip,
    handle_track,
    parse_ua,
)

CHROME_WIN = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
SAFARI_IOS = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
EDGE_WIN = CHROME_WIN + " Edg/120.0.0.0"
WHALE = CHROME_WIN + " Whale/3.21.192.18"
ANDROID_TABLET = (
    "Mozilla/5.0 (Linux; Android 13; SM-X700) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
BOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
HEADLESS = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "HeadlessChrome/141.0.7390.54 Safari/537.36"
)


def _capture(monkeypatch) -> dict:
    """insert_row를 가로채 저장될 행을 돌려준다."""
    saved: dict = {}

    def fake_insert(table, row, **kwargs):
        saved["table"] = table
        saved["row"] = row
        return True

    monkeypatch.setattr(track_mod, "insert_row", fake_insert)
    return saved


# ── UA 파싱 ────────────────────────────────────────────────────────────


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


def test_parse_ua_whale_not_misread_as_chrome():
    assert parse_ua(WHALE)["browser"] == "Whale"


def test_parse_ua_android_tablet_has_no_mobile_token():
    got = parse_ua(ANDROID_TABLET)
    assert got["device"] == "tablet"
    assert got["os"] == "Android"


def test_parse_ua_bot():
    got = parse_ua(BOT)
    assert got["device"] == "bot"
    assert got["is_mobile"] is False


def test_parse_ua_headless_chrome_is_bot():
    # HeadlessChrome UA는 일반 Chrome과 거의 같다. 안 잡으면 스캐너가
    # 데스크톱 방문자로 집계된다(프로덕션 실측 2026-08-22).
    got = parse_ua(HEADLESS)
    assert got["device"] == "bot"
    assert got["browser"] is None


def test_parse_ua_automation_clients_are_bots():
    for ua in ("curl/8.4.0", "python-requests/2.31.0", "Go-http-client/2.0",
               "Scrapy/2.11 (+https://scrapy.org)", "node-fetch/1.0"):
        assert parse_ua(ua)["device"] == "bot", ua


def test_parse_ua_real_chrome_still_not_bot():
    # 봇 패턴을 넓히면서 진짜 브라우저를 삼키지 않았는지 고정한다.
    for ua in (CHROME_WIN, SAFARI_IOS, EDGE_WIN, WHALE, ANDROID_TABLET):
        assert parse_ua(ua)["device"] != "bot", ua


def test_parse_ua_empty():
    got = parse_ua("")
    assert got["browser"] is None and got["device"] is None


# ── referrer ───────────────────────────────────────────────────────────


def test_clean_referrer_strips_query():
    assert (
        clean_referrer(
            "https://cafe.naver.com/abc/12345?page=2&from=search", "dart.example.com"
        )
        == "https://cafe.naver.com/abc/12345"
    )


def test_clean_referrer_strips_fragment():
    assert (
        clean_referrer("https://google.com/search#top", "dart.example.com")
        == "https://google.com/search"
    )


def test_clean_referrer_drops_self_host():
    assert clean_referrer("https://dart.example.com/#a=1", "dart.example.com") is None


def test_clean_referrer_empty_is_none():
    assert clean_referrer("", "dart.example.com") is None


def test_clean_referrer_rejects_scheme_less_value():
    assert clean_referrer("not-a-url", "dart.example.com") is None


# ── IP ─────────────────────────────────────────────────────────────────


def test_client_ip_takes_first_of_forwarded_chain():
    assert client_ip({"x-forwarded-for": "203.0.113.9, 70.41.3.18"}) == "203.0.113.9"


def test_client_ip_missing_is_none():
    assert client_ip({}) is None


# ── handle_track ───────────────────────────────────────────────────────


def test_handle_track_rejects_bad_origin():
    status, _ = handle_track({"event": "pageview"}, {}, origin_ok=False)
    assert status == 403


def test_handle_track_rejects_unknown_event():
    status, _ = handle_track({"event": "steal"}, {}, origin_ok=True)
    assert status == 400


def test_handle_track_rejects_missing_event():
    status, _ = handle_track({}, {}, origin_ok=True)
    assert status == 400


def test_handle_track_stores_whitelisted_fields(monkeypatch):
    saved = _capture(monkeypatch)
    status, _ = handle_track(
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
            "crtfc_key": "사용자 DART 키는 절대 저장하지 않는다",
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
    assert saved["table"] == "viewer_events"
    assert row["event"] == "scan"
    assert row["corp_name"] == "셀트리온"
    assert row["stock_code"] == "068270"
    assert row["visitor_id"] == "abc-123"
    assert row["ip"] == "203.0.113.9"
    assert row["country"] == "KR" and row["city"] == "Seoul"
    assert row["browser"] == "Chrome" and row["os"] == "Windows"
    assert row["referrer"] == "https://google.com/search"
    assert "evil" not in row
    assert "crtfc_key" not in row


def test_handle_track_decodes_percent_encoded_city(monkeypatch):
    # Vercel geo 헤더는 퍼센트 인코딩돼 온다 — 그대로 저장하면 대시보드에
    # "San%20Jose"가 그대로 보인다(프로덕션 실측 2026-08-22).
    saved = _capture(monkeypatch)
    handle_track(
        {"event": "pageview"},
        {"x-vercel-ip-city": "San%20Jose", "x-vercel-ip-country": "US"},
        origin_ok=True,
    )
    assert saved["row"]["city"] == "San Jose"
    assert saved["row"]["country"] == "US"


def test_handle_track_decodes_non_ascii_city(monkeypatch):
    saved = _capture(monkeypatch)
    handle_track(
        {"event": "pageview"},
        {"x-vercel-ip-city": "%EC%84%9C%EC%9A%B8"},
        origin_ok=True,
    )
    assert saved["row"]["city"] == "서울"


def test_handle_track_leaves_plain_city_untouched(monkeypatch):
    saved = _capture(monkeypatch)
    handle_track(
        {"event": "pageview"}, {"x-vercel-ip-city": "Mapo-gu"}, origin_ok=True
    )
    assert saved["row"]["city"] == "Mapo-gu"


def test_handle_track_truncates_overlong_values(monkeypatch):
    saved = _capture(monkeypatch)
    handle_track({"event": "scan", "corp_name": "가" * 5000}, {}, origin_ok=True)
    assert len(saved["row"]["corp_name"]) <= MAX_FIELD_CHARS


def test_handle_track_returns_204_even_when_store_fails(monkeypatch):
    # 수집 실패를 클라이언트에 에러로 돌려주면 뷰어 콘솔이 빨개진다.
    monkeypatch.setattr(track_mod, "insert_row", lambda t, row, **kw: False)
    status, _ = handle_track({"event": "pageview"}, {}, origin_ok=True)
    assert status == 204


def test_handle_track_nulls_absent_fields(monkeypatch):
    saved = _capture(monkeypatch)
    handle_track({"event": "pageview"}, {}, origin_ok=True)
    row = saved["row"]
    # 컬럼은 항상 존재해야 한다 — PostgREST는 없는 키를 기본값으로 채운다.
    for field in ("visitor_id", "corp_name", "stock_code", "ip", "country"):
        assert field in row and row[field] is None


def test_max_body_bytes_is_small():
    assert MAX_BODY_BYTES <= 2048
