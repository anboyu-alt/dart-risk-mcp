"""v0.5.0 신규 신호 키 정의·매핑 검증."""
import unittest

from dart_risk_mcp.core.signals import (
    SIGNAL_TYPES,
    SIGNAL_KEY_TO_TAXONOMY,
)


NEW_KEYS = [
    "FUND_DIVERSION",
    "FUND_UNREPORTED",
    "DECISION_RELATED_PARTY",
    "DECISION_OVERSIZED",
    "DECISION_NO_EXTVAL",
]


class TestNewSignalKeys(unittest.TestCase):
    def test_all_new_keys_registered_in_signal_types(self):
        keys = {s["key"] for s in SIGNAL_TYPES}
        for k in NEW_KEYS:
            self.assertIn(k, keys, f"{k} missing from SIGNAL_TYPES")

    def test_all_new_keys_have_taxonomy_mapping(self):
        for k in NEW_KEYS:
            self.assertIn(k, SIGNAL_KEY_TO_TAXONOMY, f"{k} missing mapping")
            self.assertTrue(
                SIGNAL_KEY_TO_TAXONOMY[k],
                f"{k} mapping empty",
            )

    def test_signal_types_have_label_and_score(self):
        for s in SIGNAL_TYPES:
            if s["key"] in NEW_KEYS:
                self.assertIn("label", s)
                self.assertIn("score", s)
                self.assertIsInstance(s["score"], int)
                self.assertGreater(s["score"], 0)


if __name__ == "__main__":
    unittest.main()
