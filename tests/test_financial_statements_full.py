# -*- coding: utf-8 -*-
"""get_financial_statements_full — 전체 계정을 사용자에게 낸다.

`get_financial_summary`는 `fetch_financial_statements`(주요 계정)를 불러 14개만
낸다. 실측 CSA 코스믹 2025에서 그 API가 주는 계정명은 14종이고 **매출원가·
판매비와관리비·금융수익·금융원가·기타이익·기타손실·지분법손익이 하나도 없다**.

재료는 이미 있었다 — `fetch_financial_statements_all`(`fnlttSinglAcntAll`)이
전체 계정을 받아 오는데, `server.py`가 회전율·Beneish·대여금 추출 같은 **내부
계산에만** 쓰고 도구로 노출한 적이 없다.

## sj_div는 IS가 아니라 CIS일 수 있다

실측(2026-09-11):

    CSA 코스믹 2025   BS 43 · **CIS 26** · CF 99 · SCE 91   ← IS **없음**
    삼성전자   2024   BS 52 · IS 17 · CIS 13 · CF 40 · SCE 91
    셀트리온   2024   BS 42 · IS 26 · CIS 12 · CF 46 · SCE 144
    두산       2024   BS 65 · IS 29 · CIS 14 · CF 60 · SCE 192

손익계산서를 따로 내는 회사도 있고 포괄손익계산서 하나만 내는 회사도 있다.
`statement="IS"`를 글자 그대로 받으면 **CSA 코스믹에서 0행**이 된다 — 그래서
`IS`는 둘 다 고른다.

## 계정명을 고치지 않는다

스펙이 「금융비용·기타수익·기타비용」이라 적었지만 원문은 **「금융원가」·
「기타이익」·「기타손실」**이다(값은 같다). 원문 표기를 우리 어휘로 바꾸면
사용자가 공시 원문에서 그 줄을 못 찾는다.
"""
import json
import pathlib
import unittest
from unittest.mock import patch

from dart_risk_mcp import server

_FX = pathlib.Path(__file__).resolve().parent / "fixtures" / "api"
_ROWS = json.loads((_FX / "fsall_csa_2025_cfs.json").read_text(encoding="utf-8"))


def _run(statement="", year="2025", fs_div="CFS", rows=None, report_type="annual"):
    seq = [list(_ROWS if rows is None else rows)]

    def _fetch(corp_code, api_key, yr, rt="annual", fd="CFS"):
        return seq[0] if fd == fs_div else []

    with patch.object(server, "_api_key", return_value="k"), \
         patch.object(server, "resolve_corp",
                      return_value=("CSA 코스믹",
                                    {"corp_code": "00406037", "stock_code": "083660"})), \
         patch.object(server, "fetch_financial_statements_all", side_effect=_fetch):
        return server.get_financial_statements_full(
            "CSA 코스믹", year, report_type, fs_div, statement)


class TestVerificationCase(unittest.TestCase):
    """스펙의 일곱 줄 — `get_financial_summary`로는 하나도 안 나온다."""

    EXPECT = {
        "매출원가": "17,729,615,657",
        "판매비와관리비": "15,834,703,455",
        "금융수익": "3,661,979,936",
        "금융원가": "3,637,741,789",      # 스펙의 「금융비용」 — 원문 표기는 이것
        "기타이익": "67,066,511",          # 스펙의 「기타수익」
        "기타손실": "1,221,114,739",       # 스펙의 「기타비용」
        "지분법손익": "-6,833,892",
    }

    def test_일곱_줄이_모두_나온다(self):
        out = _run(statement="IS")
        for name, amount in self.EXPECT.items():
            self.assertIn(name, out, f"계정 {name}이 없다")
            self.assertIn(amount, out, f"{name}의 금액 {amount}이 없다")


class TestStatementSelection(unittest.TestCase):
    def test_IS는_CIS도_고른다(self):
        """CSA 코스믹에는 IS가 없고 CIS만 있다 — 글자대로 받으면 0행이다."""
        out = _run(statement="IS")
        self.assertIn("포괄손익계산서", out)
        self.assertIn("매출원가", out)

    def test_기본은_BS와_손익과_CF다(self):
        out = _run()
        for nm in ("재무상태표", "포괄손익계산서", "현금흐름표"):
            self.assertIn(nm, out)

    def test_기본에_자본변동표는_없다(self):
        self.assertNotIn("자본변동표", _run())

    def test_SCE는_지정하면_나온다(self):
        self.assertIn("자본변동표", _run(statement="SCE"))

    def test_BS만_지정하면_손익은_없다(self):
        out = _run(statement="BS")
        self.assertIn("자산총계", out)
        self.assertNotIn("포괄손익계산서", out)

    def test_모르는_statement는_안내한다(self):
        out = _run(statement="엉뚱")
        self.assertIn("BS", out)
        self.assertNotIn("자산총계", out)


