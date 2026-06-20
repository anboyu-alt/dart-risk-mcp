import dart_risk_mcp.core.dart_client as dc


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
