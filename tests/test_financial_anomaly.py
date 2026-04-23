"""detect_financial_anomaly 순수 로직 검증 (v0.7.0 임계값 기준)."""
import unittest

from dart_risk_mcp.core.dart_client import detect_financial_anomaly


def _base(rev=1000, ar=100, inv=100, ocf=50, ni=50, eq=500, cap=100) -> dict:
    return {
        "매출액": rev,
        "매출채권": ar,
        "재고자산": inv,
        "영업활동현금흐름": ocf,
        "당기순이익": ni,
        "자본총계": eq,
        "자본금": cap,
    }


class TestDetectFinancialAnomaly(unittest.TestCase):
    def test_ar_surge_triggers_at_10pp(self):
        # 전기 AR/매출 = 100/1000 = 10%
        # 당기 AR/매출 = 210/1000 = 21% → Δ=11%p → FLAG
        cur = _base(ar=210)
        pri = _base(ar=100)
        flags, _ = detect_financial_anomaly(cur, pri)
        self.assertIn("AR_SURGE", flags)

        # 당기 AR/매출 = 190/1000 = 19% → Δ=9%p → NO FLAG
        cur2 = _base(ar=190)
        flags2, _ = detect_financial_anomaly(cur2, pri)
        self.assertNotIn("AR_SURGE", flags2)

    def test_ar_surge_missing_field_skips(self):
        cur = {"매출액": 1000}  # 매출채권 없음
        pri = _base()
        flags, metrics = detect_financial_anomaly(cur, pri)
        self.assertNotIn("AR_SURGE", flags)

    def test_inventory_surge_boundary(self):
        # 전기 INV/매출 = 100/1000 = 10%
        # 당기 INV/매출 = 210/1000 = 21% → Δ=11%p → FLAG
        cur = _base(inv=210)
        pri = _base(inv=100)
        flags, _ = detect_financial_anomaly(cur, pri)
        self.assertIn("INVENTORY_SURGE", flags)

        # 당기 INV/매출 = 190/1000 = 19% → Δ=9%p → NO FLAG (10%p 경계 잠금)
        cur2 = _base(inv=190)
        flags2, _ = detect_financial_anomaly(cur2, pri)
        self.assertNotIn("INVENTORY_SURGE", flags2)

    def test_cash_gap_profit_positive_cf_negative(self):
        cur = _base(ni=30, ocf=-5)
        pri = _base()
        flags, _ = detect_financial_anomaly(cur, pri)
        self.assertIn("CASH_GAP", flags)

    def test_cash_gap_both_positive_no_flag(self):
        cur = _base(ni=30, ocf=20)
        pri = _base()
        flags, _ = detect_financial_anomaly(cur, pri)
        self.assertNotIn("CASH_GAP", flags)

    def test_capital_impairment_below_200(self):
        # 자본총계 150 / 자본금 100 = 150% → 200% 미만 → FLAG
        cur = _base(eq=150, cap=100)
        pri = _base(eq=500, cap=100)
        flags, _ = detect_financial_anomaly(cur, pri)
        self.assertIn("CAPITAL_IMPAIRMENT", flags)

    def test_capital_impairment_at_boundary(self):
        # 자본총계 200 / 자본금 100 = 200% → strict < 200 → NO FLAG
        cur = _base(eq=200, cap=100)
        pri = _base(eq=500, cap=100)
        flags, _ = detect_financial_anomaly(cur, pri)
        self.assertNotIn("CAPITAL_IMPAIRMENT", flags)

    def test_account_name_fallback(self):
        # "영업수익"을 "매출액" 대체 명칭으로 인식
        # AR/매출 = 710/1000 = 71% (전기 20%) → Δ=51%p → FLAG (10%p 기준 충족)
        cur = {"영업수익": 1000, "매출채권": 710, "재고자산": 100,
               "영업활동현금흐름": 50, "당기순이익": 50, "자본총계": 500, "자본금": 100}
        pri = {"영업수익": 1000, "매출채권": 200, "재고자산": 100,
               "영업활동현금흐름": 50, "당기순이익": 50, "자본총계": 500, "자본금": 100}
        flags, _ = detect_financial_anomaly(cur, pri)
        self.assertIn("AR_SURGE", flags)


if __name__ == "__main__":
    unittest.main()
