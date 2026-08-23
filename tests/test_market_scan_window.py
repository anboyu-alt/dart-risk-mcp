"""시장 스캔 절단 제거 + 시점 지정 + 대기 예산 분기 (v1.18.1, 2026-08-23).

옛 구현은 2일 청크로 돌다 상한(1,000건)에 닿으면 하루로 재분할했는데,
1년 코퍼스 실측에서 **2일 묶음의 92%가 상한에 닿았다**(122개 중 112개).
거의 항상 재분할된다면 2일 청크는 헛조회를 한 번 더 하는 것일 뿐이다.

하루 상한도 15페이지(1,500건)로는 부족했다 — 실측 하루 분포는 중앙값 774 ·
p90 2,224 · **최대 6,006**건이라 영업일의 18%에서 깨졌다.

라이브 검증(2026-08-23, 30일 창): 전체 **19,524건** 스캔 · 절단 0 ·
독립 수집한 1년 코퍼스의 같은 구간과 **정확히 일치**. 시간은 218.9초 →
168.7초로 오히려 줄었다(헛조회가 사라져서).
"""
from unittest.mock import patch

import pytest

import dart_risk_mcp.server as srv
from dart_risk_mcp.core.dart_client import FETCH_OK


def _ok(rows):
    """옛 스텁 반환값을 상태 반환 계약으로 감싼다.

    시장 스캔은 하루 조회 **실패**를 부재로 말하지 않으려고 상태를 함께
    받는다(2026-08-23). 여기서 재는 것은 청크·상한·창 계산이라 정상
    상태로 감싸면 검증 내용은 그대로다.
    """
    if callable(rows):
        return lambda *a, **kw: (rows(*a, **kw), FETCH_OK)
    return lambda *a, **kw: (rows, FETCH_OK)


class TestBudgetBranch:
    """긴 창은 바로 실행하지 않고 예상 소요와 좁히는 법을 먼저 안내한다."""

    @patch.object(srv, "_DART_API_KEY", "k")
    def test_긴_창은_안내만_반환한다(self):
        with patch.object(srv, "fetch_market_disclosures_with_status",
                          side_effect=_ok(AssertionError)("조회하면 안 된다")):
            out = srv.search_market_disclosures("all_risk", days=30)
        assert "걸립니다" in out
        assert "confirm_long=True" in out

    @patch.object(srv, "_DART_API_KEY", "k")
    def test_confirm_long이면_실행한다(self):
        with patch.object(srv, "fetch_market_disclosures_with_status", side_effect=_ok([])):
            out = srv.search_market_disclosures("all_risk", days=30,
                                                confirm_long=True)
        assert "걸립니다" not in out

    @patch.object(srv, "_DART_API_KEY", "k")
    def test_짧은_창은_바로_실행한다(self):
        with patch.object(srv, "fetch_market_disclosures_with_status", side_effect=_ok([])) as m:
            srv.search_market_disclosures("all_risk", days=7)
        assert m.called

    @patch.object(srv, "_DART_API_KEY", "k")
    def test_안내가_좁히는_법을_함께_준다(self):
        """기다리라고만 하면 분기가 아니다 — 대안을 줘야 고를 수 있다."""
        with patch.object(srv, "fetch_market_disclosures_with_status", side_effect=_ok([])):
            out = srv.search_market_disclosures("cb_issue", days=90)
        assert "from_date=" in out
        assert f"days={srv._LONG_SCAN_DAYS}" in out
        assert "cb_issue" in out, "preset을 유지한 예시여야 그대로 복사해 쓴다"

    def test_경계가_실측에_근거한다(self):
        """7일 17.7초 · 14일 107.5초 실측 — 경계는 그 사이다."""
        assert 7 <= srv._LONG_SCAN_DAYS < 14


