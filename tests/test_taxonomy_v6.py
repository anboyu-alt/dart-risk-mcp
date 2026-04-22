"""v0.6.0 taxonomy·패턴 등록 검증."""
import unittest

from dart_risk_mcp.core.taxonomy import TAXONOMY, CROSS_SIGNAL_PATTERNS


class TestV6Taxonomy(unittest.TestCase):
    def test_2_7_exists(self):
        self.assertIn("2.7", TAXONOMY)
        entry = TAXONOMY["2.7"]
        self.assertEqual(entry["label"], "자본 이벤트 과다 반복")
        self.assertEqual(entry["severity"], "HIGH")

    def test_capital_churn_pattern_registered(self):
        names = {p["name"] for p in CROSS_SIGNAL_PATTERNS.values()}
        self.assertIn("capital_churn_anomaly", names)


if __name__ == "__main__":
    unittest.main()
