"""부분 겹침 패턴 관찰 — "전부 일치할 때만 발화"에서 "관찰된 만큼 보여주고
무엇을 확인할지 알려주기"로 바꾼 두 계층을 검증한다.

- core.taxonomy.find_pattern_overlaps: 순수 함수, 교집합/정렬/결정성.
- server._render_pattern_watch_block: analyze_company_risk·build_event_timeline
  공용 렌더러. capital_backflow의 v1.6.1 내용 확인 게이트가 부분 관찰
  표기로 바뀐 뒤에도 그대로 보존되는지가 핵심(게이트 실패 시 그 패턴은
  "N개 중 M개 관찰" 형태로도 절대 노출되면 안 된다).
"""
import itertools
import unittest

from dart_risk_mcp.core.catalog import taxonomy_label_ko
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS, find_pattern_overlaps
from dart_risk_mcp.server import _render_pattern_watch_block


class TestFindPatternOverlaps(unittest.TestCase):
    def test_below_min_overlap_is_excluded(self):
        self.assertEqual(find_pattern_overlaps(["2.7"], min_overlap=2), [])

    def test_at_min_overlap_is_included(self):
        result = find_pattern_overlaps(["2.7", "4.3"], min_overlap=2)
        ids = {r["pattern_id"] for r in result}
        self.assertIn("capital_churn_anomaly", ids)

    def test_full_match_has_empty_missing(self):
        result = find_pattern_overlaps(["2.7", "4.3"], min_overlap=2)
        churn = next(r for r in result if r["pattern_id"] == "capital_churn_anomaly")
        self.assertEqual(churn["missing"], [])
        self.assertEqual(churn["n_matched"], churn["n_total"])
        self.assertEqual(churn["n_matched"], 2)

    def test_partial_match_reports_matched_and_missing_sorted(self):
        # audit_insider_dump signal_sequence = ["4.4", "7.1", "3.1"] — 이엠티
        # 실측 재현: 3개 중 2개(4.4, 3.1)만 관찰된 경우.
        result = find_pattern_overlaps(["4.4", "3.6", "3.1"], min_overlap=2)
        aid = next(r for r in result if r["pattern_id"] == "audit_insider_dump")
        self.assertEqual(aid["n_matched"], 2)
        self.assertEqual(aid["n_total"], 3)
        self.assertEqual(aid["matched"], ["3.1", "4.4"])  # taxonomy id 오름차순
        self.assertEqual(aid["missing"], ["7.1"])
        # 3.6은 audit_insider_dump의 signal_sequence에 없으므로 matched/missing
        # 어느 쪽에도 나타나지 않는다(무관한 taxonomy는 조용히 무시).
        self.assertNotIn("3.6", aid["matched"] + aid["missing"])

    def test_unknown_taxonomy_id_does_not_raise(self):
        result = find_pattern_overlaps(["99.9", "3.1"], min_overlap=2)
        self.assertIsInstance(result, list)

    def test_checkpoints_present_when_registered(self):
        result = find_pattern_overlaps(["4.4", "3.1"], min_overlap=2)
        aid = next(r for r in result if r["pattern_id"] == "audit_insider_dump")
        self.assertTrue(aid["checkpoints"])

    def test_determinism_across_input_orderings_and_set_input(self):
        ids = ["3.1", "5.7", "2.7", "4.3"]
        outputs = [
            find_pattern_overlaps(set(p), min_overlap=2)
            for p in itertools.permutations(ids)
        ]
        first = outputs[0]
        for out in outputs[1:]:
            self.assertEqual(out, first)

    def test_sort_order_ratio_desc_then_n_matched_desc_then_id_asc(self):
        # zombie_ma(6/6=1.0 완전일치) vs delisting_evasion(3/6=0.5 부분일치)
        # — 충족률이 높은 쪽이 앞선다.
        # 2026-08-25: 임계가 패턴 크기에 비례하게 바뀌어(60%) delisting_evasion은
        # 6개 중 4개가 필요하다 — 8.1을 더해 4/6으로 만든다(정렬 검증이 목적).
        result = find_pattern_overlaps(
            ["3.1", "2.4", "1.2", "4.3", "7.1", "2.7", "8.1"], min_overlap=2
        )
        ids = [r["pattern_id"] for r in result]
        self.assertIn("zombie_ma", ids)
        self.assertIn("delisting_evasion", ids)
        self.assertLess(ids.index("zombie_ma"), ids.index("delisting_evasion"))

    def test_every_pattern_id_is_a_real_cross_signal_pattern_key(self):
        # find_pattern_overlaps가 CROSS_SIGNAL_PATTERNS 밖의 키를 만들어내지
        # 않는지(오타·복사 실수 회귀 가드).
        all_ids = sorted({tid for p in CROSS_SIGNAL_PATTERNS.values() for tid in p["signal_sequence"]})
        result = find_pattern_overlaps(all_ids, min_overlap=2)
        for r in result:
            self.assertIn(r["pattern_id"], CROSS_SIGNAL_PATTERNS)


