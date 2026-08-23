"""공정거래법 제26조 서식의 자금유출 상대방 추출 (2026-08-23).

`parse_outflow_detail`은 주요사항보고서 서식만 알고 있었다. 공정위
대규모내부거래 공시(「특수관계인에대한자금대여」·「특수관계인에대한담보제공」)는
서식이 달라 **상대방 추출 0%**였다.

라이브 실측(2026-08-01~14):

| 제목 계열 | 수정 전 | 수정 후 |
|---|---|---|
| 특수관계인에대한자금대여 | 0/6 | **6/6** |
| 특수관계인에대한담보제공 | 0/6 | **6/6** |
| 타인에대한채무보증결정(대조군) | 6/6 | 6/6 |
| 금전대여결정(대조군) | 6/6 | 6/6 |

1년 기준 705 + 215 = **920건 이상**이 영향받는다. 이 필드는 표시용이
아니라 `capital_backflow` 게이트의 **판정 입력**이라, 계열회사 자금대여인데
`unknown`으로 떨어져 패턴이 발화하지 못했다 — 신호 이름이
"특수관계인에대한…"인데 특수관계 판정을 못 하고 있었다.
"""
import pytest

from dart_risk_mcp.core.dart_client import (
    classify_outflow_relation, parse_outflow_detail,
)

# 실측 원문(제이에이치코믹스 20260804, 한화 20260804)의 특징 구간
FT_LOAN = (
    "특수관계인에대한자금대여 6.0 (주)제이에이치코믹스 특수관계인에 대한 자금대여 "
    "기업집단명 네이버 회사명 (주)제이에이치코믹스 공시일자 2026.08.04 "
    "관련법규 공정거래법 제26조 (단위 : 백만 원) "
    "1. 거래상대방 손제호 회사와의 관계 임원 "
    "2. 대여금 내역 가. 거래일자 2026.08.03 나. 거래금액 4,900 "
    "다. 거래상대방 총잔액 4,900 라. 이자율(%) 4.6 "
    "3. 거래의 목적 사업수행관련 자금대여"
)
FT_COLLATERAL = (
    "특수관계인에대한담보제공 6.0 (주)한화 특수관계인에 대한 담보제공 "
    "기업집단명 한화 회사명 (주)한화 공시일자 2026.08.04. "
    "관련법규 공정거래법 제26조 (단위 : 백만 원) "
    "1. 거래상대방 아산배방개발(주) 회사와의 관계 계열회사 "
    "2. 담보제공 내역 가. 담보제공일자 PF 대출약정 체결일 "
    "나. 채권자 어센트배방제일차(주) 등 대주단 마. 담보한도 366,960 "
    "바. 담보금액 305,800"
)
# 대조군 — 주요사항보고서 서식(기존 경로)
MSR_GUARANTEE = (
    "타인에 대한 채무보증 결정 1. 채무자 금정산 하늘채 분양계약자 "
    "- 회사와의 관계 - 2. 채권자 흥국저축은행 외 4개사 "
    "3. 채무(차입)금액(원) 100,000,000,000 4. 채무보증내역 "
    "채무보증금액(원) 100,000,000,000"
)
MSR_LOAN = (
    "금전대여 결정 1. 대여 상대 (주)한국파일 -회사와의 관계 종속회사 "
    "2. 금전대여 내역 대여금액 (원) 5,000,000,000"
)


class TestFairTradeFormat:
    def test_자금대여_상대방과_관계를_읽는다(self):
        d = parse_outflow_detail(FT_LOAN)
        assert d["counterparty"] == "손제호"
        assert d["relation"] == "임원"
        assert d["kind"] == "loan"

    def test_담보제공_상대방과_관계를_읽는다(self):
        d = parse_outflow_detail(FT_COLLATERAL)
        assert d["counterparty"] == "아산배방개발(주)"
        assert d["relation"] == "계열회사"
        assert d["kind"] == "collateral"

    def test_금액을_백만원_단위로_환산한다(self):
        """이 서식은 「(단위 : 백만 원)」을 머리에 단다."""
        assert parse_outflow_detail(FT_LOAN)["amount"] == 4_900_000_000
        assert parse_outflow_detail(FT_COLLATERAL)["amount"] == 305_800_000_000

    @pytest.mark.parametrize("text,want", [
        (FT_LOAN, "affiliated"),          # 임원
        (FT_COLLATERAL, "affiliated"),    # 계열회사
    ])
    def test_게이트가_쓰는_관계_판정이_선다(self, text, want):
        """표시용이 아니라 capital_backflow 게이트의 판정 입력이다."""
        assert classify_outflow_relation(parse_outflow_detail(text)["relation"]) == want


class TestExistingFormatsUnchanged:
    """공정위 분기를 앞에 넣었으므로 기존 경로가 밀리지 않는지."""

    def test_채무보증_서식이_그대로다(self):
        d = parse_outflow_detail(MSR_GUARANTEE)
        assert d["kind"] == "guarantee"
        assert "분양계약자" in d["counterparty"]
        assert d["amount"] == 100_000_000_000

    def test_금전대여_서식이_그대로다(self):
        d = parse_outflow_detail(MSR_LOAN)
        assert d["kind"] == "loan"
        assert d["counterparty"] == "(주)한국파일"
        assert d["relation"] == "종속회사"
        assert d["amount"] == 5_000_000_000

    def test_해당없는_원문은_빈_결과다(self):
        assert parse_outflow_detail("주주총회소집공고")["kind"] == ""
        assert parse_outflow_detail("")["counterparty"] == ""

    def test_주식담보제공계약은_흡수하지_않는다(self):
        """STAKE_PLEDGE는 별개 신호다 — 「담보설정금액」 필드명이 겹친다."""
        pledge = ("최대주주변경을수반하는주식담보제공계약체결 "
                  "1. 담보제공자(최대주주) 관련 사항 담보설정금액 1,000,000,000")
        assert parse_outflow_detail(pledge)["kind"] == ""
