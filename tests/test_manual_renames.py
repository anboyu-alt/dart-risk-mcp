# -*- coding: utf-8 -*-
"""KOSPI 개명 소급 경로 — 수동 시드(manual_renames.json) + corp-aliases 보조 인덱스.

배경: '상호변경안내' 백필(backfill_renames.py)은 사실상 코스닥 전용이라
(corp_renames 610사 중 K 354 vs Y 2, 2026-08-03 실측) 유가증권 개명
(실례: 에이프로젠KIC → 에이프로젠, corp_code 00152385)은 자동으로 못 잡는다.
수동 시드는 근거 rcept_no 없는 entry를 기계적으로 거부한다(등재 금지 기조).
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.discover_actors as da


def _valid_seed() -> dict:
    return {
        "version": 1,
        "renames": {
            "00152385": {
                "names": ["(주)에이프로젠케이아이씨"],
                "events": [{
                    "date": "2020-03",
                    "rcept_no": "20200306000345",
                    "before": ["(주)에이프로젠케이아이씨"],
                    "after": "에이프로젠",
                    "src": "manual",
                }],
            }
        },
    }


class _SeedFileMixin(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def write_seed(self, obj) -> Path:
        p = self.dir / "manual_renames.json"
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return p


class TestLoadManualRenames(_SeedFileMixin):
    def test_valid_seed_loads(self):
        renames, errors = da.load_manual_renames(self.write_seed(_valid_seed()))
        self.assertEqual(errors, [])
        self.assertIn("00152385", renames)
        self.assertEqual(renames["00152385"]["names"],
                         ["(주)에이프로젠케이아이씨"])
        self.assertEqual(renames["00152385"]["events"][0]["rcept_no"],
                         "20200306000345")

    def test_missing_file_returns_empty(self):
        renames, errors = da.load_manual_renames(self.dir / "absent.json")
        self.assertEqual(renames, {})
        self.assertEqual(errors, [])

    def test_event_without_rcept_no_rejected(self):
        seed = _valid_seed()
        del seed["renames"]["00152385"]["events"][0]["rcept_no"]
        renames, errors = da.load_manual_renames(self.write_seed(seed))
        self.assertEqual(renames, {})
        self.assertTrue(any("rcept_no" in e for e in errors))

    def test_bad_rcept_no_format_rejected(self):
        seed = _valid_seed()
        seed["renames"]["00152385"]["events"][0]["rcept_no"] = "2020-03-06"
        renames, errors = da.load_manual_renames(self.write_seed(seed))
        self.assertEqual(renames, {})
        self.assertTrue(errors)

    def test_bad_corp_code_rejected(self):
        seed = _valid_seed()
        seed["renames"]["에이프로젠"] = seed["renames"].pop("00152385")
        renames, errors = da.load_manual_renames(self.write_seed(seed))
        self.assertEqual(renames, {})
        self.assertTrue(any("corp_code" in e for e in errors))

    def test_empty_names_rejected(self):
        seed = _valid_seed()
        seed["renames"]["00152385"]["names"] = []
        renames, errors = da.load_manual_renames(self.write_seed(seed))
        self.assertEqual(renames, {})
        self.assertTrue(errors)

    def test_entry_without_events_rejected(self):
        seed = _valid_seed()
        seed["renames"]["00152385"]["events"] = []
        renames, errors = da.load_manual_renames(self.write_seed(seed))
        self.assertEqual(renames, {})
        self.assertTrue(errors)

    def test_valid_entry_survives_invalid_sibling(self):
        seed = _valid_seed()
        seed["renames"]["00000000"] = {"names": ["옛이름"], "events": []}
        renames, errors = da.load_manual_renames(self.write_seed(seed))
        self.assertIn("00152385", renames)
        self.assertNotIn("00000000", renames)
        self.assertTrue(errors)

    def test_malformed_json_returns_error(self):
        p = self.dir / "manual_renames.json"
        p.write_text("{broken", encoding="utf-8")
        renames, errors = da.load_manual_renames(p)
        self.assertEqual(renames, {})
        self.assertTrue(errors)


class TestAliasNameIndex(unittest.TestCase):
    def test_folds_old_names_to_corp_codes(self):
        amap = {"알로이스": {"corp_code": "01309795", "stock_code": "297570",
                             "current": "아틀라스링크"},
                "에이프로젠KIC": {"corp_code": "00152385", "stock_code": "007460",
                                  "current": "에이프로젠"}}
        with patch("dart_risk_mcp.core.dart_client.load_corp_aliases",
                   return_value=amap):
            idx = da._alias_name_index()
        from dart_risk_mcp.core.known_actors import fold_name
        self.assertEqual(idx[fold_name("알로이스")], {"01309795"})
        # 라틴 표기 KIC는 fold가 한글 음차(케이아이씨)로 수렴시킨다
        self.assertEqual(idx[fold_name("(주)에이프로젠케이아이씨")], {"00152385"})

    def test_failure_returns_empty(self):
        with patch("dart_risk_mcp.core.dart_client.load_corp_aliases",
                   side_effect=RuntimeError("network down")):
            self.assertEqual(da._alias_name_index(), {})


class TestCombinedLegacyIndex(unittest.TestCase):
    def test_unions_corp_renames_and_aliases(self):
        sdata = {"corp_renames": {"00111111": {"names": ["옛코스닥"],
                                               "events": []}}}
        amap = {"옛코스피": {"corp_code": "00222222", "current": "새코스피"}}
        with patch("dart_risk_mcp.core.dart_client.load_corp_aliases",
                   return_value=amap):
            idx = da._combined_legacy_index(sdata)
        from dart_risk_mcp.core.known_actors import fold_name
        self.assertEqual(idx[fold_name("옛코스닥")], {"00111111"})
        self.assertEqual(idx[fold_name("옛코스피")], {"00222222"})

    def test_conflicting_sources_keep_both_codes(self):
        # 같은 옛 사명이 두 corp_code를 가리키면 합집합으로 남긴다 —
        # reconcile의 모호 가드(len==1)가 해석을 거부하게 하는 보수적 동작.
        sdata = {"corp_renames": {"00111111": {"names": ["중복명"],
                                               "events": []}}}
        amap = {"중복명": {"corp_code": "00999999", "current": "다른회사"}}
        with patch("dart_risk_mcp.core.dart_client.load_corp_aliases",
                   return_value=amap):
            idx = da._combined_legacy_index(sdata)
        from dart_risk_mcp.core.known_actors import fold_name
        self.assertEqual(idx[fold_name("중복명")], {"00111111", "00999999"})


class TestApplyManualRenames(_SeedFileMixin):
    def test_merges_into_corp_renames(self):
        sdata = {"version": 1, "sightings": {}}
        changed = da.apply_manual_renames(sdata, self.write_seed(_valid_seed()))
        self.assertTrue(changed)
        self.assertEqual(sdata["corp_renames"]["00152385"]["names"],
                         ["(주)에이프로젠케이아이씨"])

    def test_idempotent_second_apply(self):
        sdata = {"version": 1, "sightings": {}}
        path = self.write_seed(_valid_seed())
        da.apply_manual_renames(sdata, path)
        self.assertFalse(da.apply_manual_renames(sdata, path))

    def test_missing_seed_is_noop(self):
        sdata = {"version": 1, "sightings": {}}
        self.assertFalse(da.apply_manual_renames(sdata, self.dir / "absent.json"))
        self.assertNotIn("corp_renames", sdata)

    def test_invalid_entries_not_merged(self):
        seed = _valid_seed()
        del seed["renames"]["00152385"]["events"][0]["rcept_no"]
        sdata = {"version": 1, "sightings": {}}
        self.assertFalse(da.apply_manual_renames(sdata, self.write_seed(seed)))
        self.assertNotIn("00152385", sdata.get("corp_renames", {}))


class TestReconcileWithManualSeed(_SeedFileMixin):
    """종단: 수동 시드 → legacy 인덱스 → 옛 사명 행위자 키 해석·병합."""

    def _corp_index(self):
        from dart_risk_mcp.core.known_actors import fold_name
        # 현재 명부에는 새 사명만 있다 (옛 사명은 corpCode.xml에서 사라짐)
        return {fold_name("에이프로젠"): {"00152385"}}

    def test_old_key_resolves_to_corp_id(self):
        sdata = {"version": 1, "sightings": {
            "(주)에이프로젠케이아이씨": [
                {"company": "A사", "corp_code": "0001", "date": "2018-10",
                 "rcept_no": "20181010000001", "src": "funding"}]}}
        da.apply_manual_renames(sdata, self.write_seed(_valid_seed()))
        changed = da.reconcile_corp_renames(
            sdata, self._corp_index(), da._legacy_name_index(sdata))
        self.assertTrue(changed)
        self.assertEqual(sdata["actor_corp_ids"]["00152385"],
                         "(주)에이프로젠케이아이씨")

    def test_old_key_merges_into_current_key(self):
        sdata = {"version": 1, "sightings": {
            "(주)에이프로젠케이아이씨": [
                {"company": "A사", "corp_code": "0001", "date": "2018-10",
                 "rcept_no": "20181010000001", "src": "funding"}],
            "(주)에이프로젠": [
                {"company": "B사", "corp_code": "0002", "date": "2024-05",
                 "rcept_no": "20240510000002", "src": "funding"}]}}
        da.apply_manual_renames(sdata, self.write_seed(_valid_seed()))
        da.reconcile_corp_renames(
            sdata, self._corp_index(), da._legacy_name_index(sdata))
        self.assertNotIn("(주)에이프로젠케이아이씨", sdata["sightings"])
        recs = sdata["sightings"]["(주)에이프로젠"]
        self.assertEqual(len(recs), 2)
        self.assertEqual(sdata["aliases"]["(주)에이프로젠케이아이씨"],
                         "(주)에이프로젠")


class TestVerifyManualRenames(unittest.TestCase):
    """merge_manual_renames.py의 DART 대조 검증 — rcept↔corp 연결(치명) +
    원문 옛 사명 표기(경고)."""

    def _renames(self):
        return _valid_seed()["renames"]

    def test_linkage_and_name_ok(self):
        import scripts.merge_manual_renames as mm
        with patch.object(mm, "_fetch_day_list",
                          return_value=["20200306000345", "20200306000999"]), \
             patch.object(mm, "fetch_document_text",
                          return_value="회 사 명 : (주)에이프로젠케이아이씨"):
            errors, warnings = mm.verify_manual_renames(self._renames(), "KEY")
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_rcept_not_filed_by_corp_is_error(self):
        import scripts.merge_manual_renames as mm
        with patch.object(mm, "_fetch_day_list", return_value=["다른접수번호"]), \
             patch.object(mm, "fetch_document_text", return_value=""):
            errors, _ = mm.verify_manual_renames(self._renames(), "KEY")
        self.assertTrue(any("00152385" in e for e in errors))

    def test_name_absent_from_document_is_warning(self):
        import scripts.merge_manual_renames as mm
        with patch.object(mm, "_fetch_day_list",
                          return_value=["20200306000345"]), \
             patch.object(mm, "fetch_document_text",
                          return_value="옛 사명이 등장하지 않는 원문"):
            errors, warnings = mm.verify_manual_renames(self._renames(), "KEY")
        self.assertEqual(errors, [])
        self.assertTrue(warnings)

    def test_latin_display_matches_korean_seed_name(self):
        # 원문이 '에이프로젠 KIC'(라틴 표기)여도 fold 음차 수렴으로 매칭
        import scripts.merge_manual_renames as mm
        with patch.object(mm, "_fetch_day_list",
                          return_value=["20200306000345"]), \
             patch.object(mm, "fetch_document_text",
                          return_value="에이프로젠 KIC/정기주주총회결과"):
            errors, warnings = mm.verify_manual_renames(self._renames(), "KEY")
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_already_merged_events_skip_api(self):
        # sightings에 이미 있는 rcept_no는 재검증하지 않는다 (호출 예산)
        import scripts.merge_manual_renames as mm
        sdata = {"corp_renames": {"00152385": {
            "names": ["(주)에이프로젠케이아이씨"],
            "events": [{"rcept_no": "20200306000345"}]}}}
        with patch.object(mm, "_fetch_day_list") as day_list, \
             patch.object(mm, "fetch_document_text") as doc:
            errors, warnings = mm.verify_manual_renames(
                self._renames(), "KEY", existing=sdata["corp_renames"])
        day_list.assert_not_called()
        doc.assert_not_called()
        self.assertEqual((errors, warnings), ([], []))


if __name__ == "__main__":
    unittest.main()
