"""다년 기업 조회의 페이지 상한 (2026-08-23 최초 · **2026-08-26 재보정**).

## 처음 (2026-08-23)

`_resolve_lookback`을 쓰는 도구는 창에 비례해 상한을 올렸지만, 그 함수를
안 쓰는 세 경로가 기본값 10페이지(1,000건)를 쓰고 있었다. 실측 로그 —
`공시목록 1000건 초과 기업 (corp_code=00126380, total=3547) — 일부 누락`.

## 재보정 (2026-08-26) — 한 곳만 고쳐서 나머지에 안 닿았다

같은 계산이 **네 곳**으로 흩어져 있었고 서로 달랐다.

    _resolve_lookback         max(50, years*10)      ← 2026-08-23에 고침
    _resolve_window           max(10, min(50, …))    ← 50에서 잘림
    find_actor_overlap        (days//365+1)*10       ← 옛 공식 그대로
    track_capital_structure   years*10               ← 옛 공식 그대로

이 파일의 옛 테스트가 **`track_capital_structure` 1년 = 10페이지를 계약으로
못 박고 있었다** — 즉 그 회귀를 잠가 두고 있었다. 실측이 그 전제를 뒤집는다
(10개사, 2026-08-26):

    삼성전자      1년 2,894  3년 3,930  5년 4,364
    미래에셋증권   1년 1,662  3년 4,384  5년 **8,452**
    NH투자증권    1년 1,090  3년 2,997  5년 **5,612**

1년 조회도 10페이지로는 삼성전자에서 **1,894건이 잘린다**. 그리고 50페이지
상한은 5년 조회에서 미래에셋 3,452건을 버린다.

이제 `_page_budget(days)` 한 곳이 정한다 — 1년당 20페이지, 하한 50.

## 잘릴 때는 말한다

상한을 아무리 올려도 잘리는 회사는 남는다. 옛 코드는 그걸 `FETCH_OK`로
접어 **로그에만** 남겼다 — 화면은 창 전체를 조회한 것처럼 보였다.
list.json은 최신순이라 잘리는 쪽은 언제나 오래된 쪽이다.
"""
from unittest.mock import patch

import pytest

import dart_risk_mcp.server as srv
from dart_risk_mcp.core.dart_client import FETCH_OK, FETCH_TRUNCATED


def _capture_max_pages(fn, *args, **kwargs):
    seen = {}

    def fake(corp_code, api_key, lookback_days=90, max_pages=10, **kw):
        seen.setdefault("max_pages", max_pages)
        seen.setdefault("lookback_days", lookback_days)
        return []

    def fake_ws(*a, **kw):
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


# (회사, 1년, 3년, 5년) — 2026-08-26 list.json total_count 실측
_MEASURED = [
    ("삼성전자", 2894, 3930, 4364),
    ("미래에셋증권", 1662, 4384, 8452),
    ("NH투자증권", 1090, 2997, 5612),
    ("삼성증권", 804, 2365, 4970),
    ("현대차증권", 764, 2616, 3949),
]


class TestPageBudget:
    @pytest.mark.parametrize("years,col", [(1, 1), (3, 2), (5, 3)])
    def test_실측_최대치를_덮는다(self, years, col):
        """실측이 있는 창(1·3·5년)만 본다 — 없는 해를 지어내지 않는다."""
        budget = srv._page_budget(years * 365) * 100
        worst = max(m[col] for m in _MEASURED)
        assert budget >= worst, f"{years}년 상한 {budget}건 < 실측 최대 {worst}건"

    def test_1년도_10페이지로는_모자란다(self):
        """옛 계약(1년=10페이지)이 왜 틀렸는지를 남긴다."""
        assert 10 * 100 < 2894

    def test_하한이_50페이지다(self):
        assert srv._page_budget(30) == 50
        assert srv._page_budget(365) == 50

    def test_창이_길면_는다(self):
        assert srv._page_budget(5 * 365) == 100

    def test_작은_회사는_비용이_늘지_않는다(self):
        """상한은 상한일 뿐 — total_count로 조기 종료한다."""
        import inspect

        from dart_risk_mcp.core import dart_client as dc

        src = inspect.getsource(dc.fetch_company_disclosures_with_status)
        assert "if page_no * 100 >= total:" in src


