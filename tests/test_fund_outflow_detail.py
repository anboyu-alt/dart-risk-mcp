"""v1.6.1: 자금유출성 신호 실질 판정 — 원문 상대방 추출 + 관계 분류 + 게이트.

FUND_OUTFLOW(금전대여·채무보증·담보제공·유형자산양수)는 제목만으로 매칭되면
계열사 지원이 일상인 회사 전부가 걸린다. 이 테스트는:
  1) parse_outflow_detail — 원문(fetch_document_text 출력 형태: 태그 제거·공백
     단일화)에서 상대방·관계·금액을 추출하는 순수 파서. fixture 3종은 전부
     라이브 확인된 실측 서식(한농화성 20260728800659, 피플바이오 20260731901330,
     아틀라스링크 20260729900778)이다.
  2) classify_outflow_relation — 관계 원문을 4범주(affiliated/subsidiary/
     external/unknown)로 분류.
  3) STAKE_PLEDGE 신호가 FUND_OUTFLOW와 겹치지 않고 분리되는지.
  4) capital_backflow 게이트 순수 로직 — affiliated 있음/subsidiary만/unknown만.
"""
import unittest

from dart_risk_mcp.core.dart_client import (
    parse_outflow_detail,
    classify_outflow_relation,
    fetch_outflow_detail,
)
from dart_risk_mcp.core.signals import match_signals


# ── fixture: 실측 원문 서식 (fetch_document_text 출력 형태) ──────────────────

_LOAN_TEXT = (
    "1. 대여 상대 바스프한농화성솔루션스 주식회사 영문 BASF Korea Chemicals "
    "Solutions Co., Ltd. - 회사와의 관계 계열회사 2. 금전대여 내역 거래일자 "
    "2026-08-04 대여금액(원) 20,584,257,000 자기자본(원) 174,481,832,690 "
    "자기자본대비(%) 11.80 3. 금전대여 목적 시설투자자금 4. 금전대여 총잔액(원) "
    "23,034,257,000"
)

_COLLATERAL_TEXT = (
    "1. 채무자 주식회사 이스턴네트웍스 - 회사와의 관계 주요주주의 특수관계인 "
    "2. 채권자 새마을금고 3. 채무(차입)금액(원) 3,620,000,000 4. 담보제공 내역 "
    "담보설정금액(원) 4,346,000,000 자기자본대비(%) 15.19"
)

_GUARANTEE_TEXT = (
    "1. 채무자 주식회사 한국파일 -회사와의 관계 종속회사 2. 채권자 신한은행 "
    "3. 채무(차입)금액(원) 8,600,000,000 4. 채무보증내역 채무보증금액(원) "
    "3,725,385,833 자기자본대비(%) 6.8"
)

# 아틀라스링크(구 알로이스) 20260120900216/20251015900139 라이브 확인 — "대여
# 상대"가 아니라 "성명(법인명)" 라벨을 쓰고, 관계도 "-회사와의 관계"가 아니라
# "(회사와의 관계)"로 감싼 뒤 바로 뒤에 하이픈 접두 부가 항목이 이어지는 세 번째
# 실측 변형. 최초 구현이 "unknown"으로 놓쳤던 실사례라 회귀 가드로 고정한다.
_LOAN_ALT_LABEL_TEXT = (
    "1. 성명(법인명) 주식회사 한국파일 (회사와의 관계) 종속회사 -최근 6월 이내 "
    "제3자 배정에 의한 신주취득 여부 아니오 2. 금전대여 내역 거래일자 "
    "2026-01-20 대여금액 (원) 5,000,000,000 -자기자본(원) 40,374,430,233 "
    "-자기자본 대비(%) 12.4 -대기업해당여부 미해당 이율 (%) 4.6"
)

