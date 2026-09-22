"""KIND 시장경보(투자주의·경고·위험) 파서·조회 검증.

픽스처는 `tests/fixtures/kind/*.html` — 2026-09-22 실측한 KIND 응답 원문
그대로다(공백을 지운 재구성 픽스처는 실전 0건인 키워드를 못 잡는다는
CLAUDE.md 교훈에 따라 원문을 그대로 쓴다).
"""
import pathlib
import unittest
from unittest.mock import MagicMock, patch

from dart_risk_mcp.core import kind_client
from dart_risk_mcp.core.kind_client import (
    KIND_ALERT_URL,
    KIND_MAX_WINDOW_DAYS,
    fetch_market_alerts,
    parse_kind_alert_table,
)

_FX = pathlib.Path(__file__).resolve().parent / "fixtures" / "kind"


def _load(name: str) -> str:
    return (_FX / name).read_text(encoding="utf-8")


class TestParseCaution(unittest.TestCase):
    def test_page1_size10_parses_10_rows_with_reason(self):
        html = _load("caution_page1_size10.html")
        records, meta = parse_kind_alert_table(html, "caution")

        self.assertFalse(meta["parse_failed"])
        self.assertFalse(meta["empty"])
        self.assertEqual(meta["total"], 4900)
        self.assertEqual(meta["columns"], ["번호", "종목명", "유형", "공시일", "지정일"])
        self.assertEqual(len(records), 10)

        first = records[0]
        self.assertEqual(first["kind"], "caution")
        self.assertEqual(first["name"], "네패스아크")
        self.assertEqual(first["reason"], "매매관여과다종목")
        self.assertEqual(first["announced"], "20260921")
        self.assertEqual(first["designated"], "20260922")
        self.assertEqual(first["market"], "코스닥")
        self.assertNotIn("released", first)

    def test_pidelix_6_rows_various_reasons(self):
        html = _load("caution_A032580_pidelix.html")
        records, meta = parse_kind_alert_table(html, "caution")

        self.assertFalse(meta["parse_failed"])
        self.assertEqual(meta["total"], 6)
        self.assertEqual(len(records), 6)

        first = records[0]
        self.assertEqual(first["name"], "피델릭스")
        self.assertEqual(first["reason"], "투자경고 지정예고")
        self.assertEqual(first["announced"], "20260907")
        self.assertEqual(first["designated"], "20260908")

        reasons = {r["reason"] for r in records}
        self.assertIn("투자경고 지정해제", reasons)
        self.assertIn("종가급변", reasons)
        self.assertIn("소수계좌 매수관여 과다", reasons)


class TestParseWarningRisk(unittest.TestCase):
    def test_warning_page1_size10(self):
        html = _load("warning_page1_size10.html")
        records, meta = parse_kind_alert_table(html, "warning")

        self.assertFalse(meta["parse_failed"])
        self.assertEqual(meta["total"], 481)
        self.assertEqual(meta["columns"], ["번호", "종목명", "공시일", "지정일", "해제일"])
        self.assertEqual(len(records), 10)

        first = records[0]
        self.assertEqual(first["kind"], "warning")
        self.assertEqual(first["name"], "가온전선")
        self.assertEqual(first["announced"], "20260427")
        self.assertEqual(first["designated"], "20260428")
        self.assertEqual(first["released"], "20260511")
        self.assertEqual(first["market"], "유가증권")
        self.assertNotIn("reason", first)

    def test_risk_page1_size10(self):
        html = _load("risk_page1_size10.html")
        records, meta = parse_kind_alert_table(html, "risk")

        self.assertFalse(meta["parse_failed"])
        self.assertEqual(meta["total"], 49)
        self.assertEqual(len(records), 10)

        first = records[0]
        self.assertEqual(first["name"], "가온전선")
        self.assertEqual(first["announced"], "20260508")
        self.assertEqual(first["designated"], "20260511")
        self.assertEqual(first["released"], "20260527")

    def test_pidelix_risk_single_row(self):
        html = _load("risk_A032580_pidelix.html")
        records, meta = parse_kind_alert_table(html, "risk")

        self.assertFalse(meta["parse_failed"])
        self.assertEqual(meta["total"], 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "피델릭스")
        self.assertEqual(records[0]["designated"], "20260526")
        self.assertEqual(records[0]["released"], "20260611")

    def test_pidelix_warning_undischarged_is_none(self):
        html = _load("warning_A032580_pidelix.html")
        records, meta = parse_kind_alert_table(html, "warning")

        self.assertFalse(meta["parse_failed"])
        self.assertEqual(meta["total"], 3)
        self.assertEqual(len(records), 3)

        # 최신(row id 3)이 해제 전 "-" → None
        undischarged = [r for r in records if r["designated"] == "20260910"][0]
        self.assertIsNone(undischarged["released"])
        # 나머지는 해제일이 채워져 있다
        discharged = [r for r in records if r["designated"] == "20260611"][0]
        self.assertEqual(discharged["released"], "20260625")


