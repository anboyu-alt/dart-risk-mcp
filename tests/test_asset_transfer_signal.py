"""ASSET_TRANSFER(자산 처분·양도) 부활 회귀 테스트 (2026-08-22, 2차 정리).

옛 키워드 5종("자산매각"·"사옥매각"·"자회사매각"·"사업양도"·"저가매각")은
1년 코퍼스(고유 공시 201,361건)에서 **전부 0건**이었다 — 개념어를 적어 둔
것이고 DART 제목 표기가 아니었다. 실제 표기로 교체하고, taxonomy 5.3
("특수관계인에게 공정가 미만으로 이전")을 원문으로 확인하는 계층을 붙였다.
"""
import pytest

from dart_risk_mcp.core.dart_client import (
    classify_outflow_relation,
    parse_asset_disposal_detail,
)
from dart_risk_mcp.core.signals import (
    AMBIGUOUS_SIGNAL_KEYS,
    SIGNAL_KEY_TO_TAXONOMY,
    SIGNAL_TYPES,
    match_signals,
)
from dart_risk_mcp.server import _is_asset_disposal_title

_SIG = next(s for s in SIGNAL_TYPES if s["key"] == "ASSET_TRANSFER")

DISPOSAL_TITLES = [
    "유형자산처분결정",
    "유형자산처분결정(종속회사의주요경영사항)",
    "비유동자산처분결정",
    "주요사항보고서(유형자산양도결정)",
    "특수관계인에대한자산양도",
    "영업양도결정(종속회사의주요경영사항)",
]


class TestMatching:
    @pytest.mark.parametrize("title", DISPOSAL_TITLES)
    def test_실제_표기를_잡는다(self, title):
        assert "ASSET_TRANSFER" in [s["key"] for s in match_signals(title)], title

    def test_자산유동화_등록신청서는_잡지_않는다(self):
        """「자산양도등의등록신청서」는 663건/년으로 이 계열에서 가장 흔하지만
        자산유동화에 관한 법률상 **유동화자산 양도 등록**이지, 자산이 특정인에게
        넘어가는 사건이 아니다. "자산양도" 단독 키워드를 쓰면 전부 걸린다."""
        for t in ("자산양도등의등록신청서", "[첨부정정]자산양도등의등록신청서"):
            assert "ASSET_TRANSFER" not in [s["key"] for s in match_signals(t)], t

    def test_영업양수는_반대_방향이라_잡지_않는다(self):
        keys = [s["key"] for s in match_signals("주요사항보고서(영업양수결정)")]
        assert "ASSET_TRANSFER" not in keys
        assert "ACQ_REVIEW" in keys

    def test_옛_개념어는_돌아오지_않는다(self):
        for kw in ("자산매각", "사옥매각", "자회사매각", "사업양도", "저가매각"):
            assert kw not in _SIG["keywords"], kw


class TestScoring:
    def test_참고_강도이며_헤드라인으로_올라가지_않는다(self):
        """정상적인 자산 교체·유동성 확보가 대다수라 이 신호 하나로는
        판단 근거가 되지 않는다 — FUND_OUTFLOW·ACQ_REVIEW와 같은 취급."""
        assert _SIG["score"] == 1
        assert "ASSET_TRANSFER" in AMBIGUOUS_SIGNAL_KEYS

    def test_taxonomy는_5_3_하나다(self):
        assert SIGNAL_KEY_TO_TAXONOMY["ASSET_TRANSFER"] == ["5.3"]


