"""Beneish 개별 변수 6종 (compute_beneish_variables, PR-5) 테스트."""
import unittest

from dart_risk_mcp.core.dart_client import compute_beneish_variables


def _by_key(result):
    return {r["key"]: r for r in result}


class TestComputeBeneishVariables(unittest.TestCase):
    FULL_CUR = {
        "매출액": 1000, "매출채권": 300, "매출총이익": 200,
        "유동자산": 500, "유형자산": 300, "자산총계": 1000,
        "판매비와관리비": 100, "부채총계": 600,
    }
    FULL_PRI = {
        "매출액": 1000, "매출채권": 200, "매출총이익": 400,
        "유동자산": 600, "유형자산": 300, "자산총계": 1000,
        "판매비와관리비": 150, "부채총계": 500,
    }

    def test_all_six_computed(self):
        d = _by_key(compute_beneish_variables(self.FULL_CUR, self.FULL_PRI))
        self.assertEqual(set(d.keys()), {"DSRI", "GMI", "AQI", "SGI", "SGAI", "LVGI"})

    def test_values(self):
        d = _by_key(compute_beneish_variables(self.FULL_CUR, self.FULL_PRI))
        self.assertAlmostEqual(d["DSRI"]["value"], 1.5)   # (300/1000)/(200/1000)
        self.assertAlmostEqual(d["GMI"]["value"], 2.0)    # (400/1000)/(200/1000) — 마진 악화
        self.assertAlmostEqual(d["AQI"]["value"], 2.0)    # (1-0.8)/(1-0.9)
        self.assertAlmostEqual(d["SGI"]["value"], 1.0)
        self.assertAlmostEqual(d["SGAI"]["value"], 100/150)
        self.assertAlmostEqual(d["LVGI"]["value"], 1.2)   # 0.6/0.5

    def test_gmi_falls_back_to_cogs(self):
        cur = {"매출액": 1000, "매출원가": 800}
        pri = {"매출액": 1000, "매출원가": 600}
        d = _by_key(compute_beneish_variables(cur, pri))
        # GM_c=200, GM_p=400 → GMI=(400/1000)/(200/1000)=2.0
        self.assertAlmostEqual(d["GMI"]["value"], 2.0)

    def test_missing_accounts_skip_variables(self):
        cur = {"매출액": 1000, "매출채권": 300}
        pri = {"매출액": 500, "매출채권": 100}
        d = _by_key(compute_beneish_variables(cur, pri))
        self.assertIn("DSRI", d)
        self.assertIn("SGI", d)
        self.assertNotIn("AQI", d)
        self.assertNotIn("LVGI", d)

    def test_zero_denominators_no_crash(self):
        cur = {"매출액": 0, "매출채권": 300, "자산총계": 0, "부채총계": 10,
               "유동자산": 1, "유형자산": 1}
        pri = dict(cur)
        self.assertEqual(compute_beneish_variables(cur, pri), [])

    def test_empty_inputs(self):
        self.assertEqual(compute_beneish_variables({}, {}), [])

    def test_no_mscore_or_grades_in_output(self):
        # v0.8.5: 합산 점수·등급 표현이 결과 구조에 없음
        result = compute_beneish_variables(self.FULL_CUR, self.FULL_PRI)
        for r in result:
            self.assertEqual(set(r.keys()), {"key", "name", "value", "meaning"})
            self.assertNotIn("score", str(r).lower())
            self.assertNotIn("m_score", str(r).lower())


if __name__ == "__main__":
    unittest.main()
