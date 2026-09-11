# -*- coding: utf-8 -*-
"""재무제표 계정명 — 회사가 쓰지 않은 이름을 내지 않는다.

`fnlttSinglAcntAll`은 회사가 제출한 XBRL의 **표준 태그**에 맞춘 계정명을 준다.
회사(또는 작성 시스템)가 어느 태그에 실었느냐에 따라 원문과 어긋난다.

## 확인된 사고

CSA 코스믹 2025 연결에서 API가 이렇게 준다.

    파생상품평가손익            -8,969,358
    해외사업장환산외환차이(세후기타포괄손익)  -6,606,386

감사보고서 원문 연결포괄손익계산서(단위: 원)는 이렇다.

    | 해외사업환산손익 | | (6,606,386) | | (39,687,270) | |
    | 지분법자본변동   | | (8,969,358) | | | |

-8,969,358은 블루원(주) 관계기업투자에서 나온 **지분법자본변동**이다. 파생상품과
무관하다. 「파생상품평가손익」·「해외사업장환산외환차이」는 **문서 전체에 0건**이다.
기사에 「파생상품평가손익 896만9358원」이라 쓰면 정정 사유가 된다.

## 규모 (2026-09-12 · 8개사 · API 행 1,444개)

    대조 성공 76.9%  (같음 50.6% · **다름 26.4%**)
    모호      9.1%
    못찾음   14.0%

API가 계정 이름의 **네 개 중 하나**를 바꿔 준다.

## ⚠ 틀린 이름을 조용히 붙이는 것이 지금보다 나쁘다

- **재무제표별로** 찾는다(BS는 재무상태표 표에서). 전역으로 찾으면 모호가
  41 → 16으로 나빠지고 엉뚱한 표의 행에 붙는다.
- **날짜 같은 것은 계정명이 아니다.** 실측 삼성전자 자본총계 402조가
  자본변동표의 「2025.12.31(당기말)」 행에 물렸다.
- 같은 금액에 **다른 이름이 둘 이상**이면 붙이지 않고 후보를 적는다.
- 숫자는 **API 값 그대로** 둔다. 이 작업이 바꾸는 것은 이름뿐이다.
"""
import pathlib
import unittest

from dart_risk_mcp.core.audit_report import (
    build_fs_account_index,
    lookup_fs_account,
)

_FX = pathlib.Path(__file__).resolve().parent / "fixtures" / "audit_reports"
_CSA = (_FX / "csa_cosmic_2025_fs_section.md").read_text(encoding="utf-8")
_SAM = (_FX / "samsung_2025_fs_section.md").read_text(encoding="utf-8")


class TestUnitDetection(unittest.TestCase):
    def test_원_단위를_읽는다(self):
        self.assertEqual(build_fs_account_index(_CSA)["unit"], ("원", 1))

    def test_백만원_단위를_읽는다(self):
        self.assertEqual(build_fs_account_index(_SAM)["unit"], ("백만원", 1_000_000))

    def test_단위가_없으면_원으로_본다(self):
        self.assertEqual(build_fs_account_index("| 과 목 | 당기 |\n")["unit"],
                         ("원", 1))

    def test_재무제표_표제가_없으면_대조하지_않는다(self):
        """구간을 못 가르면 **전역으로 찾지 않는다** — 엉뚱한 표의 행에 붙는다.

        실측에서 전역 매칭은 모호를 16 → 41로 늘렸고, 삼성전자 자본총계가
        자본변동표 날짜 행에 물렸다. 못 찾는 쪽이 낫다.
        """
        idx = build_fs_account_index(
            "| 과 목 | 당기 |\n|---|---|\n| 유동자산 | 1,000 |\n")
        self.assertEqual(idx["by_div"], {})
        self.assertEqual(lookup_fs_account(idx, "BS", 1000, "유동자산")["status"],
                         "missing")


