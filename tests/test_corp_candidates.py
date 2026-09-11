# -*- coding: utf-8 -*-
"""동명 법인 후보 — 이름 하나에 corp_code가 여럿일 때 임의로 고르지 않는다.

`_corp_cache`는 **이름을 키로 쓰는 dict**라 동명 법인이 있으면 한쪽이 반드시
사라진다. `_merge_corp_entry`가 「상장 우선, 동급이면 modify_date 최신」으로
어느 쪽을 남길지 정하지만 — 그건 **근사치이고 사용자에게 보이지도 않는다**.

비상장 법인을 조회할 때 이 침묵이 그대로 오답이 된다. 실측(2026-09-11
corpCode.xml 전수 119,173법인): 고유 이름 111,272 중 **동명 이름 5,536개 ·
거기 묶인 법인 13,437개**. 상장사가 낀 묶음은 523개뿐이라, 동명 문제는
대부분 **비상장끼리**의 문제다 — 즉 새 도구가 정면으로 만나는 경우다.

    '올품' → 00442385 (modify_date 20170630, 공시 **0건**)
             00455750 (modify_date 20240110, 공시 19건 · 현행)

modify_date 규칙이 다행히 맞는 쪽을 고르지만, 규칙이 틀리는 이름에서는
사용자가 **빈손을 받고 이유를 모른다**. 그래서 후보를 보존하고 되묻는다.

캐시 파일명이 `corp_codes_v3.json`인 이유: 페이로드에 `dupes`가 늘어
포맷이 바뀌었다. CLAUDE.md의 규칙대로 **파일명을 바꿔** 신·구 버전이 각자
캐시를 갖게 한다(2026-08-05 실사고 — v2 페이로드를 레거시 경로에 썼다가
구버전 설치본이 전 도구 즉사).
"""
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from dart_risk_mcp.core import dart_client as dc


def _zip(entries):
    items = "".join(
        f"<list><corp_code>{c}</corp_code><corp_name>{n}</corp_name>"
        f"<corp_eng_name></corp_eng_name><stock_code>{s}</stock_code>"
        f"<modify_date>{m}</modify_date></list>"
        for n, c, s, m in entries
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", f"<result>{items}</result>".encode("utf-8"))
    return buf.getvalue()


ENTRIES = [
    ("올품", "00442385", "", "20170630"),
    ("올품", "00455750", "", "20240110"),
    ("앤로보틱스", "01358296", "", "20251202"),
    ("앤로보틱스", "00808068", "138360", "20260303"),
    ("삼성전자", "00126380", "005930", "20260101"),
]


class _CacheDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # ⚠ 전역을 **복원**한다. 안 하면 이 파일이 만든 가짜 5건짜리 명부가
        #   남아 뒤에 도는 resolve_corp 계열 테스트가 엉뚱하게 실패한다.
        _saved = (dc._corp_cache, dc._corp_dupes)
        def _restore():
            dc._corp_cache, dc._corp_dupes = _saved
        self.addCleanup(_restore)
        dc._corp_cache = {}
        dc._corp_dupes = {}
        resp = MagicMock(status_code=200, content=_zip(ENTRIES))
        self.p1 = patch.object(dc, "_retry", return_value=resp)
        self.p2 = patch.object(dc, "_resolve_corp_cache_dir", return_value=self.tmp)
        self.p1.start(); self.p2.start()
        self.addCleanup(self.p1.stop); self.addCleanup(self.p2.stop)


class TestFindCorpCandidates(_CacheDir):
    def test_동명이면_후보를_모두_돌려준다(self):
        got = dc.find_corp_candidates("올품", "k")
        self.assertEqual({c["corp_code"] for c in got}, {"00442385", "00455750"})

    def test_최신_수정분이_앞에_온다(self):
        got = dc.find_corp_candidates("올품", "k")
        self.assertEqual(got[0]["corp_code"], "00455750")
        self.assertEqual(got[0]["modify_date"], "20240110")

    def test_상장사가_비상장보다_앞이다(self):
        got = dc.find_corp_candidates("앤로보틱스", "k")
        self.assertEqual(got[0]["corp_code"], "00808068")
        self.assertEqual(got[0]["stock_code"], "138360")

    def test_유일하면_한_건이다(self):
        got = dc.find_corp_candidates("삼성전자", "k")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["corp_code"], "00126380")

    def test_없는_이름은_빈_목록이다(self):
        self.assertEqual(dc.find_corp_candidates("없는회사", "k"), [])

    def test_공백만_있는_이름은_빈_목록이다(self):
        self.assertEqual(dc.find_corp_candidates("   ", "k"), [])


class TestCachePersistsDupes(_CacheDir):
    def test_캐시_파일에_후보가_남는다(self):
        dc.find_corp_candidates("올품", "k")
        payload = json.loads((self.tmp / "corp_codes_v3.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["_v"], dc._CORP_CACHE_VERSION)
        self.assertIn("올품", payload["dupes"])
        self.assertNotIn("삼성전자", payload["dupes"], "동명이 아닌 이름은 담지 않는다")

    def test_캐시에서_다시_읽어도_후보가_산다(self):
        dc.find_corp_candidates("올품", "k")
        dc._corp_cache, dc._corp_dupes = {}, {}
        with patch.object(dc, "_retry", side_effect=AssertionError("재다운로드하면 안 된다")):
            got = dc.find_corp_candidates("올품", "k")
        self.assertEqual(len(got), 2)

    def test_옛_포맷_파일은_읽지_않는다(self):
        """v2 파일이 남아 있어도 v3는 제 파일만 본다."""
        (self.tmp / "corp_codes_v2.json").write_text(
            json.dumps({"_v": 2, "data": {"엉뚱": {"corp_code": "x", "stock_code": ""}}}),
            encoding="utf-8")
        dc.find_corp_candidates("올품", "k")
        self.assertNotIn("엉뚱", dc._corp_cache)

    def test_기존_이름_조회는_그대로다(self):
        """`resolve_corp`가 쓰는 평면 dict는 모양이 바뀌지 않는다."""
        dc.find_corp_candidates("올품", "k")
        self.assertEqual(dc._corp_cache["삼성전자"],
                         {"corp_code": "00126380", "stock_code": "005930"})
        self.assertEqual(dc._corp_cache["올품"]["corp_code"], "00455750")


if __name__ == "__main__":
    unittest.main()
