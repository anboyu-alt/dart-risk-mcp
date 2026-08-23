"""펀드 상품명이 회사 신호를 켜던 문제 — 문서 종류로 가른다.

집합투자증권 공시는 자산운용사가 내는 **상품 등록·판매 서류**다. 회사가
낸 사건 공시가 아닌데, 제목에 상품명이 통째로 들어가 회사 사건 키워드와
부딪힌다.

이 함정은 이 레포에서 이미 두 번 우연히 발견됐다(둘 다 코드 주석에 남아
있다): `"미달"` ← 「미(美)달러」 · `"지연"` ← 「글로벌클린에너지연금증권」.
세 번째를 기다리는 대신 문서 종류로 가른다.

1년 코퍼스 실측(2026-08-23) — 「집합투자증권」이 든 제목 중 신호가 붙는
것은 6종 6건이고 **전부 상품명 때문**이었다:

| 상품명 조각 | 켜던 신호 | 건수 |
|---|---|---|
| 자사주매입고배당주…투자신탁 | TREASURY | 3 |
| 글로벌4차산업전환사채증권…투자신탁 | CB_BW | 2 |
| 지속가능글로벌테마주증권투자신탁 | THEME_STOCK | 1 |

이 마커가 회사 사건을 삼키는 사례는 **0건**이다.
"""
import json
import pathlib

import pytest

from dart_risk_mcp.core.qualifiers import (
    FUND_PRODUCT_MARKS, _demotion_reason, parse_report_name)
from dart_risk_mcp.core.signals import match_signals

_CORPUS = json.loads(
    (pathlib.Path(__file__).parent / "fixtures" / "corpus"
     / "signal_titles_365d.json").read_text(encoding="utf-8"))


def _reason(nm):
    return _demotion_reason(parse_report_name(nm), {"flr_nm": "", "corp_name": ""})


class TestFundProductDemoted:
    OBSERVED_BEFORE = [
        "일괄신고서(집합투자증권-신탁형)(한화PLUS자사주매입고배당주증권상장지수투자신탁(주식))",
        "투자설명서(집합투자증권)(한화PLUS자사주매입고배당주증권상장지수투자신탁(주식))",
        "증권발행실적보고서(집합투자증권)(한화PLUS자사주매입고배당주증권상장지수투자신탁(주식))",
        "증권발행실적보고서(집합투자증권)(미래에셋글로벌4차산업전환사채증권자투자신탁H[채권])",
        "증권발행실적보고서(집합투자증권)(AB지속가능글로벌테마주증권투자신탁(주식-재간접형))",
    ]

    @pytest.mark.parametrize("nm", OBSERVED_BEFORE)
    def test_펀드_서류는_강등된다(self, nm):
        assert "집합투자증권(펀드) 서류" in (_reason(nm) or ""), nm

    @pytest.mark.parametrize("nm", OBSERVED_BEFORE)
    def test_신호_자체는_지우지_않는다(self, nm):
        """한정층은 신호를 없애지 않고 tier만 바꾼다 — 이 레포의 설계."""
        assert match_signals(nm), nm


class TestCompanyFilingsUntouched:
    KEEP = [
        "주요사항보고서(자기주식취득결정)",
        "주요사항보고서(자기주식처분결정)",
        "주요사항보고서(전환사채권발행결정)",
        "주요사항보고서(신주인수권부사채권발행결정)",
        "자기주식취득결과보고서",
    ]

    @pytest.mark.parametrize("nm", KEEP)
    def test_회사_공시는_이_규칙에_걸리지_않는다(self, nm):
        assert "집합투자증권" not in (_reason(nm) or ""), nm


class TestCorpusInvariant:
    def test_마커가_회사_사건을_삼키지_않는다(self):
        """코퍼스 전체에서, 이 규칙으로 강등되는 제목은 전부 펀드 서류다."""
        for t in _CORPUS["titles"]:
            nm = t["nm"]
            if not match_signals(nm):
                continue
            if "집합투자증권(펀드) 서류" not in (_reason(nm) or ""):
                continue
            assert any(m in nm for m in FUND_PRODUCT_MARKS), nm

    def test_관측된_마커만_넣는다(self):
        """넓히려면 근거가 필요하다 — 지금은 실측된 한 종뿐이다."""
        assert FUND_PRODUCT_MARKS == ("집합투자증권",)
