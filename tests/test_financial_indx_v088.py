"""v0.8.8 — fetch_company_indicators + detect_financial_anomaly prior_indx YoY.
v0.8.9(SE-4h) — fetch_indicator_history (분류 보존 + 다년 조회) 추가.

검증:
1. fetch_company_indicators는 4개 idx_cl_code(M210000·M220000·M230000·M240000)를
   각각 호출해 응답을 {idx_nm: float, ...} flat dict로 합친다.
2. idx_val=None / 숫자 변환 불가 항목은 dict에서 제외.
3. status≠000 응답은 조용히 스킵 (다른 cl_code는 정상 반영).
4. 빈 corp_code/api_key는 빈 dict.
5. detect_financial_anomaly에 current_indx/prior_indx 인자가 추가돼도
   기존 호출(인자 미지정)과 호환.
6. prior_indx가 있으면 metrics에 indx 기반 항목이 추가되며,
   YoY 변동률(delta_pct)이 계산되고 flagged=False 유지(절대 임계 없음).
7. fetch_indicator_history는 연도별·분류별 행 목록을 반환하며
   fetch_company_indicators는 완전히 무변경이다(플랫 dict 계약 유지).
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from dart_risk_mcp.core import dart_client


def _resp(status: str = "000", lst: list | None = None) -> MagicMock:
    r = MagicMock()
    r.json.return_value = {
        "status": status,
        "message": "정상" if status == "000" else "데이터 없음",
        "list": lst or [],
    }
    return r


def _make_indx_side(per_cl: dict[str, list]):
    """idx_cl_code → list[item] 매핑으로 _retry side_effect 생성."""

    def _side(method, url, **kwargs):
        if "fnlttSinglIndx" not in url:
            return _resp(status="013")
        cl = (kwargs.get("params") or {}).get("idx_cl_code")
        return _resp(lst=per_cl.get(cl, []))

    return _side


def _make_indx_history_side(per_year_cl: dict[str, dict[str, list]]):
    """(bsns_year, idx_cl_code) → list[item] 매핑으로 _retry side_effect 생성.

    per_year_cl에 없는 (year, cl) 조합은 status=000, 빈 list로 응답한다
    (다년 루프에서 매 연도·분류를 다 지정하지 않아도 되도록).
    """

    def _side(method, url, **kwargs):
        if "fnlttSinglIndx" not in url:
            return _resp(status="013")
        params = kwargs.get("params") or {}
        year = params.get("bsns_year")
        cl = params.get("idx_cl_code")
        year_map = per_year_cl.get(year)
        if year_map is None:
            return _resp(lst=[])
        return _resp(lst=year_map.get(cl, []))

    return _side


class TestFetchCompanyIndicators(unittest.TestCase):
    def setUp(self):
        cache = getattr(dart_client, "_company_indicators_cache", None)
        if cache is not None:
            cache.clear()

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_merges_four_idx_cl_codes(self, mock_retry):
        mock_retry.side_effect = _make_indx_side({
            "M210000": [{"idx_nm": "순이익률", "idx_val": "11.775"}],
            "M220000": [{"idx_nm": "자기자본비율", "idx_val": "83.495"},
                         {"idx_nm": "부채비율", "idx_val": "19.768"}],
            "M230000": [{"idx_nm": "매출액증가율(YoY)", "idx_val": "63.447"}],
            "M240000": [{"idx_nm": "매출채권회전율", "idx_val": "8.1"},
                         {"idx_nm": "재고자산회전율", "idx_val": "122.567"}],
        })
        result = dart_client.fetch_company_indicators(
            "00413046", "KEY", "2024", "11011"
        )
        self.assertEqual(result["순이익률"], 11.775)
        self.assertEqual(result["자기자본비율"], 83.495)
        self.assertAlmostEqual(result["부채비율"], 19.768, places=3)
        self.assertEqual(result["매출액증가율(YoY)"], 63.447)
        self.assertEqual(result["매출채권회전율"], 8.1)
        self.assertEqual(result["재고자산회전율"], 122.567)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_skips_none_and_unparseable_values(self, mock_retry):
        mock_retry.side_effect = _make_indx_side({
            "M240000": [
                {"idx_nm": "매출채권회전율", "idx_val": None},
                {"idx_nm": "총자산회전율", "idx_val": ""},
                {"idx_nm": "재고자산회전율", "idx_val": "abc"},
                {"idx_nm": "정상값", "idx_val": "12.34"},
            ],
        })
        result = dart_client.fetch_company_indicators(
            "00413046", "KEY", "2024", "11011"
        )
        self.assertNotIn("매출채권회전율", result)
        self.assertNotIn("총자산회전율", result)
        self.assertNotIn("재고자산회전율", result)
        self.assertEqual(result["정상값"], 12.34)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_partial_cl_code_failure_isolated(self, mock_retry):
        def _side(method, url, **kwargs):
            cl = (kwargs.get("params") or {}).get("idx_cl_code")
            if cl == "M210000":
                return _resp(lst=[{"idx_nm": "순이익률", "idx_val": "5.0"}])
            if cl == "M220000":
                return _resp(status="013")  # 데이터 없음
            if cl == "M230000":
                raise RuntimeError("network err")
            return _resp(status="000", lst=[])

        mock_retry.side_effect = _side
        result = dart_client.fetch_company_indicators(
            "00413046", "KEY", "2024", "11011"
        )
        # 성공한 항목만 반영
        self.assertEqual(result.get("순이익률"), 5.0)
        # 다른 카테고리 항목 없음

    def test_rejects_empty_inputs(self):
        self.assertEqual(
            dart_client.fetch_company_indicators("", "KEY", "2024", "11011"), {}
        )
        self.assertEqual(
            dart_client.fetch_company_indicators("X", "", "2024", "11011"), {}
        )


class TestDetectFinancialAnomalyWithIndx(unittest.TestCase):
    def test_backward_compatible_without_indx(self):
        """기존 호출(인자 2개)은 그대로 동작."""
        current = {"매출액": 1000, "매출채권": 100, "재고자산": 50,
                   "당기순이익": 80, "영업활동현금흐름": 70,
                   "자본총계": 500, "자본금": 100}
        prior = {"매출액": 900, "매출채권": 80, "재고자산": 40,
                 "당기순이익": 60, "영업활동현금흐름": 50,
                 "자본총계": 480, "자본금": 100}
        flags, metrics = dart_client.detect_financial_anomaly(current, prior)
        self.assertIsInstance(flags, list)
        self.assertIsInstance(metrics, list)
        # indx 항목은 추가되지 않음
        for m in metrics:
            self.assertNotIn("delta_pct", m)

    def test_appends_indx_metrics_when_provided(self):
        current = {"매출액": 1000, "매출채권": 100,
                   "당기순이익": 80, "영업활동현금흐름": 70,
                   "자본총계": 500, "자본금": 100}
        prior = {"매출액": 900, "매출채권": 80,
                 "당기순이익": 60, "영업활동현금흐름": 50,
                 "자본총계": 480, "자본금": 100}
        current_indx = {"매출채권회전율": 8.1, "자기자본비율": 80.0, "순이익률": 8.0}
        prior_indx = {"매출채권회전율": 12.3, "자기자본비율": 78.0, "순이익률": 6.7}
        flags, metrics = dart_client.detect_financial_anomaly(
            current, prior,
            current_indx=current_indx, prior_indx=prior_indx,
        )
        indx_metrics = [m for m in metrics if m.get("source") == "indx"]
        self.assertGreaterEqual(len(indx_metrics), 1)
        # 매출채권회전율: 8.1 vs 12.3 → -34.1% YoY
        ar_turnover = next(m for m in indx_metrics if m["name"] == "매출채권회전율")
        self.assertAlmostEqual(ar_turnover["current"], 8.1, places=2)
        self.assertAlmostEqual(ar_turnover["prior"], 12.3, places=2)
        self.assertLess(ar_turnover["delta_pct"], 0)
        self.assertAlmostEqual(ar_turnover["delta_pct"], (8.1 - 12.3) / 12.3 * 100, places=2)
        self.assertFalse(ar_turnover.get("flagged", False),
                         "indx 항목은 절대 임계 없이 사실 표기만")

    def test_handles_missing_prior_indx_value(self):
        current_indx = {"매출채권회전율": 8.1}
        prior_indx = {}  # 비어있음
        flags, metrics = dart_client.detect_financial_anomaly(
            {}, {}, current_indx=current_indx, prior_indx=prior_indx,
        )
        indx_metrics = [m for m in metrics if m.get("source") == "indx"]
        # 전기 데이터가 없으면 YoY 계산 불가 → 항목 자체 스킵
        self.assertEqual(indx_metrics, [])

    def test_zero_prior_avoids_div_zero(self):
        current_indx = {"매출액증가율(YoY)": 30.0}
        prior_indx = {"매출액증가율(YoY)": 0.0}
        flags, metrics = dart_client.detect_financial_anomaly(
            {}, {}, current_indx=current_indx, prior_indx=prior_indx,
        )
        # 분모 0 처리: delta_pct = None 또는 표기 다름. 단, 예외 없이 반환.
        # metric 자체는 존재하되 delta_pct가 None인지 확인.
        indx_metrics = [m for m in metrics if m.get("source") == "indx"]
        for m in indx_metrics:
            if m["name"] == "매출액증가율(YoY)":
                self.assertIsNone(m.get("delta_pct"))


class TestFetchCompanyIndicatorsUnchanged(unittest.TestCase):
    """fetch_indicator_history 추가가 fetch_company_indicators에 영향 없음을 증명.

    scan_financial_anomaly가 이 함수를 그대로 쓴다. 같은 입력에 대해
    이전과 동일한 평평한 dict를 반환해야 하며(분류 키가 섞이지 않음),
    이것이 MCP 도구 무영향의 증거다(SE-4h Task 1).
    """

    def setUp(self):
        cache = getattr(dart_client, "_company_indicators_cache", None)
        if cache is not None:
            cache.clear()

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_flat_dict_contract_unchanged(self, mock_retry):
        mock_retry.side_effect = _make_indx_side({
            "M210000": [{"idx_nm": "순이익률", "idx_val": "-22.56"}],
            "M220000": [{"idx_nm": "부채비율", "idx_val": "130.248"}],
            "M230000": [{"idx_nm": "매출액증가율(YoY)", "idx_val": "-14.469"}],
            "M240000": [{"idx_nm": "매출채권회전율", "idx_val": "8.1"}],
        })
        result = dart_client.fetch_company_indicators(
            "01011526", "KEY", "2025", "11011"
        )
        self.assertEqual(result, {
            "순이익률": -22.56,
            "부채비율": 130.248,
            "매출액증가율(YoY)": -14.469,
            "매출채권회전율": 8.1,
        })
        self.assertIsInstance(result, dict)
        for v in result.values():
            self.assertIsInstance(v, float)


class TestFetchIndicatorHistory(unittest.TestCase):
    """fetch_indicator_history — 연도별·분류 보존 다년 조회 (SE-4h Task 1)."""

    def setUp(self):
        cache = getattr(dart_client, "_indicator_history_cache", None)
        if cache is not None:
            cache.clear()
        self._year_patch = patch(
            "dart_risk_mcp.core.dart_client._previous_business_year",
            return_value=2025,
        )
        self._year_patch.start()
        self.addCleanup(self._year_patch.stop)
        # 일시적 실패 재시도(_fetch_indx_page)가 실제로 1초·2초 잠들면 이
        # 클래스가 수십 초로 늘어난다. 잠은 검증 대상이 아니다.
        self._sleep_patch = patch("time.sleep")
        self.mock_sleep = self._sleep_patch.start()
        self.addCleanup(self._sleep_patch.stop)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_rows_have_four_keys(self, mock_retry):
        mock_retry.side_effect = _make_indx_history_side({
            "2025": {"M210000": [{"idx_nm": "순이익률", "idx_cl_nm": "수익성",
                                    "idx_val": "-22.56"}]},
        })
        rows = dart_client.fetch_indicator_history("01011526", "KEY", 1)["rows"]
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(
                set(row.keys()), {"bsns_year", "category", "idx_nm", "idx_val"}
            )

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_lookback_years_1_still_fetches_three_years(self, mock_retry):
        mock_retry.side_effect = _make_indx_history_side({
            "2025": {"M210000": [{"idx_nm": "순이익률", "idx_cl_nm": "수익성",
                                    "idx_val": "-22.56"}]},
            "2024": {"M210000": [{"idx_nm": "순이익률", "idx_cl_nm": "수익성",
                                    "idx_val": "-152.661"}]},
            "2023": {"M210000": [{"idx_nm": "순이익률", "idx_cl_nm": "수익성",
                                    "idx_val": "1.0"}]},
        })
        rows = dart_client.fetch_indicator_history("01011526", "KEY", 1)["rows"]
        years = {row["bsns_year"] for row in rows}
        self.assertEqual(years, {"2025", "2024", "2023"})

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_lookback_years_5_fetches_five_years(self, mock_retry):
        per_year = {
            str(y): {"M210000": [{"idx_nm": "순이익률", "idx_cl_nm": "수익성",
                                    "idx_val": "1.0"}]}
            for y in range(2021, 2026)
        }
        mock_retry.side_effect = _make_indx_history_side(per_year)
        rows = dart_client.fetch_indicator_history("01011526", "KEY", 5)["rows"]
        years = {row["bsns_year"] for row in rows}
        self.assertEqual(years, {"2021", "2022", "2023", "2024", "2025"})

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_lookback_years_99_capped_at_five(self, mock_retry):
        per_year = {
            str(y): {"M210000": [{"idx_nm": "순이익률", "idx_cl_nm": "수익성",
                                    "idx_val": "1.0"}]}
            for y in range(2015, 2026)
        }
        mock_retry.side_effect = _make_indx_history_side(per_year)
        rows = dart_client.fetch_indicator_history("01011526", "KEY", 99)["rows"]
        years = {row["bsns_year"] for row in rows}
        self.assertEqual(len(years), 5)
        self.assertEqual(years, {"2021", "2022", "2023", "2024", "2025"})

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_missing_idx_val_key_becomes_none_no_keyerror(self, mock_retry):
        # 엔켐 실측 사례: idx_val 키 자체가 없는 레코드.
        mock_retry.side_effect = _make_indx_history_side({
            "2025": {"M210000": [{"idx_nm": "세전계속사업이익률", "idx_cl_nm": "수익성"}]},
        })
        rows = dart_client.fetch_indicator_history("01011526", "KEY", 1)["rows"]
        target = [r for r in rows if r["idx_nm"] == "세전계속사업이익률"]
        self.assertEqual(len(target), 1)
        self.assertIsNone(target[0]["idx_val"])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_empty_or_nonnumeric_idx_val_becomes_none(self, mock_retry):
        mock_retry.side_effect = _make_indx_history_side({
            "2025": {"M210000": [
                {"idx_nm": "빈값", "idx_cl_nm": "수익성", "idx_val": ""},
                {"idx_nm": "문자값", "idx_cl_nm": "수익성", "idx_val": "abc"},
                {"idx_nm": "정상값", "idx_cl_nm": "수익성", "idx_val": "12.34"},
            ]},
        })
        rows = dart_client.fetch_indicator_history("01011526", "KEY", 1)["rows"]
        by_name = {r["idx_nm"]: r["idx_val"] for r in rows if r["bsns_year"] == "2025"}
        self.assertIsNone(by_name["빈값"])
        self.assertIsNone(by_name["문자값"])
        self.assertEqual(by_name["정상값"], 12.34)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_category_filled_from_idx_cl_nm(self, mock_retry):
        mock_retry.side_effect = _make_indx_history_side({
            "2025": {
                "M210000": [{"idx_nm": "순이익률", "idx_cl_nm": "수익성", "idx_val": "1.0"}],
                "M220000": [{"idx_nm": "부채비율", "idx_cl_nm": "안정성", "idx_val": "130.2"}],
            },
        })
        rows = dart_client.fetch_indicator_history("01011526", "KEY", 1)["rows"]
        by_name = {r["idx_nm"]: r["category"] for r in rows if r["bsns_year"] == "2025"}
        self.assertEqual(by_name["순이익률"], "수익성")
        self.assertEqual(by_name["부채비율"], "안정성")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_category_falls_back_to_idx_cl_code_then_gita(self, mock_retry):
        def _side(method, url, **kwargs):
            if "fnlttSinglIndx" not in url:
                return _resp(status="013")
            params = kwargs.get("params") or {}
            cl = params.get("idx_cl_code")
            if cl != "M210000":
                return _resp(lst=[])
            return _resp(lst=[
                # idx_cl_nm 은 없고 code 만 있다 → code 로 폴백해야 한다.
                # 이 행이 없으면 폴백을 통째로 지워도 테스트가 통과한다
                # (아래 "기타" 행만으로는 code 분기가 실행되지 않는다).
                {"idx_nm": "코드만있음", "idx_cl_code": "M210000", "idx_val": "2.0"},
                {"idx_nm": "이름만있음", "idx_val": "1.0"},  # idx_cl_nm/code 둘 다 없음
            ])

        mock_retry.side_effect = _side
        rows = dart_client.fetch_indicator_history("01011526", "KEY", 1)["rows"]
        by_name = {
            r["idx_nm"]: r["category"] for r in rows if r["bsns_year"] == "2025"
        }
        self.assertEqual(by_name["코드만있음"], "M210000")
        self.assertEqual(by_name["이름만있음"], "기타")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_one_year_failure_does_not_abort_others(self, mock_retry):
        def _side(method, url, **kwargs):
            if "fnlttSinglIndx" not in url:
                return _resp(status="013")
            params = kwargs.get("params") or {}
            year = params.get("bsns_year")
            if year == "2024":
                raise RuntimeError("network err")
            if year == "2025":
                return _resp(lst=[{"idx_nm": "순이익률", "idx_cl_nm": "수익성",
                                    "idx_val": "1.0"}])
            if year == "2023":
                return _resp(lst=[{"idx_nm": "순이익률", "idx_cl_nm": "수익성",
                                    "idx_val": "2.0"}])
            return _resp(lst=[])

        mock_retry.side_effect = _side
        result = dart_client.fetch_indicator_history("01011526", "KEY", 1)
        years_present = {row["bsns_year"] for row in result["rows"]}
        self.assertIn("2025", years_present)
        self.assertIn("2023", years_present)
        self.assertNotIn("2024", years_present)
        # 그리고 그 사실이 값으로 남아야 한다 — 빠진 해가 조용히 사라지면
        # 화면은 점 두 개짜리 "추이"를 아무 설명 없이 그린다.
        self.assertEqual(result["years_failed"], ["2024"])
        self.assertEqual(result["years_retrieved"], ["2025", "2023"])

    def test_rejects_empty_inputs(self):
        empty = {"years_requested": [], "years_retrieved": [],
                 "years_failed": [], "rows": []}
        self.assertEqual(dart_client.fetch_indicator_history("", "KEY", 1), empty)
        self.assertEqual(dart_client.fetch_indicator_history("X", "", 1), empty)


class TestIndicatorHistoryYearAccounting(unittest.TestCase):
    """어느 연도가 실제로 조회됐는지를 값으로 돌려준다 (SE-4h 최종 수정).

    리뷰가 라이브에서 관측한 증상: 같은 회사·같은 인자인데 첫 호출은 66행
    (2025년만), 이후 호출은 198행(3개 연도). 12콜 버스트 중 일부가 실패하면
    그 해가 통째로 사라지는데, 예전 구현은 debug 로그만 남기고 행 목록만
    돌려줘 화면이 "조회 실패"와 "그 회사에 자료가 없음"을 구분할 수 없었다.
    """

    def setUp(self):
        cache = getattr(dart_client, "_indicator_history_cache", None)
        if cache is not None:
            cache.clear()
        self._year_patch = patch(
            "dart_risk_mcp.core.dart_client._previous_business_year",
            return_value=2025,
        )
        self._year_patch.start()
        self.addCleanup(self._year_patch.stop)
        self._sleep_patch = patch("time.sleep")
        self.mock_sleep = self._sleep_patch.start()
        self.addCleanup(self._sleep_patch.stop)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_all_years_retrieved_reports_no_gap(self, mock_retry):
        mock_retry.side_effect = _make_indx_history_side({
            str(y): {"M210000": [{"idx_nm": "순이익률", "idx_cl_nm": "수익성지표",
                                  "idx_val": "1.0"}]}
            for y in (2023, 2024, 2025)
        })
        result = dart_client.fetch_indicator_history("01011526", "KEY", 1)
        self.assertEqual(result["years_requested"], ["2025", "2024", "2023"])
        self.assertEqual(result["years_retrieved"], ["2025", "2024", "2023"])
        self.assertEqual(result["years_failed"], [])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_status_013_year_is_absent_not_failed(self, mock_retry):
        """013(데이터 없음)은 확정 답변이다 — 조회 실패로 적으면 거짓말이 된다."""

        def _side(method, url, **kwargs):
            if "fnlttSinglIndx" not in url:
                return _resp(status="013")
            year = (kwargs.get("params") or {}).get("bsns_year")
            if year != "2025":
                return _resp(status="013")
            return _resp(lst=[{"idx_nm": "순이익률", "idx_cl_nm": "수익성지표",
                               "idx_val": "1.0"}])

        mock_retry.side_effect = _side
        result = dart_client.fetch_indicator_history("01011526", "KEY", 1)
        self.assertEqual(result["years_retrieved"], ["2025"])
        self.assertEqual(result["years_failed"], [])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_transient_status_020_is_retried_and_can_succeed(self, mock_retry):
        """HTTP 200 + status 020은 예외도 5xx도 아니라 _retry가 절대 다시
        시도하지 않는다. 그 재시도를 이 함수가 직접 책임진다."""
        calls = {"n": 0}

        def _side(method, url, **kwargs):
            if "fnlttSinglIndx" not in url:
                return _resp(status="013")
            calls["n"] += 1
            if calls["n"] == 1:  # 첫 호출만 스로틀
                return _resp(status="020")
            return _resp(lst=[{"idx_nm": "순이익률", "idx_cl_nm": "수익성지표",
                               "idx_val": "1.0"}])

        mock_retry.side_effect = _side
        result = dart_client.fetch_indicator_history("01011526", "KEY", 1)
        # 재시도가 성공했으므로 실패 연도는 없어야 한다.
        self.assertEqual(result["years_failed"], [])
        self.assertEqual(result["years_retrieved"], ["2025", "2024", "2023"])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_permanent_status_is_not_retried(self, mock_retry):
        """900(키 오류)은 몇 번을 물어도 같은 답이다 — 쿼터만 태운다."""
        seen = []

        def _side(method, url, **kwargs):
            if "fnlttSinglIndx" not in url:
                return _resp(status="013")
            seen.append((kwargs.get("params") or {}).get("bsns_year"))
            return _resp(status="900")

        mock_retry.side_effect = _side
        result = dart_client.fetch_indicator_history("01011526", "KEY", 1)
        # 3개 연도 × 4분류 = 12콜. 재시도했다면 그보다 많아진다.
        self.assertEqual(len(seen), 12)
        self.assertEqual(result["years_failed"], ["2025", "2024", "2023"])
        self.assertEqual(result["years_retrieved"], [])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_failed_result_is_not_cached(self, mock_retry):
        """일시적 사고를 10분 캐시에 굳히면 다시 눌러도 같은 반쪽 화면이다."""
        state = {"fail": True}

        def _side(method, url, **kwargs):
            if "fnlttSinglIndx" not in url:
                return _resp(status="013")
            year = (kwargs.get("params") or {}).get("bsns_year")
            if year == "2024" and state["fail"]:
                return _resp(status="800")
            return _resp(lst=[{"idx_nm": "순이익률", "idx_cl_nm": "수익성지표",
                               "idx_val": "1.0"}])

        mock_retry.side_effect = _side
        first = dart_client.fetch_indicator_history("01011526", "KEY", 1)
        self.assertEqual(first["years_failed"], ["2024"])

        state["fail"] = False
        second = dart_client.fetch_indicator_history("01011526", "KEY", 1)
        self.assertEqual(second["years_failed"], [])
        self.assertEqual(second["years_retrieved"], ["2025", "2024", "2023"])


if __name__ == "__main__":
    unittest.main()
