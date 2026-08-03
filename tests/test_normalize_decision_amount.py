# -*- coding: utf-8 -*-
"""_normalize_decision 금액 폴백 — dlptn_cpt(거래상대방 자본금) 오사용 회귀.

opendart 실측: `dlptn_cpt`는 "거래상대방(자본금(원))" — 거래금액이 아니다.
business_acq/div는 단일 거래금액 필드가 없어(주석에도 "0으로 남는 것이
데이터 자체의 한계"라고 명시) 폴백이 dlptn_cpt에 도달하면 상대방 자본금이
거래금액으로 표시되고, ≥50억이면 DECISION_NO_EXTVAL이 잘못된 근거로
발화했다(2026-08-04 정적 감사 A-1). 금액 폴백에서 dlptn_cpt를 제거한다.
"""
import unittest

from dart_risk_mcp.core.dart_client import _normalize_decision


class TestNormalizeDecisionAmount(unittest.TestCase):
    def test_counterparty_capital_is_not_amount(self):
        raw = {
            "dlptn_cmpnm": "상대방주식회사",
            "dlptn_cpt": "9,999,999,999",  # 상대방 자본금 — 거래금액 아님
        }
        d = _normalize_decision(raw, "business_acq", "url")
        self.assertEqual(d.get("amount", 0), 0)

    def test_real_price_field_still_parses(self):
        raw = {"inhdtl_inhprc": "17,400,000,000"}
        d = _normalize_decision(raw, "tangible_acq", "url")
        self.assertEqual(d.get("amount"), 17_400_000_000)

    def test_relation_field_not_used_as_counterparty_name(self):
        # dlptn_rl_cmpn은 "거래상대방(회사와의 관계)" — 상대방 이름이 아니다.
        # 이름 폴백에 섞여 있으면 이름 자리에 "계열회사"가 표시됐다(감사 A-3).
        raw = {"dlptn_rl_cmpn": "계열회사"}
        d = _normalize_decision(raw, "tangible_acq", "url")
        self.assertEqual(d.get("counterparty"), "")
        self.assertEqual(d.get("relation_text"), "계열회사")
        self.assertTrue(d.get("related_party"))  # 관계 텍스트 기반 판정은 유지

    def test_counterparty_newline_normalized(self):
        # 코오롱인더 20260507000581 실측 — 원문 개행이 필드에 섞여 온다
        raw = {"extr_tgcmp_cmpnm": "코오롱글로텍 주식회사(\nKOLON GLOTECH, INC.)"}
        d = _normalize_decision(raw, "stock_exchange", "url")
        self.assertEqual(d.get("counterparty"),
                         "코오롱글로텍 주식회사( KOLON GLOTECH, INC.)")


if __name__ == "__main__":
    unittest.main()
