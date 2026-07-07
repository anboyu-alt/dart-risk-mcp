"""전기 재작성 감지 + 영업/순이익 방향 괴리 (PR-6) 테스트."""
import unittest

from dart_risk_mcp.core.dart_client import (
    detect_profit_direction_divergence,
    detect_restatement,
)
from dart_risk_mcp.core.explain import flag_to_prose


class TestProfitDirectionDivergence(unittest.TestCase):
    def test_pos_neg_flagged(self):
        # 영업흑자 + 순손실 → 영업외 손실
        flags, metrics = detect_profit_direction_divergence(
            {"영업이익": 100, "당기순이익": -50})
        self.assertEqual(flags, ["OPNET_POS_NEG"])
        self.assertTrue(metrics[0]["flagged"])
        self.assertEqual(metrics[0]["flag_key"], "OPNET_POS_NEG")

    def test_neg_pos_flagged(self):
        # 영업적자 + 순이익 흑자 → 일회성 이익 의심 (역방향 확장)
        flags, _ = detect_profit_direction_divergence(
            {"영업이익": -100, "당기순이익": 50})
        self.assertEqual(flags, ["OPNET_NEG_POS"])

    def test_same_direction_not_flagged(self):
        for cur in ({"영업이익": 100, "당기순이익": 50},
                    {"영업이익": -100, "당기순이익": -50}):
            flags, metrics = detect_profit_direction_divergence(cur)
            self.assertEqual(flags, [])
            self.assertFalse(metrics[0]["flagged"])  # 지표 행은 항상 표기

    def test_zero_not_flagged(self):
        flags, _ = detect_profit_direction_divergence(
            {"영업이익": 0, "당기순이익": -50})
        self.assertEqual(flags, [])

    def test_missing_accounts_no_metric(self):
        flags, metrics = detect_profit_direction_divergence({"매출액": 100})
        self.assertEqual((flags, metrics), ([], []))

    def test_alias_variant(self):
        flags, _ = detect_profit_direction_divergence(
            {"영업이익(손실)": 100, "당기순이익(손실)": -50})
        self.assertEqual(flags, ["OPNET_POS_NEG"])

    def test_prose(self):
        for key in ("OPNET_POS_NEG", "OPNET_NEG_POS"):
            title, body = flag_to_prose(key, {"current_op": 100, "current_ni": -50})
            self.assertTrue(title)
            self.assertIn("100", body)


def _row(fs_div, nm, thstrm, frmtrm=None):
    return {"fs_div": fs_div, "account_nm": nm,
            "thstrm_amount": thstrm, "frmtrm_amount": frmtrm}


class TestDetectRestatement(unittest.TestCase):
    def test_no_restatement_when_consistent(self):
        cur = [_row("CFS", "매출액", "2,000", "1,000")]
        pri = [_row("CFS", "매출액", "1,000")]
        self.assertEqual(detect_restatement(cur, pri), [])

    def test_restatement_detected(self):
        # 작년 보고 당기 1,000 → 올해 보고 전기 800 (-20%)
        cur = [_row("CFS", "매출액", "2,000", "800"),
               _row("CFS", "당기순이익(손실)", "50", "100")]
        pri = [_row("CFS", "매출액", "1,000"),
               _row("CFS", "당기순이익(손실)", "100")]
        hits = detect_restatement(cur, pri)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["account"], "매출액")
        self.assertEqual(hits[0]["prior_reported"], 1000)
        self.assertEqual(hits[0]["restated"], 800)
        self.assertAlmostEqual(hits[0]["diff_pct"], -20.0)

    def test_tolerance_filters_rounding(self):
        # 0.5% 이내 차이(단위 반올림)는 무시
        cur = [_row("OFS", "자산총계", "999", "1,003")]
        pri = [_row("OFS", "자산총계", "1,000")]
        self.assertEqual(detect_restatement(cur, pri), [])

    def test_fs_div_isolated(self):
        # CFS 전기값 vs OFS 당기값은 비교하지 않음
        cur = [_row("CFS", "매출액", "2,000", "800")]
        pri = [_row("OFS", "매출액", "1,000")]
        self.assertEqual(detect_restatement(cur, pri), [])

    def test_sorted_by_magnitude(self):
        cur = [_row("CFS", "매출액", "0", "900"),
               _row("CFS", "자산총계", "0", "500")]
        pri = [_row("CFS", "매출액", "1,000"),
               _row("CFS", "자산총계", "1,000")]
        hits = detect_restatement(cur, pri)
        self.assertEqual([h["account"] for h in hits], ["자산총계", "매출액"])

    def test_zero_to_nonzero(self):
        cur = [_row("CFS", "부채총계", "10", "500")]
        pri = [_row("CFS", "부채총계", "0")]
        hits = detect_restatement(cur, pri)
        self.assertEqual(len(hits), 1)
        self.assertIsNone(hits[0]["diff_pct"])

    def test_empty_inputs(self):
        self.assertEqual(detect_restatement([], []), [])
        self.assertEqual(detect_restatement(None, None), [])

    def test_prose(self):
        title, body = flag_to_prose("RESTATEMENT", {
            "details": [{"fs_div": "CFS", "account": "매출액",
                         "prior_reported": 1000, "restated": 800, "diff_pct": -20.0}],
        })
        self.assertIn("재작성", title + body)
        # fs_div는 한국어 라벨로 렌더 (hygiene: 괄호 영문 코드 금지)
        self.assertIn("매출액(연결) -20.0%", body)


if __name__ == "__main__":
    unittest.main()
