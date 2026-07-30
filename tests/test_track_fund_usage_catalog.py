"""track_fund_usage의 카탈로그 발췌 배선 회귀 테스트 (SE-13 Task 1).

버그: server.py의 track_fund_usage가
`load_catalog_excerpt(["zombie_ma", "fake_new_biz"])`처럼 **패턴 키**를 넘기고
있었다. 그러나 load_catalog_excerpt(taxonomy_ids)는 taxonomy ID(예: "5.1")를
기대하며 TAXONOMY dict에서 조회한다 — 패턴 키는 그 dict에 없는 키라
`TAXONOMY.get(tid)`가 항상 None → 조용히 스킵 → 최종 반환값이 언제나
빈 문자열이었다. 호출 자체는 존재했고 예외도 없었기 때문에 "호출됐는지"만
보는 테스트로는 절대 못 잡는다 — 그래서 이 테스트는 실제 함수를 실제
taxonomy ID로 호출한 뒤 **결과 문자열에 실제 내용이 들어있는지**를 검증한다.
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp.core.catalog import load_catalog_excerpt
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS, TAXONOMY
from dart_risk_mcp import server


class TestLoadCatalogExcerptContract(unittest.TestCase):
    """load_catalog_excerpt 자체의 계약: 패턴 키는 미스, taxonomy ID는 히트."""

    def test_pattern_keys_are_not_valid_taxonomy_ids(self):
        # 원래 버그를 재현: 패턴 키 문자열은 TAXONOMY의 키가 아니다.
        self.assertNotIn("zombie_ma", TAXONOMY)
        self.assertNotIn("fake_new_biz", TAXONOMY)

    def test_calling_with_pattern_keys_returns_empty(self):
        # 버그 상황 그대로 재현 — 항상 빈 문자열이었다는 사실을 문서화.
        excerpt = load_catalog_excerpt(["zombie_ma", "fake_new_biz"])
        self.assertEqual(excerpt, "")

    def test_calling_with_real_taxonomy_ids_returns_nonempty(self):
        # zombie_ma·fake_new_biz 패턴의 signal_sequence(실제 taxonomy ID)로
        # 호출하면 실제 카탈로그 산문이 나와야 한다.
        tax_ids = list(dict.fromkeys(
            CROSS_SIGNAL_PATTERNS["zombie_ma"]["signal_sequence"]
            + CROSS_SIGNAL_PATTERNS["fake_new_biz"]["signal_sequence"]
        ))
        excerpt = load_catalog_excerpt(tax_ids)
        self.assertNotEqual(excerpt, "")
        self.assertGreater(len(excerpt), 100)  # 단순 공백/빈 문자열이 아님을 확인


SAMPLE_ANOMALY_RECORD = {
    "year": "2024",
    "kind": "private",
    "tm": "1",
    "pay_amount": 3_000_000_000,
    "plan_useprps": "신사업투자",
    "plan_amount": 3_000_000_000,
    "real_dtls_cn": "운영자금",
    "real_dtls_amount": 3_000_000_000,
    "dffrnc_resn": "사업 취소로 일반 운영자금으로 변경 사용",
    "flags": ["FUND_DIVERSION"],
}


@patch.dict("os.environ", {"DART_API_KEY": "KEY"})
@patch("dart_risk_mcp.server.fetch_dividend_history")
@patch("dart_risk_mcp.server.fetch_fund_usage")
@patch("dart_risk_mcp.server.resolve_corp")
class TestTrackFundUsageCatalogWiring(unittest.TestCase):
    """track_fund_usage MCP 도구 출력에 실제 카탈로그 산문이 나오는지 검증.

    핵심: `load_catalog_excerpt`가 "호출됐다"만 보는 테스트(mock 호출 여부)는
    이 버그를 못 잡는다 — 버그 상태에서도 호출은 매번 일어났다. 반드시 도구의
    **최종 출력 문자열**에 실제 카탈로그 내용이 들어있는지를 확인해야 한다.
    """

    def test_anomaly_output_contains_real_catalog_prose(
        self, mock_resolve, mock_fetch_fund, mock_fetch_div
    ):
        mock_resolve.return_value = ("테스트기업", {"corp_code": "001", "stock_code": "123456"})
        mock_fetch_fund.return_value = [dict(SAMPLE_ANOMALY_RECORD)]
        mock_fetch_div.return_value = []

        out = server.track_fund_usage("테스트기업", lookback_years=1)

        self.assertIn("이상 신호가 감지된 건", out)

        # 버그 상태였다면 excerpt가 빈 문자열이라 아래 어떤 카탈로그 산문도
        # 출력에 나타나지 않는다. 수정 후에는 zombie_ma/fake_new_biz의
        # signal_sequence가 걸치는 카테고리 MD 중 최소 하나의 실제 문구가
        # 반드시 등장해야 한다.
        tax_ids = list(dict.fromkeys(
            CROSS_SIGNAL_PATTERNS["zombie_ma"]["signal_sequence"]
            + CROSS_SIGNAL_PATTERNS["fake_new_biz"]["signal_sequence"]
        ))
        expected_excerpt = load_catalog_excerpt(tax_ids)
        self.assertTrue(expected_excerpt, "테스트 전제 자체가 깨짐: 기대 발췌가 비어있음")

        # 발췌 전체가 그대로 삽입되므로, 발췌 첫 줄(헤더)이 출력에 있어야 한다.
        first_line = expected_excerpt.strip().splitlines()[0]
        self.assertIn(first_line, out)

    def test_no_anomaly_no_catalog_needed(
        self, mock_resolve, mock_fetch_fund, mock_fetch_div
    ):
        mock_resolve.return_value = ("테스트기업", {"corp_code": "001", "stock_code": "123456"})
        clean_record = dict(SAMPLE_ANOMALY_RECORD)
        clean_record["flags"] = []
        mock_fetch_fund.return_value = [clean_record]
        mock_fetch_div.return_value = []

        out = server.track_fund_usage("테스트기업", lookback_years=1)
        self.assertIn("별도 경고 신호는 없습니다", out)


if __name__ == "__main__":
    unittest.main()