class TestVerificationCase(unittest.TestCase):
    """사고가 난 두 줄."""

    def setUp(self):
        self.idx = build_fs_account_index(_CSA)

    def test_지분법자본변동을_찾는다(self):
        r = lookup_fs_account(self.idx, "CIS", -8_969_358, "파생상품평가손익")
        self.assertEqual(r["status"], "diff")
        self.assertEqual(r["name"], "지분법자본변동")

    def test_해외사업환산손익을_찾는다(self):
        r = lookup_fs_account(self.idx, "CIS", -6_606_386,
                              "해외사업장환산외환차이(세후기타포괄손익)")
        self.assertEqual(r["status"], "diff")
        self.assertEqual(r["name"], "해외사업환산손익")

    def test_같은_이름이면_같음이다(self):
        r = lookup_fs_account(self.idx, "CIS", -6_833_892, "지분법손익")
        self.assertEqual(r["status"], "same")
        self.assertEqual(r["name"], "지분법손익")

    def test_매출액도_같음이다(self):
        r = lookup_fs_account(self.idx, "CIS", 27_930_330_148, "매출액")
        self.assertEqual(r["status"], "same")


class TestNormalizationIsNotOverEager(unittest.TestCase):
    def test_번호_접두는_차이로_보지_않는다(self):
        idx = build_fs_account_index(
            "| 재 무 상 태 표 |\n|---|\n"
            "| 과 목 | 당기 |\n|---|---|\n| I. 유동자산 | 1,000 |\n")
        r = lookup_fs_account(idx, "BS", 1000, "유동자산")
        self.assertEqual(r["status"], "same")
        self.assertEqual(r["name"], "I. 유동자산", "원문 표기를 그대로 보여준다")

    def test_들여쓰기_불릿은_차이로_보지_않는다(self):
        """실측 두산 자본변동표는 하위 항목에 「- 」을 붙인다(「- 당기순이익」).

        불릿은 표의 들여쓰기 표시이지 계정명의 일부가 아니다 — 「다름」으로
        세면 이름이 실제로 갈린 것처럼 읽힌다. ⚠ **표시는 원문 그대로** 두고
        비교할 때만 접는다(번호 접두와 같은 처리).
        """
        idx = build_fs_account_index(
            "| 자 본 변 동 표 |\n|---|\n| 과 목 | 자본금 |\n|---|---|\n"
            "| - 당기순이익 | 1,000 |\n")
        r = lookup_fs_account(idx, "SCE", 1000, "당기순이익")
        self.assertEqual(r["status"], "same")
        self.assertEqual(r["name"], "- 당기순이익", "원문 표기를 그대로 보여준다")

    def test_자간이_벌어져도_차이가_아니다(self):
        idx = build_fs_account_index(
            "| 손 익 계 산 서 |\n|---|\n"
            "| 과 목 | 당기 |\n|---|---|\n| 법 인 세 비 용 | 1,000 |\n")
        self.assertEqual(lookup_fs_account(idx, "IS", 1000, "법인세비용")["status"],
                         "same")

    def test_뜻이_다르면_다름이다(self):
        idx = build_fs_account_index(
            "| 재 무 상 태 표 |\n|---|\n"
            "| 과 목 | 당기 |\n|---|---|\n| 관계기업및공동기업투자 | 1,000 |\n")
        r = lookup_fs_account(idx, "BS", 1000, "종속및공동기업투자")
        self.assertEqual(r["status"], "diff")


