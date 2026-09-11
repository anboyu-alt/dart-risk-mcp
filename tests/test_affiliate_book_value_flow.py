# -*- coding: utf-8 -*-
"""타법인 출자현황 — 응답에 있는 장부가액 흐름을 화면이 버리지 않는다.

2026-09-11 제보(기사 작성 중 발견). CSA 코스믹 2025 사업보고서의 젠트로그룹:

    최초취득금액 7,946,837,000 · 기초 장부가액 1,294,271,000
    증감(평가)  -1,294,271,000 · 기말 장부가액 **"-"**

79억을 넣어 12.9억까지 깎였다가 **그해에 전액을 턴** 자회사인데, 표에는
기말만 실려 `-` 한 글자로 증발했다. 게다가 정렬 키가 기말 장부가액이고
파싱 실패를 -1로 두어 **목록 맨 뒤로** 밀렸다.

응답에는 `frst_acqs_amount`·`bsis_blce_acntbk_amount`·
`incrs_dcrs_acqs_dsps_amount`·`incrs_dcrs_evl_lstmn`이 **처음부터 있었다**.
`tests/test_no_dead_fields.py`는 이 부류를 못 잡는다 — 그 검사는 「읽는데
아무도 안 넣는 키」를 찾고, 이건 **응답에 있는데 아무도 안 읽는 키**다.

규모(2026-09-11 · 20개사 2025 사업보고서 · 개별 750행): 기초 잔액이 있었는데
기말이 0·미기재인 건이 **39건(5.2%)**. 이마트 ㈜에메랄드에스피브이
2조 6,531억 → 0 · 삼성전자 SoundHound Inc. 496억 → 0 ·
두산에너빌리티 Doosan Enerbility Vietnam 2,030억 → 0.

라벨은 DART 스펙 이름을 그대로 쓴다 — 같은 표본에서
`기초 + 증감(취득·처분) + 증감(평가) = 기말`이 **707/750(94%)** 성립한다.
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp.server import get_affiliate_investments

# CSA 코스믹 00406037 · 2025 사업보고서 실측 행(라이브에서 잘라 옴)
JENTRO = {
    "inv_prm": "주식회사 젠트로그룹 (*1)",
    "frst_acqs_de": "2019.09.01",
    "invstmnt_purps": "경영참여",
    "frst_acqs_amount": "7,946,837,000",
    "bsis_blce_qota_rt": "100.0",
    "bsis_blce_acntbk_amount": "1,294,271,000",
    "incrs_dcrs_acqs_dsps_amount": "-",
    "incrs_dcrs_evl_lstmn": "-1,294,271,000",
    "trmend_blce_qota_rt": "100.0",
    "trmend_blce_acntbk_amount": "-",
    "recent_bsns_year_fnnr_sttus_tot_assets": "6,223,095,000",
    "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "-1,140,164,000",
}
PLO = {
    "inv_prm": "피엘오조합",
    "frst_acqs_de": "2025.12.26",
    "invstmnt_purps": "경영참여",
    "frst_acqs_amount": "4,000,000,000",
    "bsis_blce_qota_rt": "99.98",
    "bsis_blce_acntbk_amount": "-",
    "incrs_dcrs_acqs_dsps_amount": "4,000,000,000",
    "incrs_dcrs_evl_lstmn": "4,000,000,000",
    "trmend_blce_qota_rt": "99.98",
    "trmend_blce_acntbk_amount": "4,000,000,000",
    "recent_bsns_year_fnnr_sttus_tot_assets": "4,724,016,000",
    "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "-98,509,000",
}
# 기말만 있고 규모가 작은 행 — 정렬 기준이 기말뿐이면 전액 상각 건이
# 이것보다도 뒤로 밀린다(옛 `_book`은 기말 `"-"`를 -1로 뒀다).
SMALL = {
    "inv_prm": "블루원 주식회사",
    "frst_acqs_de": "2025.11.17",
    "invstmnt_purps": "경영참여",
    "frst_acqs_amount": "25,000,000",
    "bsis_blce_qota_rt": "23.5",
    "bsis_blce_acntbk_amount": "-",
    "incrs_dcrs_acqs_dsps_amount": "564,000,000",
    "incrs_dcrs_evl_lstmn": "564,000,000",
    "trmend_blce_qota_rt": "23.5",
    "trmend_blce_acntbk_amount": "564,000,000",
    "recent_bsns_year_fnnr_sttus_tot_assets": "2,332,752,000",
    "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "-29,080,000",
}
ROWS = [JENTRO, PLO, SMALL]


def _render(rows=None):
    with patch("dart_risk_mcp.server._api_key", return_value="k"), \
         patch("dart_risk_mcp.server.resolve_corp",
               return_value=("CSA 코스믹", {"corp_code": "00406037",
                                            "stock_code": "083660"})), \
         patch("dart_risk_mcp.server.fetch_affiliate_investments",
               return_value=list(ROWS if rows is None else rows)):
        return get_affiliate_investments("CSA 코스믹", "2025")


class TestBookValueFlowIsVisible(unittest.TestCase):
    def test_기초장부가액이_표에_있다(self):
        out = _render()
        self.assertIn("기초", out)
        self.assertIn("1,294,271,000", out)

    def test_증감이_표에_있다(self):
        """전액 상각 사실은 이 칸에만 있다."""
        self.assertIn("-1,294,271,000", _render())

    def test_최초취득금액이_표에_있다(self):
        """「얼마를 넣었나」 — 79.4억."""
        self.assertIn("7,946,837,000", _render())

    def test_전액_소멸_건을_사실로_센다(self):
        """기초 잔액이 있었는데 기말이 0·미기재인 건수를 요약에 적는다."""
        out = _render()
        self.assertRegex(out, r"기말 장부가액[^\n]*(0|미기재)[^\n]*1건")

    def test_전액_소멸_건이_목록_꼴찌로_밀리지_않는다(self):
        """정렬이 기말만 보면 기초 12.9억 건이 기말 5.6억 건보다 뒤로 간다.

        `_scale`은 기초·기말 중 큰 값을 쓴다 — 그해 안에 회사가 들고 있던
        규모다. 피엘오(40억) > 젠트로(12.9억) > 블루원(5.6억)이 옳은 순서다.
        """
        out = _render()
        self.assertLess(out.index("젠트로그룹"), out.index("블루원"),
                        "기초 12.9억 건이 기말 5.6억 건보다 뒤에 있다")
        self.assertLess(out.index("피엘오조합"), out.index("젠트로그룹"))

    def test_소멸_건이_없으면_그_문장을_내지_않는다(self):
        """소음 방지 — 해당 건이 0이면 요약에 줄을 더하지 않는다."""
        self.assertNotRegex(_render([PLO]), r"기말 장부가액[^\n]*미기재[^\n]*건")

    def test_표가_깨지지_않는다(self):
        """헤더 칸 수 = 구분선 칸 수 = 각 행 칸 수."""
        rows = [ln for ln in _render().splitlines() if ln.startswith("|")]
        self.assertGreaterEqual(len(rows), 4)
        widths = {ln.count("|") for ln in rows}
        self.assertEqual(len(widths), 1, f"칸 수가 어긋남: {widths}")


class TestDocstringMatchesScreen(unittest.TestCase):
    def test_반환_설명이_없는_열을_약속하지_않는다(self):
        """독스트링이 「총자산」을 준다고 적는데 표에 그 열이 없었다."""
        doc = get_affiliate_investments.__doc__ or ""
        out = _render()
        if "총자산" in doc:
            self.assertIn("총자산", out, "독스트링이 화면에 없는 열을 약속한다")

    def test_합계_행_제외를_밝힌다(self):
        """원문에는 합계 행이 있고 이 표는 개별 건만 센다 — 침묵하지 않는다."""
        self.assertIn("합계", _render())


if __name__ == "__main__":
    unittest.main()
