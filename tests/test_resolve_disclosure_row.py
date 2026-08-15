# -*- coding: utf-8 -*-
"""resolve_disclosure_row_from_rcept_no 단위 테스트.

배경: check_disclosure_risk가 rcept_no로 불릴 때 title을 f"접수번호 {rcept_no}"
자리표시자로 만들어 match_signals에 넘겨, 어떤 신호도 매칭될 수 없었다
(함수 132줄에 report_nm이 0회 등장). 실제 행을 복원해 제목·제출인을 얻는다.

기존 resolve_corp_code_from_rcept_no와 별개 함수인 이유: 그쪽은
pblntf_ty="B"(주요사항보고)로 좁혀 조회해 지분공시(D)·거래소공시(H)를
찾지 못한다(실측: 대량보유보고 20260731000779 → ""). 통합하면 DS005 경로의
호출 예산이 1페이지에서 12페이지로 늘어난다.
"""
import unittest
from unittest.mock import patch, MagicMock

from dart_risk_mcp.core import dart_client


def _list_resp(status="000", lst=None, total_page=1):
    resp = MagicMock()
    lst = lst or []
    resp.json.return_value = {
        "status": status,
        "message": "정상" if status == "000" else "필수값 누락",
        "list": lst,
        "total_page": total_page,
        "total_count": len(lst),
    }
    return resp


_ROW = {
    "rcept_no": "20260731000779",
    "corp_code": "00126380",
    "corp_name": "삼성전자",
    "stock_code": "005930",
    "corp_cls": "Y",
    "report_nm": "주식등의대량보유상황보고서(일반)",
    "flr_nm": "삼성물산",
    "rcept_dt": "20260731",
    "rm": "",
}


class TestResolveDisclosureRow(unittest.TestCase):
    def setUp(self):
        dart_client._rcept_row_cache.clear()

    def test_invalid_rcept_no_returns_none(self):
        self.assertIsNone(
            dart_client.resolve_disclosure_row_from_rcept_no("123", "key")
        )

    def test_no_api_key_returns_none(self):
        self.assertIsNone(
            dart_client.resolve_disclosure_row_from_rcept_no("20260731000779", "")
        )

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_found_on_first_page_returns_full_row(self, mock_retry):
        mock_retry.return_value = _list_resp(lst=[
            {"rcept_no": "20260731000111", "corp_name": "다른회사"},
            _ROW,
        ])
        row = dart_client.resolve_disclosure_row_from_rcept_no(
            "20260731000779", "key"
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["report_nm"], "주식등의대량보유상황보고서(일반)")
        self.assertEqual(row["flr_nm"], "삼성물산")
        self.assertEqual(row["corp_name"], "삼성전자")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_does_not_send_pblntf_ty(self, mock_retry):
        """유형 필터를 보내면 지분공시(D)·거래소공시(H)를 못 찾는다."""
        mock_retry.return_value = _list_resp(lst=[_ROW])
        dart_client.resolve_disclosure_row_from_rcept_no("20260731000779", "key")
        params = mock_retry.call_args.kwargs["params"]
        self.assertNotIn("pblntf_ty", params)
        self.assertEqual(params["bgn_de"], "20260731")
        self.assertEqual(params["end_de"], "20260731")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_found_on_later_page(self, mock_retry):
        mock_retry.side_effect = [
            _list_resp(lst=[{"rcept_no": "20260731000001"}], total_page=3),
            _list_resp(lst=[{"rcept_no": "20260731000002"}], total_page=3),
            _list_resp(lst=[_ROW], total_page=3),
        ]
        row = dart_client.resolve_disclosure_row_from_rcept_no(
            "20260731000779", "key"
        )
        self.assertIsNotNone(row)
        self.assertEqual(mock_retry.call_count, 3)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_stops_at_total_page(self, mock_retry):
        mock_retry.return_value = _list_resp(
            lst=[{"rcept_no": "20260731000001"}], total_page=2
        )
        row = dart_client.resolve_disclosure_row_from_rcept_no(
            "20260731000779", "key"
        )
        self.assertIsNone(row)
        self.assertEqual(mock_retry.call_count, 2)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_respects_max_pages(self, mock_retry):
        mock_retry.return_value = _list_resp(
            lst=[{"rcept_no": "20260731000001"}], total_page=99
        )
        row = dart_client.resolve_disclosure_row_from_rcept_no(
            "20260731000779", "key", max_pages=4
        )
        self.assertIsNone(row)
        self.assertEqual(mock_retry.call_count, 4)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_bad_status_stops_immediately(self, mock_retry):
        mock_retry.return_value = _list_resp(status="100", total_page=9)
        row = dart_client.resolve_disclosure_row_from_rcept_no(
            "20260731000779", "key"
        )
        self.assertIsNone(row)
        self.assertEqual(mock_retry.call_count, 1)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_network_error_returns_none(self, mock_retry):
        mock_retry.side_effect = RuntimeError("boom")
        self.assertIsNone(
            dart_client.resolve_disclosure_row_from_rcept_no(
                "20260731000779", "key"
            )
        )

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_second_call_hits_cache(self, mock_retry):
        mock_retry.return_value = _list_resp(lst=[_ROW])
        dart_client.resolve_disclosure_row_from_rcept_no("20260731000779", "key")
        dart_client.resolve_disclosure_row_from_rcept_no("20260731000779", "key")
        self.assertEqual(mock_retry.call_count, 1)

    def test_row_cache_is_separate_from_corp_cache(self):
        """값 타입이 dict vs str이고 조회 범위도 달라 공유하면 오염된다."""
        self.assertIsNot(
            dart_client._rcept_row_cache, dart_client._rcept_corp_cache
        )


if __name__ == "__main__":
    unittest.main()
