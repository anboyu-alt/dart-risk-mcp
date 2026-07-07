"""R&D 비중 추출 + 연속 적자 연수 (PR-7) 테스트."""
import unittest
from unittest.mock import patch, MagicMock

from dart_risk_mcp.core.dart_client import extract_rd_values, fetch_loss_streak
from dart_risk_mcp.core import dart_client


class TestExtractRdValues(unittest.TestCase):
    # 라이브 원문 그대로의 픽스처 (2026-07 6사 검증)
    def test_celltrion_style(self):
        text = "연구개발비 / 매출액 비율 [연구개발비용계÷당기매출액×100] 11.59% 11.81% 15.75% 주1) 임상"
        self.assertEqual(extract_rd_values(text), [11.59, 11.81, 15.75])

    def test_samsung_style(self):
        text = "연구개발비 / 매출액 비율 [연구개발비용 총계÷당기매출액×100] 11.3% 11.6% 10.9% ※ 연결"
        self.assertEqual(extract_rd_values(text), [11.3, 11.6, 10.9])

    def test_helixmith_style_bare_continuation(self):
        # 첫 값만 %가 붙고 이후 연도는 % 생략된 변형
        text = "연구개발비 / 매출액 비율 [연구개발비용계÷당기매출액×100] 115.80% 173.25 562.34 마. 연구개발실적"
        self.assertEqual(extract_rd_values(text), [115.80, 173.25, 562.34])

    def test_bare_continuation_requires_decimal(self):
        # 소수점 없는 인접 정수(과제수 등)는 연속 값으로 안 잡음
        text = "연구개발비 / 매출액 비율 2.47% 과제수 82 163"
        self.assertEqual(extract_rd_values(text), [2.47])

    def test_gap_limit_blocks_distant_numbers(self):
        # 헤더와 첫 값 사이 30자 초과면 미검출 (다른 표 오탐 방지)
        text = "연구개발비 / 매출액 비율 " + ("가" * 40) + " 55.5%"
        self.assertEqual(extract_rd_values(text), [])

    def test_no_header(self):
        self.assertEqual(extract_rd_values("일반 본문에는 비율 12.3% 만 있음"), [])
        self.assertEqual(extract_rd_values(""), [])

    def test_daesan_variant_header(self):
        text = "매출액 대비 연구개발비용 비중 3.1% 2.9%"
        self.assertEqual(extract_rd_values(text), [3.1, 2.9])


def _fs_rows(op, ni):
    return [
        {"fs_div": "CFS", "account_nm": "영업이익", "thstrm_amount": str(op)},
        {"fs_div": "CFS", "account_nm": "당기순이익", "thstrm_amount": str(ni)},
    ]


class TestFetchLossStreak(unittest.TestCase):
    @patch("dart_risk_mcp.core.dart_client.fetch_financial_statements")
    def test_streak_counted_from_latest(self, mock_fs):
        # 최신 2년 적자, 3년 전 흑자 → 연속 2년
        mock_fs.side_effect = [
            _fs_rows(-10, -5),   # 직전 연도
            _fs_rows(-20, -8),
            _fs_rows(30, 12),
            _fs_rows(-1, -1),    # 흑자 이후의 과거 적자는 연속에 미포함
            _fs_rows(5, 5),
        ]
        r = fetch_loss_streak("001", "KEY", 5)
        self.assertEqual(r["op_loss_streak"], 2)
        self.assertEqual(r["ni_loss_streak"], 2)
        self.assertEqual(len(r["years"]), 5)

    @patch("dart_risk_mcp.core.dart_client.fetch_financial_statements")
    def test_missing_year_breaks_streak(self, mock_fs):
        # 중간 연도 데이터 없음 → 보수적으로 연속 중단
        mock_fs.side_effect = [_fs_rows(-10, -5), [], _fs_rows(-20, -8)]
        r = fetch_loss_streak("001", "KEY", 3)
        self.assertEqual(r["op_loss_streak"], 1)

    @patch("dart_risk_mcp.core.dart_client.fetch_financial_statements")
    def test_mixed_signs(self, mock_fs):
        # 영업적자·순흑자 → op만 연속
        mock_fs.side_effect = [_fs_rows(-10, 5), _fs_rows(-20, 8)]
        r = fetch_loss_streak("001", "KEY", 2)
        self.assertEqual(r["op_loss_streak"], 2)
        self.assertEqual(r["ni_loss_streak"], 0)

    @patch("dart_risk_mcp.core.dart_client.fetch_financial_statements")
    def test_api_error_graceful(self, mock_fs):
        mock_fs.side_effect = RuntimeError("boom")
        r = fetch_loss_streak("001", "KEY", 3)
        self.assertEqual(r["op_loss_streak"], 0)
        self.assertEqual(len(r["years"]), 3)


class TestExtractRdRatioFromReport(unittest.TestCase):
    @patch("dart_risk_mcp.core.dart_client._fetch_document_zip")
    @patch("dart_risk_mcp.core.dart_client.fetch_company_disclosures")
    def test_no_business_report_returns_empty(self, mock_discs, mock_zip):
        mock_discs.return_value = [{"report_nm": "주요사항보고서", "rcept_no": "1"}]
        self.assertEqual(
            dart_client.extract_rd_ratio_from_report("001", "KEY"), {})
        mock_zip.assert_not_called()

    @patch("dart_risk_mcp.core.dart_client._decode_zip_file")
    @patch("dart_risk_mcp.core.dart_client._fetch_document_zip")
    @patch("dart_risk_mcp.core.dart_client.fetch_company_disclosures")
    def test_extracts_from_largest_file(self, mock_discs, mock_zip, mock_decode):
        mock_discs.return_value = [
            {"report_nm": "사업보고서 (2025.12)", "rcept_no": "20260101000001"}]
        zf = MagicMock()
        zf.namelist.return_value = ["a.xml", "b.xml"]
        mock_zip.return_value = zf
        mock_decode.side_effect = [
            "<p>짧은 파일</p>",
            "<p>연구개발비 / 매출액 비율 [산식] 5.5% 4.4% 3.3% 이하 본문</p>" * 3,
        ]
        r = dart_client.extract_rd_ratio_from_report("001", "KEY")
        self.assertEqual(r["values"], [5.5, 4.4, 3.3])
        self.assertEqual(r["rcept_no"], "20260101000001")


if __name__ == "__main__":
    unittest.main()
