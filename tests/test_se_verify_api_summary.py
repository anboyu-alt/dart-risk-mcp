"""scripts/se_verify_api.py 최종 요약 로직.

네트워크·Supabase 자격증명 없이도 검증 가능하도록 요약 문자열 생성을
`summary_lines()`로 분리했다. `--steps` 기본값이 낮아 section·disclosure
실동작 검증을 건너뛰었을 때도 "전부 통과했습니다"라고 말하면 안 된다는
회귀를 이 테스트가 막는다.
"""
import unittest

from scripts.se_verify_api import summary_lines


class TestSummaryLines(unittest.TestCase):
    def test_all_pass_no_skips_reports_all_passed(self):
        lines = summary_lines(failures=[], skipped=[])
        self.assertEqual(lines, ["\n전부 통과했습니다."])

    def test_failures_are_listed(self):
        lines = summary_lines(failures=["작업 생성 (201)"], skipped=[])
        self.assertIn("\n실패 1건:", lines)
        self.assertIn("  - 작업 생성 (201)", lines)
        self.assertNotIn("\n전부 통과했습니다.", lines)

    def test_skipped_checks_are_listed_and_never_reported_as_all_passed(self):
        """이 브랜치 리뷰에서 지적된 결함 그 자체 — --steps 기본값(2)으로
        section·disclosure 실동작 검증을 건너뛰어도 "전부 통과했습니다"가
        찍히면 검증 스크립트가 거짓을 말하는 것이다."""
        lines = summary_lines(failures=[], skipped=["section 실동작·격리 검증"])
        joined = "\n".join(lines)
        self.assertIn("건너뜀 1건", joined)
        self.assertIn("section 실동작·격리 검증", joined)
        self.assertNotIn("전부 통과했습니다", joined)
        self.assertIn("전부 통과라고 볼 수 없습니다", joined)

    def test_failures_and_skips_both_reported(self):
        lines = summary_lines(failures=["A"], skipped=["B"])
        joined = "\n".join(lines)
        self.assertIn("실패 1건", joined)
        self.assertIn("건너뜀 1건", joined)
        self.assertNotIn("전부 통과했습니다", joined)


if __name__ == "__main__":
    unittest.main()
