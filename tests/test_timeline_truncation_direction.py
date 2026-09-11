# -*- coding: utf-8 -*-
"""목록을 자를 때 **최근을 버리지 않는다**.

`detect_capital_churn`이 돌려주는 `events`는 `rcept_dt` **오름차순**이다
(`dart_client.py`의 `events.sort(key=lambda e: e["rcept_dt"])`). 그것을
`[:30]`으로 자르면 **가장 오래된 30건**이 남고 최근이 사라진다.

실측(2026-09-12 라이브): 제이스코홀딩스 3년 조회인데 시계열 마지막 줄이
**2025-06-27**이었다 — 2025년 하반기와 2026년 이벤트가 통째로 빠졌다.
이 도구의 목적이 「자본 주무르기 리듬」이고 불공정거래 모니터링에서 가장
중요한 구간이 최근인데, 화면은 「총 N건 중 30건 표시」라고만 적어
**어느 쪽 30건인지 말하지 않는다**.

CLAUDE.md의 `FETCH_TRUNCATED` 기록과 같은 계열이다 — 그때는 list.json이
최신순이라 오래된 쪽이 잘렸고, 여기서는 정렬이 반대라 최근이 잘린다.
공통점은 **어느 쪽이 잘리는지 화면이 말하지 않았다**는 것이다.

⚠ 표시 순서는 시간순을 지킨다 — 시계열은 흐름을 보는 것이라 뒤집으면 안 된다.
최근 N건을 **고르되** 시간순으로 그린다.
"""
import re
import unittest
from unittest.mock import patch

import pytest

from dart_risk_mcp import server as S


def _events(n: int) -> list[dict]:
    """오름차순 이벤트 n건 — 2020년부터 하루씩."""
    out = []
    for i in range(n):
        y, md = 2020 + i // 300, i % 300
        dt = f"{y}{(md // 28) + 1:02d}{(md % 28) + 1:02d}"
        out.append({"rcept_dt": dt, "report_nm": f"전환사채권발행결정 {i}",
                    "key": "CB_BW", "label": "CB/BW발행",
                    "rcept_no": f"{dt}{i:06d}"})
    return out


def _run_capital(n=50):
    evs = _events(n)
    # ⚠ 계약은 `detect_capital_churn`의 실제 반환에서 가져온다 — 손으로
    #   적으면 키가 어긋나 엉뚱한 KeyError를 쫓게 된다.
    churn = {"flags": [], "events": evs, "total_events": len(evs),
             "max_12m_count": 0, "max_dilutive_12m": 0,
             "max_non_dilutive_12m": 0, "by_year": {}, "lookback_years": 3}
    with patch.object(S, "_api_key", return_value="k"), \
         patch.object(S, "resolve_corp",
                      return_value=("갑", {"corp_code": "00000000",
                                           "stock_code": "000000"})), \
         patch.object(S, "fetch_company_disclosures_with_status",
                      return_value=([], "FETCH_OK")), \
         patch.object(S, "fetch_treasury_decisions", return_value=[]), \
         patch.object(S, "detect_capital_churn", return_value=churn), \
         patch.object(S, "fetch_debt_balance",
                      return_value={"total": 0, "year": None, "by_kind": {},
                                    "within_1y": 0, "within_1y_ratio": None,
                                    "fetch_failed": False}), \
         patch.object(S, "detect_debt_rollover",
                      return_value={"flagged": False, "reason": ""}):
        return S.track_capital_structure("갑", 3)


def _dates(out: str) -> list[str]:
    return re.findall(r"^- (\d{8}) · ", out, re.M)


@pytest.mark.usefixtures("no_structured_dart")
class TestCapitalTimeline(unittest.TestCase):
    def test_최근을_버리지_않는다(self):
        """마지막 이벤트가 화면에 있어야 한다 — 지금은 가장 오래된 30건뿐이다."""
        evs = _events(50)
        out = _run_capital(50)
        self.assertIn(evs[-1]["rcept_dt"], out,
                      "가장 최근 이벤트가 사라졌다")

    def test_표시는_시간순을_지킨다(self):
        ds = _dates(_run_capital(50))
        self.assertEqual(ds, sorted(ds), "시계열은 흐름이라 뒤집으면 안 된다")

    def test_어느_쪽_30건인지_밝힌다(self):
        """「총 N건 중 30건 표시」만으로는 **어느 쪽 30건인지** 알 수 없다."""
        out = _run_capital(50)
        self.assertRegex(out, r"총 50건 중 \*{0,2}최근 30건")
        self.assertIn("앞선 20건", out)

    def test_상한_이하면_전부_낸다(self):
        ds = _dates(_run_capital(12))
        self.assertEqual(len(ds), 12)

    def test_상한_이하면_생략_문구를_붙이지_않는다(self):
        out = _run_capital(12)
        self.assertNotIn("생략", out)


