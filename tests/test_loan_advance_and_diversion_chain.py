"""금감원 2019-12-19 무자본 M&A 합동점검 반영 검증.

- capital_backflow field_evidence 교체(아틀라스링크 실명 제거 → 금감원 인용)
- 신규 패턴 fund_diversion_chain (CB/BW 조달 → 타법인주식·영업 양수)
- extract_loan_advance / LOAN_ADVANCE_SURGE (대여금·선급금 유용 경로 도구화)
"""
import unittest

from dart_risk_mcp.core.dart_client import (
    detect_financial_anomaly,
    extract_loan_advance,
)
from dart_risk_mcp.core.taxonomy import (
    CROSS_SIGNAL_PATTERNS,
    TAXONOMY,
    find_pattern_match,
)


class TestCapitalBackflowEvidenceReplaced(unittest.TestCase):
    """SE 후속: 아틀라스링크 실명 인용을 당국 적발 인용으로 교체."""

    def test_no_named_company_in_evidence(self):
        evidence = CROSS_SIGNAL_PATTERNS["capital_backflow"]["field_evidence"]
        joined = " ".join(evidence)
        self.assertNotIn("아틀라스링크", joined)
        self.assertNotIn("알로이스", joined)

    def test_evidence_cites_fss_investigation(self):
        evidence = CROSS_SIGNAL_PATTERNS["capital_backflow"]["field_evidence"]
        joined = " ".join(evidence)
        self.assertIn("금감원", joined)
        self.assertIn("2019-12-19", joined)
        self.assertIn("무자본 M&A 합동점검", joined)

    def test_pattern_still_registered_with_same_sequence(self):
        pattern = CROSS_SIGNAL_PATTERNS["capital_backflow"]
        self.assertEqual(pattern["signal_sequence"], ["3.1", "5.7"])
        self.assertEqual(pattern["severity"], "CRITICAL")
        self.assertEqual(pattern["timeline_months"], 12)

    def test_taxonomy_5_7_mentions_fss_investigation(self):
        desc = TAXONOMY["5.7"]["description"]
        self.assertIn("금감원", desc)
        self.assertIn("무자본 M&A 합동점검", desc)


class TestFundDiversionChainPattern(unittest.TestCase):
    def test_pattern_registered(self):
        self.assertIn("fund_diversion_chain", CROSS_SIGNAL_PATTERNS)
        pattern = CROSS_SIGNAL_PATTERNS["fund_diversion_chain"]
        self.assertEqual(pattern["signal_sequence"], ["1.1", "5.8"])
        self.assertEqual(pattern["timeline_months"], 12)
        self.assertEqual(pattern["severity"], "HIGH")

    def test_evidence_cites_fss_investigation_no_judgment_words(self):
        evidence = CROSS_SIGNAL_PATTERNS["fund_diversion_chain"]["field_evidence"]
        joined = " ".join(evidence)
        self.assertIn("금감원", joined)
        self.assertIn("비상장주식 취득 7,030억(55%)", joined)
        # v0.8.5 무판정 원칙 — 등급/단정 어휘 부재 확인
        for banned in ("매우위험", "고위험", "중위험", "저위험", "위험 등급"):
            self.assertNotIn(banned, joined)

    def test_pattern_matches_cb_bw_plus_acq_review(self):
        matched = find_pattern_match(["1.1", "5.8"])
        self.assertIsNotNone(matched)
        self.assertEqual(matched["pattern_id"], "fund_diversion_chain")

    def test_pattern_does_not_match_acq_review_alone(self):
        matched = find_pattern_match(["5.8"])
        self.assertIsNone(matched)

    def test_pattern_does_not_collide_with_capital_backflow(self):
        # capital_backflow는 {3.1, 5.7}, fund_diversion_chain은 {1.1, 5.8} —
        # 교집합이 없어 서로 오발화하지 않는다.
        matched = find_pattern_match(["3.1", "5.7"])
        self.assertEqual(matched["pattern_id"], "capital_backflow")
        matched2 = find_pattern_match(["1.1", "5.8"])
        self.assertEqual(matched2["pattern_id"], "fund_diversion_chain")


