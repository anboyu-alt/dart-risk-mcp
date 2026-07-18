"""XBRL 감가상각비 추출(parse/extract_xbrl_depreciation) + Beneish DEPI·TATA 검증.

fnlttXbrl.xml 인스턴스에서 감가상각비를 좁게 추출해 기존에 '감가상각비 미노출'로
제외됐던 DEPI·TATA를 복원한다 (2026-07 XBRL 타당성 검토 B안).
"""
import io
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from dart_risk_mcp.core import dart_client


def _ctx(ctx_id: str, start: str, end: str, member: str = "", extra_dim: str = "") -> str:
    seg = ""
    members = []
    if member:
        members.append(
            f'<xbrldi:explicitMember dimension="ifrs-full:'
            f'ConsolidatedAndSeparateFinancialStatementsAxis">'
            f"ifrs-full:{member}</xbrldi:explicitMember>"
        )
    if extra_dim:
        members.append(
            f'<xbrldi:explicitMember dimension="ifrs-full:ProductsAndServicesAxis">'
            f"{extra_dim}</xbrldi:explicitMember>"
        )
    if members:
        seg = f"<xbrli:segment>{''.join(members)}</xbrli:segment>"
    return (
        f'<xbrli:context id="{ctx_id}">'
        f"<xbrli:entity><xbrli:identifier>x</xbrli:identifier>{seg}</xbrli:entity>"
        f"<xbrli:period><xbrli:startDate>{start}</xbrli:startDate>"
        f"<xbrli:endDate>{end}</xbrli:endDate></xbrli:period>"
        f"</xbrli:context>"
    )


def _fact(tag: str, ctx_id: str, value: int) -> str:
    return (
        f'<{tag} contextRef="{ctx_id}" unitRef="KRW" decimals="-6">{value}</{tag}>'
    )


def _instance(contexts: list[str], facts: list[str]) -> str:
    return "<xbrli:xbrl>" + "".join(contexts) + "".join(facts) + "</xbrli:xbrl>"


_TAG = "ifrs-full:DepreciationExpense"

# 연결/별도 × 당기/전기 + 분기 + 세그먼트 차원 컨텍스트를 모두 갖춘 인스턴스
_FULL_INSTANCE = _instance(
    contexts=[
        _ctx("CFY_CON", "2025-01-01", "2025-12-31", member="ConsolidatedMember"),
        _ctx("PFY_CON", "2024-01-01", "2024-12-31", member="ConsolidatedMember"),
        _ctx("CFY_SEP", "2025-01-01", "2025-12-31", member="SeparateMember"),
        _ctx("PFY_SEP", "2024-01-01", "2024-12-31", member="SeparateMember"),
        _ctx("CQ4_CON", "2025-10-01", "2025-12-31", member="ConsolidatedMember"),
        _ctx("SEG", "2025-01-01", "2025-12-31", member="ConsolidatedMember",
             extra_dim="entity:PhoneMember"),
    ],
    facts=[
        _fact(_TAG, "CFY_CON", 1000),
        _fact(_TAG, "PFY_CON", 800),
        _fact(_TAG, "CFY_SEP", 600),
        _fact(_TAG, "PFY_SEP", 500),
        _fact(_TAG, "CQ4_CON", 250),
        _fact(_TAG, "SEG", 300),
    ],
)


class TestParseXbrlDepreciation(unittest.TestCase):
    def test_cfs_picks_consolidated_full_year(self):
        r = dart_client.parse_xbrl_depreciation(_FULL_INSTANCE, "CFS")
        self.assertEqual(r["current"], 1000)
        self.assertEqual(r["prior"], 800)
        self.assertEqual(r["tag"], _TAG)

    def test_ofs_picks_separate(self):
        r = dart_client.parse_xbrl_depreciation(_FULL_INSTANCE, "OFS")
        self.assertEqual(r["current"], 600)
        self.assertEqual(r["prior"], 500)

    def test_no_axis_fallback(self):
        # 연결/별도 축이 없는 소형사 인스턴스 — 무차원 컨텍스트로 폴백
        inst = _instance(
            contexts=[
                _ctx("CFY", "2025-01-01", "2025-12-31"),
                _ctx("PFY", "2024-01-01", "2024-12-31"),
            ],
            facts=[_fact(_TAG, "CFY", 70), _fact(_TAG, "PFY", 60)],
        )
        r = dart_client.parse_xbrl_depreciation(inst, "CFS")
        self.assertEqual(r["current"], 70)
        self.assertEqual(r["prior"], 60)

    def test_no_dep_tag_returns_none(self):
        inst = _instance(
            contexts=[_ctx("CFY", "2025-01-01", "2025-12-31")],
            facts=['<ifrs-full:Revenue contextRef="CFY" unitRef="KRW">1</ifrs-full:Revenue>'],
        )
        r = dart_client.parse_xbrl_depreciation(inst, "CFS")
        self.assertIsNone(r["current"])
        self.assertIsNone(r["prior"])
        self.assertIsNone(r["tag"])