class TestSafetyGuards(unittest.TestCase):
    def test_날짜_행은_계정명이_아니다(self):
        """삼성전자 자본총계가 자본변동표 날짜 행에 물렸다."""
        idx = build_fs_account_index(_SAM)
        r = lookup_fs_account(idx, "BS", 402_135_600 * 1_000_000, "자본총계")
        self.assertNotEqual(r["name"], "2025.12.31(당기말)")
        self.assertIn(r["status"], ("same", "diff", "missing", "ambiguous"))

    def test_공백이_낀_날짜도_계정명이_아니다(self):
        """실측 두산 자본변동표: API 「기초」가 원문 「2025. 1. 1.(당기초)」에 물렸다.

        옛 가드는 `2025.01.01` 꼴만 봐서 **점 뒤에 공백이 있는 표기**를 통과
        시켰다. 이름을 날짜로 바꿔 내면 기사에 그대로 옮겨질 때 사고다 —
        「기초」는 계정이고 그 행 머리는 시점 표시일 뿐이다.
        """
        txt = ("| 자 본 변 동 표 |\n|---|\n| 과 목 | 자본금 |\n|---|---|\n"
               "| 2025. 1. 1.(당기초) | 1,234 |\n")
        idx = build_fs_account_index(txt)
        self.assertEqual(lookup_fs_account(idx, "SCE", 1234, "기초")["status"],
                         "missing")

    def test_연월일_한글_표기도_계정명이_아니다(self):
        """실측 STX 자본변동표 「2025년 1월 1일(당기초)」 — 8개사 2,659행 중 32건."""
        txt = ("| 자 본 변 동 표 |\n|---|\n| 과 목 | 자본금 |\n|---|---|\n"
               "| 2025년 1월 1일(당기초) | 4,321 |\n")
        idx = build_fs_account_index(txt)
        self.assertEqual(lookup_fs_account(idx, "SCE", 4321, "기초")["status"],
                         "missing")

    def test_진짜_계정명은_날짜_가드에_걸리지_않는다(self):
        """실측 삼성전자 「3. 연결실체의 변동」·제이스코 「신주발행비」는 계정이다."""
        txt = ("| 자 본 변 동 표 |\n|---|\n| 과 목 | 자본금 |\n|---|---|\n"
               "| 3. 연결실체의 변동 | 555 |\n| 신주발행비 | 666 |\n")
        idx = build_fs_account_index(txt)
        self.assertEqual(lookup_fs_account(idx, "SCE", 555, "연결실체의 변동")["status"],
                         "same")
        self.assertEqual(lookup_fs_account(idx, "SCE", 666, "신주발행비")["name"],
                         "신주발행비")

    def test_같은_금액에_이름이_둘이면_붙이지_않는다(self):
        txt = ("| 재 무 상 태 표 |\n|---|\n"
               "| 과 목 | 당기 |\n|---|---|\n"
               "| 가나자산 | 1,000 |\n| 다라부채 | 1,000 |\n")
        idx = build_fs_account_index(txt)
        r = lookup_fs_account(idx, "BS", 1000, "무언가")
        self.assertEqual(r["status"], "ambiguous")
        self.assertEqual(sorted(r["candidates"]), ["가나자산", "다라부채"])
        self.assertEqual(r["name"], "")

    def test_없으면_못찾음이다(self):
        idx = build_fs_account_index(_CSA)
        r = lookup_fs_account(idx, "CIS", 12_345_678_901, "없는계정")
        self.assertEqual(r["status"], "missing")
        self.assertEqual(r["name"], "")

    def test_재무제표별로_찾는다(self):
        """BS 금액을 손익 표에서 찾지 않는다."""
        txt = ("| 재 무 상 태 표 |\n|---|\n| 과 목 | 당기 |\n|---|---|\n"
               "| 자산총계 | 500 |\n"
               "| 포 괄 손 익 계 산 서 |\n|---|\n| 과 목 | 당기 |\n|---|---|\n"
               "| 매출액 | 500 |\n")
        idx = build_fs_account_index(txt)
        self.assertEqual(lookup_fs_account(idx, "BS", 500, "자산총계")["name"],
                         "자산총계")
        self.assertEqual(lookup_fs_account(idx, "CIS", 500, "매출액")["name"],
                         "매출액")

    def test_손익과_포괄손익은_서로_폴백한다(self):
        txt = ("| 포 괄 손 익 계 산 서 |\n|---|\n| 과 목 | 당기 |\n|---|---|\n"
               "| 매출액 | 700 |\n")
        idx = build_fs_account_index(txt)
        self.assertEqual(lookup_fs_account(idx, "IS", 700, "매출액")["status"],
                         "same")

    def test_금액_0은_찾지_않는다(self):
        """0은 표에 흔해 아무 데나 물린다."""
        idx = build_fs_account_index(_CSA)
        self.assertEqual(lookup_fs_account(idx, "CIS", 0, "영업외손익")["status"],
                         "missing")



