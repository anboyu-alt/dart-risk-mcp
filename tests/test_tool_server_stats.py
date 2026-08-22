"""tool_server.stats — 대시보드 집계 조회의 단위 테스트.

토큰이 안 걸리면 접속 로그 전체가 공개된다. 인증 분기를 가장 먼저 고정한다.
Supabase 조회는 monkeypatch로 가짜를 넣는다 — 네트워크를 타지 않는다.
"""
import tool_server.stats as stats_mod
from tool_server.stats import DAYS_MAX, handle_stats, token_ok

TOKEN = "s3cret-token-value"


def _stub(monkeypatch, rows, seen=None):
    def fake_select(path, **kwargs):
        if seen is not None:
            seen["path"] = path
        return rows

    monkeypatch.setattr(stats_mod, "select_rows", fake_select)


# ── 인증 ───────────────────────────────────────────────────────────────


def test_token_missing_env_denies(monkeypatch):
    monkeypatch.delenv("OPS_TOKEN", raising=False)
    assert token_ok("아무거나") is False


def test_token_empty_supplied_denies(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    assert token_ok("") is False


def test_token_exact_match_allows(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    assert token_ok(TOKEN) is True


def test_token_prefix_denies(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    assert token_ok(TOKEN[:-1]) is False


def test_handle_stats_503_when_token_unset(monkeypatch):
    # 토큰을 안 걸어둔 채 배포되면 열린 상태가 된다 — 그럴 바엔 닫는다.
    monkeypatch.delenv("OPS_TOKEN", raising=False)
    status, _ = handle_stats({"view": "corps"}, "")
    assert status == 503


def test_handle_stats_401_on_bad_token(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    status, _ = handle_stats({"view": "corps"}, "nope")
    assert status == 401


def test_handle_stats_does_not_query_when_unauthorized(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)

    def boom(path, **kwargs):
        raise AssertionError("인증 실패면 DB를 건드리면 안 된다")

    monkeypatch.setattr(stats_mod, "select_rows", boom)
    assert handle_stats({"view": "corps"}, "wrong")[0] == 401


# ── 뷰 ─────────────────────────────────────────────────────────────────


def test_handle_stats_400_on_unknown_view(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    status, _ = handle_stats({"view": "everything"}, TOKEN)
    assert status == 400


def test_corps_view_aggregates_across_days(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    _stub(
        monkeypatch,
        [
            {"corp_name": "셀트리온", "stock_code": "068270", "day": "2026-08-21",
             "views": 2, "visitors": 2},
            {"corp_name": "셀트리온", "stock_code": "068270", "day": "2026-08-22",
             "views": 3, "visitors": 1},
            {"corp_name": "두산", "stock_code": "000150", "day": "2026-08-22",
             "views": 4, "visitors": 4},
        ],
    )
    status, body = handle_stats({"view": "corps", "days": "30"}, TOKEN)
    assert status == 200
    rows = body["rows"]
    # 조회수 내림차순, 같은 회사는 날짜를 합산한다.
    assert rows[0]["corp_name"] == "셀트리온" and rows[0]["views"] == 5
    assert rows[0]["visitors"] == 3  # 날짜별 순방문자 합 = 연인원
    assert rows[1]["corp_name"] == "두산" and rows[1]["views"] == 4


def test_traffic_view_passes_through(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    _stub(monkeypatch, [{"day": "2026-08-22", "pageviews": 10, "visitors": 4}])
    status, body = handle_stats({"view": "traffic"}, TOKEN)
    assert status == 200 and body["rows"][0]["pageviews"] == 10


def test_timeline_view_requires_visitor_id(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    status, _ = handle_stats({"view": "timeline"}, TOKEN)
    assert status == 400


def test_timeline_view_rejects_injection_shaped_id(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    status, _ = handle_stats(
        {"view": "timeline", "visitor_id": "abc&select=*"}, TOKEN
    )
    assert status == 400


def test_timeline_view_returns_rows(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    seen = {}
    _stub(
        monkeypatch,
        [{"ts": "2026-08-22T01:00:00Z", "event": "scan", "corp_name": "두산"}],
        seen,
    )
    status, body = handle_stats(
        {"view": "timeline", "visitor_id": "abc-123"}, TOKEN
    )
    assert status == 200
    assert body["rows"][0]["corp_name"] == "두산"
    assert "visitor_id=eq.abc-123" in seen["path"]


# ── 기간 필터 ──────────────────────────────────────────────────────────


def test_days_filter_is_applied(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    seen = {}
    _stub(monkeypatch, [], seen)
    handle_stats({"view": "traffic", "days": "7"}, TOKEN)
    # 상한을 안 걸면 전체 스캔이 된다.
    assert "day=gte." in seen["path"]


def test_days_is_clamped_to_max(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    _stub(monkeypatch, [])
    _, body = handle_stats({"view": "traffic", "days": "99999"}, TOKEN)
    assert body["days"] == DAYS_MAX


def test_days_garbage_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("OPS_TOKEN", TOKEN)
    _stub(monkeypatch, [])
    _, body = handle_stats({"view": "traffic", "days": "어제"}, TOKEN)
    assert body["days"] == stats_mod.DAYS_DEFAULT
