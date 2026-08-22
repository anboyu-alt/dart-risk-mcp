"""특정 보고서를 찾는 조회는 공시 유형으로 좁힌다 (2026-08-23).

`extract_rd_ratio_from_report`는 사업보고서 **하나**만 찾으면 되는데 550일치
전체를 훑고 있었다. 삼성전자는 그 창에 3,547건(36페이지)이라 기본 상한
1,000건에서 절단됐고, 사업보고서가 그 뒤에 있으면 R&D 블록이 조용히 사라진다.

정기공시(`pblntf_ty="A"`)로 좁히면 같은 창이 **7건(1페이지)**이다 — 절단이
원천적으로 없어지고 36배 싸다.

라이브(2026-08-23): `scan_financial_anomaly("삼성전자")` 16.4초 → **7.8초**,
절단 경고 사라짐, R&D 블록 유지.
"""
from unittest.mock import patch

import dart_risk_mcp.core.dart_client as dc


class _Resp:
    def json(self):
        return {"status": "000", "list": [], "total_count": 0}


class TestPblntfTyParam:
    def test_기본_호출은_유형을_안_보낸다(self):
        """옛 호출자의 동작은 그대로 — 전체 조회."""
        seen = {}

        def fake(method, url, **kw):
            seen.update(kw["params"])
            return _Resp()

        with patch.object(dc, "_retry", side_effect=fake):
            dc.fetch_company_disclosures("00126380", "k")
        assert "pblntf_ty" not in seen

    def test_유형을_주면_그대로_보낸다(self):
        seen = {}

        def fake(method, url, **kw):
            seen.update(kw["params"])
            return _Resp()

        with patch.object(dc, "_retry", side_effect=fake):
            dc.fetch_company_disclosures("00126380", "k", pblntf_ty="A")
        assert seen["pblntf_ty"] == "A"

    def test_날짜_범위와_함께_쓸_수_있다(self):
        seen = {}

        def fake(method, url, **kw):
            seen.update(kw["params"])
            return _Resp()

        with patch.object(dc, "_retry", side_effect=fake):
            dc.fetch_company_disclosures("00126380", "k", pblntf_ty="A",
                                         bgn_de="20240101", end_de="20240630")
        assert seen["pblntf_ty"] == "A"
        assert seen["bgn_de"] == "20240101"


class TestRdExtractionScope:
    def test_R_D_추출이_정기공시만_조회한다(self):
        """사업보고서는 정기공시다 — 전체를 훑을 이유가 없다."""
        seen = {}

        def fake(corp_code, api_key, lookback_days=90, max_pages=10,
                 bgn_de="", end_de="", pblntf_ty=""):
            seen["pblntf_ty"] = pblntf_ty
            seen["lookback_days"] = lookback_days
            return []

        with patch.object(dc, "fetch_company_disclosures", side_effect=fake):
            dc.extract_rd_ratio_from_report("00126380", "k")
        assert seen["pblntf_ty"] == "A"
        assert seen["lookback_days"] >= 365, "사업보고서는 연 1회라 1년 이상 필요"

    def test_사업보고서를_찾으면_그것을_쓴다(self):
        """필터를 걸어도 원래 동작(제목으로 사업보고서 선별)은 그대로."""
        rows = [
            {"report_nm": "반기보고서 (2025.06)", "rcept_no": "1"},
            {"report_nm": "사업보고서 (2025.12)", "rcept_no": "2"},
        ]
        picked = {}

        def fake_zip(rcept_no, api_key, **kw):
            picked["rcept_no"] = rcept_no
            return None            # ZIP을 못 열면 {} 반환 — 선별 결과만 본다

        with patch.object(dc, "fetch_company_disclosures", return_value=rows), \
             patch.object(dc, "_fetch_document_zip", side_effect=fake_zip):
            dc.extract_rd_ratio_from_report("00126380", "k")
        assert picked.get("rcept_no") == "2"
