# -*- coding: utf-8 -*-
"""FUND_UNREPORTED의 전제 — 「납입 전」인 돈을 「받은 돈」이라 말하지 않는다.

2026-09-11 제보(기사 작성 중 발견). CSA 코스믹(00406037) 2025 반기보고서:

    납입일 2025.09.25 · 결산일 2025.06.30 · 계획 9,999,000,000원
    실제 집행 0원 · 차이사유 **「납입 전」**

원문이 스스로 "납입 전"이라 적은 건에 도구가 *"받은 돈이 어디에 쓰였는지
보고되지 않고 있습니다 … 자금 유용 가능성을 배제하기 어렵습니다"*를 붙였다.
받지도 않은 99억 9,900만원을 두고 사용내역 미보고라 한 것이다.

파급은 표시에 그치지 않는다 — `FUND_UNREPORTED`는 taxonomy **4.3**에 매핑되고
(`signals.SIGNAL_KEY_TO_TAXONOMY`), 4.3을 요구하는 패턴이 넷이다
(`delisting_evasion`·`zombie_ma`·`fake_new_biz`·`capital_churn_anomaly`).
즉 이 한 줄이 상폐 회피 패턴의 겹침 수를 올린다.

**판정은 키워드가 아니라 날짜 비교로 한다.** 30개사×4년×4개 보고서코드
실측(2026-09-11)에서 차이사유 「납입 전」은 **1건**뿐이라 표기에 기댈 수 없다.
반면 `pay_de > stlm_dt`(납입일이 그 보고서 결산일보다 늦다)는 같은 표본에서
3건이고 **그중 발화하던 것이 정확히 이 1건**이다 — 오탐 0.
"""
import unittest

from dart_risk_mcp.core import dart_client as dc


def _rec(**kw):
    """정규화 레코드 골격 — 실측 CSA 코스믹 값을 기본으로."""
    base = {
        "kind": "private", "year": 2025, "tm": "-",
        "pay_de": "2025.09.25", "stlm_dt": "20250630",
        "pay_amount": 0, "plan_useprps": "9,999", "plan_amount": 9_999_000_000,
        "real_dtls_cn": "운영자금", "real_dtls_amount": 0,
        "dffrnc_resn": "납입 전", "plan_cats": [], "real_cats": [],
    }
    base.update(kw)
    return base


class TestPaymentPendingIsNotUnreported(unittest.TestCase):
    def test_결산일_이후_납입은_미기재로_보지_않는다(self):
        """라이브 재현 건 — 결산일(0630) 이후 납입일(0925)."""
        self.assertNotIn("FUND_UNREPORTED", dc._detect_fund_anomaly(_rec()))

    def test_차이사유가_납입_전이면_날짜가_없어도_보지_않는다(self):
        """결산일이 안 오는 응답도 있으므로 표기도 함께 본다."""
        for resn in ("납입 전", "납입전", "미납입", "납입 예정"):
            with self.subTest(resn=resn):
                r = _rec(stlm_dt="", dffrnc_resn=resn)
                self.assertNotIn("FUND_UNREPORTED", dc._detect_fund_anomaly(r))

    def test_결산일_이전_납입이면_그대로_발화한다(self):
        """돈이 들어온 뒤 집행이 0이면 여전히 관찰 대상이다."""
        r = _rec(pay_de="2025.03.10", dffrnc_resn="")
        self.assertIn("FUND_UNREPORTED", dc._detect_fund_anomaly(r))

    def test_날짜가_같은_날이면_납입된_것으로_본다(self):
        """경계 — 결산일 당일 납입은 그 보고서에 잡힌다."""
        r = _rec(pay_de="2025.06.30", dffrnc_resn="")
        self.assertIn("FUND_UNREPORTED", dc._detect_fund_anomaly(r))

    def test_날짜가_비면_옛_동작_그대로다(self):
        """`stlm_dt`·`pay_de` 어느 쪽이 없어도 판정을 바꾸지 않는다."""
        for kw in ({"stlm_dt": ""}, {"pay_de": ""}, {"stlm_dt": "", "pay_de": ""}):
            with self.subTest(**kw):
                r = _rec(dffrnc_resn="", **kw)
                self.assertIn("FUND_UNREPORTED", dc._detect_fund_anomaly(r))

    def test_미사용_예치류는_계속_발화한다(self):
        """돈은 들어왔고 안 썼다고 보고한 건 — 전제가 틀리지 않았다.

        같은 표본에서 71건이며(「미사용」 25 · 「미사용잔액은 정기예금 등에
        예치」 13 …) 플래그를 빼면 패턴 입력이 통째로 달라진다. 여기서
        고치는 것은 **전제가 틀린 건 하나**이고, 나머지는 문구로 다룬다.
        """
        for resn in ("미사용", "미사용잔액은 정기예금 등에 예치", "자금 집행 시기 미도래"):
            with self.subTest(resn=resn):
                r = _rec(pay_de="2025.03.10", dffrnc_resn=resn)
                self.assertIn("FUND_UNREPORTED", dc._detect_fund_anomaly(r))

    def test_정규화가_결산일을_싣는다(self):
        """판정이 읽을 수 있도록 `stlm_dt`가 레코드에 있어야 한다."""
        item = {
            "tm": "-", "pay_de": "2025.09.25", "stlm_dt": "2025-06-30",
            "mtrpt_cptal_use_plan_useprps": "9,999",
            "mtrpt_cptal_use_plan_prcure_amount": "9,999,000,000",
            "real_cptal_use_dtls_cn": "운영자금",
            "real_cptal_use_dtls_amount": "-",
            "dffrnc_occrrnc_resn": "납입 전",
        }
        rec = dc._normalize_fund_usage(item, "private", 2025)
        self.assertEqual(rec["stlm_dt"], "20250630")
        self.assertTrue(rec["pay_pending"])
        self.assertNotIn("FUND_UNREPORTED", dc._detect_fund_anomaly(rec))


class TestProseDoesNotAssumeMoneyArrived(unittest.TestCase):
    """해설이 「납입이 끝난 자금」을 전제하지 않는다.

    발화 115건 중 **71건(62%)**에 차이사유가 적혀 있는데도 해설은
    *"이 보고가 누락되면"*이라 단정했다 — 회사가 무언가 보고한 건에
    「보고되지 않고 있습니다」라 적는 것은 제 데이터와 반대다.
    """

    def test_제목과_본문이_수령을_단정하지_않는다(self):
        from dart_risk_mcp.core.explain import FLAG_PROSE, flag_to_prose

        title, body = flag_to_prose("FUND_UNREPORTED")
        whole = f"{title} {body}"
        for banned in ("받은 돈", "납입이 끝난"):
            self.assertNotIn(banned, whole, f"수령 단정: {banned!r}")
        self.assertIn("FUND_UNREPORTED", FLAG_PROSE)


if __name__ == "__main__":
    unittest.main()