# 최대주주변경을수반하는주식담보제공계약체결 — 별개 서식(오너 개인 담보, 회사
# 자금 유출이 아님). parse_outflow_detail은 이 서식을 다루지 않는다(kind="").
_STAKE_PLEDGE_TEXT = (
    "1. 담보제공자(최대주주) 관련 사항 - 명칭(성명, 법인명, 조합명, 단체명) "
    "최병채 - 공시일 현재 소유 주식 수(주) 11,377,670 지분율(%) 23.42 "
    "2. 채무(차입)금액 총액(원) 37,800,000,000 3. 담보설정금액 총액(원) "
    "64,260,000,000"
)


class TestParseOutflowDetail(unittest.TestCase):
    def test_loan_fixture(self):
        r = parse_outflow_detail(_LOAN_TEXT)
        self.assertEqual(r["kind"], "loan")
        self.assertEqual(r["counterparty"], "바스프한농화성솔루션스 주식회사")
        self.assertEqual(r["relation"], "계열회사")
        self.assertEqual(r["amount"], 20584257000)
        self.assertAlmostEqual(r["equity_ratio"], 11.80)

    def test_collateral_fixture(self):
        r = parse_outflow_detail(_COLLATERAL_TEXT)
        self.assertEqual(r["kind"], "collateral")
        self.assertEqual(r["counterparty"], "주식회사 이스턴네트웍스")
        self.assertEqual(r["relation"], "주요주주의 특수관계인")
        self.assertEqual(r["amount"], 4346000000)
        self.assertAlmostEqual(r["equity_ratio"], 15.19)

    def test_guarantee_fixture(self):
        r = parse_outflow_detail(_GUARANTEE_TEXT)
        self.assertEqual(r["kind"], "guarantee")
        self.assertEqual(r["counterparty"], "주식회사 한국파일")
        self.assertEqual(r["relation"], "종속회사")
        self.assertEqual(r["amount"], 3725385833)
        self.assertAlmostEqual(r["equity_ratio"], 6.8)

    def test_hyphen_variant_no_space(self):
        # "-회사와의 관계"(공백 없는 하이픈) 변형 — guarantee/collateral 서식에서
        # 실측 확인된 두 변형 중 하나. loan은 하이픈+공백("- 회사와의 관계"),
        # guarantee/collateral 실측은 공백 없는 "-회사와의 관계"였다(둘 다 커버).
        text = (
            "1. 채무자 테스트법인 -회사와의 관계 계열회사 2. 채권자 국민은행 "
            "3. 채무(차입)금액(원) 1,000,000,000 4. 채무보증내역 채무보증금액(원) "
            "500,000,000 자기자본대비(%) 1.0"
        )
        r = parse_outflow_detail(text)
        self.assertEqual(r["counterparty"], "테스트법인")
        self.assertEqual(r["relation"], "계열회사")

    def test_hyphen_variant_with_space(self):
        text = (
            "1. 채무자 테스트법인 - 회사와의 관계 계열회사 2. 채권자 국민은행 "
            "3. 채무(차입)금액(원) 1,000,000,000 4. 담보제공 내역 담보설정금액(원) "
            "500,000,000 자기자본대비(%) 1.0"
        )
        r = parse_outflow_detail(text)
        self.assertEqual(r["counterparty"], "테스트법인")
        self.assertEqual(r["relation"], "계열회사")

    def test_loan_alt_label_fixture(self):
        # "성명(법인명)" 라벨 + "(회사와의 관계)" 괄호형 + 하이픈 부가 항목 변형.
        r = parse_outflow_detail(_LOAN_ALT_LABEL_TEXT)
        self.assertEqual(r["kind"], "loan")
        self.assertEqual(r["counterparty"], "주식회사 한국파일")
        self.assertEqual(r["relation"], "종속회사")
        self.assertEqual(r["amount"], 5000000000)
        self.assertAlmostEqual(r["equity_ratio"], 12.4)

    def test_empty_text_returns_blank_fields(self):
        r = parse_outflow_detail("")
        self.assertEqual(r, {
            "counterparty": "", "relation": "", "amount": 0,
            "equity_ratio": 0.0, "kind": "",
        })

    def test_unrecognized_text_returns_blank_kind(self):
        r = parse_outflow_detail("아무 관련 없는 임의의 공시 본문입니다.")
        self.assertEqual(r["kind"], "")
        self.assertEqual(r["counterparty"], "")

    def test_stake_pledge_format_not_handled_as_outflow(self):
        # 별개 서식 — 금전대여/채무보증/담보제공 3종 어느 키워드도 없어 kind="".
        r = parse_outflow_detail(_STAKE_PLEDGE_TEXT)
        self.assertEqual(r["kind"], "")

    def test_fetch_outflow_detail_empty_without_api_key(self):
        self.assertEqual(fetch_outflow_detail("20260728800659", ""), {})
        self.assertEqual(fetch_outflow_detail("", "dummy"), {})


