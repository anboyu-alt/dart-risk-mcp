# -*- coding: utf-8 -*-
"""숫자 HTML 엔티티 디코딩 견고성.

공시 원문은 외부 입력이다 — chr() 범위(0x110000) 밖 숫자 엔티티가 오면
_decode_html_entities가 ValueError를 던졌고, try/except 없는
fetch_document_content 경로를 타고 view_disclosure MCP 도구까지 예외가
전파됐다(2026-08-04 파서 퍼징에서 발견). 디코딩 불가능한 엔티티는
원문 표기 그대로 남기고 절대 예외를 전파하지 않는다.
"""
import unittest

from dart_risk_mcp.core.dart_client import (
    _decode_html_entities,
    _html_to_structured_text,
)


class TestNumericEntityRobustness(unittest.TestCase):
    def test_out_of_range_decimal_entity_no_crash(self):
        # 0x110000 == 1114112 — chr() 허용 범위 바로 밖
        out = _html_to_structured_text("<p>&#1114112;</p>")
        self.assertIn("&#1114112;", out)  # 원문 보존, 예외 없음

    def test_huge_decimal_entity_no_crash(self):
        out = _decode_html_entities("&#99999999999999999999;")
        self.assertIn("&#99999999999999999999;", out)

    def test_out_of_range_hex_entity_no_crash(self):
        out = _decode_html_entities("&#x110000;")
        self.assertIn("&#x110000;", out)

    def test_surrogate_entity_no_crash(self):
        # 서로게이트 코드포인트는 chr()은 되지만 인코딩 불가 — 원문 보존이 안전
        out = _decode_html_entities("&#xD800;")
        self.assertIsInstance(out, str)

    def test_valid_entities_still_decode(self):
        self.assertEqual(_decode_html_entities("&#65;&#x42;"), "AB")
        out = _html_to_structured_text("<p>&#44608;&amp;</p>")
        self.assertIn("김", out)
        self.assertIn("&", out)


if __name__ == "__main__":
    unittest.main()
