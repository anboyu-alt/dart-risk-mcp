"""최대주주변경 원문 상세 추출 — 후속 과제 1위 (control_change_detail).

금감원 무자본 M&A 합동점검(2019-12-19): 적발 24사의 신규 최대주주 82%가
비외감법인·투자조합, 인수자금 대부분이 주식담보대출(단계①). 지금까지
"최대주주변경" 제목만으로 SHAREHOLDER 신호를 켰던 것에서, 원문의 신규
최대주주 실체·자금조달 방법을 사실로 추출하도록 격상한다.

이 테스트는:
  1) parse_control_change_detail — 원문(fetch_document_text 출력 형태: 태그
     제거·공백 단일화)에서 변경전/후 최대주주·비율·변경사유·지분인수목적·
     자금조달을 추출하는 순수 파서. fixture 4종은 전부 라이브 확인된 실측
     서식이다: 아틀라스링크 20260709900615, 졸스 20260728900445,
     제이케이시냅스 20260728900521, 선광 20260727900769.
  2) classify_holder_type — 명칭 표기 기준 사실 라벨 5분류.
  3) strip_holder_suffix — "외 N인/명"(단위 유무·공백 유무) 접미 제거.
"""
import unittest

from dart_risk_mcp.core.dart_client import (
    parse_control_change_detail,
    classify_holder_type,
    strip_holder_suffix,
)


# ── fixture: 실측 원문 서식 (fetch_document_text 출력 형태, 라이브 확인) ──────

# 아틀라스링크 20260709900615 — "외 1인"(공백 있음), 자기자금만(차입금 0).
_ATLASLINK_TEXT = (
    "아틀라스링크/최대주주변경/(2026.07.09)최대주주변경 최대주주 변경 "
    "1. 변경내용 변경전 최대주주등 신정관 외 1인 소유주식수(주) 7,075,504 "
    "소유비율(%) 20.44 변경후 최대주주등 미래산업 주식회사 외 4인 "
    "소유주식수(주) 13,558,808 소유비율(%) 39.16 2. 변경사유 최대주주 변경을 "
    "수반하는 주식양수도 거래 완료 -실권주 인수로 인한 변경 여부 아니오 "
    "-양수도 주식의 의무보유 여부 아니오 3. 지분인수목적 경영권 이전 "
    "-인수자금 조달방법 자기자금(원) 11,191,984,000 차입금(원) - 차입처 - "
    "차입기간 - ~ - 담보내역 - -인수후 임원 선ㆍ해임 계획 2026년 6월 12일 "
    "임시주주총회에서 선임함 4. 변경일자 2026-07-09"
)

# 졸스 20260728900445 — "외N명"(공백 없이 붙는 변형), (주) 접두.
_JOLS_TEXT = (
    "졸스/최대주주변경/(2026.07.28)최대주주변경 최대주주 변경 "
    "1. 변경내용 변경전 최대주주등 (주)바른손이앤에이 외 2명 소유주식수(주) "
    "4,081,494 소유비율(%) 34.86 변경후 최대주주등 (주)지피클럽외 1명 "
    "소유주식수(주) 5,469,007 소유비율(%) 32.70 2. 변경사유 제3자배정 "
    "유상증자 납입을 통한 최대주주 변경 -실권주 인수로 인한 변경 여부 아니오 "
    "-양수도 주식의 의무보유 여부 아니오 3. 지분인수목적 경영참여, 기업가치 "
    "제고 및 경영정상화 -인수자금 조달방법 자기자금(원) 8,000,000,030 "
    "차입금(원) - 차입처 - 차입기간 - ~ - 담보내역 - -인수후 임원 선ㆍ해임 "
    "계획 임시주주총회를 통해 선임 예정 4. 변경일자 2026-07-28"
)

# 제이케이시냅스 20260728900521 — "외 N" 접미 없음, (주) 접미(휴림로봇(주)).
_JKSYNAPS_TEXT = (
    "제이케이시냅스/최대주주변경/(2026.07.28)최대주주변경 최대주주 변경 "
    "1. 변경내용 변경전 최대주주등 (주)엠에이치테크 소유주식수(주) 1,530,054 "
    "소유비율(%) 13.59 변경후 최대주주등 휴림로봇(주) 소유주식수(주) "
    "3,099,173 소유비율(%) 21.58 2. 변경사유 제3자배정 유상증자로 인한 "
    "최대주주 변경 -실권주 인수로 인한 변경 여부 아니오 -양수도 주식의 "
    "의무보유 여부 예 3. 지분인수목적 경영권 참여 -인수자금 조달방법 "
    "자기자금(원) 2,999,999,464 차입금(원) - 차입처 - 차입기간 - ~ - "
    "담보내역 - -인수후 임원 선ㆍ해임 계획 임시주주총회를 통해 선임 예정 "
    "4. 변경일자 2026-07-28"
)

