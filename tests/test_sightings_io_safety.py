# -*- coding: utf-8 -*-
"""sightings 파일 I/O 안전성 (2026-08-04 감사 B-1·B-2).

- B-2: 존재하는데 손상된 sightings를 빈 스켈레톤으로 대체하면 다음 저장에서
  누적 데이터 전체가 소실된다 — _load는 손상 시 중단해야 한다.
- B-1: 직접 쓰기 도중 크래시가 나면 절단 JSON이 남고 워크플로우 커밋
  스텝(if: always())이 그것을 커밋할 수 있다 — 원자 교체로 저장한다.
"""
import json
import tempfile
import unittest
from pathlib import Path

import scripts.discover_actors as da


class TestLoadSafety(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_missing_file_returns_skeleton(self):
        out = da._load(self.dir / "absent.json", {"version": 1, "sightings": {}})
        self.assertEqual(out, {"version": 1, "sightings": {}})

    def test_corrupt_existing_file_aborts(self):
        p = self.dir / "sightings.json"
        p.write_text('{"version": 1, "sight', encoding="utf-8")  # 절단 JSON
        with self.assertRaises(SystemExit):
            da._load(p, {"version": 1, "sightings": {}})

    def test_valid_file_loads(self):
        p = self.dir / "sightings.json"
        p.write_text('{"version": 1, "sightings": {"a": []}}', encoding="utf-8")
        out = da._load(p, {})
        self.assertEqual(out["sightings"], {"a": []})


class TestAtomicWrite(unittest.TestCase):
    def test_writes_valid_json_and_no_tmp_leftover(self):
        d = Path(tempfile.mkdtemp())
        p = d / "sightings.json"
        da._atomic_write_json(p, {"version": 1, "sightings": {"김테스트": []}})
        self.assertEqual(json.loads(p.read_text(encoding="utf-8"))["version"], 1)
        self.assertEqual(list(d.glob("*.tmp")), [])

    def test_overwrites_existing(self):
        d = Path(tempfile.mkdtemp())
        p = d / "sightings.json"
        p.write_text('{"old": true}', encoding="utf-8")
        da._atomic_write_json(p, {"new": True})
        self.assertEqual(json.loads(p.read_text(encoding="utf-8")), {"new": True})


if __name__ == "__main__":
    unittest.main()
