"""_table_to_markdown의 DART 전용 값 셀(<TE>/<TU>) 처리 회귀 테스트.

주요사항보고서류 원문 XML은 라벨을 <TD>, 제출인이 기재한 값을 <TE>에 담는다
(아틀라스링크 유형자산양수 20260722000373 실측). TE를 셀로 취급하지 않으면
값이 전부 누락된 라벨 골격만 남아 — 뷰어 원문 열람과 자금유출 상대방 파싱이
통째로 깨진다(2026-08-02 실사고: capital_backflow가 뷰어에서 미발화).
"""
import unittest

from dart_risk_mcp.core.dart_client import _html_to_structured_text, _table_to_markdown

# 실측 마크업 축약 (아틀라스링크 20260722000373 원문 구조)
_TE_TABLE = """
<TABLE>
<TR><TD ROWSPAN="5" ENG="6. Counterparty">6. 거래상대방</TD>
    <TD ALIGN="CENTER" ENG="Company name">회사명(성명)</TD>
    <TE ALIGN="CENTER" ACODE="OTH_NM"><SPAN USERMARK="F-BT ">㈜</SPAN> <SPAN>로아앤코홀딩스</SPAN></TE></TR>
<TR><TD>회사와의 관계</TD><TE>계열회사</TE></TR>
</TABLE>
"""


class TestTeCells(unittest.TestCase):
    def test_te_values_survive_table_conversion(self):
        md = _table_to_markdown(_TE_TABLE)
        self.assertIn("로아앤코홀딩스", md)
        self.assertIn("계열회사", md)
        # 라벨-값이 같은 행의 인접 셀로 남아야 뷰어 셀 파서가 읽는다
        self.assertIn("| 회사와의 관계 | 계열회사 |", md)

    def test_te_values_survive_full_conversion(self):
        text = _html_to_structured_text(_TE_TABLE)
        self.assertIn("로아앤코홀딩스", text)
        self.assertIn("계열회사", text)

    def test_plain_td_tables_unchanged(self):
        md = _table_to_markdown("<table><tr><td>a</td><td>b</td></tr></table>")
        self.assertEqual(md.splitlines()[0], "| a | b |")