# 선광 20260727900769 — 개인명(단위 생략 "외 22"), 변경전이 개인·변경후가 법인.
_SUNKWANG_TEXT = (
    "선광/최대주주변경/(2026.07.27)최대주주변경 최대주주 변경 "
    "1. 변경내용 변경전 최대주주등 심충식 외 22 소유주식수(주) 3,860,628 "
    "소유비율(%) 58.49 변경후 최대주주등 (주)화인파트너스 외 20 "
    "소유주식수(주) 3,859,648 소유비율(%) 58.48 2. 변경사유 최대주주 변경을 "
    "수반하는 주식양수도 계약의 거래 종결에 따른 최대주주 변경 -실권주 인수로 "
    "인한 변경 여부 아니오 -양수도 주식의 의무보유 여부 아니오 3. "
    "지분인수목적 지분 추가 취득을 통한 지배구조 안정화 -인수자금 조달방법 "
    "자기자금(원) 6,530,823,750 차입금(원) - 차입처 - 차입기간 - ~ - "
    "담보내역 - -인수후 임원 선ㆍ해임 계획 - 4. 변경일자 2026-07-27"
)

# 실제 라이브 확인은 안 됐으나(6사 매트릭스 중 차입금>0 사례 미발견), DART
# 서식 문서상 명시된 필드(차입처·차입기간·담보내역)를 채운 합성 fixture —
# borrowed_fund>0 경로(차입처·담보내역 렌더, "조합" 명칭 분류)를 고정한다.
_LEVERAGED_TEXT = (
    "1. 변경내용 변경전 최대주주등 홍길동 소유주식수(주) 100,000 "
    "소유비율(%) 10.00 변경후 최대주주등 (주)가나다투자조합 외 2인 "
    "소유주식수(주) 500,000 소유비율(%) 25.00 2. 변경사유 최대주주 변경을 "
    "수반하는 주식양수도 거래 완료 -실권주 인수로 인한 변경 여부 아니오 "
    "-양수도 주식의 의무보유 여부 아니오 3. 지분인수목적 경영권 이전 "
    "-인수자금 조달방법 자기자금(원) 1,000,000,000 차입금(원) 4,000,000,000 "
    "차입처 주식회사 대한저축은행 차입기간 2026-01-01 ~ 2027-01-01 담보내역 "
    "발행주식 500,000주 근질권 설정 -인수후 임원 선ㆍ해임 계획 - "
    "4. 변경일자 2026-01-15"
)


class TestParseControlChangeDetail(unittest.TestCase):
    def test_atlaslink_fixture(self):
        r = parse_control_change_detail(_ATLASLINK_TEXT)
        self.assertEqual(r["prev_holder"], "신정관 외 1인")
        self.assertEqual(r["new_holder"], "미래산업 주식회사 외 4인")
        self.assertAlmostEqual(r["new_ratio"], 39.16)
        self.assertEqual(r["reason"], "최대주주 변경을 수반하는 주식양수도 거래 완료")
        self.assertEqual(r["purpose"], "경영권 이전")
        self.assertEqual(r["self_fund"], 11191984000)
        self.assertEqual(r["borrowed_fund"], 0)
        self.assertEqual(r["lender"], "")
        self.assertEqual(r["collateral"], "")

    def test_jols_fixture_no_space_before_wae(self):
        """"(주)지피클럽외 1명" — "외" 앞에 공백이 없는 변형."""
        r = parse_control_change_detail(_JOLS_TEXT)
        self.assertEqual(r["prev_holder"], "(주)바른손이앤에이 외 2명")
        self.assertEqual(r["new_holder"], "(주)지피클럽외 1명")
        self.assertAlmostEqual(r["new_ratio"], 32.70)
        self.assertEqual(r["reason"], "제3자배정 유상증자 납입을 통한 최대주주 변경")
        self.assertEqual(r["purpose"], "경영참여, 기업가치 제고 및 경영정상화")
        self.assertEqual(r["self_fund"], 8000000030)
        self.assertEqual(r["borrowed_fund"], 0)

    def test_jksynaps_fixture_no_wae_suffix(self):
        """법인명 단독 — "외 N" 접미 자체가 없는 변형, (주)가 접미로 붙음."""
        r = parse_control_change_detail(_JKSYNAPS_TEXT)
        self.assertEqual(r["prev_holder"], "(주)엠에이치테크")
        self.assertEqual(r["new_holder"], "휴림로봇(주)")
        self.assertAlmostEqual(r["new_ratio"], 21.58)
        self.assertEqual(r["purpose"], "경영권 참여")
        self.assertEqual(r["self_fund"], 2999999464)
        self.assertEqual(r["borrowed_fund"], 0)

    def test_sunkwang_fixture_unit_omitted(self):
        """개인명 + "외 N"에서 단위(인/명)가 아예 생략된 변형."""
        r = parse_control_change_detail(_SUNKWANG_TEXT)
        self.assertEqual(r["prev_holder"], "심충식 외 22")
        self.assertEqual(r["new_holder"], "(주)화인파트너스 외 20")
        self.assertAlmostEqual(r["new_ratio"], 58.48)
        self.assertEqual(r["purpose"], "지분 추가 취득을 통한 지배구조 안정화")
        self.assertEqual(r["self_fund"], 6530823750)
        self.assertEqual(r["borrowed_fund"], 0)

    def test_leveraged_fixture_borrowed_fund(self):
        """차입금>0 — 차입처·담보내역까지 채워진 서식(합성, DART 서식 명시 필드)."""
        r = parse_control_change_detail(_LEVERAGED_TEXT)
        self.assertEqual(r["new_holder"], "(주)가나다투자조합 외 2인")
        self.assertEqual(r["self_fund"], 1000000000)
        self.assertEqual(r["borrowed_fund"], 4000000000)
        self.assertEqual(r["lender"], "주식회사 대한저축은행")
        self.assertTrue(r["collateral"].startswith("발행주식"))

    def test_empty_text_returns_defaults(self):
        r = parse_control_change_detail("")
        self.assertEqual(r["prev_holder"], "")
        self.assertEqual(r["new_holder"], "")
        self.assertEqual(r["new_ratio"], 0.0)
        self.assertEqual(r["self_fund"], 0)
        self.assertEqual(r["borrowed_fund"], 0)

    def test_no_match_returns_defaults(self):
        r = parse_control_change_detail("전혀 관계없는 임의의 공시 원문입니다.")
        self.assertEqual(r["new_holder"], "")
        self.assertEqual(r["new_ratio"], 0.0)


