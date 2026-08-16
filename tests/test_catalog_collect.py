"""Phase A 게시판 목록 수집·필터 회귀 테스트.

설계 근거(2026-08-16 실측, 600건 표본): 금감원 보도자료는 은행·보험·서민금융이
대부분이라 전부 열면 낭비다. 목록의 담당부서 컬럼으로 거르면 24.5%로 좁혀지고,
연도별 편차도 20~31%로 안정적이다(부서명이 계속 개편되는데도 부분일치가 견딤).
"""
import json
import unittest
from pathlib import Path

from scripts.catalog import collect

_FIXTURE = Path(__file__).parent / "fixtures" / "catalog" / "fss_list_page.html"


class TestParseListRows(unittest.TestCase):
    def setUp(self):
        self.rows = collect.parse_list_rows(_FIXTURE.read_text(encoding="utf-8"))

    def test_parses_all_rows(self):
        self.assertEqual(len(self.rows), 4)

    def test_extracts_fields(self):
        r = self.rows[0]
        self.assertEqual(r["id"], "12170")
        self.assertEqual(r["title"], "자본시장 불공정거래에 대한 조사결과 조치")
        self.assertEqual(r["dept"], "자본시장조사2국")
        self.assertEqual(r["date"], "2015-12-31")

    def test_decodes_html_entities(self):
        # 목록 href의 &amp; 와 제목의 특수문자가 정리돼야 한다
        r = self.rows[2]
        self.assertNotIn("&amp;", r["title"])
        self.assertIn("가이드북", r["title"])

    def test_multi_dept_preserved_raw(self):
        self.assertEqual(self.rows[1]["dept"], "조사1국/조사3국")

    def test_empty_html_yields_nothing(self):
        self.assertEqual(collect.parse_list_rows("<html><body>없음</body></html>"), [])


class TestDeptFilter(unittest.TestCase):
    def test_capital_market_depts_hit(self):
        for d in ("자본시장조사2국", "기업공시국", "회계심사국", "금융투자감독국",
                  "자산운용감독실", "공시심사실", "회계감리1국"):
            self.assertTrue(collect.dept_hit(d), d)

    def test_investigation_numbered_depts_hit(self):
        # '조사1국'은 '조사국'을 부분문자열로 포함하지 않는다 — 첫 설계에서 놓쳤던 결함.
        for d in ("조사1국", "조사3국", "조사1국/조사3국", "특별조사국", "공매도특별조사단"):
            self.assertTrue(collect.dept_hit(d), d)

    def test_unrelated_depts_miss(self):
        for d in ("은행감독국", "보험감독국", "서민금융지원국", "금융교육국",
                  "저축은행감독국", "거시감독국"):
            self.assertFalse(collect.dept_hit(d), d)

    def test_insurance_investigation_excluded(self):
        # '보험조사국'은 보험사기 담당이라 '조사'류에 걸려도 제외해야 한다.
        self.assertFalse(collect.dept_hit("보험조사국"))
        self.assertFalse(collect.dept_hit("보험감리실"))

    def test_slash_separated_any_hit(self):
        self.assertTrue(collect.dept_hit("금융중심지지원센터/기업공시국"))


class TestTitleFilter(unittest.TestCase):
    def test_keywords_detected(self):
        self.assertIn("불공정거래", collect.title_keywords("자본시장 불공정거래 조사결과"))
        self.assertIn("전환사채", collect.title_keywords("전환사채 발행 관련 유의사항"))

    def test_no_keyword(self):
        self.assertEqual(collect.title_keywords("은행지주회사 선정"), [])

    def test_general_notice_detected(self):
        for t in ("영문 가이드북 제작ㆍ발간", "회계현안설명회 개최", "금융투자업 인가 의결",
                  "검사 사례집 발간·배포", "홍보아이디어 공모전 수상작 발표"):
            self.assertTrue(collect.is_general_notice(t), t)

    def test_enforcement_titles_not_general_notice(self):
        for t in ("공시위반 법인에 대한 조치", "사업보고서 및 감사보고서 등에 대한 조사·감리결과 조치",
                  "공매도의 제한 위반행위 조치"):
            self.assertFalse(collect.is_general_notice(t), t)


class TestPassesFilter(unittest.TestCase):
    def setUp(self):
        self.rows = collect.parse_list_rows(_FIXTURE.read_text(encoding="utf-8"))

    def test_four_way_split(self):
        got = [collect.passes_filter(r) for r in self.rows]
        # 0: 부서+키워드 통과 / 1: 부서(조사1국)+키워드 통과 / 2: 부서 맞지만 일반안내 / 3: 완전 탈락
        self.assertEqual(got, [True, True, False, False])

    def test_keyword_only_row_passes(self):
        # 부서가 비자본시장이어도 제목 키워드가 있으면 통과해야 한다
        row = {"id": "1", "title": "불공정거래 신고 포상금 지급", "dept": "총무국", "date": "2024-01-01"}
        self.assertTrue(collect.passes_filter(row))

    def test_general_notice_overrides_dept_and_keyword(self):
        row = {"id": "2", "title": "전환사채 관련 설명회 개최", "dept": "기업공시국", "date": "2024-01-01"}
        self.assertFalse(collect.passes_filter(row))


class TestToRecord(unittest.TestCase):
    def test_builds_standard_record(self):
        row = {"id": "133239", "title": "불공정거래 조사결과 조치", "dept": "조사1국", "date": "2024-01-18"}
        rec = collect.to_record(row)
        self.assertEqual(rec["source"], "fss")
        self.assertEqual(rec["id"], "133239")
        self.assertEqual(rec["dept"], "조사1국")
        self.assertTrue(rec["url"].startswith("https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId=133239"))
        self.assertIn("불공정거래", rec["matched_keywords"])
        self.assertTrue(rec["matched_dept"])


class TestState(unittest.TestCase):
    def test_roundtrip_and_corrupt_handling(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "state.json"
            self.assertEqual(collect.load_state(p), {"done_pages": []})
            collect.save_state(p, {"done_pages": ["2010:1"]})
            self.assertEqual(collect.load_state(p)["done_pages"], ["2010:1"])
            p.write_text("{ not json", encoding="utf-8")
            self.assertEqual(collect.load_state(p), {"done_pages": []})

    def test_page_key_format(self):
        self.assertEqual(collect.page_key(2010, 3), "2010:3")


if __name__ == "__main__":
    unittest.main()
