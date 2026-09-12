# -*- coding: utf-8 -*-
"""라틴 브랜드 표기 → 한글 음사 해석 (2026-09-13).

배경: DART corpCode.xml의 정식 명칭은 라틴 브랜드를 한글로 음사한다
(케이티앤지 ← KT&G). 사용자는 브랜드 표기로 묻는데 명부에 그 글자가 없어
`resolve_corp("KT&G")`가 None이었다 — 코스피 상위 종목인데도.

이 테스트가 고정하는 것:
  ① 음사 변환 자체가 결정적일 것
  ② 음사는 **마지막 수단**일 것 — 앞 경로(정확·종목코드·별칭·부분)의 답을
     한 건도 바꾸지 않는다. 명부 전수 실측에서 무조건 적용하면 84건이 바뀌고
     살아 있는 회사가 폐지된 껍데기로 밀려났다(IPS·KR·DS).
  ③ 한 글자 머리는 음사하지 않을 것
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp.core import dart_client as dc


class TestLatinHeadToHangul(unittest.TestCase):
    """① 변환 규칙 — 네트워크 없이."""

    def test_브랜드_표기를_음사한다(self):
        cases = {
            "KT&G": "케이티앤지",
            "TKG휴켐스": "티케이지휴켐스",
            "LS일렉트릭": "엘에스일렉트릭",
            "SK바이오팜": "에스케이바이오팜",
            "GI이노베이션": "지아이이노베이션",
            "RF세미": "알에프세미",
            "F&가이드": "에프앤가이드",
        }
        for q, want in cases.items():
            with self.subTest(q=q):
                self.assertEqual(dc.latin_head_to_hangul(q), want)

    def test_대소문자를_가리지_않는다(self):
        self.assertEqual(dc.latin_head_to_hangul("kt&g"), "케이티앤지")

    def test_한_글자_머리는_음사하지_않는다(self):
        # "K" → 「케이」는 흔한 낱말이라 오타 한 글자가 엉뚱한 회사를 부른다.
        # 부분 일치의 _MIN_PARTIAL_QUERY 와 같은 판단.
        for q in ("K", "S전자", "A"):
            with self.subTest(q=q):
                self.assertEqual(dc.latin_head_to_hangul(q), "")

    def test_라틴으로_시작하지_않으면_빈_값(self):
        for q in ("삼성전자", "", "   ", "1KT", "케이티앤지"):
            with self.subTest(q=q):
                self.assertEqual(dc.latin_head_to_hangul(q), "")

    def test_머리는_구분자에서_끊긴다(self):
        # 머리 구간은 A-Z 와 & 만 받는다. 'K-T' 의 머리는 'K' 한 글자라
        # _MIN_TRANSLIT_HEAD 에 걸려 음사하지 않는다 — 「케이」로 번지면 안 된다.
        self.assertEqual(dc.latin_head_to_hangul("K-T"), "")
        self.assertEqual(dc.latin_head_to_hangul("2K"), "")
        # 두 글자 이상이면 구분자 앞까지만 음사하고 나머지는 그대로 둔다.
        self.assertEqual(dc.latin_head_to_hangul("KT-1"), "케이티-1")

    def test_한글_꼬리는_그대로_둔다(self):
        self.assertEqual(dc.latin_head_to_hangul("KB제27호기업인수목적"),
                         "케이비제27호기업인수목적")


def _cache(mapping):
    """{이름: (corp_code, stock_code)} → _corp_cache 모양."""
    return {n: {"corp_code": c, "stock_code": s} for n, (c, s) in mapping.items()}


class TestResolveOrder(unittest.TestCase):
    """② 음사는 마지막 수단 — 앞 경로의 답을 바꾸지 않는다."""

    def setUp(self):
        self.p1 = patch.object(dc, "load_corp_aliases", return_value={})
        self.p1.start()
        self.addCleanup(self.p1.stop)

    def _resolve(self, cache, query):
        with patch.object(dc, "_corp_cache", _cache(cache)):
            return dc.resolve_corp(query, "k")

    def test_음사로_KT_and_G를_찾는다(self):
        r = self._resolve({"케이티앤지": ("00244455", "033780")}, "KT&G")
        self.assertIsNotNone(r, "KT&G 가 여전히 None 이다")
        self.assertEqual(r[0], "케이티앤지")
        self.assertEqual(r[1]["stock_code"], "033780")
        self.assertIn("음사", r[1]["alias_note"])

    def test_정확_일치가_음사보다_앞선다(self):
        # 'F&F' 는 명부에 그 표기 그대로 있다 — 음사(에프앤에프)로 가면 안 된다.
        r = self._resolve({"F&F": ("1", "383220"), "에프앤에프": ("2", "999999")}, "F&F")
        self.assertEqual(r[0], "F&F")
        self.assertNotIn("alias_note", r[1])

    def test_부분_일치가_음사보다_앞선다(self):
        # 실측 회귀: 'IPS' 는 원익IPS(현존)를 잡아야 하고
        # 아이피에스(폐지)로 밀려나면 안 된다.
        r = self._resolve({"원익IPS": ("1", "240810"), "아이피에스": ("2", "051820")}, "IPS")
        self.assertEqual(r[0], "원익IPS")

    def test_종목코드가_음사보다_앞선다(self):
        r = self._resolve({"케이티앤지": ("00244455", "033780")}, "033780")
        self.assertEqual(r[0], "케이티앤지")
        self.assertNotIn("alias_note", r[1])

    def test_음사_결과가_명부에_없으면_None(self):
        # 「에스피씨삼립」은 없다(정식 명칭이 「삼립」) — 지어내지 않는다.
        self.assertIsNone(self._resolve({"삼립": ("1", "005610")}, "SPC삼립"))

    def test_음사가_부분_일치를_되살리지_않는다(self):
        # 음사 결과는 **정확 일치**만 본다. 부분 일치로 번지면 위험이 커진다.
        self.assertIsNone(self._resolve({"케이티앤지홀딩스": ("1", "111111")}, "KT&G"))


class TestViewerCorpSearch(unittest.TestCase):
    """뷰어 서버 폴백(`/api/corp`)도 같은 공백을 갖고 있었다.

    ⚠ CLAUDE.md: "core를 고쳐도 뷰어는 안 따라온다 — 사용자가 보는 건 뷰어다."
    `search_corp_candidates`는 `resolve_corp`를 쓰지 않는 별도 구현이라
    같은 경로를 따로 넣어야 한다.
    """

    def setUp(self):
        from tool_server.corp import search_corp_candidates
        self.search = search_corp_candidates

    def test_음사로_찾는다(self):
        cache = _cache({"케이티앤지": ("00244455", "033780")})
        got = self.search("KT&G", cache, {})
        self.assertTrue(got, "뷰어 폴백이 KT&G 를 못 찾는다")
        self.assertEqual(got[0]["name"], "케이티앤지")
        self.assertEqual(got[0]["alias_of"], "KT&G")

    def test_부분_일치가_음사보다_위에_온다(self):
        # core 와 같은 순서 — 두 화면이 다른 순서를 내면 그게 드리프트다.
        cache = _cache({"원익IPS": ("1", "240810"), "아이피에스": ("2", "051820")})
        names = [c["name"] for c in self.search("IPS", cache, {})]
        self.assertEqual(names[0], "원익IPS")
        self.assertIn("아이피에스", names)

    def test_정확_일치를_밀어내지_않는다(self):
        cache = _cache({"F&F": ("1", "383220"), "에프앤에프": ("2", "999999")})
        self.assertEqual(self.search("F&F", cache, {})[0]["name"], "F&F")

    def test_음사_결과가_없으면_더하지_않는다(self):
        cache = _cache({"삼립": ("1", "005610")})
        self.assertEqual(self.search("SPC삼립", cache, {}), [])


class TestNoRegressionOnKnownCases(unittest.TestCase):
    """③ 기존 문서화된 동작이 그대로인가."""

    def setUp(self):
        self.p1 = patch.object(dc, "load_corp_aliases", return_value={})
        self.p1.start()
        self.addCleanup(self.p1.stop)

    def test_빈_입력은_여전히_None(self):
        with patch.object(dc, "_corp_cache", _cache({"경": ("1", "")})):
            self.assertIsNone(dc.resolve_corp("", "k"))
            self.assertIsNone(dc.resolve_corp("   ", "k"))

    def test_한_글자_부분_일치는_여전히_안_한다(self):
        with patch.object(dc, "_corp_cache", _cache({"가주": ("1", "")})):
            self.assertIsNone(dc.resolve_corp("주", "k"))


if __name__ == "__main__":
    unittest.main()