class TestClassifyHolderType(unittest.TestCase):
    def test_union_partnership(self):
        self.assertEqual(classify_holder_type("가나다투자조합"), "조합")
        self.assertEqual(classify_holder_type("(주)가나다투자조합 외 2인"), "조합")

    def test_limited_company(self):
        self.assertEqual(classify_holder_type("가나다 유한회사"), "유한회사")
        self.assertEqual(classify_holder_type("가나다 유한책임회사"), "유한회사")

    def test_stock_company(self):
        self.assertEqual(classify_holder_type("(주)지피클럽"), "주식회사")
        self.assertEqual(classify_holder_type("㈜지피클럽"), "주식회사")
        self.assertEqual(classify_holder_type("미래산업 주식회사 외 4인"), "주식회사")
        self.assertEqual(classify_holder_type("휴림로봇(주)"), "주식회사")

    def test_other_corporate(self):
        self.assertEqual(classify_holder_type("가나다 법인"), "기타법인")
        self.assertEqual(classify_holder_type("Gadaka Inc."), "기타법인")
        self.assertEqual(classify_holder_type("Gadaka LLC"), "기타법인")

    def test_no_corporate_marker(self):
        self.assertEqual(classify_holder_type("심충식 외 22"), "법인 표기 없음")
        self.assertEqual(classify_holder_type("신정관 외 1인"), "법인 표기 없음")
        self.assertEqual(classify_holder_type("홍길동"), "법인 표기 없음")

    def test_empty_name(self):
        self.assertEqual(classify_holder_type(""), "법인 표기 없음")
        self.assertEqual(classify_holder_type(None), "법인 표기 없음")


class TestStripHolderSuffix(unittest.TestCase):
    def test_space_before_wae_with_unit(self):
        self.assertEqual(strip_holder_suffix("신정관 외 1인"), "신정관")
        self.assertEqual(strip_holder_suffix("미래산업 주식회사 외 4인"), "미래산업 주식회사")

    def test_no_space_before_wae(self):
        self.assertEqual(strip_holder_suffix("(주)지피클럽외 1명"), "(주)지피클럽")

    def test_unit_omitted(self):
        self.assertEqual(strip_holder_suffix("심충식 외 22"), "심충식")
        self.assertEqual(strip_holder_suffix("(주)화인파트너스 외 20"), "(주)화인파트너스")

    def test_no_suffix_unchanged(self):
        self.assertEqual(strip_holder_suffix("휴림로봇(주)"), "휴림로봇(주)")
        self.assertEqual(strip_holder_suffix("(주)엠에이치테크"), "(주)엠에이치테크")

    def test_empty(self):
        self.assertEqual(strip_holder_suffix(""), "")
        self.assertEqual(strip_holder_suffix(None), "")


if __name__ == "__main__":
    unittest.main()
