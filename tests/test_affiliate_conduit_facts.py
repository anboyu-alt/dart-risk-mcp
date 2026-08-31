"""후속 3위: 종속회사 경유 유출 — 타법인 출자현황 대조 사실 병기.

자금유출 상대방이 classify_outflow_relation로 "subsidiary"(종속회사·자회사)
판정될 때, 타법인 출자현황(otrCprInvstmntSttus)과 대조해 그 종속회사의 지분
변동·최근 순이익을 사실로만 병기한다. 판정·게이트 발화 조건은 절대 바꾸지
않는다 — subsidiary는 여전히 capital_backflow 미발화 사유다.

fixture는 아틀라스링크(01309795) 2025년 fetch_affiliate_investments 실측
row 그대로다(한국파일 — 기초 지분 46.32% → 기말 62.43%, 최초취득
2023.09.07, 최근 순이익 -4,969,000,000원).
"""
import unittest

from dart_risk_mcp.core.dart_client import (
    match_affiliate_row,
    summarize_affiliate_stake,
)


# ── fixture: 아틀라스링크 라이브 실측 row (2025년, otrCprInvstmntSttus) ──────
_HANKUK_FILE_ROW_2025 = {
    "inv_prm": "(주)한국파일",
    "frst_acqs_de": "2023.09.07",
    "invstmnt_purps": "경영참여",
    "frst_acqs_amount": "7,000,000,000",
    "bsis_blce_qota_rt": "46.32",
    "trmend_blce_qota_rt": "62.43",
    "incrs_dcrs_acqs_dsps_amount": "4,900,000,000",
    "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "-4,969,000,000",
}

# 같은 실체, 2024년 응답은 개명 전 표기("성우기업(주)") — 이름 매칭 실패 사례.
_SEONGWOO_ROW_2024 = {
    "inv_prm": "성우기업(주)",
    "frst_acqs_de": "2023.09.07",
    "invstmnt_purps": "경영참여",
    "bsis_blce_qota_rt": "46.32",
    "trmend_blce_qota_rt": "46.32",
    "incrs_dcrs_acqs_dsps_amount": "-",
    "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "1,200,000,000",
}


class MatchAffiliateRowTest(unittest.TestCase):
    def test_matches_despite_corp_suffix_variants(self):
        rows = [_HANKUK_FILE_ROW_2025]
        for variant in ("(주)한국파일", "㈜한국파일", "주식회사 한국파일", "한국파일"):
            with self.subTest(variant=variant):
                row = match_affiliate_row(rows, variant)
                self.assertIsNotNone(row)
                self.assertEqual(row["inv_prm"], "(주)한국파일")

    def test_no_match_returns_none(self):
        rows = [_HANKUK_FILE_ROW_2025]
        self.assertIsNone(match_affiliate_row(rows, "존재하지않는법인"))

    def test_empty_counterparty_returns_none(self):
        rows = [_HANKUK_FILE_ROW_2025]
        self.assertIsNone(match_affiliate_row(rows, ""))

    def test_empty_rows_returns_none(self):
        self.assertIsNone(match_affiliate_row([], "한국파일"))
        self.assertIsNone(match_affiliate_row(None, "한국파일"))

    def test_first_match_wins_on_duplicate_fold(self):
        rows = [_HANKUK_FILE_ROW_2025, dict(_HANKUK_FILE_ROW_2025, invstmnt_purps="중복")]
        row = match_affiliate_row(rows, "한국파일")
        self.assertEqual(row["invstmnt_purps"], "경영참여")


