# -*- coding: utf-8 -*-
"""`get_financial_summary`의 계정명도 **회사 표기가 아니다**.

`get_financial_statements_full`을 고치며 확인한 것과 같은 결함이 이 도구에도
있다 — `fnlttSinglAcnt`가 주는 계정명 역시 회사가 제출한 **XBRL 표준 태그**에
맞춘 이름이다. 실측(2026-09-12 · 8개사 241행): **15.4%가 감사보고서 원문 표기와
다르다**(같음 33.2%).

## 뜻이 뒤집히는 표기 — 15개사 중 8곳

    CSA 코스믹    API 「이익잉여금」        → 원문 「결손금」        -694억
    제이스코홀딩스  API 「이익잉여금」        → 원문 「결손금」        -963억
    STX         API 「이익잉여금」        → 원문 「Ⅴ. 결손금」     -3,229억
    CSA 코스믹    API 「영업이익」          → 원문 「영업손실」       -56억
    KR모터스      API 「법인세차감전 순이익」  → 원문 「법인세비용차감전순손실」

전부 **적자 회사**다 — 이 도구의 주 사용처가 바로 그런 회사다. 기사에
「CSA 코스믹 이익잉여금 -694억」이라 쓰면 숫자 부호는 맞지만 **회사가 쓰지 않은,
뜻이 반대인 계정명**이다.

## 왜 대조를 붙이지 않고 안내만 하나

대조에는 감사보고서 ZIP 조회가 필요하다. 이 도구는 **가볍고 빠른 것이 쓸모**라
(`get_financial_statements_full`이 그 무거운 길을 이미 맡는다) 호출을 늘리는 대신
**사실을 적고 갈 곳을 알려준다** — `compare_financials`에 한 것과 같은 처리이며
추가 호출이 0이다.
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp import server as S

_ROWS = [
    {"fs_div": "CFS", "fs_nm": "연결재무제표", "sj_div": "BS", "sj_nm": "재무상태표",
     "account_nm": "이익잉여금", "thstrm_amount": "-69,439,977,790",
     "frmtrm_amount": "-62,000,000,000", "currency": "KRW", "ord": "1"},
    {"fs_div": "CFS", "fs_nm": "연결재무제표", "sj_div": "CIS", "sj_nm": "포괄손익계산서",
     "account_nm": "영업이익", "thstrm_amount": "-5,633,988,964",
     "frmtrm_amount": "-4,000,000,000", "currency": "KRW", "ord": "2"},
]


def _run():
    with patch.object(S, "_api_key", return_value="k"), \
         patch.object(S, "resolve_corp",
                      return_value=("CSA 코스믹", {"corp_code": "00406037",
                                                "stock_code": "083660"})), \
         patch.object(S, "fetch_financial_statements", return_value=list(_ROWS)):
        return S.get_financial_summary("CSA 코스믹", "2025", "annual")


class TestFooterIsHonest(unittest.TestCase):
    def test_계정명이_공시_원문이라고_읽히지_않게_한다(self):
        out = _run()
        self.assertIn("API", out)

    def test_어긋날_수_있다는_사실을_적는다(self):
        out = _run()
        self.assertIn("다를 수 있", out)

    def test_원문_표기가_필요하면_갈_곳을_알려준다(self):
        self.assertIn("get_financial_statements_full", _run())

    def test_뜻이_뒤집히는_실례를_든다(self):
        """「어긋날 수 있다」만으로는 무슨 뜻인지 와닿지 않는다."""
        out = _run()
        self.assertIn("결손금", out)


class TestNumbersUntouched(unittest.TestCase):
    def test_금액은_그대로다(self):
        out = _run()
        self.assertIn("-69,439,977,790", out)

    def test_계정명은_API_표기_그대로_보여준다(self):
        """이 도구는 대조를 하지 않는다 — 이름을 바꾸지 않고 사실만 덧붙인다."""
        out = _run()
        self.assertIn("이익잉여금", out)


class TestNoJudgement(unittest.TestCase):
    def test_점수나_등급을_붙이지_않는다(self):
        out = _run()
        for banned in ("매우위험", "고위험", "위험도", "등급"):
            self.assertNotIn(banned, out)


if __name__ == "__main__":
    unittest.main()