class TestDateRange:
    @patch.object(srv, "_DART_API_KEY", "k")
    def test_구간을_지정할_수_있다(self):
        seen = []

        def fake(key, bgn, end, **kw):
            seen.append((bgn, end))
            return []

        with patch.object(srv, "fetch_market_disclosures_with_status", side_effect=_ok(fake)):
            srv.search_market_disclosures("all_risk",
                                          from_date="2026-08-18",
                                          to_date="2026-08-20")
        assert [b for b, _ in seen] == ["20260818", "20260819", "20260820"]

    @patch.object(srv, "_DART_API_KEY", "k")
    def test_구간이_days를_이긴다(self):
        seen = []

        def fake(key, bgn, end, **kw):
            seen.append(bgn)
            return []

        with patch.object(srv, "fetch_market_disclosures_with_status", side_effect=_ok(fake)):
            srv.search_market_disclosures("all_risk", days=90,
                                          from_date="2026-08-18",
                                          to_date="2026-08-19")
        assert len(seen) == 2, "days=90이 무시돼야 한다"

    @patch.object(srv, "_DART_API_KEY", "k")
    @pytest.mark.parametrize("kw,frag", [
        ({"from_date": "2025-13-99"}, "from_date 형식"),
        ({"to_date": "abc"}, "to_date 형식"),
        ({"from_date": "2026-08-20", "to_date": "2026-08-18"}, "뒤입니다"),
    ])
    def test_잘못된_구간을_알린다(self, kw, frag):
        with patch.object(srv, "fetch_market_disclosures_with_status",
                          side_effect=_ok(AssertionError)("조회하면 안 된다")):
            out = srv.search_market_disclosures("all_risk", **kw)
        assert out.startswith("❌")
        assert frag in out

    @patch.object(srv, "_DART_API_KEY", "k")
    def test_90일을_넘는_구간은_거절한다(self):
        with patch.object(srv, "fetch_market_disclosures_with_status",
                          side_effect=_ok(AssertionError)("조회하면 안 된다")):
            out = srv.search_market_disclosures(
                "all_risk", from_date="2026-01-01", to_date="2026-08-01")
        assert out.startswith("❌")
        assert "90일" in out

    @patch.object(srv, "_DART_API_KEY", "k")
    def test_헤더에_구간이_표시된다(self):
        with patch.object(srv, "fetch_market_disclosures_with_status",
                          side_effect=_ok([{"rcept_no": "1", "report_nm": "x",
                                         "corp_name": "가", "rcept_dt": "20260818",
                                         "flr_nm": "가"}])):
            out = srv.search_market_disclosures("all_risk",
                                                from_date="2026-08-18",
                                                to_date="2026-08-18")
        assert "2026.08.18~2026.08.18" in out


class TestDailyChunking:
    @patch.object(srv, "_DART_API_KEY", "k")
    def test_하루씩_조회한다(self):
        """2일 청크는 92%가 상한에 닿아 재분할됐다 — 헛조회였다."""
        seen = []

        def fake(key, bgn, end, **kw):
            seen.append((bgn, end))
            return []

        with patch.object(srv, "fetch_market_disclosures_with_status", side_effect=_ok(fake)):
            srv.search_market_disclosures("all_risk", days=3)
        assert all(b == e for b, e in seen), "청크마다 시작일=종료일이어야 한다"
        assert len(seen) == 3

    @patch.object(srv, "_DART_API_KEY", "k")
    def test_페이지_상한이_실측_최대를_덮는다(self):
        """하루 최대 6,006건(2026-03-31 사업보고서 마감일) 실측."""
        seen = {}

        def fake(key, bgn, end, max_pages=10, **kw):
            seen["max_pages"] = max_pages
            return []

        with patch.object(srv, "fetch_market_disclosures_with_status", side_effect=_ok(fake)):
            srv.search_market_disclosures("all_risk", days=1)
        assert seen["max_pages"] * 100 >= 6006

    @patch.object(srv, "_DART_API_KEY", "k")
    def test_상한에_닿으면_정직하게_표기한다(self):
        """전수라고 말할 수 없을 때는 그렇게 적는다."""
        rows = [{"rcept_no": str(i), "report_nm": "주요사항보고서(전환사채권발행결정)",
                 "corp_name": "가", "rcept_dt": "20260818", "flr_nm": "가"}
                for i in range(7000)]
        with patch.object(srv, "fetch_market_disclosures_with_status", side_effect=_ok(rows)):
            out = srv.search_market_disclosures("cb_issue", days=1)
        assert "절단" in out

    @patch.object(srv, "_DART_API_KEY", "k")
    def test_상한_아래면_절단을_말하지_않는다(self):
        rows = [{"rcept_no": "1", "report_nm": "주요사항보고서(전환사채권발행결정)",
                 "corp_name": "가", "rcept_dt": "20260818", "flr_nm": "가"}]
        with patch.object(srv, "fetch_market_disclosures_with_status", side_effect=_ok(rows)):
            out = srv.search_market_disclosures("cb_issue", days=1)
        assert "절단" not in out


class TestEstimate:
    def test_추정이_창에_비례한다(self):
        assert srv._estimate_scan_seconds(30) > srv._estimate_scan_seconds(7)

    def test_추정이_실측과_같은_자릿수다(self):
        """30일 라이브 168.7초 — 추정 180초와 같은 자릿수여야 안내가 쓸모 있다."""
        est = srv._estimate_scan_seconds(30)
        assert 100 <= est <= 300, f"추정 {est}초 — 실측 168.7초와 괴리"
