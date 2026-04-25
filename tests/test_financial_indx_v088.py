"""v0.8.8 — fetch_company_indicators + detect_financial_anomaly prior_indx YoY.

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


if __name__ == "__main__":
    unittest.main()
