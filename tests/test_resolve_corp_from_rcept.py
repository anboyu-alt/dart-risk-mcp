"""resolve_corp_code_from_rcept_no + check_disclosure_risk DS005 섹션 복원 검증.

배경(2026-08-04 재감사): check_disclosure_risk가 fetch_major_decision을
corp_code="" 로 호출했는데, DS005 12개 엔드포인트는 corp_code+bgn_de+end_de가
항상 필수라(rcept_no 단독 모드 없음, status=100 확인) 이 섹션은 구조적으로
죽은 코드였다. rcept_no → corp_code를 list.json 1일 범위 조회로 역해석해
섹션이 실제로 발화할 수 있게 한다.
"""
import unittest
from unittest.mock import patch, MagicMock

from dart_risk_mcp.core import dart_client


def _list_resp(status="000", lst=None, total_count=None):
    resp = MagicMock()
    lst = lst or []
    resp.json.return_value = {
        "status": status,
        "message": "정상" if status == "000" else "필수값 누락",
        "list": lst,
        "total_count": total_count if total_count is not None else len(lst),
    }
    return resp


class TestResolveCorpCodeFromRceptNo(unittest.TestCase):
    def setUp(self):
        dart_client._rcept_corp_cache.clear()

    def test_invalid_rcept_no_returns_empty(self):
        self.assertEqual(
            dart_client.resolve_corp_code_from_rcept_no("123", "key"), ""
        )

    def test_no_api_key_returns_empty(self):
        self.assertEqual(
            dart_client.resolve_corp_code_from_rcept_no("20260722000373", ""), ""
        )

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_found_on_first_page(self, mock_retry):
        mock_retry.return_value = _list_resp(lst=[
            {"rcept_no": "20260722000999", "corp_code": "00000001"},
            {"rcept_no": "20260722000373", "corp_code": "01309795"},
        ])
        cc = dart_client.resolve_corp_code_from_rcept_no("20260722000373", "key")
        self.assertEqual(cc, "01309795")
        # 접수일 하루 범위 + 주요사항보고(B)로 좁혀 조회했는지
        params = mock_retry.call_args.kwargs["params"]
        self.assertEqual(params["bgn_de"], "20260722")
        self.assertEqual(params["end_de"], "20260722")
        self.assertEqual(params["pblntf_ty"], "B")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_result_is_cached(self, mock_retry):
        mock_retry.return_value = _list_resp(lst=[
            {"rcept_no": "20260722000373", "corp_code": "01309795"},
        ])
        dart_client.resolve_corp_code_from_rcept_no("20260722000373", "key")
        dart_client.resolve_corp_code_from_rcept_no("20260722000373", "key")
        self.assertEqual(mock_retry.call_count, 1)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_api_error_fails_fast(self, mock_retry):
        mock_retry.return_value = _list_resp(status="100")
        cc = dart_client.resolve_corp_code_from_rcept_no("20260722000373", "key")
        self.assertEqual(cc, "")
        self.assertEqual(mock_retry.call_count, 1)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_early_exit_on_match_in_second_page(self, mock_retry):
        page1 = _list_resp(
            lst=[{"rcept_no": f"202607220001{i:02d}", "corp_code": "00000001"}
                 for i in range(100)],
            total_count=300,
        )
        page2 = _list_resp(
            lst=[{"rcept_no": "20260722000373", "corp_code": "01309795"}],
            total_count=300,
        )
        mock_retry.side_effect = [page1, page2]
        cc = dart_client.resolve_corp_code_from_rcept_no("20260722000373", "key")
        self.assertEqual(cc, "01309795")
        # 3페이지째는 호출하지 않음 (조기 종료)
        self.assertEqual(mock_retry.call_count, 2)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_not_found_within_page_cap_returns_empty(self, mock_retry):
        pages = [
            _list_resp(
                lst=[{"rcept_no": f"2026072200{p}{i:03d}", "corp_code": "00000001"}
                     for i in range(100)],
                total_count=1000,
            )
            for p in range(5)
        ]
        mock_retry.side_effect = pages
        cc = dart_client.resolve_corp_code_from_rcept_no(
            "20260722999999", "key", max_pages=3
        )
        self.assertEqual(cc, "")
        # 페이지 상한(3) 초과 호출 금지 — API 예산 보호
        self.assertEqual(mock_retry.call_count, 3)


