"""detect_financial_anomaly 순수 로직 검증."""
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
    def test_ar_surge_triggers_at_50pp(self):
        # 전기 20% → 당기 71% → Δ=51%p → flag
        cur = _base(ar=710)
        pri = _base(ar=200)
        flags, _ = detect_financial_anomaly(cur, pri)
        self.assertIn("AR_SURGE", flags)
        # 49%p boundary: 당기 69% → Δ=49%p → no flag
        cur2 = _base(ar=690)
        flags2, _ = detect_financial_anomaly(cur2, pri)
        self.assertNotIn("AR_SURGE", flags2)

    def test_ar_surge_missing_field_skips(self):
        cur = {"매출액": 1000}  # 매출채권 없음
        pri = _base()
        flags, metrics = detect_financial_anomaly(cur, pri)
        self.assertNotIn("AR_SURGE", flags)

    def test_inventory_surge_boundary(self):
        # 전기 10% → 당기 70% → Δ=60%p → flag
        cur = _base(inv=700)
        pri = _base(inv=100)
        flags, _ = detect_financial_anomaly(cur, pri)
        self.assertIn("INVENTORY_SURGE", flags)

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

    def test_capital_impairment_below_50(self):
        # 자본총계 40 / 자본금 100 = 40% → flag
        cur = _base(eq=40)
        pri = _base(eq=60)
        flags, _ = detect_financial_anomaly(cur, pri)
        self.assertIn("CAPITAL_IMPAIRMENT", flags)

    def test_capital_impairment_at_boundary(self):
        # 자본총계 50 / 자본금 100 = 50% → no flag (strict <)
        cur = _base(eq=50)
        pri = _base(eq=60)
        flags, _ = detect_financial_anomaly(cur, pri)
        self.assertNotIn("CAPITAL_IMPAIRMENT", flags)

    def test_account_name_fallback(self):
        # "영업수익"을 "매출액" 대체 명칭으로 인식
        cur = {"영업수익": 1000, "매출채권": 710, "재고자산": 100,
               "영업활동현금흐름": 50, "당기순이익": 50, "자본총계": 500, "자본금": 100}
        pri = {"영업수익": 1000, "매출채권": 200, "재고자산": 100,
               "영업활동현금흐름": 50, "당기순이익": 50, "자본총계": 500, "자본금": 100}
        flags, _ = detect_financial_anomaly(cur, pri)
        self.assertIn("AR_SURGE", flags)


if __name__ == "__main__":
    unittest.main()
