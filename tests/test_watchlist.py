import json
import os
import shutil
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
        """손상 파일은 빈 구조로 읽되, **원본을 옆으로 치우고 그 사실을 담는다**.

        2026-08-23 라이브 재현: 3명이 저장된 파일을 절반만 남기고(쓰기 도중
        중단 흉내) `add`를 한 번 부르니 3명이 전부 사라지고 새로 넣은 1명만
        남았다. 백업도 없었다. 워치리스트는 캐시가 아니라 사용자가 직접 채운
        자산이라(그래서 ~/.config에 둔다) 조용히 버리면 안 된다.
        """
        from dart_risk_mcp.core.watchlist import load_watchlist
        Path(self._path).write_text("{ not valid json", encoding="utf-8")
        got = load_watchlist()
        self.assertEqual(got["version"], 1)
        self.assertEqual(got["persons"], {})
        bak = Path(self._path + ".corrupt")
        self.assertTrue(bak.exists(), "손상 파일을 치우지 않으면 다음 저장이 덮어쓴다")
        self.assertEqual(bak.read_text(encoding="utf-8"), "{ not valid json")
        self.assertEqual(got["_quarantined"], str(bak))

    def test_list_persons_sorted_with_counts(self):
        from dart_risk_mcp.core.watchlist import add_person, list_persons
        add_person("오종원", ["인트로메딕"])
        add_person("신승수", ["CG인바이츠", "티쓰리"])
        # 가나다순 정렬: "신승수" < "오종원"
        self.assertEqual(list_persons(), [("신승수", 2), ("오종원", 1)])



class TestWatchlistDurability(unittest.TestCase):
    """사용자 자산이므로 쓰다 멈춰도, 깨져 있어도 잃지 않는다.

    라이브 재현(2026-08-23): 3명이 저장된 파일을 절반만 남기고 `add`를 한 번
    부르니 3명이 전부 사라지고 새로 넣은 1명만 남았다 — 백업 없이.

    두 곳을 고쳤다.
      ① `save_watchlist`가 임시 파일에 쓰고 교체한다(원자적) — 애초에
         잘린 파일이 생기지 않는다.
      ② `load_watchlist`가 읽을 수 없는 파일을 `.corrupt`로 치운다 —
         다음 저장이 그 위에 덮어쓰지 못한다.
    """

    def setUp(self):
        self._dir = tempfile.mkdtemp()
        self._path = str(Path(self._dir) / "watchlist.json")
        self._prev = os.environ.get("DART_WATCHLIST_PATH")
        os.environ["DART_WATCHLIST_PATH"] = self._path

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("DART_WATCHLIST_PATH", None)
        else:
            os.environ["DART_WATCHLIST_PATH"] = self._prev
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_저장은_임시파일을_남기지_않는다(self):
        from dart_risk_mcp.core.watchlist import add_person
        add_person("김갑", ["A사"])
        leftovers = [p.name for p in Path(self._dir).iterdir()
                     if p.name != "watchlist.json"]
        self.assertEqual(leftovers, [], f"임시 파일이 남았다: {leftovers}")

    def test_손상_파일이_덮어써지지_않는다(self):
        from dart_risk_mcp.core.watchlist import add_person, list_persons
        add_person("김갑", ["A사"])
        add_person("이을", ["B사"])
        raw = Path(self._path).read_text(encoding="utf-8")
        Path(self._path).write_text(raw[: len(raw) // 2], encoding="utf-8")

        add_person("박병", ["C사"])
        self.assertEqual([n for n, _ in list_persons()], ["박병"])
        bak = Path(self._path + ".corrupt")
        self.assertTrue(bak.exists())
        self.assertIn("김갑", bak.read_text(encoding="utf-8"),
                      "치워 둔 파일에 이전 내용이 남아 있어야 되살릴 수 있다")

    def test_손상이_여러_번이어도_앞선_백업을_덮지_않는다(self):
        from dart_risk_mcp.core.watchlist import add_person, load_watchlist
        Path(self._path).write_text("첫 번째 손상", encoding="utf-8")
        load_watchlist()
        add_person("김갑", ["A사"])
        Path(self._path).write_text("두 번째 손상", encoding="utf-8")
        load_watchlist()
        names = sorted(p.name for p in Path(self._dir).iterdir()
                       if ".corrupt" in p.name)
        self.assertEqual(len(names), 2, f"백업이 덮어써졌다: {names}")

    def test_저장할_때_격리_표시는_파일에_남기지_않는다(self):
        """`_quarantined`는 이번 호출에만 쓰는 표시라 디스크에 새면 안 된다."""
        from dart_risk_mcp.core.watchlist import add_person
        Path(self._path).write_text("깨진 내용", encoding="utf-8")
        add_person("김갑", ["A사"])
        saved = json.loads(Path(self._path).read_text(encoding="utf-8"))
        self.assertNotIn("_quarantined", saved)

    def test_정상_파일은_치우지_않는다(self):
        from dart_risk_mcp.core.watchlist import add_person, load_watchlist
        add_person("김갑", ["A사"])
        got = load_watchlist()
        self.assertNotIn("_quarantined", got)
        self.assertFalse(Path(self._path + ".corrupt").exists())

if __name__ == "__main__":
    unittest.main()
