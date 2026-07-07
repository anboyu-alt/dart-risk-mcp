"""타법인 출자현황 조회 (get_affiliate_investments, PR-3) 테스트."""
import unittest
from unittest.mock import patch, MagicMock

from dart_risk_mcp.core import dart_client
from dart_risk_mcp import server


def _resp(status="000", lst=None):
    m = MagicMock()
    m.json.return_value = {"status": status, "list": lst or []}
    return m


SAMPLE_ROWS = [
    {"inv_prm": "합계", "trmend_blce_qota_rt": "-", "trmend_blce_acntbk_amount": "999999"},
    {"inv_prm": "알파SPC", "invstmnt_purps": "경영참여",
     "trmend_blce_qota_rt": "100.0", "trmend_blce_acntbk_amount": "5,000",
     "frst_acqs_de": "20240315", "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "(1,200)"},
    {"inv_prm": "베타조합", "invstmnt_purps": "단순투자",
     "trmend_blce_qota_rt": "12.5", "trmend_blce_acntbk_amount": "80,000",
     "frst_acqs_de": "20191102", "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "3,400"},
    {"inv_prm": "감마상사", "invstmnt_purps": "경영참여",
     "trmend_blce_qota_rt": "51.0", "trmend_blce_acntbk_amount": "-",
     "frst_acqs_de": "20240701", "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "-"},
]


class TestFetchAffiliateInvestments(unittest.TestCase):
    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_returns_rows_without_totals(self, mock_retry):
        mock_retry.return_value = _resp(lst=SAMPLE_ROWS)
        rows = dart_client.fetch_affiliate_investments("00000001", "KEY", "2024")
        names = [r["inv_prm"] for r in rows]
        self.assertNotIn("합계", names)
        self.assertEqual(len(rows), 3)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_non_000_status_returns_empty(self, mock_retry):
        mock_retry.return_value = _resp(status="013")
        self.assertEqual(dart_client.fetch_affiliate_investments("00000001", "KEY", "2024"), [])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_exception_returns_empty(self, mock_retry):
        mock_retry.side_effect = RuntimeError("boom")
        self.assertEqual(dart_client.fetch_affiliate_investments("00000001", "KEY", "2024"), [])

    def test_missing_key_returns_empty(self):
        self.assertEqual(dart_client.fetch_affiliate_investments("00000001", "", "2024"), [])


@patch.dict("os.environ", {"DART_API_KEY": "KEY"})
@patch("dart_risk_mcp.server.fetch_affiliate_investments")
@patch("dart_risk_mcp.server.resolve_corp")
class TestGetAffiliateInvestmentsTool(unittest.TestCase):
    def test_renders_facts_and_table(self, mock_resolve, mock_fetch):
        mock_resolve.return_value = ("테스트기업", {"corp_code": "001", "stock_code": "123456"})
        mock_fetch.return_value = SAMPLE_ROWS[1:]  # 합계 제외분
        out = server.get_affiliate_investments("테스트기업", year="2024")
        # 요약 사실 라인
        self.assertIn("총 3건", out)
        self.assertIn("지분율 50% 이상 2건", out)      # 알파SPC 100%, 감마상사 51%
        self.assertIn("순이익 적자 1건", out)          # 알파SPC (1,200)
        self.assertIn("2024년 신규 취득 2건", out)     # 알파SPC, 감마상사
        # 표 정렬: 장부가액 80,000(베타) > 5,000(알파) > -(감마)
        self.assertLess(out.index("베타조합"), out.index("알파SPC"))
        self.assertLess(out.index("알파SPC"), out.index("감마상사"))
        # 단위 유의 안내
        self.assertIn("단위", out)

    def test_empty_result_message(self, mock_resolve, mock_fetch):
        mock_resolve.return_value = ("테스트기업", {"corp_code": "001", "stock_code": ""})
        mock_fetch.return_value = []
        out = server.get_affiliate_investments("테스트기업", year="2024")
        self.assertIn("찾지 못했습니다", out)

    def test_unknown_company(self, mock_resolve, mock_fetch):
        mock_resolve.return_value = ("", {})
        out = server.get_affiliate_investments("없는회사")
        self.assertIn("찾을 수 없습니다", out)

    def test_top30_footer(self, mock_resolve, mock_fetch):
        mock_resolve.return_value = ("테스트기업", {"corp_code": "001", "stock_code": ""})
        mock_fetch.return_value = [
            {"inv_prm": f"법인{i}", "invstmnt_purps": "단순투자",
             "trmend_blce_qota_rt": "1.0", "trmend_blce_acntbk_amount": str(i),
             "frst_acqs_de": "20200101", "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "1"}
            for i in range(40)
        ]
        out = server.get_affiliate_investments("테스트기업", year="2024")
        self.assertIn("외 10건", out)

    def test_multiline_purpose_does_not_break_table(self, mock_resolve, mock_fetch):
        # 라이브 발견 사례(제이스코 JSCO PH): 출자목적에 개행 포함 → 표 붕괴 방지
        mock_resolve.return_value = ("테스트기업", {"corp_code": "001", "stock_code": ""})
        mock_fetch.return_value = [
            {"inv_prm": "해외법인", "invstmnt_purps": "필리핀 현지법인\n설립",
             "trmend_blce_qota_rt": "95", "trmend_blce_acntbk_amount": "100",
             "frst_acqs_de": "20230405", "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "-1"},
        ]
        out = server.get_affiliate_investments("테스트기업", year="2024")
        self.assertIn("필리핀 현지법인 설립", out)
        for line in out.splitlines():
            if line.startswith("|") and "해외법인" in line:
                self.assertEqual(line.count("|"), 7)  # 6컬럼 = 파이프 7개

    def test_no_score_or_grade_words(self, mock_resolve, mock_fetch):
        # v0.8.5: 점수·등급 표현 미유입
        import re
        mock_resolve.return_value = ("테스트기업", {"corp_code": "001", "stock_code": ""})
        mock_fetch.return_value = SAMPLE_ROWS[1:]
        out = server.get_affiliate_investments("테스트기업", year="2024")
        self.assertIsNone(re.search(r"매우위험|고위험|중위험|저위험|위험\s*등급|종합\s*스코어", out))


if __name__ == "__main__":
    unittest.main()