@pytest.mark.usefixtures("no_structured_dart")
class TestAnalyzeCapitalTimeline(unittest.TestCase):
    """`analyze_company_risk`의 「자본 변동 타임라인」도 같은 구조다.

    12개월 창이라 범위는 좁지만 **15개사 중 7곳이 상한(10건)을 넘는다**
    (2026-09-12 실측): 코아스 21 · 유티아이 21 · CSA 코스믹 15 · HLB 14 ·
    진원생명과학 14 · KR모터스 12 · 오르비텍 12. 그 회사들에서 화면에 남는 것은
    **가장 오래된 10건**이다 — 코아스는 11건이 잘리고 그게 전부 최근이다.
    """

    def _run(self, n):
        evs = _events(n)
        for i, e in enumerate(evs):          # 전부 12개월 창 안으로 옮긴다
            e["rcept_dt"] = f"2026{(i % 9) + 1:02d}{(i % 28) + 1:02d}"
        evs.sort(key=lambda e: e["rcept_dt"])
        churn = {"flags": [], "events": evs, "total_events": len(evs),
                 "max_12m_count": len(evs), "max_dilutive_12m": 0,
                 "max_non_dilutive_12m": 0, "by_year": {}, "lookback_years": 1}
        with patch.object(S, "_api_key", return_value="k"), \
             patch.object(S, "resolve_corp",
                          return_value=("갑", {"corp_code": "00000000",
                                               "stock_code": "000000"})), \
             patch.object(S, "fetch_company_disclosures_with_status",
                          return_value=([], "FETCH_OK")), \
             patch.object(S, "detect_capital_churn", return_value=churn):
            return S.analyze_company_risk("갑", 1), evs

    def test_최근을_버리지_않는다(self):
        out, evs = self._run(21)
        if "자본 변동 타임라인" not in out:
            self.skipTest("이 경로에서 블록이 렌더되지 않는다")
        self.assertIn(evs[-1]["rcept_dt"], out, "가장 최근 이벤트가 사라졌다")

    def test_생략된_쪽이_어디인지_밝힌다(self):
        out, _ = self._run(21)
        if "자본 변동 타임라인" not in out:
            self.skipTest("이 경로에서 블록이 렌더되지 않는다")
        self.assertIn("앞선", out)


@pytest.mark.usefixtures("no_structured_dart")
class TestDividendHistory(unittest.TestCase):
    """`track_fund_usage`의 배당 이력도 같은 구조다.

    `sorted(key=(bsns_year, se))` **오름차순** + `[:20]`이라 오래된 쪽만 남는다.
    실측(2026-09-12 라이브, 5년 조회): 삼성전자·셀트리온·KB금융·나이스정보통신이
    **전부 20줄에서 끊기고 마지막이 2022~2023년**이었다 — 최근 2~3년 배당이
    통째로 화면에 없다. 배당은 한 연도에 구분(주당배당금·배당성향·수익률 …)이
    여럿이라 5년이면 쉽게 20건을 넘는다.

    「... 외 N건」은 적고 있었지만 **그 N건이 최근이라는 사실**은 말하지 않았다.
    """

    def _run(self, n_years=6, per_year=5):
        recs = []
        for y in range(2020, 2020 + n_years):
            for k in range(per_year):
                recs.append({"bsns_year": str(y), "reprt_code": "11011",
                             "se": f"구분{k}", "stock_knd": "보통주",
                             "thstrm": f"{y}{k}", "frmtrm": "1"})
        with patch.object(S, "_api_key", return_value="k"), \
             patch.object(S, "resolve_corp",
                          return_value=("갑", {"corp_code": "00000000",
                                               "stock_code": "000000"})), \
             patch.object(S, "fetch_fund_usage", return_value=[{
                 "year": "2025", "reprt_code": "11011", "kind": "공모",
                 "tm": "1", "pay_de": "20250101", "stlm_dt": "20251231",
                 # ⚠ 금액은 **정수**다 — `fetch_fund_usage`가 `_to_int_safe`로
                 #   정규화해 넘긴다. 문자열로 두면 렌더의 `:,`가 ValueError다.
                 "plan_useprps": "운영자금", "plan_amount": 1000000000,
                 "real_dtls_cn": "운영자금", "real_dtls_amount": 1000000000,
                 "dffrnc_resn": "", "pay_amount": 1000000000,
                 "pay_pending": False, "flags": [],
                 "plan_cats": ["운영자금"], "real_cats": ["운영자금"]}]), \
             patch.object(S, "fetch_dividend_history", return_value=recs), \
             patch.object(S, "detect_dividend_drain", return_value=[]):
            return S.track_fund_usage("갑", 5)

    def test_최근_연도를_버리지_않는다(self):
        out = self._run()
        self.assertIn("2025", out, "가장 최근 배당 연도가 사라졌다")

    def test_어느_쪽이_잘렸는지_밝힌다(self):
        out = self._run()
        self.assertIn("앞선", out)

    def test_표시는_시간순을_지킨다(self):
        out = self._run()
        ys = re.findall(r"^- (\d{4})  구분", out, re.M)
        self.assertEqual(ys, sorted(ys))

    def test_상한_이하면_전부_낸다(self):
        out = self._run(n_years=2, per_year=3)
        self.assertNotIn("앞선", out)
        self.assertIn("2020", out)
        self.assertIn("2021", out)


if __name__ == "__main__":
    unittest.main()
