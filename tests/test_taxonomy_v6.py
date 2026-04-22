"""v0.6.0 taxonomy·패턴 등록 검증."""
import unittest

from dart_risk_mcp.core.taxonomy import TAXONOMY, CROSS_SIGNAL_PATTERNS


class TestV6Taxonomy(unittest.TestCase):
    def test_2_7_exists(self):
        self.assertIn("2.7", TAXONOMY)
        entry = TAXONOMY["2.7"]
        self.assertEqual(entry["name"], "자본 이벤트 과다 반복")
        self.assertEqual(entry["severity"], "HIGH")

    def test_capital_churn_pattern_registered(self):
        names = {p["name"] for p in CROSS_SIGNAL_PATTERNS.values()}
        self.assertIn("capital_churn_anomaly", names)


class TestV61PatternExtensions(unittest.TestCase):
    """v0.6.1: zombie_ma, delisting_evasion 패턴에 v0.6.0 신호 연동."""

    def test_zombie_ma_includes_capital_churn(self):
        from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS
        self.assertIn("2.7", CROSS_SIGNAL_PATTERNS["zombie_ma"]["signal_sequence"])

    def test_delisting_evasion_includes_capital_churn_and_impairment(self):
        from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS
        seq = CROSS_SIGNAL_PATTERNS["delisting_evasion"]["signal_sequence"]
        self.assertIn("2.7", seq)
        self.assertIn("8.2", seq)


if __name__ == "__main__":
    unittest.main()
