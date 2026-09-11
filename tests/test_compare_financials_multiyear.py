# -*- coding: utf-8 -*-
"""compare_financials 확장 — 회사 20곳 · 연도 구간.

도구가 「최대 5개 기업 · 단일 연도」로 막고 있었다. 그런데
`fetch_multi_financial`은 corp_code를 **콤마로 묶어 한 번에** 부르고
docstring도 최대 100개라 적는다 — 막은 것은 도구 쪽뿐이었다.

## 콜 수는 회사 수와 무관하다

실측(2026-09-11 · 20개사 · 2024년): **한 번의 콜로 606행 · 20개사 전부**가
왔다(누락 0). 그래서 예상 콜 수는 **연도 수**다 — 스펙이 적은 「회사 × 연도의
곱」이 아니다. 연도 폭 상한이 10이라 콜은 최대 10회다.

## 결산월은 추가 콜 없이 안다

응답에 `thstrm_dt`가 있다(`"2024.12.31 현재"` · `"2024.01.01 ~ 2024.12.31"`).
`fetch_company_info`를 회사마다 부르면 N콜이 늘지만, 이 값이면 0콜이다.

## 연결과 별도를 더하지 않는다

응답은 CFS와 OFS를 **나란히** 준다(실측 304 · 302행). 시계열 표에서는 회사마다
한쪽을 골라 쓰고 **어느 쪽인지 행에 적는다** — 섞으면 삼성전자 자산총계가
514조와 324조로 오간다.
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp import server


def _row(code, acct, amount, *, year="2024", div="CFS", sj="BS",
         dt="2024.12.31 현재", cur="KRW"):
    return {"corp_code": code, "stock_code": "", "account_nm": acct,
            "thstrm_amount": amount, "frmtrm_amount": "-", "bfefrmtrm_amount": "-",
            "bsns_year": year, "fs_div": div, "fs_nm": "연결재무제표",
            "sj_div": sj, "sj_nm": "재무상태표", "currency": cur,
            "thstrm_dt": dt, "thstrm_nm": "제 1 기", "ord": "1"}


_CODES = {"갑회사": "00000001", "을회사": "00000002", "병회사": "00000003"}


def _multi(codes, api_key, year, report_type="annual"):
    out = []
    for c in codes:
        base = 1000 * (int(c[-1])) * (int(year) - 2020)
        out.append(_row(c, "매출액", f"{base:,}", year=year, sj="IS",
                        dt=f"{year}.01.01 ~ {year}.12.31"))
        out.append(_row(c, "자산총계", f"{base * 3:,}", year=year))
        out.append(_row(c, "영업이익", f"{base // 10:,}", year=year, sj="IS",
                        dt=f"{year}.01.01 ~ {year}.12.31"))
    return out


def _run(names, year="2024", year_to="", accounts=None, multi=_multi,
         resolve=None):
    def _res(q, k):
        if resolve is not None:
            return resolve(q, k)
        return (q, {"corp_code": _CODES[q], "stock_code": ""}) if q in _CODES else None

    with patch.object(server, "_api_key", return_value="k"), \
         patch.object(server, "resolve_corp", side_effect=_res), \
         patch.object(server, "fetch_multi_financial", side_effect=multi):
        return server.compare_financials(names, year, year_to, "annual", accounts)


class TestCompanyLimit(unittest.TestCase):
    def test_스무_곳까지_받는다(self):
        codes = {f"회사{i}": f"{i:08d}" for i in range(1, 21)}
        with patch.object(server, "_api_key", return_value="k"), \
             patch.object(server, "resolve_corp",
                          side_effect=lambda q, k: (q, {"corp_code": codes[q],
                                                        "stock_code": ""})), \
             patch.object(server, "fetch_multi_financial", side_effect=_multi):
            out = server.compare_financials(list(codes), "2024")
        self.assertNotIn("최대", out.splitlines()[0])
        self.assertIn("회사20", out)

    def test_스물한_곳이면_나눠_부르라고_한다(self):
        out = _run([f"회사{i}" for i in range(21)])
        self.assertIn("20", out)
        self.assertIn("나눠", out)

    def test_한_곳이면_거절한다(self):
        self.assertIn("2개", _run(["갑회사"]))


class TestYearRange(unittest.TestCase):
    def test_구간을_주면_연도별로_낸다(self):
        out = _run(["갑회사", "을회사"], "2022", "2024")
        for y in ("2022", "2023", "2024"):
            self.assertIn(y, out)

    def test_연도마다_한_번씩만_부른다(self):
        """콜 수는 **연도 수**다 — 회사 수와 곱해지지 않는다."""
        calls = []

        def _spy(codes, api_key, year, report_type="annual"):
            calls.append((tuple(codes), year))
            return _multi(codes, api_key, year, report_type)

        _run(["갑회사", "을회사", "병회사"], "2022", "2024", multi=_spy)
        self.assertEqual([y for _, y in calls], ["2022", "2023", "2024"])
        self.assertTrue(all(len(c) == 3 for c, _ in calls),
                        "회사를 한 번에 묶어 보내야 한다")

    def test_예상_콜_수를_밝힌다(self):
        out = _run(["갑회사", "을회사"], "2022", "2024")
        self.assertIn("3", out)
        self.assertTrue("콜" in out or "조회" in out)

    def test_열_해를_넘기면_거절하고_이유를_밝힌다(self):
        out = _run(["갑회사", "을회사"], "2010", "2024")
        self.assertIn("10", out)
        self.assertNotIn("━━", out)

    def test_역순_구간은_거절한다(self):
        self.assertIn("❌", _run(["갑회사", "을회사"], "2024", "2022"))

    def test_구간을_안_주면_옛_동작_그대로다(self):
        out = _run(["갑회사", "을회사"], "2024")
        self.assertIn("━━ 갑회사 ━━", out)


class TestAccountFilter(unittest.TestCase):
    def test_계정을_좁힌다(self):
        out = _run(["갑회사", "을회사"], "2022", "2024", accounts=["매출액"])
        self.assertIn("매출액", out)
        self.assertNotIn("자산총계", out)

    def test_부분일치로_고른다(self):
        out = _run(["갑회사", "을회사"], "2022", "2024", accounts=["영업"])
        self.assertIn("영업이익", out)

    def test_아무것도_안_걸리면_그렇게_말한다(self):
        out = _run(["갑회사", "을회사"], "2022", "2024", accounts=["없는계정"])
        self.assertIn("없는계정", out)
        self.assertNotIn("매출액", out)


class TestFactsAreKept(unittest.TestCase):
    def test_비12월_결산을_밝힌다(self):
        def _m(codes, api_key, year, report_type="annual"):
            rows = _multi(codes, api_key, year, report_type)
            for r in rows:
                if r["corp_code"] == "00000002":
                    r["thstrm_dt"] = f"{year}.03.31 현재"
            return rows

        out = _run(["갑회사", "을회사"], "2022", "2024", multi=_m)
        self.assertIn("결산", out)
        self.assertIn("을회사", out)

    def test_연결인지_별도인지_회사마다_적는다(self):
        def _m(codes, api_key, year, report_type="annual"):
            rows = _multi(codes, api_key, year, report_type)
            for r in rows:
                if r["corp_code"] == "00000002":
                    r["fs_div"] = "OFS"
                    r["fs_nm"] = "재무제표"
            return rows

        out = _run(["갑회사", "을회사"], "2022", "2024", multi=_m)
        self.assertIn("연결", out)
        self.assertIn("별도", out)

    def test_찾지_못한_회사를_빈칸으로_두지_않는다(self):
        def _res(q, k):
            return (q, {"corp_code": _CODES[q], "stock_code": ""}) if q in _CODES else None

        out = _run(["갑회사", "을회사", "없는회사"], "2022", "2024", resolve=_res)
        self.assertIn("없는회사", out)
        self.assertIn("찾", out)

    def test_한_해가_비면_그_해를_밝힌다(self):
        def _m(codes, api_key, year, report_type="annual"):
            return [] if year == "2023" else _multi(codes, api_key, year, report_type)

        out = _run(["갑회사", "을회사"], "2022", "2024", multi=_m)
        self.assertIn("2023", out)

    def test_점수나_등급을_붙이지_않는다(self):
        out = _run(["갑회사", "을회사"], "2022", "2024")
        for banned in ("매우위험", "고위험", "위험도", "점수", "등급"):
            self.assertNotIn(banned, out)


if __name__ == "__main__":
    unittest.main()