class TestClassifyOutflowRelation(unittest.TestCase):
    def test_affiliated_branch(self):
        for r in ("계열회사", "관계회사", "최대주주", "주요주주", "임원",
                   "대표이사", "주요주주의 특수관계인", "특수관계자"):
            self.assertEqual(classify_outflow_relation(r), "affiliated", r)

    def test_subsidiary_branch(self):
        self.assertEqual(classify_outflow_relation("종속회사"), "subsidiary")
        self.assertEqual(classify_outflow_relation("자회사"), "subsidiary")

    def test_external_branch(self):
        for r in ("-", "타인", "해당없음", "해당 없음"):
            self.assertEqual(classify_outflow_relation(r), "external", r)

    def test_unknown_branch(self):
        self.assertEqual(classify_outflow_relation(""), "unknown")
        self.assertEqual(classify_outflow_relation(None), "unknown")
        self.assertEqual(classify_outflow_relation("알수없는표기"), "unknown")

    def test_negated_relation_is_not_affiliated(self):
        # "특수관계 없음"류 부정 표기는 키워드 부분 일치로 affiliated가 되면
        # 안 된다 — capital_backflow(CRITICAL) 게이트의 오발화 경로.
        for r in ("특수관계 없음", "해당사항 없음(특수관계 없음)",
                  "특수관계 아님", "최대주주 아님", "특수관계인에 해당하지 않음",
                  "없음", "특수관계 무관"):
            self.assertEqual(classify_outflow_relation(r), "external", r)

    def test_negated_subsidiary_is_not_subsidiary(self):
        self.assertEqual(classify_outflow_relation("종속회사 아님"), "external")


class TestStakePledgeSignalSeparation(unittest.TestCase):
    def _keys(self, title: str) -> set[str]:
        return {s["key"] for s in match_signals(title)}

    def test_stake_pledge_title_matches_stake_pledge_not_fund_outflow(self):
        keys = self._keys("최대주주변경을수반하는주식담보제공계약체결")
        self.assertIn("STAKE_PLEDGE", keys)
        self.assertNotIn("FUND_OUTFLOW", keys)

    def test_stake_pledge_release_variant_matches(self):
        self.assertIn(
            "STAKE_PLEDGE", self._keys("최대주주변경을수반하는주식담보제공계약해제")
        )

    def test_third_party_collateral_decision_still_matches_fund_outflow(self):
        keys = self._keys("타인에대한담보제공결정")
        self.assertIn("FUND_OUTFLOW", keys)
        self.assertNotIn("STAKE_PLEDGE", keys)

    def test_related_party_collateral_without_gyeoljeong_suffix_matches(self):
        # 라이브 시장 스캔 실측(2026-07-31): "결정" 접미사 없는 이 제목이
        # "담보제공결정" 단독 키워드로는 누락됐다 — 효성화학·동화농산 등 4사 동일 제목.
        keys = self._keys("특수관계인에대한담보제공")
        self.assertIn("FUND_OUTFLOW", keys)
        self.assertNotIn("STAKE_PLEDGE", keys)


