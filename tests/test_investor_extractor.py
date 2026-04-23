import unittest
from unittest.mock import patch
from dart_risk_mcp.core.investor_extractor import extract_rights_offering_investors


class TestExtractRightsOfferingInvestors(unittest.TestCase):
    def test_extract_from_piic_decision_success(self):
        payload = {
            "status": "000",
            "list": [
                {"actsen": "제3자배정", "actnmn": "AA펀드", "fric_tisstk_fta": "10000000000"},
                {"actsen": "일반공모", "actnmn": "BB증권", "fric_tisstk_fta": "5000000000"},
            ],
        }
        with patch(
            "dart_risk_mcp.core.investor_extractor.fetch_piic_decision",
            return_value=payload,
        ):
            investors = extract_rights_offering_investors("20240201000001", "key", "testcc")
        self.assertEqual(len(investors), 2)
        self.assertEqual(investors[0]["name"], "AA펀드")
        self.assertEqual(investors[0]["type"], "제3자배정")
        self.assertEqual(investors[0]["amount"], "10000000000")
        self.assertEqual(investors[0]["source"], "rights_offering")

    def test_extract_empty_on_no_piic_data_tries_pifric(self):
        pifric_payload = {
            "status": "000",
            "list": [{"actsen": "제3자배정", "actnmn": "CC파트너스", "fric_tisstk_fta": "2000000000"}],
        }
        with patch(
            "dart_risk_mcp.core.investor_extractor.fetch_piic_decision",
            return_value={},
        ), patch(
            "dart_risk_mcp.core.investor_extractor.fetch_pifric_decision",
            return_value=pifric_payload,
        ):
            investors = extract_rights_offering_investors("20240201000002", "key", "testcc")
        self.assertEqual(len(investors), 1)
        self.assertEqual(investors[0]["name"], "CC파트너스")

    def test_extract_empty_on_fric_only(self):
        # 무상증자는 인수인 개념이 없어 구조화+HTML 모두 빈 리스트
        with patch(
            "dart_risk_mcp.core.investor_extractor.fetch_piic_decision",
            return_value={},
        ), patch(
            "dart_risk_mcp.core.investor_extractor.fetch_pifric_decision",
            return_value={},
        ), patch(
            "dart_risk_mcp.core.investor_extractor._html_fallback",
            return_value=[],
        ):
            investors = extract_rights_offering_investors("20240201000003", "key", "testcc")
        self.assertEqual(investors, [])

    def test_extract_cleans_name_whitespace(self):
        payload = {
            "status": "000",
            "list": [{"actsen": "제3자배정", "actnmn": "  AA  펀드  ", "fric_tisstk_fta": "1"}],
        }
        with patch(
            "dart_risk_mcp.core.investor_extractor.fetch_piic_decision",
            return_value=payload,
        ):
            investors = extract_rights_offering_investors("20240201000004", "key", "testcc")
        self.assertEqual(investors[0]["name"], "AA 펀드")

    def test_extract_skips_blank_names(self):
        payload = {
            "status": "000",
            "list": [
                {"actsen": "제3자배정", "actnmn": "", "fric_tisstk_fta": "1"},
                {"actsen": "제3자배정", "actnmn": "-", "fric_tisstk_fta": "1"},
                {"actsen": "제3자배정", "actnmn": "정상펀드", "fric_tisstk_fta": "1"},
            ],
        }
        with patch(
            "dart_risk_mcp.core.investor_extractor.fetch_piic_decision",
            return_value=payload,
        ):
            investors = extract_rights_offering_investors("20240201000005", "key", "testcc")
        self.assertEqual(len(investors), 1)
        self.assertEqual(investors[0]["name"], "정상펀드")

    def test_extract_fallbacks_to_pifric_on_empty_piic_list(self):
        # DART가 status=000이지만 빈 list를 반환하는 경우에도 pifric로 폴백해야 한다
        piic_empty = {"status": "000", "list": []}
        pifric_payload = {
            "status": "000",
            "list": [{"actsen": "제3자배정", "actnmn": "DD펀드",
                      "fric_tisstk_fta": "3000000000"}],
        }
        with patch(
            "dart_risk_mcp.core.investor_extractor.fetch_piic_decision",
            return_value=piic_empty,
        ), patch(
            "dart_risk_mcp.core.investor_extractor.fetch_pifric_decision",
            return_value=pifric_payload,
        ) as mock_pifric:
            investors = extract_rights_offering_investors("20240201000006", "key", "testcc")
        mock_pifric.assert_called_once()
        self.assertEqual(len(investors), 1)
        self.assertEqual(investors[0]["name"], "DD펀드")

    def test_skips_structured_uses_html_when_no_corp_code(self):
        # corp_code 없으면 구조화 경로 건너뜀, 바로 HTML 폴백
        html_result = [{"name": "HTML추출", "type": "", "amount": "", "source": "rights_offering"}]
        with patch(
            "dart_risk_mcp.core.investor_extractor.fetch_piic_decision"
        ) as mock_piic, patch(
            "dart_risk_mcp.core.investor_extractor._html_fallback",
            return_value=html_result,
        ):
            investors = extract_rights_offering_investors("20240201000007", "key")
        mock_piic.assert_not_called()
        self.assertEqual(investors[0]["name"], "HTML추출")


if __name__ == "__main__":
    unittest.main()
