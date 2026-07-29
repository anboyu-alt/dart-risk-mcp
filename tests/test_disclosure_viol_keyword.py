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


if __name__ == "__main__":
    unittest.main()
