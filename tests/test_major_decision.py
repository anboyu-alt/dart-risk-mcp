"""fetch_major_decision·resolve_decision_type 검증."""
import unittest
from unittest.mock import patch, MagicMock

from dart_risk_mcp.core import dart_client
from dart_risk_mcp.core.dart_client import resolve_decision_type


def _mock_resp(status="000", lst=None):
    resp = MagicMock()
    resp.json.return_value = {
        "status": status,
        "message": "정상" if status == "000" else "",
        "list": lst or [],
    }
    return resp


class TestResolveDecisionType(unittest.TestCase):
    def test_stock_acquisition(self):
        self.assertEqual(
            resolve_decision_type("타법인 주식 및 출자증권 양수결정"),
            "stock_acq",
        )

    def test_merger(self):
        self.assertEqual(resolve_decision_type("회사합병결정"), "merger")

    def test_amendment_prefix_ignored(self):
        self.assertEqual(
            resolve_decision_type("[기재정정] 영업양수결정"),
            "business_acq",
        )

    def test_unknown_returns_empty(self):
        self.assertEqual(resolve_decision_type("분기보고서"), "")


class TestFetchMajorDecision(unittest.TestCase):
    def setUp(self):
        dart_client._major_decision_cache.clear()

    def test_invalid_rcept_no(self):
        result = dart_client.fetch_major_decision("123", "K", "merger")
        self.assertIn("error", result)

    def test_unknown_decision_type_returns_error(self):
        result = dart_client.fetch_major_decision(
            "20240101000001", "K", decision_type=""
        )
        self.assertIn("error", result)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_related_party_and_oversized_flags(self, mock_retry):
        # inhdtl_tast_vs는 DS005 양수 8개 엔드포인트의 실제 필드명
        # (opendart_api_guide.md·실측 확인, v1.6.0에서 구 필드명
        # inhdamount_totalast_rt를 대체 — 그 필드는 실존하지 않아
        # asset_ratio가 항상 0으로 계산되던 버그가 있었다).
        mock_retry.return_value = _mock_resp(lst=[{
            "dlptn_cmpnm": "특수관계회사",
            "dlptn_rl_cmpn": "최대주주의 계열회사",
            "inh_pp": "50000000000",
            "inhdtl_tast_vs": "35.5",
            "ftc_stt_atn": "예",
            "exevl_atn": "아니오",
            "bddd": "2024-05-10",
        }])
        result = dart_client.fetch_major_decision(
            "20240510000001", "K", decision_type="stock_acq"
        )
        self.assertNotIn("error", result)
        self.assertIn("DECISION_RELATED_PARTY", result["flags"])
        self.assertIn("DECISION_OVERSIZED", result["flags"])
        self.assertIn("DECISION_NO_EXTVAL", result["flags"])
        self.assertEqual(result["asset_ratio"], 35.5)
        self.assertEqual(result["relation_text"], "최대주주의 계열회사")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_external_eval_name_and_opinion_extracted(self, mock_retry):
        # 아틀라스링크(01309795) 20260722000373 실측 필드 기반
        # (exevl_intn=평가기관명, exevl_op=평가의견 — 실제 DART 응답 필드명).
        mock_retry.return_value = _mock_resp(lst=[{
            "dlptn_cmpnm": "로아앤코홀딩스",
            "dlptn_rl_cmpn": "계열회사",
            "inh_pp": "6000000000",
            "inhdtl_tast_vs": "15.47",
            "exevl_atn": "예",
            "exevl_intn": "삼덕회계법인",
            "exevl_op": "적정",
            "bddd": "2026-07-22",
        }])
        result = dart_client.fetch_major_decision(
            "20260722000373", "K", decision_type="tangible_acq"
        )
        self.assertNotIn("error", result)
        self.assertTrue(result["external_eval"])
        self.assertEqual(result["ext_eval_name"], "삼덕회계법인")
        self.assertEqual(result["ext_eval_opinion"], "적정")
        self.assertEqual(result["relation_text"], "계열회사")
        self.assertIn("DECISION_RELATED_PARTY", result["flags"])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_network_failure(self, mock_retry):
        mock_retry.side_effect = Exception("timeout")
        result = dart_client.fetch_major_decision(
            "20240510000002", "K", decision_type="merger"
        )
        self.assertIn("error", result)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_cache_hit(self, mock_retry):
        mock_retry.return_value = _mock_resp(lst=[{"bddd": "2024-01-01"}])
        dart_client.fetch_major_decision(
            "20240101000099", "K", decision_type="merger"
        )
        first = mock_retry.call_count
        dart_client.fetch_major_decision(
            "20240101000099", "K", decision_type="merger"
        )
        self.assertEqual(mock_retry.call_count, first)


if __name__ == "__main__":
    unittest.main()
