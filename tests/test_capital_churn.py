"""detect_capital_churn 순수 로직 검증."""
import unittest

from dart_risk_mcp.core.dart_client import detect_capital_churn


def _ev(key: str, dt: str, is_amendment: bool = False) -> dict:
    return {
        "key": key,
        "rcept_dt": dt,
        "report_nm": "",
        "is_amendment": is_amendment,
        "score": 5,
        "label": "",
    }


class TestDetectCapitalChurn(unittest.TestCase):
    def test_empty_events_returns_no_flag(self):
        r = detect_capital_churn([], 3)
        self.assertEqual(r["flags"], [])
        self.assertEqual(r["total_events"], 0)
        self.assertEqual(r["max_12m_count"], 0)

    def test_two_events_12m_no_flag(self):
        evs = [_ev("3PCA", "20250101"), _ev("CB_BW", "20250501")]
        r = detect_capital_churn(evs, 3)
        self.assertEqual(r["total_events"], 2)
        self.assertNotIn("CAPITAL_CHURN", r["flags"])
        self.assertEqual(r["max_12m_count"], 2)

    def test_three_events_12m_triggers_flag(self):
        evs = [_ev("3PCA", "20250101"), _ev("CB_BW", "20250501"), _ev("TREASURY", "20251001")]
        r = detect_capital_churn(evs, 3)
        self.assertIn("CAPITAL_CHURN", r["flags"])
        self.assertEqual(r["max_12m_count"], 3)

    def test_events_spread_over_24m_no_flag(self):
        # 이벤트를 366일 이상 간격으로 배치: 어떤 365일 윈도우에도 2건까지만
        evs = [
            _ev("3PCA", "20240101"),
            _ev("3PCA", "20250201"),   # 396일 후
            _ev("3PCA", "20260301"),   # 독립 윈도우
        ]
        r = detect_capital_churn(evs, 3)
        self.assertLessEqual(r["max_12m_count"], 2)
        self.assertNotIn("CAPITAL_CHURN", r["flags"])

    def test_amendment_excluded(self):
        evs = [
            _ev("3PCA", "20250101"),
            _ev("CB_BW", "20250501"),
            _ev("TREASURY", "20250801", is_amendment=True),  # 제외
        ]
        r = detect_capital_churn(evs, 3)
        self.assertEqual(r["total_events"], 2)
        self.assertNotIn("CAPITAL_CHURN", r["flags"])

    def test_mixed_signals_only_capital_counted(self):
        evs = [
            _ev("3PCA", "20250101"),
            _ev("SHAREHOLDER", "20250201"),   # 비자본
            _ev("EXEC", "20250301"),           # 비자본
            _ev("CB_BW", "20250401"),
            _ev("TREASURY", "20250501"),
        ]
        r = detect_capital_churn(evs, 3)
        self.assertEqual(r["total_events"], 3)
        self.assertIn("CAPITAL_CHURN", r["flags"])


if __name__ == "__main__":
    unittest.main()
