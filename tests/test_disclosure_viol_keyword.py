"""SE-7 Task 1: DISCLOSURE_VIOL에 DART 실제 공식 용어 '불성실공시법인' 추가 검증.

실측(엔켐 실 공시 이력)으로 확인된 두 실제 제목이 DISCLOSURE_VIOL 신호로
탐지되는지, 정정공시 배제 동작(match_signals 기존 로직)은 그대로인지,
기존 DISCLOSURE_VIOL 키워드 매칭이 회귀 없이 살아있는지를 검증한다.
"""
import unittest

from dart_risk_mcp.core.signals import match_signals


class TestDisclosureViolKeyword(unittest.TestCase):
    def test_designation_title_matches_disclosure_viol(self):
        matched = match_signals("불성실공시법인지정")
        keys = {s["key"] for s in matched}
        self.assertIn("DISCLOSURE_VIOL", keys)

    def test_designation_notice_title_matches_disclosure_viol(self):
        matched = match_signals("불성실공시법인지정예고")
        keys = {s["key"] for s in matched}
        self.assertIn("DISCLOSURE_VIOL", keys)

    def test_amendment_prefixed_designation_still_excluded(self):
        # match_signals의 정정공시 배제 로직은 이 태스크의 범위 밖 — 그대로 유지되어야 한다.
        matched = match_signals("[기재정정]불성실공시법인지정")
        self.assertEqual(matched, [])

    def test_existing_disclosure_viol_keywords_still_match(self):
        for title in ["공시의무위반", "공시누락", "중요정보누락", "발행철회", "공시철회"]:
            with self.subTest(title=title):
                matched = match_signals(title)
                keys = {s["key"] for s in matched}
                self.assertIn("DISCLOSURE_VIOL", keys)


class TestDisclosureViolKeywordExpansion(unittest.TestCase):
    """taxonomy 4.3 재정의 + DISCLOSURE_VIOL 키워드 보강 검증.

    2026-06-17~2026-08-15(60일) 시장 전체 30,765건 실측: DISCLOSURE_VIOL이
    실제로 잡는 51건/16종 전부가 「불성실공시법인지정(예고)」 계열이었다.
    정정 제외 24,350건에서 "보고서미제출"·"제출지연"·"공시위반" 3개
    키워드가 기존 키워드가 놓치던 실제 DART 제목을 오탐 0건으로 추가
    포착했다(실제 관측된 제목으로 회귀 가드).
    """

    def test_report_not_submitted_real_title_matches(self):
        matched = match_signals("주권매매거래정지(사업보고서미제출)")
        keys = {s["key"] for s in matched}
        self.assertIn("DISCLOSURE_VIOL", keys)

    def test_audit_report_submission_delay_real_title_matches(self):
        matched = match_signals("기타주요경영사항(자율공시)(감사보고서제출지연)")
        keys = {s["key"] for s in matched}
        self.assertIn("DISCLOSURE_VIOL", keys)

    def test_disclosure_violation_penalty_real_title_matches(self):
        matched = match_signals("기타시장안내(공시위반제재금미납에따른가중벌점부과)")
        keys = {s["key"] for s in matched}
        self.assertIn("DISCLOSURE_VIOL", keys)

    def test_designation_notice_noncompliance_still_matches(self):
        # 기존 동작(불성실공시법인지정예고(공시불이행)) 유지 확인 — 회귀 아님.
        matched = match_signals("불성실공시법인지정예고(공시불이행)")
        keys = {s["key"] for s in matched}
        self.assertIn("DISCLOSURE_VIOL", keys)

    def test_amendment_prefixed_real_title_still_excluded(self):
        # match_signals의 정정공시 배제 로직은 이 태스크의 범위 밖 — 그대로 유지되어야 한다.
        matched = match_signals("[기재정정]불성실공시법인지정예고(공시불이행)")
        self.assertEqual(matched, [])

    def test_labels_ko_43_definition_has_no_intent_claim(self):
        # v0.8.5 무판정 원칙: 관측할 수 없는 내심("의도적")을 단정하지 않는다.
        import json
        from pathlib import Path

        labels_path = (
            Path(__file__).resolve().parents[1]
            / "data"
            / "catalog"
            / "labels_ko.json"
        )
        with open(labels_path, encoding="utf-8") as f:
            labels = json.load(f)
        definition = labels["4.3"]["definition"]
        self.assertNotIn("의도적", definition)


if __name__ == "__main__":
    unittest.main()
