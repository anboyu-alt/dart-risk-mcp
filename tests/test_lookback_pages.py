"""공시 조회 페이지 상한이 대형사를 덮는지 (2026-08-23).

옛 공식 `years * 10`은 1년 조회에 1,000건만 허용했다. 80개 조합 스윕에서
삼성전자만 절단이 남는 것으로 잡혔다 — 1년 공시가 2,891건인데 1,000건만
보고 리포트를 냈다.

1년 코퍼스(법인 45,426개) 분포:

| 1년 공시량 | 법인 수 |
|---|---:|
| 1,000건 초과 | 23개 (0.05%) |
| 3,000건 초과 | 2개 |
| **5,000건 초과** | **0개** |

50페이지면 1년 조회를 전부 덮는다. 상한을 올려도 작은 회사는 비용이 늘지
않는다 — `total_count`로 조기 종료하기 때문이다(라이브: 소형사 18.8초로
변화 없음, 삼성전자만 28.6 → 45.3초, 둘 다 예산 안).
"""
import pytest

import dart_risk_mcp.server as srv


class TestPageCap:
    @pytest.mark.parametrize("years", [1, 2, 3, 4, 5])
    def test_모든_창이_최소_50페이지다(self, years):
        _, max_pages, _ = srv._resolve_lookback(years, None)
        assert max_pages >= 50

    def test_1년_조회가_실측_최대를_덮는다(self):
        """1년 최다 법인은 4,143건(미래에셋자산운용) — 42페이지."""
        _, max_pages, _ = srv._resolve_lookback(1, None)
        assert max_pages * 100 >= 4143

    def test_창이_길수록_줄지_않는다(self):
        caps = [srv._resolve_lookback(y, None)[1] for y in range(1, 6)]
        assert caps == sorted(caps), caps

    def test_lookback_days_경로는_그대로다(self):
        """deprecated 별칭의 동작을 바꾸지 않는다."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            days, max_pages, _ = srv._resolve_lookback(1, 30)
        assert days == 30
        assert max_pages == 10


class TestCostRationale:
    def test_조기_종료가_작은_회사를_보호한다(self):
        """상한을 올려도 total_count로 끝나면 페이지를 다 안 훑는다."""
        from unittest.mock import patch
        import dart_risk_mcp.core.dart_client as dc

        calls = []

        class R:
            def json(self):
                return {"status": "000",
                        "list": [{"rcept_no": "1", "report_nm": "x"}],
                        "total_count": 1}

        def fake(method, url, **kw):
            calls.append(kw["params"]["page_no"])
            return R()

        with patch.object(dc, "_retry", side_effect=fake):
            dc.fetch_company_disclosures("00126380", "k", max_pages=50)
        assert calls == [1], "1건짜리 회사가 50페이지를 훑으면 안 된다"
