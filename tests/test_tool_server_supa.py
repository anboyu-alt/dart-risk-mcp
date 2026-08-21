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


def _configured(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-key")


def test_supa_config_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co/")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc-key")
    assert supa.supa_config() == ("https://x.supabase.co", "svc-key")


def test_supa_config_blank_when_key_missing(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert supa.supa_config() == ("", "")


def test_insert_row_posts_to_rest_endpoint(monkeypatch):
    _configured(monkeypatch)
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

    def fake_post(url, **kwargs):
        raise AssertionError("설정이 없으면 네트워크를 타면 안 된다")

    assert supa.insert_row("viewer_events", {"event": "scan"}, post=fake_post) is False


def test_insert_row_swallows_network_error(monkeypatch):
    _configured(monkeypatch)

    def fake_post(url, **kwargs):
        raise OSError("boom")

    assert supa.insert_row("viewer_events", {"event": "scan"}, post=fake_post) is False


def test_insert_row_false_on_error_status(monkeypatch):
    _configured(monkeypatch)
    assert supa.insert_row(
        "viewer_events", {"event": "scan"}, post=lambda u, **k: _Resp(400)
    ) is False


def test_select_rows_returns_payload(monkeypatch):
    _configured(monkeypatch)
    rows = [{"corp_name": "셀트리온", "views": 3}]

    def fake_get(url, **kwargs):
        assert url == "https://x.supabase.co/rest/v1/v_corp_ranking?order=views.desc"
        return _Resp(200, rows)

    assert supa.select_rows("v_corp_ranking?order=views.desc", get=fake_get) == rows


def test_select_rows_returns_empty_on_error(monkeypatch):
    _configured(monkeypatch)
    assert supa.select_rows(
        "v_corp_ranking", get=lambda u, **k: _Resp(500, {"message": "nope"})
    ) == []


def test_select_rows_returns_empty_on_non_list_payload(monkeypatch):
    _configured(monkeypatch)
    assert supa.select_rows(
        "v_corp_ranking", get=lambda u, **k: _Resp(200, {"message": "hm"})
    ) == []


def test_select_rows_returns_empty_without_config(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)

    def fake_get(url, **kwargs):
        raise AssertionError("설정이 없으면 네트워크를 타면 안 된다")

    assert supa.select_rows("v_corp_ranking", get=fake_get) == []