class TestCapitalBackflowGate(unittest.TestCase):
    def _row(self, classification, counterparty="테스트법인", relation="", rcept_no="1"):
        return {
            "rcept_dt": "2026-07-01", "report_nm": "타인에대한채무보증결정",
            "rcept_no": rcept_no, "counterparty": counterparty,
            "relation": relation, "classification": classification, "amount": 100,
        }

    def test_affiliated_present_passes(self):
        from dart_risk_mcp.server import _capital_backflow_gate
        confirmations = [self._row("affiliated", relation="계열회사")]
        gate = _capital_backflow_gate(confirmations)
        self.assertTrue(gate["pass"])
        self.assertEqual(len(gate["affiliated"]), 1)

    def test_subsidiary_only_fails_with_fact_block(self):
        from dart_risk_mcp.server import _capital_backflow_gate
        confirmations = [self._row("subsidiary", relation="종속회사")]
        gate = _capital_backflow_gate(confirmations)
        self.assertFalse(gate["pass"])
        self.assertTrue(gate["fact_lines"])
        joined = "\n".join(gate["fact_lines"])
        self.assertIn("특수관계 유출은 미확인", joined)

    def test_external_only_fails_with_fact_block(self):
        from dart_risk_mcp.server import _capital_backflow_gate
        confirmations = [self._row("external", relation="-")]
        gate = _capital_backflow_gate(confirmations)
        self.assertFalse(gate["pass"])
        self.assertTrue(gate["fact_lines"])

    def test_unknown_only_fails_with_guidance(self):
        from dart_risk_mcp.server import _capital_backflow_gate
        confirmations = [self._row("unknown", counterparty="", rcept_no="20260729900778")]
        gate = _capital_backflow_gate(confirmations)
        self.assertFalse(gate["pass"])
        joined = "\n".join(gate["fact_lines"])
        self.assertIn("상대방 미확인", joined)
        self.assertIn("20260729900778", joined)

    def test_empty_confirmations_fails_quietly(self):
        from dart_risk_mcp.server import _capital_backflow_gate
        gate = _capital_backflow_gate([])
        self.assertFalse(gate["pass"])
        self.assertEqual(gate["fact_lines"], [])

    def test_affiliated_without_control_change_fails(self):
        """한농화성 실측 오탐 방어 — 계열사 대여(affiliated)가 있어도 창 내
        실질 경영권 변경 제목이 없으면(일상적 5% 보고만으로 3.1이 켜진 경우)
        패턴 미발화 + 사실 나열."""
        from dart_risk_mcp.server import _capital_backflow_gate
        confirmations = [self._row("affiliated", relation="계열회사")]
        gate = _capital_backflow_gate(confirmations, has_control_change=False)
        self.assertFalse(gate["pass"])
        joined = "\n".join(gate["fact_lines"])
        self.assertIn("경영권 변경", joined)
        self.assertIn("적용하지 않음", joined)

    def test_has_control_change_title_helper(self):
        from dart_risk_mcp.server import _has_control_change_title
        self.assertTrue(_has_control_change_title(
            [{"report_nm": "최대주주변경을수반하는주식양수도계약체결"}]))
        self.assertTrue(_has_control_change_title([{"report_nm": "최대주주 변경"}]))
        self.assertFalse(_has_control_change_title(
            [{"report_nm": "주식등의대량보유상황보고서(일반)"},
             {"report_nm": "금전대여결정"}]))

    def test_mixed_affiliated_and_subsidiary_still_passes(self):
        from dart_risk_mcp.server import _capital_backflow_gate
        confirmations = [
            self._row("subsidiary", relation="종속회사", rcept_no="1"),
            self._row("affiliated", relation="계열회사", rcept_no="2"),
        ]
        gate = _capital_backflow_gate(confirmations)
        self.assertTrue(gate["pass"])
        self.assertEqual(len(gate["affiliated"]), 1)


if __name__ == "__main__":
    unittest.main()