class TestEmptyAndFailure(unittest.TestCase):
    def test_no_results_is_empty_not_failed(self):
        html = _load("risk_A005930_samsung_empty.html")
        records, meta = parse_kind_alert_table(html, "risk")

        self.assertFalse(meta["parse_failed"])
        self.assertTrue(meta["empty"])
        self.assertEqual(records, [])
        self.assertEqual(meta["total"], 0)

    def test_window_over_3y_empty_body_is_parse_failed(self):
        html = _load("caution_window_over_3y_empty.html")
        self.assertEqual(html, "")

        records, meta = parse_kind_alert_table(html, "caution")

        self.assertTrue(meta["parse_failed"])
        self.assertFalse(meta["empty"])
        self.assertEqual(records, [])
        self.assertIsNone(meta["total"])

    def test_swapped_columns_trigger_parse_failed(self):
        html = _load("caution_page1_size10.html")
        # 열 순서를 실제로 바꿔친다 — 구조 변경을 흉내낸다.
        swapped = html.replace(
            'fn_InitTitle("번호,종목명,유형,공시일,지정일"',
            'fn_InitTitle("번호,유형,종목명,공시일,지정일"',
        )
        self.assertNotEqual(swapped, html)

        records, meta = parse_kind_alert_table(swapped, "caution")

        self.assertTrue(meta["parse_failed"])
        self.assertEqual(records, [])
        self.assertEqual(meta["columns"], ["번호", "유형", "종목명", "공시일", "지정일"])

    def test_unknown_kind_is_parse_failed(self):
        html = _load("caution_page1_size10.html")
        records, meta = parse_kind_alert_table(html, "bogus")

        self.assertTrue(meta["parse_failed"])
        self.assertEqual(records, [])


