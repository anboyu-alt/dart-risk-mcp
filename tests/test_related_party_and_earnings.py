"""3차 정리 — RELATED_PARTY 부활 + EARNINGS_SHOCK 신설 (2026-08-22).

C 부류 3종 중 **매핑이 맞는 것은 RELATED_PARTY 하나**였다:
  · 4.2 "가격 괴리가 큰 특수관계자 거래" → 원문의 **이자율**로 확인 가능 ✅
  · 6.1 "수익 **인식 정책** 변경"       → 「손익구조 변동」은 결산 결과라 다름 ❌
  · 6.2 "우발채무 **누락**"             → 「소송등의판결」은 공시된 건이라 판정 불가 ❌

「손익구조 30% 이상 변동」은 6.1에 끼워 넣지 않고 **새 신호**로 만들어 8.5에
매핑했다(적자전환 = 부실 단계 진입 사실).
"""
import pytest

from dart_risk_mcp.core.dart_client import (
    classify_outflow_relation,
    parse_earnings_shock_detail,
    parse_related_party_detail,
)
from dart_risk_mcp.core.explain import SIGNAL_PROSE
from dart_risk_mcp.core.signals import (
    AMBIGUOUS_SIGNAL_KEYS,
    NON_TITLE_SIGNALS,
    SIGNAL_KEY_TO_TAXONOMY,
    SIGNAL_TYPES,
    match_signals,
)
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS, TAXONOMY

_BY_KEY = {s["key"]: s for s in SIGNAL_TYPES}


class TestRelatedPartyRevived:
    @pytest.mark.parametrize("title", [
        "특수관계인으로부터자금차입",
        "특수관계인으로부터받은담보",
        "특수관계인에대한출자",
    ])
    def test_자금이_들어오는_방향을_잡는다(self, title):
        assert "RELATED_PARTY" in [s["key"] for s in match_signals(title)], title

    @pytest.mark.parametrize("title,other", [
        ("특수관계인에대한자금대여", "FUND_OUTFLOW"),
        ("특수관계인에대한담보제공", "FUND_OUTFLOW"),
        ("특수관계인에대한자산양도", "ASSET_TRANSFER"),
        ("특수관계인의유상증자참여", "3PCA"),
    ])
    def test_나가는_방향은_기존_신호가_잡는다(self, title, other):
        """대칭 — 중복으로 두 번 잡히면 같은 사건이 두 줄로 나온다."""
        keys = [s["key"] for s in match_signals(title)]
        assert other in keys, title
        assert "RELATED_PARTY" not in keys, title

    def test_대규모내부거래는_넣지_않았다(self):
        """「동일인등출자계열회사와의 상품ㆍ용역거래」 2,330건/579개사는
        대기업집단의 일상 영업이라 신호 대 잡음비를 무너뜨린다."""
        for t in ("동일인등출자계열회사와의상품ㆍ용역거래",
                  "동일인등출자계열회사와의상품ㆍ용역거래변경"):
            assert match_signals(t) == [], t

    def test_사장_목록에서_빠졌다(self):
        assert "RELATED_PARTY" not in NON_TITLE_SIGNALS
        assert _BY_KEY["RELATED_PARTY"]["keywords"]

    def test_참고_강도이며_헤드라인이_아니다(self):
        assert _BY_KEY["RELATED_PARTY"]["score"] == 1
        assert "RELATED_PARTY" in AMBIGUOUS_SIGNAL_KEYS


class TestRelatedPartyParser:
    BORROW = ("특수관계인으로부터 자금차입 (단위 : 백만 원) 1. 차입유형 단기차입금 "
              "2. 차입 내역 나. 차입처 라인플러스(주) 회사와의 관계 계열회사 "
              "다. 차입기간 2026 라. 차입금액 1,500 - 자기자본대비 (%) 자본잠식 "
              "마. 이자율(%) 연 4.6% 바. 상환방법 만기일시상환")
    COLLATERAL = ("특수관계인으로부터 받은 담보 (단위 : 백만 원) 1. 담보제공자 동화기업(주) "
                  "회사와의 관계 계열회사 2. 담보 내역 바. 담보금액 30,000")
    INVEST = ("특수관계인에 대한 출자 (단위 : 백만 원) 1. 거래상대방 케이강남123PFV(가칭) "
              "회사와의 관계 계열회사(예정) 2. 출자내역 다. 출자금액 52,000")

    def test_차입은_이자율까지_읽는다(self):
        """4.2가 요구하는 '가격 괴리'를 확인할 수 있는 유일한 필드다."""
        d = parse_related_party_detail(self.BORROW)
        assert d["kind"] == "borrow"
        assert d["counterparty"] == "라인플러스(주)"
        assert d["relation"] == "계열회사"
        assert d["interest_rate"] == pytest.approx(4.6)
        assert d["equity_ratio"] == "자본잠식"

    def test_단위가_백만원이다(self):
        """공정거래법 대규모내부거래 공시는 「(단위 : 백만 원)」을 머리에 단다."""
        assert parse_related_party_detail(self.BORROW)["amount"] == 1_500_000_000
        assert parse_related_party_detail(self.COLLATERAL)["amount"] == 30_000_000_000
        assert parse_related_party_detail(self.INVEST)["amount"] == 52_000_000_000

    def test_세_서식의_상대방_필드명이_다르다(self):
        assert parse_related_party_detail(self.COLLATERAL)["counterparty"] == "동화기업(주)"
        assert parse_related_party_detail(self.INVEST)["counterparty"] == "케이강남123PFV(가칭)"

    def test_관계가_뒤_문장을_삼키지_않는다(self):
        """게으른 매칭에 종료 앵커를 좁게 주지 않으면 '계열회사 다. 차입기간 …'
        까지 통째로 잡힌다(실측으로 발견)."""
        assert parse_related_party_detail(self.BORROW)["relation"] == "계열회사"
        assert classify_outflow_relation(
            parse_related_party_detail(self.INVEST)["relation"]
        ) == "affiliated"

    def test_무관한_원문은_빈_값(self):
        assert parse_related_party_detail("")["kind"] == ""
        assert parse_related_party_detail("기업설명회(IR) 개최")["kind"] == ""


