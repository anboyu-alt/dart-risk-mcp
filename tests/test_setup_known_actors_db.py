import unittest
from unittest.mock import patch, MagicMock


class TestBackfillKnownCompanies(unittest.TestCase):
    def _page(self, name, existing_companies=None):
        return {
            "id": f"pid-{name}",
            "properties": {
                "인물명": {"title": [{"plain_text": name}]},
                "관련기업": {"multi_select": [{"name": c} for c in (existing_companies or [])]},
            },
        }

    def test_tags_known_names_with_empty_companies(self):
        import scripts.setup_known_actors_db as sdb
        query_resp = MagicMock()
        query_resp.status_code = 200
        query_resp.json.return_value = {
            "results": [self._page("LIU HUAN"), self._page("신승수"),
                       self._page("외톨이")],  # 알려지지 않은 이름 — 스킵
            "has_more": False,
        }
        patch_resp = MagicMock()
        patch_resp.status_code = 200
        with patch.object(sdb.requests, "post", return_value=query_resp), \
             patch.object(sdb.requests, "patch", return_value=patch_resp) as patch_call:
            updated = sdb.backfill_known_companies("t", "db")
        self.assertEqual(updated, 2)  # LIU HUAN, 신승수만
        # LIU HUAN 페이로드에 씨엑스아이·헝셩그룹이 포함되는지 확인
        liu_call = next(c for c in patch_call.call_args_list
                        if "pid-LIU HUAN" in c.args[0])
        names = {o["name"] for o in
                liu_call.kwargs["json"]["properties"]["관련기업"]["multi_select"]}
        self.assertEqual(names, {"씨엑스아이", "헝셩그룹"})

    def test_skips_already_tagged_rows(self):
        # 이미 관련기업이 채워진 행은 덮어쓰지 않는다
        import scripts.setup_known_actors_db as sdb
        query_resp = MagicMock()
        query_resp.status_code = 200
        query_resp.json.return_value = {
            "results": [self._page("LIU HUAN", existing_companies=["기존태그"])],
            "has_more": False,
        }
        with patch.object(sdb.requests, "post", return_value=query_resp), \
             patch.object(sdb.requests, "patch") as patch_call:
            updated = sdb.backfill_known_companies("t", "db")
        self.assertEqual(updated, 0)
        patch_call.assert_not_called()

    def test_paginates_through_all_results(self):
        import scripts.setup_known_actors_db as sdb
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = {
            "results": [self._page("신승수")], "has_more": True, "next_cursor": "c1",
        }
        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = {
            "results": [self._page("LIU HUAN")], "has_more": False,
        }
        patch_resp = MagicMock()
        patch_resp.status_code = 200
        with patch.object(sdb.requests, "post", side_effect=[page1, page2]) as post_call, \
             patch.object(sdb.requests, "patch", return_value=patch_resp):
            updated = sdb.backfill_known_companies("t", "db")
        self.assertEqual(updated, 2)
        self.assertEqual(post_call.call_count, 2)
        self.assertEqual(post_call.call_args_list[1].kwargs["json"]["start_cursor"], "c1")


class TestMainDispatch(unittest.TestCase):
    def test_main_migrates_when_db_id_present(self):
        # DB_KNOWN_ACTORS 설정 시 create 경로를 타지 않고 마이그레이션만 수행
        import scripts.setup_known_actors_db as sdb
        with patch.dict("os.environ", {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}), \
             patch.object(sdb, "ensure_company_property", return_value=True) as ensure_call, \
             patch.object(sdb, "backfill_known_companies", return_value=3) as backfill_call, \
             patch.object(sdb, "create_registry_db") as create_call:
            sdb.main()
        ensure_call.assert_called_once_with("t", "db")
        backfill_call.assert_called_once_with("t", "db")
        create_call.assert_not_called()

    def test_main_creates_when_db_id_absent(self):
        import scripts.setup_known_actors_db as sdb
        import os
        with patch.dict("os.environ", {"NOTION_TOKEN": "t",
                                       "NOTION_PARENT_PAGE_ID": "p"}, clear=False):
            os.environ.pop("DB_KNOWN_ACTORS", None)
            with patch.object(sdb, "create_registry_db", return_value="new-db") as create_call, \
                 patch.object(sdb, "seed_from_json", return_value=0):
                sdb.main()
        create_call.assert_called_once_with("t", "p")

    def test_main_raises_when_migration_property_fails(self):
        import scripts.setup_known_actors_db as sdb
        with patch.dict("os.environ", {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}), \
             patch.object(sdb, "ensure_company_property", return_value=False):
            with self.assertRaises(SystemExit):
                sdb.main()


if __name__ == "__main__":
    unittest.main()