class TestFindAnnualReportRcept(unittest.TestCase):
    """사업보고서 탐색 — pblntf_ty=A 직접 조회 (대량공시 기업 누락 방지)."""

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_uses_periodic_disclosure_type_and_year_filter(self, mock_retry):
        resp = MagicMock()
        resp.json.return_value = {"status": "000", "list": [
            {"rcept_no": "20260310000001", "report_nm": "사업보고서 (2025.12)"},
            {"rcept_no": "20250311000002", "report_nm": "사업보고서 (2024.12)"},
            {"rcept_no": "20250312000003", "report_nm": "[기재정정]사업보고서 (2024.12)"},
        ]}
        mock_retry.return_value = resp
        d = dart_client._find_annual_report_rcept("00000001", "KEY", year="2024")
        self.assertEqual(d["rcept_no"], "20250311000002")
        params = mock_retry.call_args.kwargs["params"]
        self.assertEqual(params["pblntf_ty"], "A")
        # year=2024 사업보고서는 2025년에 제출됨 — 조회 창이 2025년이어야 함
        self.assertTrue(params["bgn_de"].startswith("2025"))

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_no_match_returns_empty(self, mock_retry):
        resp = MagicMock()
        resp.json.return_value = {"status": "013", "list": []}
        mock_retry.return_value = resp
        self.assertEqual(dart_client._find_annual_report_rcept("00000001", "KEY"), {})


class TestExtractXbrlDepreciation(unittest.TestCase):
    def setUp(self):
        dart_client._xbrl_dep_cache.clear()

    @patch("dart_risk_mcp.core.dart_client._retry")
    @patch("dart_risk_mcp.core.dart_client._find_annual_report_rcept")
    def test_fetches_annual_report_xbrl(self, mock_find, mock_retry):
        mock_find.return_value = {
            "rcept_no": "20260310000001", "report_nm": "사업보고서 (2025.12)"}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("entity_x_2025-12-31.xbrl", _FULL_INSTANCE)
        resp = MagicMock()
        resp.status_code = 200
        resp.content = buf.getvalue()
        mock_retry.return_value = resp

        r = dart_client.extract_xbrl_depreciation("00000001", "KEY", "CFS")
        self.assertEqual(r["current"], 1000)
        self.assertEqual(r["prior"], 800)
        called_rcept = mock_retry.call_args.kwargs["params"]["rcept_no"]
        self.assertEqual(called_rcept, "20260310000001")

    @patch("dart_risk_mcp.core.dart_client._find_annual_report_rcept")
    def test_no_annual_report_returns_empty(self, mock_find):
        mock_find.return_value = {}
        self.assertEqual(dart_client.extract_xbrl_depreciation("00000002", "KEY", "CFS"), {})


class TestBeneishDepiTata(unittest.TestCase):
    _CUR = {
        "매출액": 10000, "매출채권": 1000, "유동자산": 5000,
        "현금및현금성자산": 1000, "유동부채": 2000,
        "유형자산": 9000, "자산총계": 20000, "부채총계": 8000,
    }
    _PRI = {
        "매출액": 9000, "매출채권": 900, "유동자산": 4000,
        "현금및현금성자산": 800, "유동부채": 1800,
        "유형자산": 9200, "자산총계": 19000, "부채총계": 7600,
    }

    def test_backward_compat_without_dep(self):
        keys = {b["key"] for b in dart_client.compute_beneish_variables(self._CUR, self._PRI)}
        self.assertNotIn("DEPI", keys)
        self.assertNotIn("TATA", keys)

    def test_depi_computed(self):
        out = dart_client.compute_beneish_variables(
            self._CUR, self._PRI, dep_current=1000, dep_prior=800)
        depi = next(b for b in out if b["key"] == "DEPI")
        # rate_p = 800/(800+9200) = 0.08, rate_c = 1000/(1000+9000) = 0.10 → 0.8
        self.assertAlmostEqual(depi["value"], 0.8, places=6)

    def test_tata_computed(self):
        out = dart_client.compute_beneish_variables(
            self._CUR, self._PRI, dep_current=1000, dep_prior=800)
        tata = next(b for b in out if b["key"] == "TATA")
        # (ΔCA 1000 − ΔCash 200 − ΔCL 200 − Dep 1000) / TA 20000 = −0.02
        self.assertAlmostEqual(tata["value"], -0.02, places=6)

    def test_depi_skipped_when_ppe_missing(self):
        cur = dict(self._CUR); cur.pop("유형자산")
        out = dart_client.compute_beneish_variables(
            cur, self._PRI, dep_current=1000, dep_prior=800)
        self.assertNotIn("DEPI", {b["key"] for b in out})


if __name__ == "__main__":
    unittest.main()
