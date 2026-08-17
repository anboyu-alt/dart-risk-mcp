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


class TestFetchListPage(unittest.TestCase):
    """리뷰 fix — 일시적 실패와 '연도 끝'(정상 응답, 행 없음)을 구분한다.

    구 버전은 요청 실패·디코딩 신뢰불가를 전부 빈 문자열로 뭉갰다. main
    루프가 빈 문자열을 '이 연도의 마지막 페이지'로 오인해, 네트워크가 한 번
    흔들리면 이후 페이지 전체가 조용히 누락됐다. fetch_list_page는 이제
    (html, ok) 튜플로 성공 여부를 명시적으로 반환한다. 네트워크 없이
    fetch 주입만으로 검증한다.
    """

    def test_fetch_exception_returns_not_ok(self):
        def boom(url):
            raise ConnectionError("network down")

        html, ok = collect.fetch_list_page(2024, 1, fetch=boom)
        self.assertEqual(html, "")
        self.assertFalse(ok)

    def test_normal_bytes_return_ok(self):
        def fake_fetch(url):
            return _FIXTURE.read_bytes()

        html, ok = collect.fetch_list_page(2024, 1, fetch=fake_fetch)
        self.assertTrue(ok)
        self.assertIn("자본시장", html)

    def test_untrusted_decode_returns_not_ok(self):
        # utf-8/euc-kr/cp949 모두 실패하고 대체문자(U+FFFD) 비율이 임계를
        # 넘는 바이트열 — decode_page가 신뢰 불가로 판정하는 입력이다.
        def garbled_fetch(url):
            return b"\xff\xfe" * 50

        html, ok = collect.fetch_list_page(2024, 1, fetch=garbled_fetch)
        self.assertEqual(html, "")
        self.assertFalse(ok)


class TestShouldStopYear(unittest.TestCase):
    """연속 실패 3회를 넘으면(사이트 장애로 간주) 그 연도를 중단하는 판정."""

    def test_below_threshold_continues(self):
        self.assertFalse(collect.should_stop_year(1))
        self.assertFalse(collect.should_stop_year(2))

    def test_at_or_above_threshold_stops(self):
        self.assertTrue(collect.should_stop_year(3))
        self.assertTrue(collect.should_stop_year(4))


class TestCheckOutputConflict(unittest.TestCase):
    """리뷰 fix — --resume 없이 재실행하면 출력이 중복 append되던 문제.

    출력 파일을 항상 append 모드로 열기 때문에 플래그 없는 재실행은 막아야
    한다. tempfile로 실제 파일 존재 여부를 검증한다(네트워크 없음).
    """

    def test_no_existing_file_is_fine(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.jsonl"
            collect.check_output_conflict(out_path, resume=False, overwrite=False, dry_run=False)  # raises 없음

    def test_existing_file_without_flags_raises(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.jsonl"
            out_path.write_text('{"id": "1"}\n{"id": "2"}\n', encoding="utf-8")
            with self.assertRaises(SystemExit) as ctx:
                collect.check_output_conflict(out_path, resume=False, overwrite=False, dry_run=False)
            self.assertIn("2건", str(ctx.exception))
            self.assertIn("--resume", str(ctx.exception))
            self.assertIn("--overwrite", str(ctx.exception))

    def test_existing_file_with_resume_is_fine(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.jsonl"
            out_path.write_text('{"id": "1"}\n', encoding="utf-8")
            collect.check_output_conflict(out_path, resume=True, overwrite=False, dry_run=False)  # raises 없음

    def test_existing_file_with_overwrite_is_fine(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.jsonl"
            out_path.write_text('{"id": "1"}\n', encoding="utf-8")
            collect.check_output_conflict(out_path, resume=False, overwrite=True, dry_run=False)  # raises 없음

    def test_existing_file_with_dry_run_is_fine(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.jsonl"
            out_path.write_text('{"id": "1"}\n', encoding="utf-8")
            collect.check_output_conflict(out_path, resume=False, overwrite=False, dry_run=True)  # raises 없음


class TestResetForOverwrite(unittest.TestCase):
    def test_overwrite_removes_both_out_and_state(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.jsonl"
            state_path = Path(tmp) / "state.json"
            out_path.write_text('{"id": "1"}\n', encoding="utf-8")
            state_path.write_text('{"done_pages": ["2010:1"]}', encoding="utf-8")

            collect.reset_for_overwrite(out_path, state_path, overwrite=True, dry_run=False)

            self.assertFalse(out_path.exists())
            self.assertFalse(state_path.exists())

    def test_overwrite_missing_files_does_not_raise(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "missing_out.jsonl"
            state_path = Path(tmp) / "missing_state.json"
            collect.reset_for_overwrite(out_path, state_path, overwrite=True, dry_run=False)  # raises 없음

    def test_without_overwrite_flag_leaves_files_untouched(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.jsonl"
            out_path.write_text('{"id": "1"}\n', encoding="utf-8")
            collect.reset_for_overwrite(out_path, out_path, overwrite=False, dry_run=False)
            self.assertTrue(out_path.exists())

    def test_dry_run_leaves_files_untouched_even_with_overwrite(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.jsonl"
            out_path.write_text('{"id": "1"}\n', encoding="utf-8")
            collect.reset_for_overwrite(out_path, out_path, overwrite=True, dry_run=True)
            self.assertTrue(out_path.exists())


if __name__ == "__main__":
    unittest.main()