class TestEarningsShock:
    TABLE = ("매출액 또는 손익구조 30%(대규모법인 15%)이상 변경 "
             "3. 매출액 또는 손익구조 변동내용(단위:천원) "
             "- 매출액 8,054,627,138 10,503,609,086 -2,448,981,948 -23.3 - "
             "- 영업이익 -815,431,280 403,125,614 -1,218,556,894 - 적자전환 "
             "- 당기순이익 -916,079,534 242,849,735 -1,158,929,269 - 적자전환")

    def test_제목을_잡는다(self):
        for t in ("매출액또는손익구조30%(대규모법인은15%)이상변동",
                  "매출액또는손익구조30%(대규모법인은15%)이상변경(자회사의주요경영사항)"):
            assert "EARNINGS_SHOCK" in [s["key"] for s in match_signals(t)], t

    def test_6_1이_아니라_8_5에_매핑한다(self):
        """6.1은 '수익 **인식 정책** 변경'이고 이 공시는 결산 결과 통보다.
        6.1의 위험신호(매출채권/매출 급등)는 이미 AR_SURGE가 재무제표로 본다."""
        assert SIGNAL_KEY_TO_TAXONOMY["EARNINGS_SHOCK"] == ["8.5"]
        assert TAXONOMY["8.5"]["base_score"] == 0
        assert _BY_KEY["EARNINGS_SHOCK"]["score"] == 0

    def test_패턴_발화를_바꾸지_않는다(self):
        used = {t for p in CROSS_SIGNAL_PATTERNS.values() for t in p["signal_sequence"]}
        assert "8.5" not in used

    def test_계정별_증감비율과_적자전환을_읽는다(self):
        d = parse_earnings_shock_detail(self.TABLE)
        assert d["turned_to_loss"] is True
        by = {r["account"]: r for r in d["rows"]}
        assert by["매출액"]["change_pct"] == pytest.approx(-23.3)
        assert by["영업이익"]["turn"] == "적자전환"
        assert by["당기순이익"]["current"] == -916_079_534

    def test_흑자전환도_구분한다(self):
        t = ("손익구조 변동내용(단위:천원) - 영업이익 100,000 -50,000 150,000 - 흑자전환")
        d = parse_earnings_shock_detail(t)
        assert d["turned_to_loss"] is False
        assert d["rows"][0]["turn"] == "흑자전환"

    def test_헤드라인으로_올라가지_않는다(self):
        """증가인지 감소인지 제목만으로는 알 수 없다."""
        assert "EARNINGS_SHOCK" in AMBIGUOUS_SIGNAL_KEYS

    def test_산문이_있다(self):
        assert "손익" in SIGNAL_PROSE["EARNINGS_SHOCK"]
        assert "특수관계인" in SIGNAL_PROSE["RELATED_PARTY"]


def test_related_party_amount_unit_eok():
    """「(단위 : 억원)」 서식 — 백만원만 처리하면 1억분의 1로 오표기된다.

    2026-08-22 실측: 삼성전자 20260730000505 출자금액 2,970 = 2,970억원.
    같은 날 포승그린파워 20260812000839는 「(단위 : 백만 원)」 차입금액
    120,000 = 1,200억원이라 두 서식이 시장에 공존한다.
    """
    eok = ("특수관계인에 대한 출자 (단위 : 억원) 1. 거래상대방 SVIC 83호 "
           "회사와의 관계 출자조합 2. 출자내역 다. 출자금액 2,970 라. 출자상대방 총출자액 3,000")
    assert parse_related_party_detail(eok)["amount"] == 297_000_000_000

    mil = ("특수관계인으로부터 자금차입 (단위 : 백만 원) 1. 차입처 (주)엘엑스인터내셔널 "
           "회사와의 관계 계열회사 라. 차입금액 120,000 - 직전사업연도말 자기자본 63,925")
    assert parse_related_party_detail(mil)["amount"] == 120_000_000_000

    bare = ("특수관계인에 대한 출자 1. 거래상대방 가나 회사와의 관계 계열회사 "
            "다. 출자금액 13,000,000,000")
    assert parse_related_party_detail(bare)["amount"] == 13_000_000_000
