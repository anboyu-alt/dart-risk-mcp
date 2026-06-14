import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestWatchlist(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = str(Path(self._tmp.name) / "watchlist.json")
        self._env = patch.dict("os.environ", {"DART_WATCHLIST_PATH": self._path})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_load_missing_file_returns_empty(self):
        from dart_risk_mcp.core.watchlist import load_watchlist
        self.assertEqual(load_watchlist(), {"version": 1, "persons": {}})

    def test_add_then_load_round_trip(self):
        from dart_risk_mcp.core.watchlist import add_person, load_watchlist
        add_person("신승수", ["CG인바이츠", "티쓰리"], note="겸직")
        data = load_watchlist()
        self.assertIn("신승수", data["persons"])
        self.assertEqual(data["persons"]["신승수"]["companies"], ["CG인바이츠", "티쓰리"])
        self.assertEqual(data["persons"]["신승수"]["note"], "겸직")
        self.assertIn("updated", data["persons"]["신승수"])

    def test_add_merges_companies_union_preserving_order(self):
        from dart_risk_mcp.core.watchlist import add_person, get_person_companies
        add_person("신승수", ["CG인바이츠", "티쓰리"])
        add_person("신승수", ["티쓰리", "헬스커넥트"])  # 티쓰리 중복
        self.assertEqual(get_person_companies("신승수"),
                         ["CG인바이츠", "티쓰리", "헬스커넥트"])

    def test_remove_person(self):
        from dart_risk_mcp.core.watchlist import add_person, remove_person, get_person_companies
        add_person("신승수", ["CG인바이츠"])
        self.assertTrue(remove_person("신승수"))
        self.assertFalse(remove_person("신승수"))  # 두 번째는 없음
        self.assertEqual(get_person_companies("신승수"), [])

    def test_get_companies_unknown_returns_empty(self):
        from dart_risk_mcp.core.watchlist import get_person_companies
        self.assertEqual(get_person_companies("없는사람"), [])

    def test_load_corrupt_json_returns_empty(self):
        from dart_risk_mcp.core.watchlist import load_watchlist
        Path(self._path).write_text("{ not valid json", encoding="utf-8")
        self.assertEqual(load_watchlist(), {"version": 1, "persons": {}})

    def test_list_persons_sorted_with_counts(self):
        from dart_risk_mcp.core.watchlist import add_person, list_persons
        add_person("오종원", ["인트로메딕"])
        add_person("신승수", ["CG인바이츠", "티쓰리"])
        # 가나다순 정렬: "신승수" < "오종원"
        self.assertEqual(list_persons(), [("신승수", 2), ("오종원", 1)])


if __name__ == "__main__":
    unittest.main()
