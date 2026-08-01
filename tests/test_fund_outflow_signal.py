"""v1.6.0: FUND_OUTFLOW/ACQ_REVIEW 신호 + capital_backflow 복합 패턴 검증.

실증 사례(아틀라스링크, 구 알로이스, 01309795/297570): 최대주주변경 주식양수도
(20260608900794) → 최대주주변경(20260709) → 주요사항보고서(유형자산양수결정)
(20260722000373: 거래상대방 로아앤코홀딩스, 회사와의 관계 계열회사, 외부평가
삼덕회계법인 적정) → 타인에대한채무보증결정(20260729900778) 연쇄.
"""
import unittest

from dart_risk_mcp.core.signals import match_signals, SIGNAL_KEY_TO_TAXONOMY
from dart_risk_mcp.core.taxonomy import (
    CROSS_SIGNAL_PATTERNS,
    TAXONOMY,
    find_pattern_match,
)


class TestFundOutflowKeywordMatch(unittest.TestCase):
    def _keys(self, title: str) -> set[str]:
        return {s["key"] for s in match_signals(title)}

    def test_money_lending_matches_fund_outflow(self):
        self.assertIn("FUND_OUTFLOW", self._keys("금전대여결정"))

    def test_debt_guarantee_autonomy_matches_fund_outflow(self):
        self.assertIn("FUND_OUTFLOW", self._keys("타인에대한채무보증결정(자율공시)"))

    def test_collateral_provision_matches_fund_outflow(self):
        self.assertIn("FUND_OUTFLOW", self._keys("담보제공결정"))

    def test_tangible_asset_acquisition_matches_fund_outflow(self):
        self.assertIn(
            "FUND_OUTFLOW", self._keys("주요사항보고서(유형자산양수결정)")
        )

    def test_business_acquisition_matches_acq_review(self):
        self.assertIn("ACQ_REVIEW", self._keys("영업양수결정"))

    def test_stock_acquisition_matches_acq_review(self):
        self.assertIn(
            "ACQ_REVIEW", self._keys("타법인주식및출자증권양수결정")
        )

    def test_amendment_prefix_still_excluded(self):
        self.assertEqual(match_signals("[기재정정]금전대여결정"), [])

    def test_no_collision_with_contingent_guarantee_keyword(self):
        # CONTINGENT의 "보증채무"와 FUND_OUTFLOW의 "채무보증"은 어순이 달라
        # 서로 부분 문자열이 아니다 — 배경 조사에서 실측 확인된 사실의 회귀 가드.
        self.assertNotIn("보증채무", "채무보증")
        self.assertNotIn("채무보증", "보증채무")


class TestFundOutflowTaxonomyMapping(unittest.TestCase):
    def test_fund_outflow_maps_to_5_7(self):
        self.assertEqual(SIGNAL_KEY_TO_TAXONOMY["FUND_OUTFLOW"], ["5.7"])
        self.assertIn("5.7", TAXONOMY)
        self.assertEqual(TAXONOMY["5.7"]["severity"], "MEDIUM")

    def test_acq_review_maps_to_5_8(self):
        self.assertEqual(SIGNAL_KEY_TO_TAXONOMY["ACQ_REVIEW"], ["5.8"])
        self.assertIn("5.8", TAXONOMY)
        self.assertEqual(TAXONOMY["5.8"]["severity"], "OBSERVATION")


class TestCapitalBackflowPattern(unittest.TestCase):
    def test_pattern_registered(self):
        self.assertIn("capital_backflow", CROSS_SIGNAL_PATTERNS)
        pattern = CROSS_SIGNAL_PATTERNS["capital_backflow"]
        self.assertEqual(pattern["signal_sequence"], ["3.1", "5.7"])
        self.assertEqual(pattern["severity"], "CRITICAL")
        self.assertEqual(pattern["timeline_months"], 12)

    def test_pattern_matches_shareholder_plus_fund_outflow(self):
        matched = find_pattern_match(["3.1", "5.7"])
        self.assertIsNotNone(matched)
        self.assertEqual(matched["pattern_id"], "capital_backflow")

    def test_pattern_does_not_match_fund_outflow_alone(self):
        # 5.7 base_score=2(참고 강도) — 3.1(최대주주변경)과 조합될 때만 발화.
        matched = find_pattern_match(["5.7"])
        self.assertIsNone(matched)

    def test_atlaslink_signal_set_matches_pattern(self):
        """아틀라스링크 실증 신호 조합(최대주주변경 + 유형자산양수)이 패턴을 발화하는지."""
        sig_keys = ["SHAREHOLDER", "FUND_OUTFLOW"]
        tax_ids = sorted({
            tid for k in sig_keys for tid in SIGNAL_KEY_TO_TAXONOMY.get(k, [])
        })
        matched = find_pattern_match(tax_ids)
        self.assertIsNotNone(matched)
        self.assertEqual(matched["pattern_id"], "capital_backflow")


if __name__ == "__main__":
    unittest.main()
