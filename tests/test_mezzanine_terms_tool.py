# -*- coding: utf-8 -*-
"""get_mezzanine_terms — 접수번호 하나의 발행 조건만 본다.

발행 조건 파싱(`parse_mezzanine_row`)은 이미 있는데, 그걸 보려면
`analyze_company_risk`를 통째로 돌려야 했다 — 회사 전체 분석(실측 27,248자)을
받아야 CB 한 건의 전환가액이 나온다. 취재에서는 단건 조회가 더 자주 필요하다.

픽스처는 실응답 그대로다(CSA 코스믹 00406037 · 20260910000549 ·
주요사항보고서(전환사채권발행결정), 2026-09-11 수집).

    권면총액 18,000,000,000 · 회차 6 · 전환가액 1,719
    시가하락 조정 최저한도 1,203  (발행가 대비 69.98%)
    전환시 발행주식수 10,471,204 · 주식총수 대비 60%
    표면이자율 2.0 · 만기이자율 6.5
    전환청구기간 2027.09.18 ~ 2029.08.18 · 납입일 2026.09.18
    자금용도 운영자금 18,000,000,000

⚠ **EB에는 리픽싱 필드가 없다.** 공란으로 두면 「리픽싱 조항 없음」으로 잘못
읽힌다 — `parse_mezzanine_row`의 `refix_field_absent`를 그대로 따른다.
"""
import json
import pathlib
import unittest
from unittest.mock import patch

from dart_risk_mcp import server

_FX = pathlib.Path(__file__).resolve().parent / "fixtures" / "api"
_CB = json.loads((_FX / "mezzanine_cb_20260910000549.json").read_text(encoding="utf-8"))
_ROW = {"report_nm": "주요사항보고서(전환사채권발행결정)",
        "corp_name": "CSA 코스믹", "rcept_dt": "20260910"}


_KEEP = object()   # "안 넘겼다"와 "None을 넘겼다"를 가른다


def _run(rcept="20260910000549", corp_code="00406037",
         resp=None, row=_KEEP, row_status="found"):
    with patch.object(server, "_api_key", return_value="k"), \
         patch.object(server, "resolve_disclosure_row_with_status",
                      return_value=(dict(_ROW) if row is _KEEP else row, row_status)), \
         patch.object(server, "resolve_corp_code_from_rcept_no",
                      return_value="00406037"), \
         patch.object(server, "fetch_cb_issue_decision",
                      return_value=(_CB if resp is None else resp)), \
         patch.object(server, "fetch_bw_issue_decision", return_value={}), \
         patch.object(server, "fetch_eb_issue_decision", return_value={}):
        return server.get_mezzanine_terms(rcept, corp_code)


class TestVerificationCase(unittest.TestCase):
    def test_기대값이_모두_나온다(self):
        out = _run()
        # 원문은 「1,203」·「1,719」다 — 없는 소수 자리를 만들지 않는다
        self.assertNotIn("1,203.0", out)
        self.assertNotIn("1,719.0", out)
        for v in ("18,000,000,000", "1,719", "1,203", "10,471,204",
                  "2.0", "6.5", "2027.09.18", "2029.08.18", "2026.09.18"):
            self.assertIn(v, out, f"{v}이 없다")

    def test_회차를_적는다(self):
        self.assertRegex(_run(), r"제?\s*6\s*회차")

    def test_자금용도를_적는다(self):
        self.assertIn("운영자금", _run())


class TestHeadlineNumbersComeFirst(unittest.TestCase):
    """취재에서 가장 먼저 보는 값 — 희석률과 리픽싱 하한."""

    def test_희석률이_표보다_앞에_있다(self):
        out = _run()
        self.assertLess(out.index("60"), out.index("표면이자율(%)"))

    def test_리픽싱_하한이_표보다_앞에_있다(self):
        out = _run()
        self.assertLess(out.index("1,203"), out.index("표면이자율(%)"))

    def test_하한을_발행가_대비_퍼센트로도_적는다(self):
        self.assertIn("69.98", _run())


class TestEbHasNoRefixField(unittest.TestCase):
    def test_EB는_조항_없음이_아니라_항목_없음이다(self):
        eb = {"list": [{"rcept_no": "20260101000001", "bd_tm": "1",
                        "bd_fta": "1,000,000,000", "ex_prc": "5,000",
                        "bd_intr_ex": "0.0", "bd_intr_sf": "1.0",
                        "bd_mtd": "2029년 01월 01일", "pymd": "2026년 01월 05일",
                        "exrqpd_bgd": "2027년 01월 05일",
                        "exrqpd_edd": "2028년 12월 05일",
                        "extg": "자기주식", "extg_tisstk_vs": "3"}]}
        row = {"report_nm": "주요사항보고서(교환사채권발행결정)",
               "corp_name": "테스트", "rcept_dt": "20260101"}
        with patch.object(server, "_api_key", return_value="k"), \
             patch.object(server, "resolve_disclosure_row_with_status",
                          return_value=(row, "found")), \
             patch.object(server, "fetch_eb_issue_decision", return_value=eb), \
             patch.object(server, "fetch_cb_issue_decision", return_value={}), \
             patch.object(server, "fetch_bw_issue_decision", return_value={}):
            out = server.get_mezzanine_terms("20260101000001", "00000001")
        self.assertIn("항목이 없", out)
        self.assertNotIn("리픽싱 조항 없음", out)
        # EB는 신주가 나오지 않는다 — 「희석」이라 부르면 안 된다
        self.assertIn("신주 없음", out)
        self.assertNotIn("잠재 희석", out)


class TestGuards(unittest.TestCase):
    def test_접수번호_형식을_본다(self):
        self.assertIn("접수번호", _run(rcept="123"))

    def test_메자닌_공시가_아니면_안내한다(self):
        row = {"report_nm": "주요사항보고서(유상증자결정)",
               "corp_name": "테스트", "rcept_dt": "20260101"}
        out = _run(row=row)
        self.assertIn("CB", out)
        self.assertNotIn("1,719", out)

    def test_제목을_못_읽으면_그렇게_말한다(self):
        out = _run(row=None, row_status="scan_limit")
        self.assertIn("제목", out)

    def test_corp_code_없으면_역해석한다(self):
        with patch.object(server, "_api_key", return_value="k"), \
             patch.object(server, "resolve_disclosure_row_with_status",
                          return_value=(dict(_ROW), "found")), \
             patch.object(server, "resolve_corp_code_from_rcept_no",
                          return_value="00406037") as rv, \
             patch.object(server, "fetch_cb_issue_decision", return_value=_CB), \
             patch.object(server, "fetch_bw_issue_decision", return_value={}), \
             patch.object(server, "fetch_eb_issue_decision", return_value={}):
            out = server.get_mezzanine_terms("20260910000549")
        rv.assert_called_once()
        self.assertIn("1,719", out)

    def test_구조화_응답이_비면_실패라고_말한다(self):
        out = _run(resp={})
        self.assertIn("받지 못", out)
        self.assertNotIn("1,719", out)

    def test_점수나_등급을_붙이지_않는다(self):
        out = _run()
        for banned in ("매우위험", "고위험", "위험도", "점수", "등급"):
            self.assertNotIn(banned, out)


if __name__ == "__main__":
    unittest.main()
