"""제목에 정정 표시가 없는데 원문이 정정신고인 공시 방어 (2026-08-22).

실사고: 포커스에이아이 20260821900279 — 제목 「유형자산처분결정(자율공시)」은
`is_amendment_disclosure`를 통과하는데 원문이 정정신고서다. 정정 원문은
「정정전 정정후」 값이 나란히 오고 정정사유가 서술문이라, 표 서식을 전제한
정규식이 문장을 통째로 삼켰다(상대방 자리에 "…양도 예정함 4. 정정사항
정정항목 정정전 정정후 2.처분내역-처분금액(원) 2,697,773,850").
"""

from dart_risk_mcp.core.dart_client import (
    _is_amended_document,
    parse_asset_disposal_detail,
    parse_earnings_shock_detail,
    parse_related_party_detail,
)
from dart_risk_mcp.core.signals import is_amendment_disclosure

# 실측 원문(20260821900279)의 머리 부분 축약
AMENDED_DISPOSAL = (
    "포커스에이아이/유형자산처분결정(자율공시)/(2026.08.21)유형자산처분결정(자율공시) "
    "정정신고(보고) 정정일자 2026-08-21 1. 정정관련 공시서류 [정정]유형자산 처분결정"
    "(자율공시) 3. 정정사유 해당부지에 대한 소유권을 매수자(거래상대방)에게 양도 예정함 "
    "4. 정정사항 정정항목 정정전 정정후 2.처분내역-처분금액(원) 2,697,773,850 3,064,686,070 "
    "2.처분내역-자산총액대비(%) 5.8 6.6 3.거래상대방 대구광역시 수성구청 (주)스마트크리에이터 "
    "4.처분목적 토지 매매"
)


def test_title_alone_does_not_catch_this():
    """제목만 보는 기존 필터로는 못 거른다 — 그래서 원문 가드가 필요하다."""
    assert is_amendment_disclosure("유형자산처분결정(자율공시)") is False


def test_is_amended_document_detects_body():
    assert _is_amended_document(AMENDED_DISPOSAL) is True
    assert _is_amended_document("") is False
    assert _is_amended_document(
        "유형자산 처분결정 1. 처분내역 거래상대방 한미반도체 주식회사"
    ) is False


def test_is_amended_document_only_reads_head():
    """본문 뒤쪽에 '정정일자'가 스쳐도 정상 공시를 버리지 않는다."""
    body = "유형자산 처분결정 거래상대방 가나 회사와의 관계 계열회사 " + "x" * 900
    assert _is_amended_document(body + " 정정일자 2026-01-01") is False


def test_disposal_parser_returns_empty_on_amended():
    out = parse_asset_disposal_detail(AMENDED_DISPOSAL)
    assert out["counterparty"] == ""
    assert out["amount"] == 0
    # 정정전 값(2,697,773,850)을 현재값으로 오인하지 않는다
    assert out["amount"] != 2697773850


def test_related_party_parser_returns_empty_on_amended():
    amended = (
        "특수관계인으로부터 자금차입 정정신고(보고) 정정일자 2026-08-21 "
        "1. 차입처 (주)가나 회사와의 관계 계열회사 라. 차입금액 120,000"
    )
    assert parse_related_party_detail(amended)["counterparty"] == ""


def test_earnings_shock_parser_returns_empty_on_amended():
    amended = (
        "매출액또는손익구조30%이상변동 정정신고(보고) 정정일자 2026-08-21 손익구조 "
        "- 매출액 100 200 -100 -50.0 - "
    )
    assert parse_earnings_shock_detail(amended)["rows"] == []


def test_normal_documents_still_parse():
    """가드가 정상 공시를 막지 않는다(회귀 방지)."""
    d = parse_related_party_detail(
        "특수관계인으로부터 자금차입 (단위 : 백만 원) 1. 차입처 (주)엘엑스인터내셔널 "
        "회사와의 관계 계열회사 라. 차입금액 120,000 마. 이자율 (%) 4.6"
    )
    assert d["counterparty"] == "(주)엘엑스인터내셔널"
    assert d["amount"] == 120_000_000_000

    a = parse_asset_disposal_detail(
        "유형자산 처분결정 거래상대방 한미반도체 주식회사 회사와의 관계 - "
        "2. 처분내역 처분금액 (원) 56,000,000,000 자산총액 대비 (%) 19.72"
    )
    assert a["counterparty"] == "한미반도체 주식회사"
    assert a["amount"] == 56_000_000_000
