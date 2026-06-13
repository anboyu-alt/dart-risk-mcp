import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestManageWatchlist(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict(
            "os.environ",
            {"DART_WATCHLIST_PATH": str(Path(self._tmp.name) / "wl.json")},
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_add_show_list_remove_flow(self):
        from dart_risk_mcp.server import manage_watchlist

        add = manage_watchlist("add", "신승수", ["CG인바이츠", "티쓰리"], "겸직")
        self.assertIn("신승수", add)
        self.assertIn("CG인바이츠", add)

        listed = manage_watchlist("list")
        self.assertIn("신승수", listed)
        self.assertIn("2개사", listed)

        shown = manage_watchlist("show", "신승수")
        self.assertIn("티쓰리", shown)
        self.assertIn("겸직", shown)

        removed = manage_watchlist("remove", "신승수")
        self.assertIn("삭제", removed)
        self.assertIn("비어 있", manage_watchlist("list"))

    def test_invalid_action(self):
        from dart_risk_mcp.server import manage_watchlist
        self.assertIn("입력 오류", manage_watchlist("frobnicate"))

    def test_add_requires_person_and_companies(self):
        from dart_risk_mcp.server import manage_watchlist
        self.assertIn("입력 오류", manage_watchlist("add", "", ["x"]))
        self.assertIn("입력 오류", manage_watchlist("add", "신승수", []))

    def test_show_unknown_person(self):
        from dart_risk_mcp.server import manage_watchlist
        self.assertIn("없습니다", manage_watchlist("show", "유령"))


if __name__ == "__main__":
    unittest.main()
