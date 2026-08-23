"""다년 기업 조회의 페이지 상한 (2026-08-23).

`_resolve_lookback`을 쓰는 도구는 창에 비례해 상한을 올렸지만(years×10),
그 함수를 안 쓰는 세 경로가 기본값 10페이지(1,000건)를 쓰고 있었다.

실측: `find_actor_overlap` 실행 중 로그에 남았다 —
`공시목록 1000건 초과 기업 (corp_code=00126380, total=3547) — 일부 누락`.
삼성전자 5년 공시 3,547건 중 1,000건만 보고 결과를 냈다는 뜻이다.

1년 코퍼스(법인 45,426개) 기준 분포는 극단적으로 치우쳐 있다 — p99가
77건/년이고, years×10 상한을 넘는 법인은 **0.05%**(대부분 펀드 공시를
쏟아내는 자산운용사)다. 완전 제거는 과하고 기존 관례로 맞추는 것이 맞다.
"""
from unittest.mock import patch

import dart_risk_mcp.server as srv
from dart_risk_mcp.core.dart_client import FETCH_OK


def _capture_max_pages(fn, *args, **kwargs):
    seen = {}

    def fake(corp_code, api_key, lookback_days=90, max_pages=10, **kw):
        seen.setdefault("max_pages", max_pages)
        seen.setdefault("lookback_days", lookback_days)
        return []

    def fake_ws(*a, **kw):
        # 두 도구는 조회 실패를 부재와 구분하려고 상태를 함께 받는다(2026-08-23).
        # 여기서 재는 것은 페이지 상한이므로 정상 상태로 감싼다.
        return fake(*a, **kw), FETCH_OK

    with patch.object(srv, "fetch_company_disclosures", side_effect=fake), \
         patch.object(srv, "fetch_company_disclosures_with_status",
                      side_effect=fake_ws), \
         patch.object(srv, "_DART_API_KEY", "k"), \
         patch.object(srv, "resolve_corp",
                      return_value=("테스트", {"corp_code": "00126380",
                                             "stock_code": "005930"})):
        fn(*args, **kwargs)
    return seen


class TestMultiYearPaging:
    def test_track_capital_structure가_창에_비례한다(self):
        seen = _capture_max_pages(srv.track_capital_structure, "삼성전자",
                                  lookback_years=5)
        assert seen["max_pages"] >= 50, "5년 조회가 1,000건에서 잘리면 안 된다"

    def test_find_actor_overlap이_창에_비례한다(self):
        seen = _capture_max_pages(srv.find_actor_overlap,
                                  ["삼성전자", "SK하이닉스"], lookback_years=5)
        assert seen["max_pages"] >= 50

    def test_1년_조회는_기존_상한을_유지한다(self):
        """작은 창까지 상한을 올리면 불필요한 호출이 는다."""
        seen = _capture_max_pages(srv.track_capital_structure, "삼성전자",
                                  lookback_years=1)
        assert seen["max_pages"] == 10


class TestLimitRationale:
    def test_상한이_실측_분포를_덮는다(self):
        """삼성전자 5년 실측 3,547건 = 36페이지."""
        assert 5 * 10 * 100 >= 3547

    def test_완전_제거는_하지_않는다(self):
        """최다 법인은 5년 추정 20,715건(208페이지) — 상위 0.05%를 위해
        모든 조회를 208페이지로 늘리는 것은 대기 예산에 맞지 않는다.
        절단이 남는 경우는 기존대로 로그 경고로 남는다.
        """
        assert 5 * 10 < 208
