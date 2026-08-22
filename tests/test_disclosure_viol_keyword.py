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

    def test_removed_keywords_were_dead(self):
        """제거한 5종은 DART 제목에 쓰이지 않는 개념어였다 (2026-08-22).

        1년 전수 270,882건에서 전부 0건이라 제거했다. 이 테스트는 그 판단을
        고정한다 — 되살리려면 CLAUDE.md 관례대로 시장 실측 근거부터 붙일 것.

        ⚠ "공시의무"가 0건인 게 아니다. 185건 있는데 전부
        「수시공시의무관련사항(공정공시)」라는 **정상 공시**이고, 붙여쓴
        "공시의무위반"이라는 표기가 0건이다.
        """
        from dart_risk_mcp.core.signals import SIGNAL_TYPES
        kws = {s["key"]: s["keywords"] for s in SIGNAL_TYPES}["DISCLOSURE_VIOL"]
        for dead in ("공시의무위반", "공시누락", "중요정보누락",
                     "발행철회", "공시철회", "보고서미제출"):
            with self.subTest(title=dead):
                self.assertNotIn(dead, kws)


class TestDisclosureViolKeywordExpansion(unittest.TestCase):
    """taxonomy 4.3 재정의 + DISCLOSURE_VIOL 키워드 보강 검증.

    2026-06-17~2026-08-15(60일) 시장 전체 30,765건 실측: DISCLOSURE_VIOL이
    실제로 잡는 51건/16종 전부가 「불성실공시법인지정(예고)」 계열이었다.
    정정 제외 24,350건에서 "보고서미제출"·"제출지연"·"공시위반" 3개
    키워드가 기존 키워드가 놓치던 실제 DART 제목을 오탐 0건으로 추가
    포착했다(실제 관측된 제목으로 회귀 가드).
    """

    # ⚠ 아래 세 픽스처는 2026-08-22까지 **공백을 지운 형태**였다. DART 실제
    # 제목에는 공백이 들어가는데(「주권매매거래정지              (사업보고서
    # 미제출)」) 정규화된 문자열로 테스트해서, "보고서미제출"(붙여쓰기)
    # 키워드가 실전에서 1년 내내 0건인 것을 못 잡았다. 실제 제목 그대로 쓴다.

    def test_report_not_submitted_real_title_matches(self):
        matched = match_signals("주권매매거래정지              (사업보고서 미제출)")
        keys = {s["key"] for s in matched}
        self.assertIn("DISCLOSURE_VIOL", keys)

    def test_audit_report_submission_delay_real_title_matches(self):
        for real in ("기타경영사항(자율공시)              (감사보고서 제출 지연)",
                     "기타경영사항(자율공시)              (감사보고서 제출지연)",
                     "기타경영사항(자율공시)              (감사보고서 지연 제출)"):
            with self.subTest(title=real):
                keys = {s["key"] for s in match_signals(real)}
                self.assertIn("DISCLOSURE_VIOL", keys)

    def test_disclosure_violation_penalty_real_title_matches(self):
        matched = match_signals(
            "기타시장안내              (공시위반제재금 미납에 따른 가중벌점 부과)")
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