class TestOrderAndLabelsAreUntouched(unittest.TestCase):
    def test_원문_순서를_지킨다(self):
        """DART 순서는 읽는 순서가 아니다 — 영업이익이 앞, 매출액이 뒤다."""
        out = _run(statement="IS")
        self.assertLess(out.index("영업이익(손실)"), out.index("매출액"))

    def test_계정명을_바꾸지_않는다(self):
        out = _run(statement="IS")
        self.assertIn("금융원가", out)
        self.assertNotIn("| 금융비용 |", out)

    def test_손실을_이익으로_고쳐_쓰지_않는다(self):
        out = _run(statement="IS")
        self.assertIn("영업이익(손실)", out)


class TestThreePeriods(unittest.TestCase):
    def test_전전기까지_세_열을_낸다(self):
        out = _run(statement="IS")
        self.assertIn("27,930,330,148", out)   # 당기 매출액
        self.assertIn("36,380,940,773", out)   # 전기
        self.assertIn("44,586,544,406", out)   # 전전기

    def test_전전기가_없으면_그_열을_내지_않는다(self):
        rows = [dict(r) for r in _ROWS if r.get("sj_div") == "CIS"]
        for r in rows:
            r["bfefrmtrm_amount"] = ""
        out = _run(statement="IS", rows=rows)
        self.assertNotIn("44,586,544,406", out)


class TestFallbackAndFailure(unittest.TestCase):
    def test_CFS가_비면_OFS로_한_번_더_시도하고_밝힌다(self):
        calls = []

        def _fetch(corp_code, api_key, yr, rt="annual", fd="CFS"):
            calls.append(fd)
            return [] if fd == "CFS" else list(_ROWS)

        with patch.object(server, "_api_key", return_value="k"), \
             patch.object(server, "resolve_corp",
                          return_value=("CSA 코스믹", {"corp_code": "00406037",
                                                    "stock_code": "083660"})), \
             patch.object(server, "fetch_financial_statements_all", side_effect=_fetch):
            out = server.get_financial_statements_full("CSA 코스믹", "2025")
        self.assertEqual(calls, ["CFS", "OFS"])
        self.assertIn("별도", out)

    def test_둘_다_비면_자료_없음과_조회_실패를_가른다(self):
        from dart_risk_mcp.core.dart_client import FetchList
        with patch.object(server, "_api_key", return_value="k"), \
             patch.object(server, "resolve_corp",
                          return_value=("CSA 코스믹", {"corp_code": "00406037",
                                                    "stock_code": "083660"})), \
             patch.object(server, "fetch_financial_statements_all",
                          return_value=FetchList(fetch_failed=True)):
            out = server.get_financial_statements_full("CSA 코스믹", "2025")
        self.assertIn("조회", out)
        self.assertNotIn("자산총계", out)

    def test_비상장사처럼_자료가_없으면_다른_길을_안내한다(self):
        with patch.object(server, "_api_key", return_value="k"), \
             patch.object(server, "resolve_corp",
                          return_value=("현대레미콘", {"corp_code": "00111111",
                                                  "stock_code": ""})), \
             patch.object(server, "fetch_financial_statements_all", return_value=[]):
            out = server.get_financial_statements_full("현대레미콘", "2025")
        self.assertIn("get_unlisted_financials", out)


class TestTruncationIsHonest(unittest.TestCase):
    def test_잘리면_몇_행_중_몇_행인지_적는다(self):
        out = _run()
        if "생략" in out:
            self.assertRegex(out, r"\d+행")

    def test_잘린_목록으로_비율을_내지_않는다(self):
        out = _run()
        self.assertNotRegex(out, r"표시한 \d+행 중 \d+(\.\d+)?%")


class TestDocstringsPointAtEachOther(unittest.TestCase):
    def test_전체_도구가_요약_도구를_가리킨다(self):
        self.assertIn("get_financial_summary",
                      server.get_financial_statements_full.__doc__ or "")

    def test_요약_도구가_전체_도구를_가리킨다(self):
        self.assertIn("get_financial_statements_full",
                      server.get_financial_summary.__doc__ or "")


class TestNoJudgement(unittest.TestCase):
    def test_점수나_등급을_붙이지_않는다(self):
        out = _run()
        for banned in ("매우위험", "고위험", "위험도", "점수", "등급"):
            self.assertNotIn(banned, out)


if __name__ == "__main__":
    unittest.main()
