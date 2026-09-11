# -*- coding: utf-8 -*-
"""find_actor_overlap·lookup_known_actor — 이름과 실제가 어긋나던 자리.

2026-09-11 제보(기사 작성 중 발견).

**①** 사토시홀딩스·에이전트AI·비트맥스를 5년 창으로 걸었더니 공통 행위자 2건이
전부 **임원 겸직**이었고 인수자는 1건뿐이었다. 세 회사 모두 「기업당 CB 3건 +
유상증자 3건」 상한에 걸렸기 때문인데, 화면은 **어느 회사가 걸렸는지만** 적고
**전체가 몇 건이었는지**를 말하지 않았다 — 분모가 없으면 무엇을 못 봤는지
읽을 수 없다. `analyze_company_risk`는 2026-08-30에 같은 자리를 고쳤다
(「CB/BW 공시 28건 중 최근 3건의 원문에서 추출 · 25건 미조회」).

그리고 도구 설명(docstring)은 *"CB/BW/EB 인수자 + 유상증자 인수자를 비교해"*
뿐이라 **임원 겸직을 한 글자도 말하지 않는다**. 실제 주 산출물이 그쪽인데
이름이 실제와 다르다.

**②** `lookup_known_actor`는 동봉 데이터가 빈 스켈레톤(`{"actors": {}}`)이라
무엇을 넣어도 같은 답이 온다. 그 자체는 설계(v1.5.0부터 인물 데이터 미포함)지만,
**어떻게 채우는지**를 도구가 말하지 않아 늘 빈 깡통으로 읽힌다.
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp import server


def _disclosures(n_cb, n_rights):
    out = []
    for i in range(n_cb):
        out.append({"rcept_no": f"cb{i:04d}", "report_nm": "전환사채권발행결정"})
    for i in range(n_rights):
        out.append({"rcept_no": f"rt{i:04d}", "report_nm": "유상증자결정"})
    return out


def _run(n_cb=28, n_rights=0):
    with patch("dart_risk_mcp.server._api_key", return_value="k"), \
         patch("dart_risk_mcp.server.resolve_corp",
               side_effect=lambda q, k: (q, {"corp_code": "001", "stock_code": ""})), \
         patch("dart_risk_mcp.server.fetch_company_disclosures_with_status",
               return_value=(_disclosures(n_cb, n_rights), "ok")), \
         patch("dart_risk_mcp.server.extract_cb_investors", return_value=[]), \
         patch("dart_risk_mcp.server.extract_rights_offering_investors",
               return_value=[]), \
         patch("dart_risk_mcp.server.fetch_executive_roster_detail", return_value={}), \
         patch("dart_risk_mcp.server.lookup_actor", return_value=[]):
        return server.find_actor_overlap(["갑회사", "을회사"], lookback_years=5)


class TestCapReportsDenominator(unittest.TestCase):
    def test_상한_고지에_전체_건수가_있다(self):
        out = _run(n_cb=28)
        self.assertIn("28", out, "전체 CB 공시 건수가 없다")
        self.assertIn("25", out, "미조회 건수가 없다")

    def test_상한에_안_걸리면_고지하지_않는다(self):
        out = _run(n_cb=2, n_rights=1)
        self.assertNotIn("미조회", out)

    def test_유상증자도_따로_센다(self):
        """CB와 유상증자는 각자 독립 상한이라 분모도 각자다."""
        out = _run(n_cb=0, n_rights=9)
        self.assertIn("9", out)
        self.assertIn("6", out, "유상증자 미조회 6건이 없다")

    def test_조기_종료가_집계를_깨지_않는다(self):
        """두 소스가 모두 상한에 닿아도 전체 건수는 끝까지 세야 한다."""
        out = _run(n_cb=28, n_rights=9)
        self.assertIn("28", out)
        self.assertIn("9", out)


class TestDocstringNamesWhatItDoes(unittest.TestCase):
    def test_임원_겸직을_설명에_적는다(self):
        doc = server.find_actor_overlap.__doc__ or ""
        self.assertIn("임원", doc, "주 산출물인 임원 겸직이 설명에 없다")

    def test_등기_여부를_단정하지_않는다(self):
        """미등기 임원도 잡힌다 — 「등기임원 겸직」이라 단정하면 거짓이다.

        2026-08-30에 뷰어에서 같은 단정을 고쳤다(셀트리온 이혁재는
        미등기 수석부사장이다).
        """
        doc = server.find_actor_overlap.__doc__ or ""
        self.assertNotIn("등기임원 겸직", doc)


class TestKnownActorTellsHowToFill(unittest.TestCase):
    def test_빈_응답이_채우는_법을_알려준다(self):
        with patch("dart_risk_mcp.server.lookup_actor", return_value=[]):
            out = server.lookup_known_actor("홍길동")
        self.assertTrue(
            "DART_KNOWN_ACTORS_PATH" in out or "NOTION_TOKEN" in out,
            "레지스트리를 채우는 경로가 안내되지 않는다",
        )

    def test_워치리스트와_다른_저장소임을_밝힌다(self):
        with patch("dart_risk_mcp.server.lookup_actor", return_value=[]):
            out = server.lookup_known_actor("홍길동")
        self.assertIn("manage_watchlist", out)


if __name__ == "__main__":
    unittest.main()