class TestAllCallSites:
    """네 경로가 **같은 예산**을 쓴다 — 흩어져 있던 것이 이번 결함의 원인이다."""

    def test_track_capital_structure(self):
        for yrs, want in [(1, 50), (5, 100)]:
            seen = _capture_max_pages(srv.track_capital_structure, "삼성전자",
                                      lookback_years=yrs)
            assert seen["max_pages"] == want

    def test_find_actor_overlap(self):
        seen = _capture_max_pages(srv.find_actor_overlap,
                                  ["삼성전자", "SK하이닉스"], lookback_years=5)
        assert seen["max_pages"] == 100

    def test_analyze_company_risk(self):
        seen = _capture_max_pages(srv.analyze_company_risk, "삼성전자",
                                  lookback_years=5)
        assert seen["max_pages"] == 100

    def test_시점_지정_경로도_같다(self):
        """`from_date`/`to_date` 경로는 별도 공식(min(50, …))을 갖고 있었다."""
        seen = _capture_max_pages(srv.analyze_company_risk, "삼성전자",
                                  from_date="2021-08-27", to_date="2026-08-26")
        # 5년 창이지만 경계 포함이라 하루 더 길다 — 올림해서 6년치를 준다.
        assert seen["max_pages"] >= 100

    def test_계산이_한_곳에만_있다(self):
        """`* 10` 같은 옛 공식이 되살아나면 잡는다."""
        import pathlib
        import re

        src = pathlib.Path(srv.__file__).read_text(encoding="utf-8")
        # 주석·docstring이 옛 공식을 인용한다(이 파일도 그렇다) — 실행 줄만 본다.
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        bad = [ln.strip() for ln in code.splitlines()
               if "max_pages" in ln and re.search(r"\*\s*10\b", ln)]
        assert not bad, f"옛 공식이 되살아났다: {bad}"
        # 대입은 전부 _page_budget을 거친다(호출부 `max_pages=max_pages`는 통과).
        assigns = [ln.strip() for ln in code.splitlines()
                   if re.match(r"\s*max_pages\s*=\s*", ln)]
        assert assigns, "대입을 하나도 못 찾았다 — 검사가 헛돈다"
        for ln in assigns:
            assert "_page_budget" in ln, ln


class TestTruncationIsVisible:
    """상한을 올려도 잘리는 회사는 남는다 — 그때는 화면이 말해야 한다."""

    def test_상태가_구분된다(self):
        assert len({FETCH_OK, FETCH_TRUNCATED}) == 2

    def test_안내가_실제_덮인_구간을_적는다(self):
        rows = [{"rcept_dt": "20260826"}, {"rcept_dt": "20250101"}]
        note = srv._truncation_notice(FETCH_TRUNCATED, rows, "최근 5년")
        assert "2025.01.01" in note
        assert "오래된 공시는" in note

    def test_안_잘렸으면_아무_말도_안_한다(self):
        rows = [{"rcept_dt": "20260826"}]
        assert srv._truncation_notice(FETCH_OK, rows, "최근 5년") == ""

    def test_리포트에_실린다(self):
        def fake_ws(*a, **kw):
            return [{"rcept_dt": "20250101", "rcept_no": "1" * 14,
                     "report_nm": "분기보고서", "corp_name": "테스트",
                     "flr_nm": "테스트"}], FETCH_TRUNCATED

        with patch.object(srv, "fetch_company_disclosures_with_status",
                          side_effect=fake_ws), \
             patch.object(srv, "_DART_API_KEY", "k"), \
             patch.object(srv, "resolve_corp",
                          return_value=("테스트", {"corp_code": "00126380",
                                                 "stock_code": "005930"})):
            out = srv.list_disclosures_by_stock("005930", lookback_years=5)
        assert "오래된 공시는" in out