class TestTaxonomyLabelKo(unittest.TestCase):
    def test_known_id_returns_nonempty_label(self):
        self.assertTrue(taxonomy_label_ko("1.1"))

    def test_unknown_id_falls_back_to_id_itself(self):
        self.assertEqual(taxonomy_label_ko("99.9"), "99.9")


class TestRenderPatternWatchBlock(unittest.TestCase):
    def test_no_overlap_returns_empty(self):
        lines, fact_lines, filtered = _render_pattern_watch_block(["1.1"], [], True, {})
        self.assertEqual(lines, [])
        self.assertEqual(fact_lines, [])
        self.assertEqual(filtered, [])

    def test_partial_overlap_renders_n_of_m_and_checkpoints(self):
        lines, _, filtered = _render_pattern_watch_block(["4.4", "3.1"], [], True, {})
        self.assertTrue(filtered)
        joined = "\n".join(lines)
        self.assertIn("━━ 관찰된 신호가 겹치는 등록 패턴 ━━", joined)
        self.assertIn("구성 신호 3개 중 2개가 이 기간 공시에서 관찰됐습니다", joined)
        self.assertIn("관찰됨:", joined)
        self.assertIn("안 보임:", joined)
        self.assertIn("확인해볼 것:", joined)

    def test_full_match_omits_missing_line(self):
        # 2.7+4.3만 넘기면 capital_churn_anomaly(정확히 이 두 신호로만
        # 구성됨)는 완전일치라 "안 보임" 줄이 없어야 한다. 같은 taxonomy를
        # 부분적으로 공유하는 다른(더 큰) 패턴이 함께 뜰 수 있으므로,
        # capital_churn_anomaly 카드 하나만 잘라내 검증한다.
        lines, _, filtered = _render_pattern_watch_block(["2.7", "4.3"], [], True, {})
        churn = next(f for f in filtered if f["pattern_id"] == "capital_churn_anomaly")
        self.assertEqual(churn["n_matched"], churn["n_total"])
        self.assertEqual(churn["missing"], [])
        joined = "\n".join(lines)
        idx = joined.index("자본 이벤트 과다 반복 — 구성 신호 2개 중 2개")
        card_end = joined.find("▸ ", idx + 1)
        card_text = joined[idx: card_end if card_end != -1 else len(joined)]
        self.assertNotIn("안 보임:", card_text)

    def test_max_show_caps_at_three_with_overflow_note(self):
        # 이 조합은 capital_backflow(게이트 실패로 제외)까지 포함해 6개 패턴이
        # 임계를 만족하며, 5개가 게이트를 통과한다(실측 확인).
        # 2026-08-25: 임계가 패턴 크기에 비례하게 바뀌어 taxonomy를 보강했다.
        tax_ids = ["3.1", "5.7", "1.2", "2.4", "4.3", "7.1", "2.7",
                   "8.1", "4.4", "2.6", "1.5", "1.3"]
        lines, fact_lines, filtered = _render_pattern_watch_block(tax_ids, [], True, {})
        self.assertEqual(len(filtered), 5)
        joined = "\n".join(lines)
        self.assertEqual(joined.count("▸ "), 3)
        # 2026-08-25: 임계가 패턴 크기에 비례하게 바뀌어(v1.20.13)
        # "2개 이상"은 낡은 문구다 — 기준을 숫자로 단정하지 않는다.
        self.assertIn("외 2개 패턴이 표시 기준을 넘겨 겹칩니다.", joined)
        self.assertNotIn("2개 이상 겹칩니다", joined)
        # capital_backflow는 confirmations가 비어 있어 게이트를 통과하지
        # 못했으므로(빈 확인 목록은 "조용히 실패" — v1.6.1 기존 동작) 목록에도
        # fact_lines에도 나타나지 않는다.
        self.assertFalse(any(f["pattern_id"] == "capital_backflow" for f in filtered))
        self.assertEqual(fact_lines, [])

    def test_capital_backflow_gate_blocks_pattern_even_when_fully_observed(self):
        """구성 taxonomy(3.1+5.7)가 전부 관찰돼도, 확인된 유출 상대가
        subsidiary(종속회사)뿐이면 v1.6.1 게이트가 패턴 노출 자체를 막는다."""
        confirmations = [{
            "rcept_dt": "2026-07-01", "report_nm": "타인에대한채무보증결정",
            "rcept_no": "1", "counterparty": "테스트법인",
            "relation": "종속회사", "classification": "subsidiary", "amount": 100,
        }]
        lines, fact_lines, filtered = _render_pattern_watch_block(
            ["3.1", "5.7"], confirmations, True, {}
        )
        joined = "\n".join(lines)
        self.assertNotIn("자금 역류", joined)
        self.assertFalse(any(f["pattern_id"] == "capital_backflow" for f in filtered))
        self.assertTrue(fact_lines)
        self.assertIn("특수관계 유출은 미확인", "\n".join(fact_lines))

    def test_capital_backflow_gate_blocks_without_control_change_title(self):
        """계열사 대여(affiliated)가 확인돼도 조회 창 내 실질 경영권 변경
        제목이 없으면(한농화성류 오탐 방지) 패턴은 목록에서 빠진다."""
        confirmations = [{
            "rcept_dt": "2026-07-01", "report_nm": "타인에대한채무보증결정",
            "rcept_no": "1", "counterparty": "테스트법인",
            "relation": "계열회사", "classification": "affiliated", "amount": 100,
        }]
        lines, fact_lines, filtered = _render_pattern_watch_block(
            ["3.1", "5.7"], confirmations, False, {}
        )
        self.assertFalse(any(f["pattern_id"] == "capital_backflow" for f in filtered))
        self.assertNotIn("자금 역류", "\n".join(lines))
        self.assertTrue(fact_lines)

    def test_capital_backflow_gate_passes_with_affiliated_confirmation(self):
        confirmations = [{
            "rcept_dt": "2026-07-01", "report_nm": "타인에대한채무보증결정",
            "rcept_no": "1", "counterparty": "테스트법인",
            "relation": "계열회사", "classification": "affiliated", "amount": 100,
        }]
        lines, fact_lines, filtered = _render_pattern_watch_block(
            ["3.1", "5.7"], confirmations, True, {}
        )
        self.assertTrue(any(f["pattern_id"] == "capital_backflow" for f in filtered))
        joined = "\n".join(lines)
        self.assertIn("자금 역류", joined)
        self.assertIn("확인된 특수관계 유출:", joined)
        self.assertIn("테스트법인", joined)
        self.assertEqual(fact_lines, [])

    def test_no_judgment_vocabulary_in_rendered_output(self):
        tax_ids = ["4.4", "3.1", "7.1", "1.2", "2.4", "2.7", "4.3"]
        lines, _, _ = _render_pattern_watch_block(tax_ids, [], True, {})
        joined = "\n".join(lines)
        self.assertTrue(joined)  # 비어 있으면 아래 단언이 무의미해진다
        for banned in ("위험합니다", "의심됩니다", "해당됩니다", "매우위험", "고위험", "가능성 높음"):
            self.assertNotIn(banned, joined)


if __name__ == "__main__":
    unittest.main()
