import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestManageAliases(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = str(Path(self._tmp.name) / "sightings.json")
        self._env = patch.dict("os.environ", {"SIGHTINGS_PATH": self._path})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _aliases(self):
        return json.loads(Path(self._path).read_text(encoding="utf-8")).get("aliases", {})

    def test_add_maps_aliases_to_canonical(self):
        import scripts.manage_aliases as ma
        from dart_risk_mcp.core.known_actors import normalize_name
        # 가공의 예시 — 실제 별칭은 비공개 sightings 저장소에만 둔다
        ma.cmd_add("KIM CHULSOO", ["김철수", "철수", "김철쑤"])
        canon = normalize_name("KIM CHULSOO")
        aliases = self._aliases()
        self.assertEqual(aliases[normalize_name("김철수")], canon)
        self.assertEqual(aliases[normalize_name("철수")], canon)
        self.assertEqual(aliases[normalize_name("김철쑤")], canon)
        # 정본 자신은 별칭 키로 들어가지 않음 (체인 방지)
        self.assertNotIn(canon, aliases)

    def test_add_skips_alias_equal_to_canonical(self):
        import scripts.manage_aliases as ma
        from dart_risk_mcp.core.known_actors import normalize_name
        ma.cmd_add("홍길동", ["홍길동", "  홍길동 "])
        # 정규화 후 정본과 같은 별칭은 등록하지 않음
        self.assertEqual(self._aliases(), {})
        self.assertNotIn(normalize_name("홍길동"), self._aliases())

    def test_remove_deletes_alias(self):
        import scripts.manage_aliases as ma
        from dart_risk_mcp.core.known_actors import normalize_name
        ma.cmd_add("KIM CHULSOO", ["김철수", "철수"])
        ma.cmd_remove("김철수")
        aliases = self._aliases()
        self.assertNotIn(normalize_name("김철수"), aliases)
        self.assertIn(normalize_name("철수"), aliases)

    def test_add_preserves_existing_sightings(self):
        # 별칭 등록은 sightings 레코드를 건드리지 않는다
        import scripts.manage_aliases as ma
        Path(self._path).write_text(json.dumps({
            "version": 1,
            "sightings": {"홍길동": [{"corp_code": "c1", "rcept_no": "R1"}]},
        }, ensure_ascii=False), encoding="utf-8")
        ma.cmd_add("KIM CHULSOO", ["김철수"])
        data = json.loads(Path(self._path).read_text(encoding="utf-8"))
        self.assertIn("홍길동", data["sightings"])
        self.assertIn("aliases", data)


if __name__ == "__main__":
    unittest.main()