class TestCheckDisclosureRiskDecisionSection(unittest.TestCase):
    """check_disclosure_risk의 '주요 결정 공시' 섹션이 corp_code 역해석과 결합해 동작하는지."""

    def setUp(self):
        dart_client._rcept_corp_cache.clear()

    # resolve_disclosure_row_with_status도 패치해야 한다 — check_disclosure_risk는
    # rcept_no와 API 키가 있으면 report_name 유무와 무관하게 이 조회를 시도한다
    # (PR #166에서 "같은 공시가 호출 형태에 따라 다른 판정을 받는" 비대칭을 없애며
    # 조건이 넓어졌다). 패치하지 않으면 이 단위 테스트가 가짜 키로 실제 DART에
    # list.json 요청을 보낸다. (None, not_found)를 돌려주면 행 복원 실패 경로로 흘러
    # title=report_name이 되므로 이 테스트가 검증하려는 DS005 섹션 동작은 그대로다.
    @patch("dart_risk_mcp.server._DART_API_KEY", "key")
    @patch("dart_risk_mcp.server.fetch_document_text", return_value="")
    @patch("dart_risk_mcp.server.fetch_major_decision")
    @patch("dart_risk_mcp.server.resolve_disclosure_row_with_status",
           return_value=(None, "not_found"))
    @patch("dart_risk_mcp.server.resolve_corp_code_from_rcept_no")
    def test_section_rendered_when_corp_code_resolved(
        self, mock_resolve, _mock_row, mock_fetch, _mock_doc
    ):
        from dart_risk_mcp.server import check_disclosure_risk

        mock_resolve.return_value = "01309795"
        mock_fetch.return_value = {
            "decision_type": "tangible_acq",
            "counterparty": "주식회사 로아앤코홀딩스",
            "amount": 17_400_000_000,
            "asset_ratio": 15.47,
            "related_party": True,
            "relation_text": "계열회사",
            "external_eval": True,
            "ext_eval_name": "삼덕회계법인",
            "ext_eval_opinion": "적정",
            "bddd": "2026-07-22",
            "flags": ["DECISION_RELATED_PARTY"],
            "raw": {},
        }
        out = check_disclosure_risk(
            rcept_no="20260722000373", report_name="유형자산 양수 결정"
        )
        self.assertIn("주요 결정 공시에서 읽히는 거래 구조", out)
        self.assertIn("로아앤코홀딩스", out)
        # 역해석된 corp_code가 fetch_major_decision에 전달됐는지
        self.assertEqual(mock_fetch.call_args.args[3], "01309795")

    @patch("dart_risk_mcp.server._DART_API_KEY", "key")
    @patch("dart_risk_mcp.server.fetch_document_text", return_value="")
    @patch("dart_risk_mcp.server.fetch_major_decision")
    @patch("dart_risk_mcp.server.resolve_disclosure_row_with_status",
           return_value=(None, "not_found"))
    @patch("dart_risk_mcp.server.resolve_corp_code_from_rcept_no")
    def test_section_omitted_when_resolution_fails(
        self, mock_resolve, _mock_row, mock_fetch, _mock_doc
    ):
        from dart_risk_mcp.server import check_disclosure_risk

        mock_resolve.return_value = ""
        out = check_disclosure_risk(
            rcept_no="20260722000373", report_name="유형자산 양수 결정"
        )
        # 섹션 자체 생략, 크래시 없음
        self.assertNotIn("주요 결정 공시에서 읽히는 거래 구조", out)
        # corp_code 없이 fetch_major_decision을 호출해 status=100 헛호출을
        # 만들지 않는다 (API 예산 보호)
        mock_fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