class TestSignConvention(unittest.TestCase):
    """원문은 비용을 괄호(차감 표시)로 적고 API는 양수로 준다.

    실측 CSA 코스믹 연결포괄손익계산서:

        | 매출원가       | 28,34 | (17,729,615,657) |
        | 판매비와관리비 | 30,34 | (15,834,703,455) |
        | 금융비용       | 31    |  (3,637,741,789) |

    API는 셋 다 **양수**로 준다. 부호를 그대로 대조하면 세 줄이 「대조 실패」가
    된다 — 원문에 버젓이 있는데 못 찾았다고 적는 것이고, 화면이 제 데이터와
    다른 것을 말한다. 실측 라이브에서 26행 중 10행만 확인되던 원인이다.

    ⚠ **정확 일치가 먼저다.** 같은 절댓값의 +행과 -행이 서로 다른 계정일 수
    있으므로, 부호가 맞는 쪽이 있으면 그것을 쓰고 없을 때만 뒤집어 본다.
    """

    def setUp(self):
        self.idx = build_fs_account_index(_CSA)

    def test_괄호로_적힌_비용을_양수로_찾는다(self):
        r = lookup_fs_account(self.idx, "CIS", 17_729_615_657, "매출원가")
        self.assertEqual(r["status"], "same")
        self.assertEqual(r["name"], "매출원가")

    def test_판매비와관리비도_찾는다(self):
        r = lookup_fs_account(self.idx, "CIS", 15_834_703_455, "판매비와관리비")
        self.assertEqual(r["status"], "same")

    def test_API가_금융원가라_부르는_줄은_원문이_금융비용이다(self):
        r = lookup_fs_account(self.idx, "CIS", 3_637_741_789, "금융원가")
        self.assertEqual(r["status"], "diff")
        self.assertEqual(r["name"], "금융비용")

    def test_부호가_맞는_쪽을_먼저_쓴다(self):
        txt = ("| 손 익 계 산 서 |\n|---|\n| 과 목 | 당기 |\n|---|---|\n"
               "| 양수항목 | 500 |\n| 음수항목 | (500) |\n")
        idx = build_fs_account_index(txt)
        self.assertEqual(lookup_fs_account(idx, "IS", 500, "x")["name"],
                         "양수항목")
        self.assertEqual(lookup_fs_account(idx, "IS", -500, "x")["name"],
                         "음수항목")

    def test_뒤집어_찾은_것도_모호하면_붙이지_않는다(self):
        txt = ("| 손 익 계 산 서 |\n|---|\n| 과 목 | 당기 |\n|---|---|\n"
               "| 가나비용 | (900) |\n| 다라비용 | (900) |\n")
        idx = build_fs_account_index(txt)
        r = lookup_fs_account(idx, "IS", 900, "어떤비용")
        self.assertEqual(r["status"], "ambiguous")
        self.assertEqual(sorted(r["candidates"]), ["가나비용", "다라비용"])


class TestParentheses(unittest.TestCase):
    def test_괄호는_음수다(self):
        idx = build_fs_account_index(
            "| 손 익 계 산 서 |\n|---|\n"
            "| 과 목 | 당기 |\n|---|---|\n| 당기순손실 | (6,674,847,300) |\n")
        r = lookup_fs_account(idx, "IS", -6_674_847_300, "당기순이익(손실)")
        self.assertEqual(r["name"], "당기순손실")


class TestEmpty(unittest.TestCase):
    def test_빈_원문은_전부_못찾음이다(self):
        idx = build_fs_account_index("")
        self.assertEqual(lookup_fs_account(idx, "BS", 100, "자산총계")["status"],
                         "missing")


if __name__ == "__main__":
    unittest.main()
