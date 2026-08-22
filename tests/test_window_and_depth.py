"""탐색 깊이 분리 + 시점 지정 조회 (v1.18.0, 2026-08-23).

**깊이**: 지금까지는 창이 1년이든 5년이든 원문 확인이 최근 3건으로 고정이라,
5년을 조회해도 3년 전 사건은 제목만 보였다. 깊이가 창을 따라가지 않으니 넓은
조회는 "많이 보는데 얕게 보는" 상태였다.

역할을 나눈다 — 넓은 창은 **지도**(신호·패턴·타임라인), 좁은 창은 **상세**
(원문까지). 사용자는 지도에서 구간을 고른 뒤 from_date/to_date로 좁혀 본다.

패턴 게이트의 원문 확인은 얕은 모드에서도 유지한다 — 표시용 사실이 아니라
패턴을 띄울지의 판정 입력이라, 빼면 지도에서 패턴 자체가 사라진다.
"""
from unittest.mock import patch

import pytest

import dart_risk_mcp.server as srv
from dart_risk_mcp.core.dart_client import normalize_date8


class TestNormalizeDate:
    @pytest.mark.parametrize("raw,want", [
        ("2026-03-31", "20260331"),
        ("2026.03.31", "20260331"),
        ("2026/03/31", "20260331"),
        ("20260331", "20260331"),
        ("  2026-03-31  ", "20260331"),
    ])
    def test_표기_변형을_흡수한다(self, raw, want):
        assert normalize_date8(raw) == want

    @pytest.mark.parametrize("bad", ["", "abc", "2026", "20261399", "20260230",
                                     "2026-3-1", None])
    def test_잘못된_값은_빈_문자열이다(self, bad):
        """조용히 무시하고 엉뚱한 창을 조회하지 않기 위해 빈 값으로 알린다."""
        assert normalize_date8(bad) == ""


class TestResolveWindow:
    def test_날짜_없으면_기존_동작이다(self):
        bgn, end, days, pages, phrase, err = srv._resolve_window(1, None)
        assert (bgn, end, err) == ("", "", "")
        assert days == 365

    def test_구간을_주면_그_구간이다(self):
        bgn, end, days, pages, phrase, err = srv._resolve_window(
            5, None, "2024-01-01", "2024-06-30")
        assert (bgn, end) == ("20240101", "20240630")
        assert days == 182
        assert "2024.01.01~2024.06.30" == phrase
        assert err == ""

    def test_구간이_lookback_years를_이긴다(self):
        _, _, days, _, _, _ = srv._resolve_window(5, None, "2024-01-01", "2024-01-31")
        assert days == 31, "lookback_years=5가 무시돼야 한다"

    def test_시작일만_주면_오늘까지다(self):
        bgn, end, _, _, _, err = srv._resolve_window(1, None, "2024-01-01", "")
        assert bgn == "20240101" and len(end) == 8 and err == ""

    def test_종료일만_주면_그날_기준_1년이다(self):
        bgn, end, days, _, _, _ = srv._resolve_window(1, None, "", "2024-06-30")
        assert end == "20240630"
        assert bgn == "20230701"
        assert days == 366

    def test_역순_구간은_오류다(self):
        *_, err = srv._resolve_window(1, None, "2024-06-30", "2024-01-01")
        assert "뒤입니다" in err

    @pytest.mark.parametrize("bad_from,bad_to", [("2025-13-99", ""), ("", "abc")])
    def test_형식_오류를_알린다(self, bad_from, bad_to):
        *_, err = srv._resolve_window(1, None, bad_from, bad_to)
        assert "형식이 올바르지 않습니다" in err

    def test_페이지_상한이_창에_비례한다(self):
        _, _, _, p_short, _, _ = srv._resolve_window(1, None, "2024-01-01", "2024-01-31")
        _, _, _, p_long, _, _ = srv._resolve_window(1, None, "2020-01-01", "2024-12-31")
        assert p_short == 10
        assert p_long > p_short


class TestDepthBoundary:
    def test_1년은_깊게_본다(self):
        assert srv._is_deep_window(365) is True

    def test_5년은_얕게_본다(self):
        assert srv._is_deep_window(5 * 365) is False

    def test_경계에_여유가_있다(self):
        """365일 조회가 경계에 딱 붙어 있으면 반올림 하나로 뒤집힌다."""
        assert srv._is_deep_window(365) is True
        assert srv._is_deep_window(400) is True
        assert srv._is_deep_window(401) is False


