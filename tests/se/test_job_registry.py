"""1단 항목 정의."""
import unittest

from se_server.jobs.registry import (
    STAGE1_SPECS,
    build_stage1_items,
    resolve_callable,
)


class TestSpecs(unittest.TestCase):
    def test_keys_are_unique(self):
        keys = [s.key for s in STAGE1_SPECS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_func_name_resolves(self):
        """등록된 이름이 실제 core 함수와 연결돼야 한다."""
        for spec in STAGE1_SPECS:
            self.assertTrue(callable(resolve_callable(spec.func_name)), spec.func_name)

    def test_every_param_name_is_supported(self):
        """param_names는 실행기가 채울 수 있는 이름이어야 한다."""
        allowed = {"corp_code", "lookback_years", "year", "bsns_year"}
        for spec in STAGE1_SPECS:
            self.assertTrue(set(spec.param_names) <= allowed, spec.key)

    def test_unknown_func_name_raises(self):
        with self.assertRaises(KeyError):
            resolve_callable("존재하지_않는_함수")

    def test_covers_expected_sections(self):
        """설계 §7.1의 1단 섹션이 모두 대표된다."""
        sections = {s.section for s in STAGE1_SPECS}
        for expected in ("헤더", "자금", "재무", "지배구조", "감사부실"):
            self.assertIn(expected, sections)


class TestBuildStage1Items(unittest.TestCase):
    def test_builds_one_item_per_spec(self):
        items = build_stage1_items("00126380", 3)
        self.assertEqual(len(items), len(STAGE1_SPECS))

    def test_all_items_are_stage1_and_pending(self):
        for item in build_stage1_items("00126380", 3):
            self.assertEqual(item.stage, 1)
            self.assertEqual(item.status, "pending")

    def test_params_are_filled_from_arguments(self):
        items = {i.key: i for i in build_stage1_items("00126380", 3)}
        for item in items.values():
            if "corp_code" in item.params:
                self.assertEqual(item.params["corp_code"], "00126380")
            if "lookback_years" in item.params:
                self.assertEqual(item.params["lookback_years"], 3)

    def test_params_never_contain_api_key(self):
        """작업 레코드는 공유 저장소에 남는다."""
        for item in build_stage1_items("00126380", 3):
            self.assertNotIn("crtfc_key", item.params)
            self.assertNotIn("api_key", item.params)

    def test_lookback_years_is_clamped_to_1_5(self):
        for raw, expected in ((0, 1), (1, 1), (5, 5), (99, 5)):
            items = build_stage1_items("0", raw)
            with_lookback = [i for i in items if "lookback_years" in i.params]
            self.assertTrue(with_lookback)
            self.assertEqual(with_lookback[0].params["lookback_years"], expected)


if __name__ == "__main__":
    unittest.main()