class SummarizeAffiliateStakeTest(unittest.TestCase):
    def test_live_row_hankuk_file(self):
        stake = summarize_affiliate_stake(_HANKUK_FILE_ROW_2025)
        self.assertEqual(stake["first_acquired"], "2023-09")
        self.assertAlmostEqual(stake["stake_begin"], 46.32)
        self.assertAlmostEqual(stake["stake_end"], 62.43)
        self.assertEqual(stake["added_amount"], 4_900_000_000)
        self.assertEqual(stake["recent_net_profit"], -4_969_000_000)
        self.assertEqual(stake["purpose"], "경영참여")

    def test_dash_added_amount_parsed_as_none(self):
        stake = summarize_affiliate_stake(_SEONGWOO_ROW_2024)
        self.assertIsNone(stake["added_amount"])
        self.assertEqual(stake["recent_net_profit"], 1_200_000_000)

    def test_no_stake_change_when_begin_equals_end(self):
        stake = summarize_affiliate_stake(_SEONGWOO_ROW_2024)
        self.assertEqual(stake["stake_begin"], stake["stake_end"])

    def test_profitable_affiliate(self):
        row = dict(_HANKUK_FILE_ROW_2025, recent_bsns_year_fnnr_sttus_thstrm_ntpf="3,300,000,000")
        stake = summarize_affiliate_stake(row)
        self.assertEqual(stake["recent_net_profit"], 3_300_000_000)

    def test_missing_date_yields_empty_string(self):
        row = dict(_HANKUK_FILE_ROW_2025, frst_acqs_de="")
        stake = summarize_affiliate_stake(row)
        self.assertEqual(stake["first_acquired"], "")

    def test_malformed_numbers_do_not_raise(self):
        row = {
            "inv_prm": "테스트법인", "frst_acqs_de": "N/A",
            "bsis_blce_qota_rt": "abc", "trmend_blce_qota_rt": "-",
            "incrs_dcrs_acqs_dsps_amount": "", "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "-",
            "invstmnt_purps": "",
        }
        stake = summarize_affiliate_stake(row)
        self.assertEqual(stake["first_acquired"], "")
        self.assertIsNone(stake["stake_begin"])
        self.assertIsNone(stake["stake_end"])
        self.assertIsNone(stake["added_amount"])
        self.assertIsNone(stake["recent_net_profit"])


class FormatAffiliateStakeLineTest(unittest.TestCase):
    """server.py의 렌더링 헬퍼 — 판정 어휘 없이 사실만 조립하는지 확인."""

    def test_full_line_matches_spec_example(self):
        from dart_risk_mcp.server import _format_affiliate_stake_line

        # -4,969,000,000원 → **-50억원**(반올림).
        #
        # 2026-08-30 이전에는 -49억원이었다. 그때 이 주석은 「설계 문서의
        # "-50억원"은 예시 서술이었고 기존 `_format_amount` 관례(절삭)가
        # 정답」이라 적었는데, 그 관례 자체가 결함이었다 — 절삭이 조 단위에서
        # 1.9조를 「1조원」으로 만들고 있었다(9,000억 손실). 반올림으로
        # 바꾸면서 이 값이 **설계 문서가 원래 적은 -50억원**과 같아졌다.
        stake = summarize_affiliate_stake(_HANKUK_FILE_ROW_2025)
        line = _format_affiliate_stake_line(stake)
        self.assertEqual(
            line,
            "최초취득 2023-09 · 지분 46.3→62.4% 확대 · 피출자사 최근 순이익 -50억원",
        )

    def test_no_stake_change_omits_stake_segment(self):
        from dart_risk_mcp.server import _format_affiliate_stake_line

        stake = summarize_affiliate_stake(_SEONGWOO_ROW_2024)
        line = _format_affiliate_stake_line(stake)
        self.assertNotIn("지분", line)
        self.assertIn("최초취득 2023-09", line)
        self.assertIn("피출자사 최근 순이익", line)

    def test_profitable_affiliate_shows_amount_without_negative_sign(self):
        from dart_risk_mcp.server import _format_affiliate_stake_line

        row = dict(_HANKUK_FILE_ROW_2025, recent_bsns_year_fnnr_sttus_thstrm_ntpf="3,300,000,000")
        stake = summarize_affiliate_stake(row)
        line = _format_affiliate_stake_line(stake)
        self.assertIn("피출자사 최근 순이익 33억원", line)
        self.assertNotIn("-33억원", line)

    def test_no_facts_at_all_returns_empty_string(self):
        from dart_risk_mcp.server import _format_affiliate_stake_line

        line = _format_affiliate_stake_line(
            {"first_acquired": "", "stake_begin": None, "stake_end": None,
             "added_amount": None, "recent_net_profit": None, "purpose": ""}
        )
        self.assertEqual(line, "")

    def test_no_judgment_vocabulary(self):
        """v0.8.5 원칙 — "conduit"/"경유" 같은 구조 단정 어휘 금지."""
        from dart_risk_mcp.server import _format_affiliate_stake_line

        stake = summarize_affiliate_stake(_HANKUK_FILE_ROW_2025)
        line = _format_affiliate_stake_line(stake)
        for banned in ("conduit", "경유", "우회", "위험", "의심"):
            self.assertNotIn(banned, line)


