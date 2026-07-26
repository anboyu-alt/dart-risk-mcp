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
        with mock.patch.object(se_cache_bench, "resolve_corp", return_value=None):
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

        # CB 공시 1건만 매칭되고 임원 보고서는 매칭되지 않는다.
        # documents == full.call_count 는 구현이 호출할 때마다 세는 값이라
        # 동어반복이므로, 기대 건수를 직접 못박는다.
        self.assertEqual(result["disclosures"], 2)
        self.assertEqual(full.call_count, 1)
        self.assertEqual(result["documents"], 1)
        self.assertEqual(full.call_args[0][0], "1")  # CB 공시의 rcept_no


class TestMeasurementIsolation(unittest.TestCase):
    """측정이 SE 캐시 효과만 반영하도록 core의 프로세스 내 캐시를 비운다.

    같은 프로세스에서 콜드/웜을 재면 core의 _corp_cache·_zip_cache가
    웜 실행을 앞당겨 단축 배수를 부풀린다. 특히 corpCode.xml은 SE 캐시의
    _NEVER_CACHE 대상이라 그 단축분은 SE와 무관하다.
    """

    def test_reset_clears_both_core_caches(self):
        dart_client = se_cache_bench.dart_client
        dart_client._corp_cache["더미"] = {"corp_code": "0"}
        dart_client._zip_cache["더미"] = (0.0, b"x")

        se_cache_bench.reset_core_process_caches()

        self.assertEqual(dart_client._corp_cache, {})
        self.assertEqual(dart_client._zip_cache, {})


class TestCountingHttp(unittest.TestCase):
    """적중 수가 0인데 빨라졌다면 그 단축은 SE 캐시 효과가 아니다."""

    class _Inner:
        def __init__(self, result):
            self.result = result
            self.puts = 0

        def get(self, url, params):
            return self.result

        def put(self, url, params, status, headers, body):
            self.puts += 1

    def test_counts_hits_and_misses(self):
        counter = se_cache_bench.CountingHttp(self._Inner((200, {}, b"x")))
        counter.get("u", {})
        counter.get("u", {})
        self.assertEqual((counter.hits, counter.misses), (2, 0))

    def test_none_counts_as_miss(self):
        counter = se_cache_bench.CountingHttp(self._Inner(None))
        counter.get("u", {})
        self.assertEqual((counter.hits, counter.misses), (0, 1))

    def test_put_delegates_to_inner(self):
        inner = self._Inner(None)
        counter = se_cache_bench.CountingHttp(inner)
        counter.put("u", {}, 200, {}, b"x")
        self.assertEqual(inner.puts, 1)

    def test_reset_counts_zeroes_both(self):
        counter = se_cache_bench.CountingHttp(self._Inner(None))
        counter.get("u", {})
        counter.reset_counts()
        self.assertEqual((counter.hits, counter.misses), (0, 0))


class TestResolveCorpContract(unittest.TestCase):
    """resolve_corp의 실패 반환값 계약을 고정한다.

    (None, None)으로 모킹하면 실제와 다른 형태라 언패킹 버그를 놓친다.
    """

    def tearDown(self):
        # _corp_cache는 모듈 전역 상태라, 이 테스트가 건드린 흔적이
        # 다른 테스트(정상 조회를 기대하는 테스트)에 새지 않도록 정리한다.
        from dart_risk_mcp.core import dart_client

        dart_client._corp_cache.clear()

    def test_returns_none_not_tuple_on_failure(self):
        from unittest import mock as _mock

        from dart_risk_mcp.core import dart_client

        with _mock.patch.object(dart_client, "_load_corp_codes", return_value=None):
            dart_client._corp_cache.clear()
            self.assertIsNone(dart_client.resolve_corp("존재하지않는회사xyz", "KEY"))


if __name__ == "__main__":
    unittest.main()
