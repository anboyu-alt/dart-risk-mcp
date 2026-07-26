"""벤치 CLI의 순수 로직. DART 호출은 스텁한다."""
import unittest
from unittest import mock

from scripts import se_cache_bench


class TestRunOnce(unittest.TestCase):
    def test_counts_disclosures_and_measures_time(self):
        clock = {"t": 0.0}

        def fake_monotonic():
            clock["t"] += 2.5
            return clock["t"]

        with mock.patch.object(
            se_cache_bench, "resolve_corp",
            return_value=("테스트회사", {"corp_code": "00000000", "stock_code": "000000"}),
        ), mock.patch.object(
            se_cache_bench, "fetch_company_disclosures",
            return_value=[{"rcept_no": "1", "report_nm": "전환사채권 발행결정"}],
        ), mock.patch.object(
            se_cache_bench, "fetch_disclosure_full", return_value={"text": "본문"}
        ), mock.patch.object(se_cache_bench.time, "monotonic", fake_monotonic):
            result = se_cache_bench.run_once("테스트회사", "KEY", 1)

        self.assertEqual(result["disclosures"], 1)
        self.assertEqual(result["documents"], 1)
        self.assertGreater(result["seconds"], 0)

    def test_unresolved_company_raises(self):
        with mock.patch.object(se_cache_bench, "resolve_corp", return_value=(None, None)):
            with self.assertRaises(ValueError):
                se_cache_bench.run_once("없는회사", "KEY", 1)

    def test_only_signal_matched_documents_fetched(self):
        """신호 매칭된 공시만 원문을 연다 (스펙 §6.1 2단)."""
        with mock.patch.object(
            se_cache_bench, "resolve_corp",
            return_value=("회사", {"corp_code": "0", "stock_code": "0"}),
        ), mock.patch.object(
            se_cache_bench, "fetch_company_disclosures",
            return_value=[
                {"rcept_no": "1", "report_nm": "전환사채권 발행결정"},
                {"rcept_no": "2", "report_nm": "임원ㆍ주요주주특정증권등소유상황보고서"},
            ],
        ), mock.patch.object(
            se_cache_bench, "fetch_disclosure_full", return_value={"text": ""}
        ) as full:
            result = se_cache_bench.run_once("회사", "KEY", 1)

        self.assertEqual(result["disclosures"], 2)
        self.assertEqual(result["documents"], full.call_count)
        self.assertLess(full.call_count, 2)


if __name__ == "__main__":
    unittest.main()
