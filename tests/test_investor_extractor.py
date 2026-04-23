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
            investors = extract_rights_offering_investors("20240201000001", "key")
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
            investors = extract_rights_offering_investors("20240201000002", "key")
        self.assertEqual(len(investors), 1)
        self.assertEqual(investors[0]["name"], "CC파트너스")

    def test_extract_empty_on_fric_only(self):
        # 무상증자는 인수인 개념이 없어 빈 리스트
        with patch(
            "dart_risk_mcp.core.investor_extractor.fetch_piic_decision",
            return_value={},
        ), patch(
            "dart_risk_mcp.core.investor_extractor.fetch_pifric_decision",
            return_value={},
        ):
            investors = extract_rights_offering_investors("20240201000003", "key")
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
            investors = extract_rights_offering_investors("20240201000004", "key")
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
            investors = extract_rights_offering_investors("20240201000005", "key")
        self.assertEqual(len(investors), 1)
        self.assertEqual(investors[0]["name"], "정상펀드")


if __name__ == "__main__":
    unittest.main()