class TestDisposalParser:
    """다섯 서식 전부 대응 — 필드명이 서로 다르다(실측)."""

    TANGIBLE = ("유형자산 처분결정 1. 처분물건 구분 토지 및 건물 2. 처분내역 "
                "처분금액(원) 20,000,000,000 자산총액(원) 133,243,438,025 "
                "자산총액대비(%) 15.01 3. 거래상대 고기봉, 이민숙 4. 처분목적 자산 매각")
    NONCURRENT = ("비유동자산 처분결정 1. 처분 목적물 비유동자산 장기대여금 "
                  "3. 처분가액 (원) 10,000,000,000 4. 처분대상 비유동자산 평가가액 (원) "
                  "10,000,000,000 5. 거래상대방 현대사모부동산투자신탁15호 - "
                  "회사와의 관계 기타 6. 처분목적 자금운용")
    TRANSFER = ("유형자산 양도 결정 2. 양도내역 양도금액(원) 7,600,000,000 "
                "자산총액(원) 66,061,636,175 자산총액대비(%) 11.50 "
                "6. 거래상대방 회사명(성명) 비티엠써비스주식회사 자본금(원) 1,500,000,000 "
                "주요사업 건물종합관리업 회사와의 관계 - 8. 외부평가에 관한 사항 외부평가 여부 예")
    RELATED = ("특수관계인에 대한 자산양도 기업집단명 장금상선 (단위 : 백만 원) "
               "1. 거래상대방 시노코페트로케미컬(주) 회사와의 관계 계열회사 "
               "2. 자산양도 내역 가. 양도일자 2026.05.06 다. 양도가액 12,899 3. 양도목적 경영상 목적")
    BUSINESS = ("영업양도 결정 3. 양도가액(원) 15,369,541,168,764 4. 양도목적 사업구조 재편 "
                "6. 양수법인 Solidigm Inc. - 회사와의 관계 계열회사")

    def test_유형자산_처분결정_관계필드가_없다(self):
        """이 서식에는 '회사와의 관계'가 아예 없다 — 상대가 개인인 경우도 있다."""
        d = parse_asset_disposal_detail(self.TANGIBLE)
        assert d["counterparty"] == "고기봉, 이민숙"
        assert d["relation"] == ""
        assert d["amount"] == 20_000_000_000
        assert d["asset_ratio"] == pytest.approx(15.01)

    def test_비유동자산_처분결정은_평가가액도_읽는다(self):
        d = parse_asset_disposal_detail(self.NONCURRENT)
        assert d["counterparty"] == "현대사모부동산투자신탁15호", "꼬리 하이픈 제거"
        assert d["relation"] == "기타"
        assert d["book_value"] == 10_000_000_000

    def test_유형자산_양도결정은_외부평가를_읽는다(self):
        d = parse_asset_disposal_detail(self.TRANSFER)
        assert d["counterparty"] == "비티엠써비스주식회사"
        assert d["extval"] == "예"

    def test_특수관계인_자산양도는_백만원_단위다(self):
        """「(단위 : 백만 원)」을 달고 「양도가액 12,899」처럼 단위 없이 적는다."""
        d = parse_asset_disposal_detail(self.RELATED)
        assert d["amount"] == 12_899_000_000
        assert classify_outflow_relation(d["relation"]) == "affiliated"

    def test_영업양도는_양수법인을_상대방으로_읽는다(self):
        d = parse_asset_disposal_detail(self.BUSINESS)
        assert d["counterparty"] == "Solidigm Inc."
        assert d["relation"] == "계열회사"

    def test_무관한_원문은_빈_값(self):
        assert parse_asset_disposal_detail("")["counterparty"] == ""
        assert parse_asset_disposal_detail("기업설명회(IR) 개최")["counterparty"] == ""


class TestWiring:
    @pytest.mark.parametrize("title,expected", [
        ("유형자산처분결정", True),
        ("특수관계인에대한자산양도", True),
        ("영업양도결정", True),
        ("자산양도등의등록신청서", False),
        ("주요사항보고서(영업양수결정)", False),
    ])
    def test_원문_파서로_넘길_제목을_가른다(self, title, expected):
        assert _is_asset_disposal_title(title) is expected

    def test_확인_대상_신호에_포함된다(self):
        import inspect

        from dart_risk_mcp import server

        src = inspect.getsource(server._outflow_review_candidates)
        assert "ASSET_TRANSFER" in src
