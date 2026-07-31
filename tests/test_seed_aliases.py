import unittest


class TestParseHeaderCorpName(unittest.TestCase):
    """공시 원문 헤더 회사명 파싱 (scripts/seed_aliases_from_headers.py).

    fixture는 실측 원문(fetch_document_text 태그 제거 후 텍스트)에서 그대로
    가져온 것 — rcept_no 20230314800431(한화오회, 접수 당시 상호 대우조선해양).
    """

    def test_extracts_corp_name_before_amendment(self):
        import scripts.seed_aliases_from_headers as sah
        # 실측: fetch_document_text('20230314800431', ...)
        txt = ("대우조선해양/단일판매ㆍ공급계약체결/(2023.03.14)단일판매ㆍ공급계약체결 "
               "단일판매ㆍ공급계약 체결 1. 판매ㆍ공급계약 구분 공사수주 - 체결계약명 "
               "LNG 운반선 2척 2. 계약내역 계약금액(원) 679,400,000,000")
        self.assertEqual(
            sah.parse_header_corp_name(txt, "단일판매ㆍ공급계약체결"),
            "대우조선해양")

    def test_extracts_corp_name_rename_notice(self):
        import scripts.seed_aliases_from_headers as sah
        txt = "옵티코어/상호변경안내/(2023.03.31)상호변경안내 1. 변경전 상호 ..."
        self.assertEqual(
            sah.parse_header_corp_name(txt, "상호변경안내"),
            "옵티코어")

    def test_no_header_returns_empty(self):
        import scripts.seed_aliases_from_headers as sah
        txt = "본문에 슬래시 구분 헤더가 전혀 없는 일반 공시 텍스트입니다."
        self.assertEqual(sah.parse_header_corp_name(txt, "단일판매ㆍ공급계약체결"), "")

    def test_empty_inputs_return_empty(self):
        import scripts.seed_aliases_from_headers as sah
        self.assertEqual(sah.parse_header_corp_name("", "제목"), "")
        self.assertEqual(sah.parse_header_corp_name("아무개/제목/(2024.01.01)", ""), "")

    def test_report_name_mismatch_is_not_captured(self):
        # 헤더의 두 번째 필드가 list.json report_nm과 다르면(우연한 '/' 나열)
        # 오탐으로 보고 빈 문자열을 반환해야 한다.
        import scripts.seed_aliases_from_headers as sah
        txt = "무관회사/전혀다른제목/(2024.01.01)본문"
        self.assertEqual(sah.parse_header_corp_name(txt, "단일판매ㆍ공급계약체결"), "")

    def test_amendment_prefixed_report_nm_still_matches(self):
        import scripts.seed_aliases_from_headers as sah
        txt = "대우조선해양/단일판매ㆍ공급계약체결/(2023.03.14)단일판매ㆍ공급계약체결 본문"
        self.assertEqual(
            sah.parse_header_corp_name(txt, "[기재정정]단일판매ㆍ공급계약체결"),
            "대우조선해양")


class TestPickSeedDisclosure(unittest.TestCase):
    """정기보고서를 피하고 가장 오래된 그 외 공시를 고르는지 (순수 함수)."""

    def test_picks_oldest_non_periodic(self):
        import scripts.seed_aliases_from_headers as sah
        discs = [
            {"rcept_no": "3", "rcept_dt": "20240301", "report_nm": "임원ㆍ주요주주특정증권등소유상황보고서"},
            {"rcept_no": "1", "rcept_dt": "20230101", "report_nm": "사업보고서"},
            {"rcept_no": "2", "rcept_dt": "20230601", "report_nm": "단일판매ㆍ공급계약체결"},
        ]
        chosen = sah.pick_seed_disclosure(discs)
        self.assertEqual(chosen["rcept_no"], "2")

    def test_all_periodic_falls_back_to_oldest(self):
        import scripts.seed_aliases_from_headers as sah
        discs = [
            {"rcept_no": "2", "rcept_dt": "20230601", "report_nm": "반기보고서"},
            {"rcept_no": "1", "rcept_dt": "20230101", "report_nm": "사업보고서"},
        ]
        chosen = sah.pick_seed_disclosure(discs)
        self.assertEqual(chosen["rcept_no"], "1")

    def test_empty_list_returns_none(self):
        import scripts.seed_aliases_from_headers as sah
        self.assertIsNone(sah.pick_seed_disclosure([]))

    def test_ignores_input_order(self):
        # 호출자가 이미 정렬해 넘겨도, 안 넘겨도 결과는 같아야 한다(내부 재정렬).
        import scripts.seed_aliases_from_headers as sah
        discs_desc = [
            {"rcept_no": "2", "rcept_dt": "20230601", "report_nm": "단일판매ㆍ공급계약체결"},
            {"rcept_no": "1", "rcept_dt": "20230101", "report_nm": "타법인주식및출자증권양수결정"},
        ]
        self.assertEqual(sah.pick_seed_disclosure(discs_desc)["rcept_no"], "1")


class TestIsValidAliasRecord(unittest.TestCase):
    """corp-aliases.json에 실제로 섞여 있던 쓰레기 5건을 규칙으로 걸러내는지."""

    def test_dash_only_old_name_invalid(self):
        from scripts.backfill_corp_aliases import is_valid_alias_record
        self.assertFalse(is_valid_alias_record("-", "MAKUS,Inc."))

    def test_english_corp_name_row_capture_invalid(self):
        from scripts.backfill_corp_aliases import is_valid_alias_record
        self.assertFalse(is_valid_alias_record(
            "Daehan Green Power Corporation", "에이전트에이아이"))
        self.assertFalse(is_valid_alias_record(
            "Korea Renewable Power Energy Corporation", "DGP"))

    def test_co_ltd_suffix_invalid(self):
        from scripts.backfill_corp_aliases import is_valid_alias_record
        self.assertFalse(is_valid_alias_record(
            "Legochem Biosciences co., Ltd. -",
            "LigaChem Biosciences Inc. 내용 수정 상호변경안내"))

    def test_rename_notice_phrase_captured_as_name_invalid(self):
        from scripts.backfill_corp_aliases import is_valid_alias_record
        self.assertFalse(is_valid_alias_record(
            "영문", "- - MAKUS, Inc. - MAKUS, Inc. - - 상호변경안내"))

    def test_normal_korean_rename_valid(self):
        from scripts.backfill_corp_aliases import is_valid_alias_record
        self.assertTrue(is_valid_alias_record("가온미디어", "가온그룹"))
        self.assertTrue(is_valid_alias_record("알로이스", "아틀라스링크"))

    def test_short_english_market_name_kept(self):
        # "DGP"/"E8" 류 짧은 영문 시장 표기는 실제 상호이므로 유지돼야 한다.
        from scripts.backfill_corp_aliases import is_valid_alias_record
        self.assertTrue(is_valid_alias_record("DGP", "에이전트에이아이"))
        self.assertTrue(is_valid_alias_record("E8", "이에이트"))


if __name__ == "__main__":
    unittest.main()
