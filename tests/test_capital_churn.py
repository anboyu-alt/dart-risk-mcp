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

    def test_three_dilutive_events_12m_triggers_flag(self):
        # 희석성 3건 → 플래그 발동
        evs = [_ev("3PCA", "20250101"), _ev("CB_BW", "20250501"), _ev("RIGHTS_UNDER", "20251001")]
        r = detect_capital_churn(evs, 3)
        self.assertIn("CAPITAL_CHURN", r["flags"])
        self.assertEqual(r["max_12m_count"], 3)

    def test_events_spread_over_24m_no_flag(self):
        # 366일 이상 간격 → 어떤 365일 윈도우에도 2건까지만
        evs = [
            _ev("3PCA", "20240101"),
            _ev("3PCA", "20250201"),
            _ev("3PCA", "20260301"),
        ]
        r = detect_capital_churn(evs, 3)
        self.assertLessEqual(r["max_12m_count"], 2)
        self.assertNotIn("CAPITAL_CHURN", r["flags"])

    def test_amendment_excluded(self):
        evs = [
            _ev("3PCA", "20250101"),
            _ev("CB_BW", "20250501"),
            _ev("TREASURY", "20250801", is_amendment=True),
        ]
        r = detect_capital_churn(evs, 3)
        self.assertEqual(r["total_events"], 2)
        self.assertNotIn("CAPITAL_CHURN", r["flags"])

    def test_mixed_signals_only_dilutive_capital_counted(self):
        # 비자본 신호 제외, 희석성 3건만 카운트
        evs = [
            _ev("3PCA", "20250101"),
            _ev("SHAREHOLDER", "20250201"),
            _ev("EXEC", "20250301"),
            _ev("CB_BW", "20250401"),
            _ev("RIGHTS_UNDER", "20250501"),
        ]
        r = detect_capital_churn(evs, 3)
        self.assertEqual(r["total_events"], 3)
        self.assertIn("CAPITAL_CHURN", r["flags"])

    def test_non_dilutive_only_three_no_flag(self):
        # 비희석성(자사주) 3건 → 거짓양성 제거
        evs = [
            _ev("TREASURY", "20250101"),
            _ev("TREASURY", "20250501"),
            _ev("TREASURY", "20251001"),
        ]
        r = detect_capital_churn(evs, 3)
        self.assertNotIn("CAPITAL_CHURN", r["flags"])
        self.assertEqual(r["total_events"], 3)

    def test_mixed_2_dilutive_2_non_dilutive_triggers_flag(self):
        # 희석성 2 + 비희석성 2 → 플래그 발동
        evs = [
            _ev("3PCA", "20250101"),
            _ev("CB_BW", "20250201"),
            _ev("TREASURY", "20250301"),
            _ev("CB_BUYBACK", "20250401"),
        ]
        r = detect_capital_churn(evs, 3)
        self.assertIn("CAPITAL_CHURN", r["flags"])
        self.assertEqual(r["total_events"], 4)

    def test_mixed_1_dilutive_3_non_dilutive_no_flag(self):
        # 희석성 1 + 비희석성 3 → 희석성 조건 미충족
        evs = [
            _ev("3PCA", "20250101"),
            _ev("TREASURY", "20250201"),
            _ev("TREASURY", "20250301"),
            _ev("CB_BUYBACK", "20250401"),
        ]
        r = detect_capital_churn(evs, 3)
        self.assertNotIn("CAPITAL_CHURN", r["flags"])

    def test_counts_reported_in_result(self):
        # max_dilutive_12m, max_non_dilutive_12m 반환 dict에 존재
        evs = [
            _ev("3PCA", "20250101"),
            _ev("CB_BW", "20250201"),
            _ev("TREASURY", "20250301"),
        ]
        r = detect_capital_churn(evs, 3)
        self.assertIn("max_dilutive_12m", r)
        self.assertIn("max_non_dilutive_12m", r)
        self.assertEqual(r["max_dilutive_12m"], 2)
        self.assertEqual(r["max_non_dilutive_12m"], 1)


if __name__ == "__main__":
    unittest.main()