class TestExtractLoanAdvance(unittest.TestCase):
    def test_bs_case_collects_balance_accounts(self):
        rows = [
            {"account_nm": "단기대여금", "sj_div": "BS",
             "thstrm_amount": "2,000,000,000", "frmtrm_amount": "500,000,000"},
            {"account_nm": "선급금", "sj_div": "BS",
             "thstrm_amount": "100,000,000", "frmtrm_amount": "50,000,000"},
        ]
        result = extract_loan_advance(rows)
        self.assertEqual(len(result["bs_items"]), 2)
        self.assertEqual(result["cf_items"], [])
        self.assertEqual(result["bs_current_total"], 2_100_000_000)
        self.assertEqual(result["bs_prior_total"], 550_000_000)

    def test_cf_case_collects_flow_accounts_separately(self):
        rows = [
            {"account_nm": "단기대여금의 증가", "sj_div": "CF",
             "thstrm_amount": "-300,000,000", "frmtrm_amount": "-100,000,000"},
        ]
        result = extract_loan_advance(rows)
        self.assertEqual(result["bs_items"], [])
        self.assertEqual(len(result["cf_items"]), 1)
        self.assertIsNone(result["bs_current_total"])
        self.assertIsNone(result["bs_prior_total"])

    def test_no_exposure_returns_empty_and_none_totals(self):
        rows = [
            {"account_nm": "매출액", "sj_div": "IS",
             "thstrm_amount": "1,000,000,000", "frmtrm_amount": "900,000,000"},
        ]
        result = extract_loan_advance(rows)
        self.assertEqual(result["bs_items"], [])
        self.assertEqual(result["cf_items"], [])
        self.assertIsNone(result["bs_current_total"])
        self.assertIsNone(result["bs_prior_total"])

    def test_prepaid_expense_excluded(self):
        rows = [
            {"account_nm": "선급비용", "sj_div": "BS",
             "thstrm_amount": "1,000,000,000", "frmtrm_amount": "900,000,000"},
            {"account_nm": "선급금", "sj_div": "BS",
             "thstrm_amount": "10,000,000", "frmtrm_amount": "5,000,000"},
        ]
        result = extract_loan_advance(rows)
        names = [i["account_nm"] for i in result["bs_items"]]
        self.assertNotIn("선급비용", names)
        self.assertIn("선급금", names)

    def test_empty_rows(self):
        result = extract_loan_advance([])
        self.assertEqual(result["bs_items"], [])
        self.assertEqual(result["cf_items"], [])
        self.assertIsNone(result["bs_current_total"])
        self.assertIsNone(result["bs_prior_total"])


class TestLoanAdvanceSurgeFlag(unittest.TestCase):
    def _fs(self):
        return {"매출액": 1000, "당기순이익": 50}

    def test_flags_when_doubled_and_above_1b(self):
        loan_advance = {"bs_current_total": 2_000_000_000,
                         "bs_prior_total": 900_000_000}
        flags, metrics = detect_financial_anomaly(
            self._fs(), self._fs(), loan_advance=loan_advance)
        self.assertIn("LOAN_ADVANCE_SURGE", flags)
        m = next(x for x in metrics if x["name"] == "대여금·선급금(재무상태표)")
        self.assertTrue(m["flagged"])

    def test_no_flag_when_below_2x(self):
        loan_advance = {"bs_current_total": 1_500_000_000,
                         "bs_prior_total": 900_000_000}
        flags, _ = detect_financial_anomaly(
            self._fs(), self._fs(), loan_advance=loan_advance)
        self.assertNotIn("LOAN_ADVANCE_SURGE", flags)

    def test_no_flag_when_below_1b_even_if_doubled(self):
        loan_advance = {"bs_current_total": 900_000_000,
                         "bs_prior_total": 100_000_000}
        flags, _ = detect_financial_anomaly(
            self._fs(), self._fs(), loan_advance=loan_advance)
        self.assertNotIn("LOAN_ADVANCE_SURGE", flags)

    def test_flags_new_exposure_with_zero_prior(self):
        loan_advance = {"bs_current_total": 1_200_000_000,
                         "bs_prior_total": 0}
        flags, _ = detect_financial_anomaly(
            self._fs(), self._fs(), loan_advance=loan_advance)
        self.assertIn("LOAN_ADVANCE_SURGE", flags)

    def test_no_metric_when_bs_total_is_none(self):
        # CF 전용 노출(bs_current_total=None)은 판정 대상이 아니다.
        loan_advance = {"bs_current_total": None, "bs_prior_total": None}
        flags, metrics = detect_financial_anomaly(
            self._fs(), self._fs(), loan_advance=loan_advance)
        self.assertNotIn("LOAN_ADVANCE_SURGE", flags)
        self.assertFalse(
            any(m["name"] == "대여금·선급금(재무상태표)" for m in metrics))

    def test_no_loan_advance_arg_is_backward_compatible(self):
        flags, metrics = detect_financial_anomaly(self._fs(), self._fs())
        self.assertNotIn("LOAN_ADVANCE_SURGE", flags)


if __name__ == "__main__":
    unittest.main()
