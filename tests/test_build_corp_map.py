import unittest


class TestMergeAliases(unittest.TestCase):
    """merge_aliases 순수 함수 단위 테스트 (scripts/build_corp_map.py)."""

    def test_renamed_corp_code_creates_alias(self):
        import scripts.build_corp_map as bcm
        old_map = {"알로이스": ["01309795", "297570"]}
        new_map = {"아틀라스링크": ["01309795", "297570"]}
        aliases = bcm.merge_aliases(old_map, new_map, {})
        self.assertIn("알로이스", aliases)
        self.assertEqual(aliases["알로이스"], {
            "corp_code": "01309795", "stock_code": "297570", "current": "아틀라스링크",
        })

    def test_existing_aliases_preserved(self):
        import scripts.build_corp_map as bcm
        existing = {"옛이름": {"corp_code": "c1", "stock_code": "111111", "current": "현재이름"}}
        # 이번 재생성에서 c1은 등장하지 않음(예: 상장폐지) — 그래도 별칭은 유지
        old_map = {"현재이름": ["c1", "111111"]}
        new_map = {}
        aliases = bcm.merge_aliases(old_map, new_map, existing)
        self.assertEqual(aliases["옛이름"], existing["옛이름"])

    def test_second_rename_updates_current(self):
        import scripts.build_corp_map as bcm
        # 이전 실행에서 이미 "A"→"B" 별칭이 있었는데, 이번엔 "B"→"C"로 다시 개명
        existing = {"A": {"corp_code": "c1", "stock_code": "111111", "current": "B"}}
        old_map = {"B": ["c1", "111111"]}
        new_map = {"C": ["c1", "222222"]}
        aliases = bcm.merge_aliases(old_map, new_map, existing)
        # 2차 개명으로 생긴 새 별칭
        self.assertEqual(aliases["B"]["current"], "C")
        # 기존 별칭의 current/stock_code도 최신으로 갱신(2차 개명 반영)
        self.assertEqual(aliases["A"]["current"], "C")
        self.assertEqual(aliases["A"]["stock_code"], "222222")

    def test_unchanged_name_creates_no_alias(self):
        import scripts.build_corp_map as bcm
        old_map = {"삼성전자": ["00126380", "005930"]}
        new_map = {"삼성전자": ["00126380", "005930"]}
        aliases = bcm.merge_aliases(old_map, new_map, {})
        self.assertEqual(aliases, {})

    def test_build_map_from_corp_cache_filters_unlisted_and_sorts(self):
        import scripts.build_corp_map as bcm
        corp_cache = {
            "나중회사": {"corp_code": "c2", "stock_code": "222222"},
            "먼저회사": {"corp_code": "c1", "stock_code": "111111"},
            "비상장회사": {"corp_code": "c3", "stock_code": ""},
        }
        result = bcm.build_map_from_corp_cache(corp_cache)
        self.assertEqual(list(result.keys()), ["나중회사", "먼저회사"])
        self.assertNotIn("비상장회사", result)
        self.assertEqual(result["먼저회사"], ["c1", "111111"])


class TestExtractRenamesFromText(unittest.TestCase):
    """상호 추출 regex 단위 테스트 (scripts/backfill_corp_aliases.py)."""

    def test_extracts_before_after_with_corp_form_stripped(self):
        import scripts.backfill_corp_aliases as bca
        # 실례 문구(rcept_no 20260612900563, 태그 제거 후 텍스트)
        txt = ("가. 변경전 국문 주식회사 알로이스 영문 ALOYS Inc. "
               "나. 변경후 국문 주식회사 아틀라스링크 영문 ATLAS LINK Inc.")
        olds, after = bca.extract_renames_from_text(txt)
        self.assertEqual(olds, {"알로이스"})
        self.assertEqual(after, "아틀라스링크")

    def test_falls_back_to_corp_name_when_after_not_found(self):
        import scripts.backfill_corp_aliases as bca
        txt = "가. 변경전 국문 주식회사 옛날회사 영문 OLD Corp."
        olds, after = bca.extract_renames_from_text(txt, fallback_after="주식회사 새이름")
        self.assertEqual(olds, {"옛날회사"})
        self.assertEqual(after, "새이름")

    def test_past_rename_history_extracted(self):
        import scripts.backfill_corp_aliases as bca
        txt = ("가. 변경전 국문 주식회사 지금이름 영문 NOW Inc. "
               "나. 변경후 국문 주식회사 최신이름 영문 NEW Inc. "
               "과거 상호변경 내역: 변경전: 한솔시큐어 주식회사 → 변경후: 지금이름 주식회사")
        olds, after = bca.extract_renames_from_text(txt)
        self.assertEqual(after, "최신이름")
        self.assertIn("지금이름", olds)
        self.assertIn("한솔시큐어", olds)

    def test_old_name_equal_to_after_is_dropped(self):
        import scripts.backfill_corp_aliases as bca
        txt = "가. 변경전 국문 주식회사 동일이름 영문 SAME Inc. 나. 변경후 국문 주식회사 동일이름 영문 SAME Inc."
        olds, after = bca.extract_renames_from_text(txt)
        self.assertEqual(olds, set())
        self.assertEqual(after, "동일이름")


class TestStripCorpForm(unittest.TestCase):
    def test_strips_prefix_and_suffix_forms(self):
        import scripts.backfill_corp_aliases as bca
        self.assertEqual(bca.strip_corp_form("주식회사 알로이스"), "알로이스")
        self.assertEqual(bca.strip_corp_form("아틀라스링크(주)"), "아틀라스링크")
        self.assertEqual(bca.strip_corp_form("㈜아틀라스링크"), "아틀라스링크")
        self.assertEqual(bca.strip_corp_form("삼성전자"), "삼성전자")


class TestMergeBackfillRecords(unittest.TestCase):
    def test_adds_new_alias_from_record(self):
        import scripts.backfill_corp_aliases as bca
        records = [{"old_name": "알로이스", "new_name": "아틀라스링크",
                    "corp_code": "01309795", "stock_code": "297570",
                    "rcept_no": "20260612900563", "date": "2026-06-12"}]
        merged = bca.merge_backfill_records({}, records)
        self.assertEqual(merged["알로이스"], {
            "corp_code": "01309795", "stock_code": "297570", "current": "아틀라스링크",
        })

    def test_existing_aliases_preserved_when_not_reencountered(self):
        import scripts.backfill_corp_aliases as bca
        existing = {"옛이름": {"corp_code": "c1", "stock_code": "111111", "current": "현재이름"}}
        merged = bca.merge_backfill_records(existing, [])
        self.assertEqual(merged, existing)

    def test_reencountered_old_name_updates_entry(self):
        import scripts.backfill_corp_aliases as bca
        existing = {"옛이름": {"corp_code": "c1", "stock_code": "111111", "current": "중간이름"}}
        records = [{"old_name": "옛이름", "new_name": "최신이름", "corp_code": "c1",
                    "stock_code": "222222", "rcept_no": "R2", "date": "2026-07-01"}]
        merged = bca.merge_backfill_records(existing, records)
        self.assertEqual(merged["옛이름"]["current"], "최신이름")
        self.assertEqual(merged["옛이름"]["stock_code"], "222222")

    def test_skips_record_where_old_equals_new(self):
        import scripts.backfill_corp_aliases as bca
        records = [{"old_name": "이름", "new_name": "이름", "corp_code": "c1",
                    "stock_code": "111111", "rcept_no": "R1", "date": "2026-01-01"}]
        merged = bca.merge_backfill_records({}, records)
        self.assertEqual(merged, {})


if __name__ == "__main__":
    unittest.main()
