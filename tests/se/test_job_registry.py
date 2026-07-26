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
        allowed = {"corp_code", "lookback_years", "lookback_days", "year", "bsns_year"}
        for spec in STAGE1_SPECS:
            self.assertTrue(set(spec.param_names) <= allowed, spec.key)

    def test_param_names_match_real_signatures(self):
        """선언한 param_names가 core 함수가 실제로 받는 인자인지 대조한다.

        전역 허용집합만 검사하면 함수마다 다른 인자명을 놓친다 —
        fetch_company_disclosures는 lookback_years가 아니라 lookback_days를
        받는다. 실행기는 func(api_key=api_key, **params)로 호출하므로
        이름이 틀리면 런타임 TypeError가 난다.
        """
        import inspect

        for spec in STAGE1_SPECS:
            accepted = set(inspect.signature(resolve_callable(spec.func_name)).parameters)
            unknown = set(spec.param_names) - accepted
            self.assertFalse(
                unknown,
                f"{spec.key}: {spec.func_name}가 받지 않는 인자 {unknown}",
            )

    def test_required_params_are_all_supplied(self):
        """기본값 없는 필수 인자를 빠뜨리지 않았는지 확인한다.

        api_key는 실행기가 따로 넘기므로 제외한다.
        """
        import inspect

        items = {i.key: i for i in build_stage1_items("00126380", 1)}
        for spec in STAGE1_SPECS:
            sig = inspect.signature(resolve_callable(spec.func_name))
            required = {
                name
                for name, p in sig.parameters.items()
                if p.default is inspect.Parameter.empty
                and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)
                and name != "api_key"
            }
            missing = required - set(items[spec.key].params)
            self.assertFalse(missing, f"{spec.key}: 필수 인자 누락 {missing}")

    def test_oversized_only_for_year_proportional_functions(self):
        """oversized 기준: 호출 수가 lookback_years에 비례하는 함수만.

        엔드포인트 몇 개를 1회씩 도는 함수는 연수와 무관한 상수 시간이다.
        """
        by_key = {s.key: s for s in STAGE1_SPECS}
        for key in ("fund_usage", "insider_timeline", "executive_roster",
                    "audit_history", "dividends", "disclosures"):
            self.assertTrue(by_key[key].oversized, f"{key}는 oversized여야 한다")
        for key in ("company_info", "affiliates", "financials", "indicators",
                    "shareholders", "debt_balance", "distress"):
            self.assertFalse(by_key[key].oversized, f"{key}는 oversized가 아니어야 한다")

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
