"""파서는 **라벨을 값으로 돌려주지 않는다**.

2026-08-23 사용자 제보로 드러난 모양이다(#234). 뷰어가 이렇게 표시했다.

    상대: 회사명(성명) (계열회사) — 1원

「회사명(성명)」은 값이 아니라 표의 하위 라벨이고, 1은 「7. 거래대금지급 |
**1**. 지급형태」의 열거번호였다. 값이 있어야 할 자리에 **라벨·번호가 들어와도
파서가 그걸 값으로 승격**시킨 것이다.

이 테스트는 개별 서식이 아니라 **성질**을 고정한다 — 값 칸이 비어 다음
라벨이 뒤따르는 문서를 주면, 파서는 그 라벨을 값으로 삼지 않고 빈 값을
돌려줘야 한다. 빈 값은 "확인하지 못했다"로 렌더되지만 라벨은 **거짓**이다.

라이브 검증(2026-08-23): 시장 표본 70건 × core 파서 5종에 같은 규칙을
돌려 냄새 0건. 채움률 outflow 44% · related 31%로, "빈 값이라서 냄새가
없는" 상태가 아니다.
"""
import re

import pytest

import dart_risk_mcp.core.dart_client as dc

# 값 자리에 나타나면 안 되는 것들 — DART 표의 라벨 어휘
LABELISH = re.compile(
    r"^(회사명|성명|법인명|거래상대방|대여상대|채무자|회사와의관계|차입처|"
    r"담보제공자|양수금액|양도금액|대여금액|담보금액|거래금액|차입금액|"
    r"출자금액|자본금|주요사업|본점소재지|지급형태|거래대금|이자율|"
    r"자기자본대비|단위)")

NAME_KEYS = ("counterparty", "issuer", "new_holder", "prev_holder", "lender",
             "relation", "relation_text")
NUM_KEYS = ("amount", "self_fund", "borrowed_fund", "book_value")


def _squash(v):
    return " ".join(str(v or "").split()).replace(" ", "") \
        .replace("(", "").replace(")", "")


def _check(name, d):
    """라벨·열거번호가 값으로 새지 않았는지 본다."""
    for k in NAME_KEYS:
        v = " ".join(str(d.get(k) or "").split())
        if not v or v == "-":
            continue
        assert not LABELISH.match(_squash(v)), f"{name}.{k}에 라벨이 들어왔다: {v!r}"
        assert len(v) <= 45, f"{name}.{k}가 문장을 삼켰다({len(v)}자): {v[:50]!r}"
    for k in NUM_KEYS:
        raw = str(d.get(k) or "").replace(",", "")
        if raw.isdigit():
            assert not (0 < int(raw) < 10000), (
                f"{name}.{k}가 열거번호처럼 작다: {raw}")


PARSERS = [
    ("parse_outflow_detail", dc.parse_outflow_detail),
    ("parse_asset_disposal_detail", dc.parse_asset_disposal_detail),
    ("parse_related_party_detail", dc.parse_related_party_detail),
    ("parse_control_change_detail", dc.parse_control_change_detail),
    ("parse_acquisition_detail", dc.parse_acquisition_detail),
]

# 값 칸이 비어 **다음 라벨이 뒤따르는** 문서들 — #234가 걸린 모양
VALUE_MISSING = [
    "1. 거래상대방 회사명(성명) 자본금(원) 300,000,000 회사와의 관계 계열회사",
    "1. 대여 상대 회사와의 관계 종속회사 대여금액(원) 5,000,000,000",
    "채무자 회사와의 관계 - 채무보증금액(원) 100,000,000,000",
    "특수관계인으로부터 자금차입 (단위 : 백만 원) 가. 차입처 "
    "회사와의 관계 계열회사 라. 차입금액 1,500",
    "6. 거래상대방 회사명(성명) 7. 거래대금지급 1. 지급형태: 현금",
    "성명(법인명) 회사와의 관계 임원 거래금액 4,900",
]

# 열거번호가 금액으로 새기 쉬운 모양
ENUM_ONLY = [
    "7. 거래대금지급 1. 지급형태: 현금2. 지급시기 및 조건: 계약금",
    "2. 양수내역 3. 양수목적 사업공간 확보",
    "거래대금 1. 현금 지급",
]


class TestNoLabelAsValue:
    @pytest.mark.parametrize("text", VALUE_MISSING,
                             ids=[t[:22] for t in VALUE_MISSING])
    @pytest.mark.parametrize("name,fn", PARSERS, ids=[p[0] for p in PARSERS])
    def test_값이_없으면_라벨을_올리지_않는다(self, name, fn, text):
        _check(name, fn(text) or {})

    @pytest.mark.parametrize("text", ENUM_ONLY, ids=[t[:22] for t in ENUM_ONLY])
    @pytest.mark.parametrize("name,fn", PARSERS, ids=[p[0] for p in PARSERS])
    def test_열거번호를_금액으로_올리지_않는다(self, name, fn, text):
        _check(name, fn(text) or {})

    @pytest.mark.parametrize("name,fn", PARSERS, ids=[p[0] for p in PARSERS])
    def test_빈_입력에서_죽지_않는다(self, name, fn):
        for text in ("", "   ", "|", "| |\n|---|"):
            _check(name, fn(text) or {})


class TestRealValuesStillParse:
    """냄새 규칙이 **진짜 값까지** 막지 않는지 — 반대 방향 확인."""

    def test_금전대여(self):
        # 실제 서식 — 관계 앞에 "-"가 붙는다(tests/test_outflow_fairtrade_format.py
        # 와 같은 픽스처). 그 표기를 빼면 관계가 안 읽힌다.
        d = dc.parse_outflow_detail(
            "금전대여 결정 1. 대여 상대 (주)한국파일 -회사와의 관계 종속회사 "
            "2. 금전대여 내역 대여금액 (원) 5,000,000,000")
        assert d["counterparty"] == "(주)한국파일"
        assert d["relation"] == "종속회사"
        assert d["amount"] == 5000000000
        _check("parse_outflow_detail", d)

    def test_특수관계인_차입(self):
        d = dc.parse_related_party_detail(
            "특수관계인으로부터 자금차입 (단위 : 백만 원) 1. 차입처 "
            "(주)엘엑스인터내셔널 회사와의 관계 계열회사 라. 차입금액 120,000 "
            "마. 이자율 (%) 4.6")
        assert d["counterparty"] == "(주)엘엑스인터내셔널"
        assert d["relation"] == "계열회사"
        assert d["amount"] == 120000 * 1_000_000
        _check("parse_related_party_detail", d)