class TestShallowNotice:
    """⚠ 이 함수는 **날짜 리스트**를 받는다(이벤트 리스트가 아니다).

    처음에는 이벤트를 받아 dict에서 날짜를 꺼냈는데, analyze_company_risk의
    이벤트는 dict이고 build_event_timeline의 이벤트는 **튜플**이라 후자에서
    AttributeError로 죽었다. 두 도구가 각각 테스트를 통과했지만 자료구조가
    다르다는 것은 아무도 확인하지 않았다 — 통합 라이브 검증에서 잡혔다.
    """

    def test_관찰된_신호의_달을_예시로_쓴다(self):
        out = srv._shallow_notice("analyze_company_risk", "제이스코홀딩스",
                                  ["20260814", "20250102"])
        assert 'from_date="2026-08-01"' in out
        assert "analyze_company_risk" in out
        assert "제이스코홀딩스" in out

    def test_신호가_없어도_예시를_준다(self):
        out = srv._shallow_notice("build_event_timeline", "가나", [])
        assert "from_date=" in out

    def test_무엇이_빠졌는지_밝힌다(self):
        """지도라는 사실을 감추면 '신호 없음'과 구분되지 않는다."""
        out = srv._shallow_notice("analyze_company_risk", "가나", [])
        assert "싣지 않았습니다" in out

    @pytest.mark.parametrize("dates", [
        ["20260301"],
        ["20260301", ""],
        [None, "20260301"],
        ["20260301120000"],      # 접수일시가 길게 와도 앞 8자리
    ])
    def test_지저분한_날짜_입력을_흡수한다(self, dates):
        out = srv._shallow_notice("t", "c", dates)
        assert 'from_date="2026-03-01"' in out


class TestShallowNoticeWiring:
    """두 도구의 이벤트 자료구조가 달라도 안내가 나오는지 — 실사고 회귀."""

    def _run(self, fn, **kw):
        rows = [{"rcept_no": "20260814900001", "report_nm": "전환사채권발행결정",
                 "corp_name": "테스트", "rcept_dt": "20260814", "flr_nm": "테스트"}]
        with (
            patch.object(srv, "_DART_API_KEY", "k"),
            patch.object(srv, "resolve_corp",
                         return_value=("테스트", {"corp_code": "00126380",
                                                "stock_code": "005930"})),
            patch.object(srv, "fetch_company_disclosures", return_value=rows),
            patch.object(srv, "fetch_document_text", return_value=""),
            patch.object(srv, "fetch_distress_events", return_value=[]),
            patch.object(srv, "extract_cb_investors", return_value=[]),
        ):
            return fn(**kw)

    def test_analyze_5년이_예외없이_안내를_낸다(self):
        out = self._run(srv.analyze_company_risk,
                        company_name="테스트", lookback_years=5)
        assert "더 깊게 보려면" in out

    def test_timeline_5년이_예외없이_안내를_낸다(self):
        """events가 튜플이라 dict를 가정하면 AttributeError로 죽던 자리."""
        out = self._run(srv.build_event_timeline,
                        company_name="테스트", lookback_years=5)
        assert "더 깊게 보려면" in out


class TestToolWiring:
    """도구가 창 오류를 그대로 사용자에게 알리는지."""

    @patch.object(srv, "_DART_API_KEY", "k")
    def test_analyze가_형식_오류를_반환한다(self):
        out = srv.analyze_company_risk("가나", from_date="2025-13-99")
        assert out.startswith("❌")
        assert "from_date" in out

    @patch.object(srv, "_DART_API_KEY", "k")
    def test_timeline이_형식_오류를_반환한다(self):
        out = srv.build_event_timeline("가나", to_date="abc")
        assert out.startswith("❌")

    @patch.object(srv, "_DART_API_KEY", "k")
    def test_list가_형식_오류를_반환한다(self):
        out = srv.list_disclosures_by_stock("023440", from_date="2025-13-99")
        assert out.startswith("❌")

    def test_세_도구가_날짜_파라미터를_받는다(self):
        import inspect
        for fn in (srv.analyze_company_risk, srv.build_event_timeline,
                   srv.list_disclosures_by_stock):
            params = inspect.signature(fn).parameters
            assert "from_date" in params, fn.__name__
            assert "to_date" in params, fn.__name__
            assert params["from_date"].default == ""


class TestFetchDateRange:
    def test_하부_함수가_구간을_그대로_보낸다(self):
        import dart_risk_mcp.core.dart_client as dc

        seen = {}

        class R:
            def json(self):
                return {"status": "000", "list": [], "total_count": 0}

        def fake(method, url, **kw):
            seen.update(kw["params"])
            return R()

        with patch.object(dc, "_retry", side_effect=fake):
            dc.fetch_company_disclosures("00126380", "k",
                                         bgn_de="20240101", end_de="20240630")
        assert seen["bgn_de"] == "20240101"
        assert seen["end_de"] == "20240630"

    def test_구간을_안_주면_lookback_days를_쓴다(self):
        import dart_risk_mcp.core.dart_client as dc

        seen = {}

        class R:
            def json(self):
                return {"status": "000", "list": [], "total_count": 0}

        def fake(method, url, **kw):
            seen.update(kw["params"])
            return R()

        with patch.object(dc, "_retry", side_effect=fake):
            dc.fetch_company_disclosures("00126380", "k", lookback_days=30)
        assert len(seen["bgn_de"]) == 8
        assert seen["bgn_de"] < seen["end_de"]
