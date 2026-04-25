"""v0.6.0 신호 키 등록 검증."""
import unittest

from dart_risk_mcp.core.signals import (
    SIGNAL_TYPES,
    SIGNAL_KEY_TO_TAXONOMY,
    CAPITAL_EVENT_KEYS,
)


NEW_KEYS = ["CAPITAL_CHURN", "AR_SURGE", "INVENTORY_SURGE", "CASH_GAP", "CAPITAL_IMPAIRMENT"]


class TestV6Signals(unittest.TestCase):
    def test_new_keys_in_signal_types(self):
        keys = {s["key"] for s in SIGNAL_TYPES}
        for k in NEW_KEYS:
            self.assertIn(k, keys, f"{k} missing in SIGNAL_TYPES")

    def test_new_keys_have_taxonomy(self):
        for k in NEW_KEYS:
            self.assertIn(k, SIGNAL_KEY_TO_TAXONOMY, f"{k} missing in SIGNAL_KEY_TO_TAXONOMY")

    def test_capital_event_keys_is_frozen_set(self):
        self.assertIsInstance(CAPITAL_EVENT_KEYS, (set, frozenset))
        expected = {"3PCA", "RIGHTS_UNDER", "GAMJA_MERGE", "REVERSE_SPLIT",
                    "TREASURY", "CB_BW", "EB", "RCPS", "TREASURY_EB",
                    "CB_ROLLOVER", "CB_BUYBACK",
                    # v0.8.7: 자사주 신탁계약 (비희석성)
                    "TREASURY_TRUST"}
        self.assertEqual(CAPITAL_EVENT_KEYS, expected)


if __name__ == "__main__":
    unittest.main()
