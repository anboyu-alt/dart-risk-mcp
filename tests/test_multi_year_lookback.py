import dart_risk_mcp.core.dart_client as dc
from dart_risk_mcp import server as srv


def test_fetch_company_disclosures_respects_max_pages(monkeypatch):
    """max_pages 만큼만 페이지를 돌고 멈춘다 (total이 더 커도)."""
    calls = {"n": 0}

    class _Resp:
        def json(self):
            # 매 페이지 100건, total은 항상 큼(절대 자연 종료 안 함)
            return {
                "status": "000",
                "total_count": 100000,
                "list": [{"rcept_no": f"{calls['n']:04d}"} for _ in range(100)],
            }

    def _fake_retry(method, url, **kwargs):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(dc, "_retry", _fake_retry)
    # 기본 max_pages=10
    rows = dc.fetch_company_disclosures("00126380", "KEY", lookback_days=365)
    assert calls["n"] == 10
    assert len(rows) == 1000
    # max_pages=30 명시
    calls["n"] = 0
    rows = dc.fetch_company_disclosures("00126380", "KEY", lookback_days=1825, max_pages=30)
    assert calls["n"] == 30
    assert len(rows) == 3000


def test_estimate_output_size():
    chars, tokens = srv._estimate_output_size("가" * 250)
    assert chars == 250
    assert tokens == 100  # round(250 / 2.5)


def test_append_size_footer_only_for_multiyear():
    body = "본문" * 100
    # 1년 이하: 변화 없음
    assert srv._append_size_footer(body, 1) == body
    # 다년: 푸터 1줄 추가
    out = srv._append_size_footer(body, 3)
    assert out.startswith(body)
    assert "예상 출력 규모" in out
    assert "토큰" in out


def test_list_disclosures_passes_years_to_core(monkeypatch):
    """lookback_years -> lookback_days(years*365), max_pages(years*10) 전달 확인."""
    captured = {}

    monkeypatch.setattr(srv, "_DART_API_KEY", "KEY")
    monkeypatch.setattr(srv, "resolve_corp", lambda q, k: ("테스트사", {"corp_code": "00000000", "stock_code": "012345"}))

    def _fake_fetch(corp_code, api_key, lookback_days, max_pages=10):
        captured["lookback_days"] = lookback_days
        captured["max_pages"] = max_pages
        return [{"rcept_no": "20240101000001", "report_nm": "사업보고서", "rcept_dt": "20240101"}]

    monkeypatch.setattr(srv, "fetch_company_disclosures", _fake_fetch)

    out = srv.list_disclosures_by_stock("012345", lookback_years=3)
    assert captured["lookback_days"] == 3 * 365
    assert captured["max_pages"] == 3 * 10
    assert "최근 3년" in out  # 다년 라벨
    assert "예상 출력 규모" in out  # years>1 푸터


def test_lookback_days_alias_backward_compat(monkeypatch):
    """deprecated lookback_days 별칭: 일 단위 동작 보존 + DeprecationWarning (v1.4.0)."""
    import warnings

    captured = {}
    monkeypatch.setattr(srv, "_DART_API_KEY", "KEY")
    monkeypatch.setattr(srv, "resolve_corp", lambda q, k: ("테스트사", {"corp_code": "00000000", "stock_code": "012345"}))

    def _fake_fetch(corp_code, api_key, lookback_days, max_pages=10):
        captured["lookback_days"] = lookback_days
        captured["max_pages"] = max_pages
        return [{"rcept_no": "20240101000001", "report_nm": "사업보고서", "rcept_dt": "20240101"}]

    monkeypatch.setattr(srv, "fetch_company_disclosures", _fake_fetch)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        out = srv.list_disclosures_by_stock("012345", lookback_days=90)

    assert captured["lookback_days"] == 90  # 일 단위 그대로(구버전 동작)
    assert captured["max_pages"] == 10  # 구버전 기본 페이지 상한
    assert "최근 90일" in out  # 구버전 라벨
    assert "예상 출력 규모" not in out  # 1년 미만 → 푸터 없음
    assert any(issubclass(x.category, DeprecationWarning) for x in w)


def test_resolve_lookback_years_path_parity():
    """years 경로: years==1 → 365일 라벨(골든 패리티), max_pages=years*10."""
    assert srv._resolve_lookback(1, None) == (365, 10, "365일")
    assert srv._resolve_lookback(3, None) == (1095, 30, "3년")
    # 범위 클램프(1~5)
    assert srv._resolve_lookback(99, None) == (1825, 50, "5년")