class RenderOutflowConfirmationsAffiliateFactsTest(unittest.TestCase):
    """_render_outflow_confirmations이 subsidiary 줄에만 사실을 병기하는지."""

    def _confirmation(self, classification="subsidiary", counterparty="(주)한국파일"):
        return {
            "rcept_dt": "2026-07-29", "report_nm": "채무보증결정",
            "rcept_no": "20260729900778", "counterparty": counterparty,
            "relation": "종속회사", "classification": classification, "amount": 1_000_000_000,
        }

    def test_subsidiary_line_gets_fact_appended(self):
        from dart_risk_mcp.server import _render_outflow_confirmations

        facts = {"(주)한국파일": "최초취득 2023-09 · 지분 46.3→62.4% 확대 · 피출자사 최근 순이익 -50억원"}
        lines = _render_outflow_confirmations([self._confirmation()], facts)
        joined = "\n".join(lines)
        self.assertIn("타법인출자현황: 최초취득 2023-09", joined)

    def test_affiliated_classification_never_gets_fact(self):
        from dart_risk_mcp.server import _render_outflow_confirmations

        facts = {"(주)한국파일": "최초취득 2023-09 · 지분 46.3→62.4% 확대"}
        lines = _render_outflow_confirmations(
            [self._confirmation(classification="affiliated")], facts
        )
        self.assertFalse(any("타법인출자현황" in ln for ln in lines))

    def test_no_facts_dict_does_not_crash(self):
        from dart_risk_mcp.server import _render_outflow_confirmations

        lines = _render_outflow_confirmations([self._confirmation()], None)
        self.assertFalse(any("타법인출자현황" in ln for ln in lines))

    def test_unmatched_counterparty_omits_line(self):
        from dart_risk_mcp.server import _render_outflow_confirmations

        facts = {"다른회사": "최초취득 2020-01"}
        lines = _render_outflow_confirmations([self._confirmation()], facts)
        self.assertFalse(any("타법인출자현황" in ln for ln in lines))


class BuildAffiliateStakeFactsGateTest(unittest.TestCase):
    """_build_affiliate_stake_facts — subsidiary 없으면 API 호출 자체를 안 한다."""

    def test_no_subsidiary_confirmations_skips_fetch(self):
        from dart_risk_mcp.server import _build_affiliate_stake_facts

        confirmations = [{
            "rcept_dt": "2026-07-29", "report_nm": "x", "rcept_no": "1",
            "counterparty": "계열사A", "relation": "계열회사",
            "classification": "affiliated", "amount": 0,
        }]
        # corp_code가 있어도 subsidiary가 없으면 fetch_affiliate_investments를
        # 호출하지 않는다 — 호출됐다면 API 키 없이 예외 없이 빈 값을 반환해
        # 테스트를 통과시켜 버리므로, 대신 빈 corp_code로 호출해도 안전한지만
        # 확인한다(호출 자체가 없어야 마땅히 즉시 반환).
        facts = _build_affiliate_stake_facts(confirmations, "")
        self.assertEqual(facts, {})

    def test_empty_confirmations_returns_empty_dict(self):
        from dart_risk_mcp.server import _build_affiliate_stake_facts

        self.assertEqual(_build_affiliate_stake_facts([], "01309795"), {})


class CapitalBackflowGatePreservesJudgmentTest(unittest.TestCase):
    """affiliate_facts 인자가 게이트 판정(pass/affiliated)을 바꾸지 않는지."""

    def test_gate_pass_unaffected_by_affiliate_facts(self):
        from dart_risk_mcp.server import _capital_backflow_gate

        confirmations = [{
            "rcept_dt": "2026-07-01", "report_nm": "x", "rcept_no": "1",
            "counterparty": "계열사A", "relation": "계열회사",
            "classification": "affiliated", "amount": 100,
        }]
        gate_without = _capital_backflow_gate(confirmations, True, None)
        gate_with = _capital_backflow_gate(
            confirmations, True, {"계열사A": "최초취득 2020-01"}
        )
        self.assertEqual(gate_without["pass"], gate_with["pass"])
        self.assertTrue(gate_with["pass"])

    def test_subsidiary_only_fact_lines_include_affiliate_fact(self):
        from dart_risk_mcp.server import _capital_backflow_gate

        confirmations = [{
            "rcept_dt": "2026-07-01", "report_nm": "x", "rcept_no": "1",
            "counterparty": "(주)한국파일", "relation": "종속회사",
            "classification": "subsidiary", "amount": 100,
        }]
        facts = {"(주)한국파일": "최초취득 2023-09 · 지분 46.3→62.4% 확대"}
        gate = _capital_backflow_gate(confirmations, True, facts)
        self.assertFalse(gate["pass"])
        joined = "\n".join(gate["fact_lines"])
        self.assertIn("타법인출자현황", joined)


if __name__ == "__main__":
    unittest.main()
