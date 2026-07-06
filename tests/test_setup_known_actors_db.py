import unittest
from unittest.mock import patch, MagicMock


class TestBackfillKnownCompanies(unittest.TestCase):
    def _page(self, name, existing_companies=None, kind=""):
        return {
            "id": f"pid-{name}",
            "properties": {
                "인물명": {"title": [{"plain_text": name}]},
                "관련기업": {"multi_select": [{"name": c} for c in (existing_companies or [])]},
                "구분": {"select": {"name": kind} if kind else None},
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
        # LIU HUAN·신승수는 관련기업+구분, 외톨이는 구분(개인) 소급 → 3건 모두 갱신
        self.assertEqual(updated, 3)
        # LIU HUAN 페이로드에 씨엑스아이·헝셩그룹이 포함되는지 확인
        liu_call = next(c for c in patch_call.call_args_list
                        if "pid-LIU HUAN" in c.args[0])
        names = {o["name"] for o in
                liu_call.kwargs["json"]["properties"]["관련기업"]["multi_select"]}
        self.assertEqual(names, {"씨엑스아이", "헝셩그룹"})

    def test_skips_fully_tagged_rows(self):
        # 관련기업·구분이 모두 채워진 행은 건드리지 않는다
        import scripts.setup_known_actors_db as sdb
        query_resp = MagicMock()
        query_resp.status_code = 200
        query_resp.json.return_value = {
            "results": [self._page("LIU HUAN", existing_companies=["기존태그"],
                                   kind="개인")],
            "has_more": False,
        }
        with patch.object(sdb.requests, "post", return_value=query_resp), \
             patch.object(sdb.requests, "patch") as patch_call:
            updated = sdb.backfill_known_companies("t", "db")
        self.assertEqual(updated, 0)
        patch_call.assert_not_called()

    def test_backfills_kind_only_when_companies_already_set(self):
        # 관련기업은 있는데 구분이 빈 행 → 구분(개인)만 소급, 관련기업 유지
        import scripts.setup_known_actors_db as sdb
        query_resp = MagicMock()
        query_resp.status_code = 200
        query_resp.json.return_value = {
            "results": [self._page("LIU HUAN", existing_companies=["기존태그"])],
            "has_more": False,
        }
        patch_resp = MagicMock()
        patch_resp.status_code = 200
        with patch.object(sdb.requests, "post", return_value=query_resp), \
             patch.object(sdb.requests, "patch", return_value=patch_resp) as patch_call:
            updated = sdb.backfill_known_companies("t", "db")
        self.assertEqual(updated, 1)
        props = patch_call.call_args.kwargs["json"]["properties"]
        self.assertEqual(props["구분"]["select"]["name"], "개인")
        self.assertNotIn("관련기업", props)

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


class TestEvidenceRecovery(unittest.TestCase):
    def _page_ev(self, name, evidence):
        return {"id": f"pid-{name}", "properties": {
            "인물명": {"title": [{"plain_text": name}]},
            "관련기업": {"multi_select": []},
            "구분": {"select": {"name": "조합"}},
            "evidence": {"rich_text": [{"plain_text": evidence}]},
        }}

    def test_recovers_companies_from_promotion_evidence(self):
        # 재PATCH 사고로 소거된 관련기업을 evidence 텍스트에서 재구성
        import scripts.setup_known_actors_db as sdb
        q = MagicMock(); q.status_code = 200
        q.json.return_value = {"results": [
            self._page_ev("에스디비조합", "문제 회사 2곳 인수자 반복 등장: CSA 코스믹·블루샤크"),
            self._page_ev("이준민", "△△전자 CB인수 인수자로 등장"),
        ], "has_more": False}
        p = MagicMock(); p.status_code = 200
        with patch.object(sdb.requests, "post", return_value=q), \
             patch.object(sdb.requests, "patch", return_value=p) as pc:
            updated = sdb.backfill_known_companies("t", "db")
        self.assertEqual(updated, 2)
        first = pc.call_args_list[0].kwargs["json"]["properties"]["관련기업"]["multi_select"]
        self.assertEqual([o["name"] for o in first], ["CSA 코스믹", "블루샤크"])
        second = pc.call_args_list[1].kwargs["json"]["properties"]["관련기업"]["multi_select"]
        self.assertEqual([o["name"] for o in second], ["△△전자"])


class TestArchiveFragments(unittest.TestCase):
    def _page(self, name):
        return {"id": f"pid-{name}", "properties": {
            "인물명": {"title": [{"plain_text": name}]}}}

    def test_archives_only_fragment_named_rows(self):
        import scripts.setup_known_actors_db as sdb
        q = MagicMock(); q.status_code = 200
        q.json.return_value = {"results": [
            self._page("으로서 결성 및"), self._page("등의 다른회사 등기임원"),
            self._page("홍길동"), self._page("교보 신기술사업투자조합"),
        ], "has_more": False}
        a = MagicMock(); a.status_code = 200
        with patch.object(sdb.requests, "post", return_value=q), \
             patch.object(sdb.requests, "patch", return_value=a) as pc:
            removed = sdb.archive_fragment_rows("t", "db")
        self.assertEqual(removed, 2)  # 조각 2개만
        archived_ids = [call.args[0] for call in pc.call_args_list]
        self.assertTrue(all("pid-홍길동" not in i for i in archived_ids))
        for call in pc.call_args_list:
            self.assertEqual(call.kwargs["json"], {"archived": True})


class TestBackfillEvidenceLinks(unittest.TestCase):
    def _page(self, name, companies, rcept="", url="https://dart.fss.or.kr",
              evidence="", linked=False):
        ev = [{"plain_text": evidence, "href": ("x" if linked else None)}]
        return {"id": f"pid-{name}", "properties": {
            "인물명": {"title": [{"plain_text": name}]},
            "관련기업": {"multi_select": [{"name": c} for c in companies]},
            "rcept_no": {"rich_text": [{"plain_text": rcept}] if rcept else []},
            "url": {"url": url},
            "evidence": {"rich_text": ev},
        }}

    def test_refresh_row_links_from_row_rcept(self):
        import scripts.setup_known_actors_db as sdb
        q = MagicMock(); q.status_code = 200
        q.json.return_value = {"results": [self._page(
            "김인수", ["△△전자"], rcept="20260101000123",
            evidence="△△전자 CB인수 인수자로 등장")], "has_more": False}
        p = MagicMock(); p.status_code = 200
        with patch.object(sdb.requests, "post", return_value=q), \
             patch.object(sdb.requests, "patch", return_value=p) as pc:
            n = sdb.backfill_evidence_links("t", "db", sightings_path="")
        self.assertEqual(n, 1)
        rich = pc.call_args.kwargs["json"]["properties"]["evidence"]["rich_text"]
        link = next(s for s in rich if s["text"].get("link"))
        self.assertIn("rcpNo=20260101000123", link["text"]["link"]["url"])

    def test_promoted_row_links_from_sightings(self):
        import scripts.setup_known_actors_db as sdb
        q = MagicMock(); q.status_code = 200
        q.json.return_value = {"results": [self._page(
            "김조합", ["에이디테크놀로지", "태웅로직스"],
            evidence="문제 회사 2곳 인수자 반복 등장: 에이디테크놀로지·태웅로직스")],
            "has_more": False}
        p = MagicMock(); p.status_code = 200
        sight = {"김조합": {"에이디테크놀로지": "20260421000499",
                          "태웅로직스": "20260422000229"}}
        with patch.object(sdb.requests, "post", return_value=q), \
             patch.object(sdb.requests, "patch", return_value=p) as pc, \
             patch.object(sdb, "_load_sightings_map", return_value=sight):
            n = sdb.backfill_evidence_links("t", "db", sightings_path="x.json")
        self.assertEqual(n, 1)
        props = pc.call_args.kwargs["json"]["properties"]
        linked = {s["text"]["content"] for s in props["evidence"]["rich_text"]
                  if s["text"].get("link")}
        self.assertEqual(linked, {"에이디테크놀로지", "태웅로직스"})
        # 대표 url도 맨몸→최신 공시로
        self.assertIn("rcpNo=20260422000229", props["url"]["url"])

    def test_skips_already_linked_rows(self):
        import scripts.setup_known_actors_db as sdb
        q = MagicMock(); q.status_code = 200
        q.json.return_value = {"results": [self._page(
            "김조합", ["A"], evidence="...", linked=True)], "has_more": False}
        with patch.object(sdb.requests, "post", return_value=q), \
             patch.object(sdb.requests, "patch") as pc, \
             patch.object(sdb, "_load_sightings_map", return_value={}):
            n = sdb.backfill_evidence_links("t", "db", sightings_path="x.json")
        self.assertEqual(n, 0)
        pc.assert_not_called()


class TestMainDispatch(unittest.TestCase):
    def test_main_migrates_when_db_id_present(self):
        # DB_KNOWN_ACTORS 설정 시 create 경로를 타지 않고 마이그레이션만 수행
        import scripts.setup_known_actors_db as sdb
        with patch.dict("os.environ", {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}), \
             patch.object(sdb, "ensure_registry_schema", return_value=True) as ensure_call, \
             patch.object(sdb, "backfill_known_companies", return_value=3) as backfill_call, \
             patch.object(sdb, "archive_fragment_rows", return_value=2) as archive_call, \
             patch.object(sdb, "backfill_evidence_links", return_value=5), \
             patch.object(sdb, "create_registry_db") as create_call:
            sdb.main()
        ensure_call.assert_called_once_with("t", "db")
        backfill_call.assert_called_once_with("t", "db")
        archive_call.assert_called_once_with("t", "db")
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
             patch.object(sdb, "ensure_registry_schema", return_value=False):
            with self.assertRaises(SystemExit):
                sdb.main()


if __name__ == "__main__":
    unittest.main()