def _fixture_response(name: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.text = _load(name)
    return resp


class TestFetchMarketAlerts(unittest.TestCase):
    def setUp(self):
        kind_client._alert_cache.clear()

    def tearDown(self):
        kind_client._alert_cache.clear()

    @patch("dart_risk_mcp.core.kind_client.requests.post")
    def test_calls_three_kinds_with_correct_params(self, mock_post):
        mock_post.side_effect = [
            _fixture_response("caution_A032580_pidelix.html"),
            _fixture_response("warning_A032580_pidelix.html"),
            _fixture_response("risk_A032580_pidelix.html"),
        ]

        result = fetch_market_alerts("032580", "20240101", "20260922")

        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(result["by_kind"], {"caution": 6, "warning": 3, "risk": 1})
        self.assertEqual(len(result["alerts"]), 10)
        self.assertFalse(result["fetch_failed"])
        self.assertFalse(result["parse_failed"])
        self.assertEqual(result["failed_kinds"], [])
        self.assertFalse(result["clamped"])
        self.assertIsNone(result["clamp_start"])
        self.assertEqual(result["source_url"], KIND_ALERT_URL)

        # 지정일 내림차순 정렬 확인
        designated_dates = [a["designated"] for a in result["alerts"]]
        self.assertEqual(designated_dates, sorted(designated_dates, reverse=True))

        seen_kinds = set()
        for call in mock_post.call_args_list:
            args, kwargs = call
            self.assertEqual(args[0], KIND_ALERT_URL)
            form = kwargs["data"]
            self.assertEqual(form["method"], "investattentwarnriskySub")
            self.assertEqual(form["repIsuSrtCd"], "A032580")
            self.assertEqual(form["searchCodeType"], "char")
            self.assertEqual(form["startDate"], "2024-01-01")
            self.assertEqual(form["endDate"], "2026-09-22")
            self.assertEqual(form["orderMode"], "4")
            self.assertEqual(form["orderStat"], "D")
            self.assertEqual(form["currentPageSize"], "100")
            self.assertEqual(form["pageIndex"], "1")

            headers = kwargs["headers"]
            self.assertEqual(headers["X-Requested-With"], "XMLHttpRequest")
            self.assertIn(KIND_ALERT_URL, headers["Referer"])

            forward = form["forward"]
            menu_index = form["menuIndex"]
            if forward == "invstcautnisu_sub":
                self.assertEqual(menu_index, "1")
                seen_kinds.add("caution")
            elif forward == "invstwarnisu_sub":
                self.assertEqual(menu_index, "2")
                seen_kinds.add("warning")
            elif forward == "invstriskisu_sub":
                self.assertEqual(menu_index, "3")
                seen_kinds.add("risk")
            else:
                self.fail(f"unexpected forward: {forward}")

        self.assertEqual(seen_kinds, {"caution", "warning", "risk"})

    @patch("dart_risk_mcp.core.kind_client.requests.post")
    def test_one_kind_failure_keeps_the_others(self, mock_post):
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        fail_resp.text = ""

        def side_effect(url, data=None, headers=None, timeout=None):
            forward = data["forward"]
            if forward == "invstwarnisu_sub":
                return fail_resp
            if forward == "invstcautnisu_sub":
                return _fixture_response("caution_A032580_pidelix.html")
            return _fixture_response("risk_A032580_pidelix.html")

        mock_post.side_effect = side_effect

        result = fetch_market_alerts("032580", "20240101", "20260922")

        self.assertTrue(result["fetch_failed"])
        self.assertEqual(result["failed_kinds"], ["warning"])
        self.assertEqual(result["by_kind"]["warning"], 0)
        self.assertEqual(result["by_kind"]["caution"], 6)
        self.assertEqual(result["by_kind"]["risk"], 1)
        # 실패한 종류를 빼고 나머지는 alerts에 실린다
        self.assertEqual(len(result["alerts"]), 7)

    @patch("dart_risk_mcp.core.kind_client.requests.post")
    def test_cache_hit_skips_network(self, mock_post):
        mock_post.side_effect = [
            _fixture_response("caution_A032580_pidelix.html"),
            _fixture_response("warning_A032580_pidelix.html"),
            _fixture_response("risk_A032580_pidelix.html"),
        ]

        first = fetch_market_alerts("032580", "20240101", "20260922")
        self.assertEqual(mock_post.call_count, 3)

        second = fetch_market_alerts("032580", "20240101", "20260922")
        self.assertEqual(mock_post.call_count, 3)  # 추가 호출 없음
        self.assertEqual(first, second)

    @patch("dart_risk_mcp.core.kind_client.requests.post")
    def test_failed_result_is_not_cached(self, mock_post):
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        fail_resp.text = ""
        mock_post.return_value = fail_resp

        first = fetch_market_alerts("032580", "20240101", "20260922")
        self.assertTrue(first["fetch_failed"])
        self.assertEqual(mock_post.call_count, 3)

        # 캐시되지 않았으므로 다시 부르면 또 네트워크를 탄다
        second = fetch_market_alerts("032580", "20240101", "20260922")
        self.assertEqual(mock_post.call_count, 6)
        self.assertTrue(second["fetch_failed"])

    @patch("dart_risk_mcp.core.kind_client.requests.post")
    def test_window_over_3_years_is_clamped(self, mock_post):
        mock_post.side_effect = [
            _fixture_response("risk_A005930_samsung_empty.html"),
            _fixture_response("risk_A005930_samsung_empty.html"),
            _fixture_response("risk_A005930_samsung_empty.html"),
        ]

        result = fetch_market_alerts("005930", "20200101", "20260922")

        self.assertTrue(result["clamped"])
        self.assertIsNotNone(result["clamp_start"])
        self.assertLess(int(result["clamp_start"]), 20260922)

        # 실제로 보낸 startDate가 3년 미만 창으로 좁혀졌는지 확인
        first_call_form = mock_post.call_args_list[0].kwargs["data"]
        sent_start = first_call_form["startDate"].replace("-", "")
        from datetime import datetime as _dt

        span_days = (
            _dt.strptime("20260922", "%Y%m%d") - _dt.strptime(sent_start, "%Y%m%d")
        ).days
        self.assertLessEqual(span_days, KIND_MAX_WINDOW_DAYS)
        self.assertGreater(span_days, 1000)  # 클램프됐지만 여전히 3년 가까이

    @patch("dart_risk_mcp.core.kind_client.requests.post")
    def test_pagination_stops_when_total_covered(self, mock_post):
        # 1페이지 응답에 total=150을 실어 2페이지까지만 부르고 멈추는지 확인.
        page1_html = _load("caution_page1_size10.html").replace(
            "전체 <em>4,900</em>건", "전체 <em>150</em>건"
        )
        page2_html = _load("caution_A032580_pidelix.html").replace(
            "전체 <em>6</em>건", "전체 <em>150</em>건"
        )

        def side_effect(url, data=None, headers=None, timeout=None):
            resp = MagicMock()
            resp.status_code = 200
            resp.text = page1_html if data["pageIndex"] == "1" else page2_html
            return resp

        mock_post.side_effect = side_effect

        records, failed = kind_client._fetch_one_kind(
            "999999", "caution", "1", "invstcautnisu_sub", "2024-01-01", "2026-09-22"
        )

        self.assertFalse(failed)
        # 10건(1페이지) + 6건(2페이지) = 16건, 3페이지 요청은 없어야 한다(150<=200)
        self.assertEqual(len(records), 16)
        self.assertEqual(mock_post.call_count, 2)

    @patch("dart_risk_mcp.core.kind_client.requests.post")
    def test_pagination_capped_at_max_pages(self, mock_post):
        # total이 아주 커도 KIND_MAX_PAGES(3)를 넘겨 부르지 않는다.
        page_html = _load("caution_page1_size10.html").replace(
            "전체 <em>4,900</em>건", "전체 <em>1000</em>건"
        )

        resp = MagicMock()
        resp.status_code = 200
        resp.text = page_html
        mock_post.return_value = resp

        records, failed = kind_client._fetch_one_kind(
            "999999", "caution", "1", "invstcautnisu_sub", "2024-01-01", "2026-09-22"
        )

        self.assertFalse(failed)
        self.assertEqual(mock_post.call_count, kind_client.KIND_MAX_PAGES)


if __name__ == "__main__":
    unittest.main()
