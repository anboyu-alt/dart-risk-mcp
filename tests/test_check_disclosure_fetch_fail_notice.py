# -*- coding: utf-8 -*-
"""check_disclosure_risk — 원문 조회 실패와 '신호 없음'의 구분.

존재하지 않는 접수번호를 넣으면 제목도 원문도 없어 아무것도 분석하지
못했는데 "의심 신호가 탐지되지 않았습니다"만 출력돼 유효한 공시처럼
읽혔다(2026-08-04 라이브 스모크). 제목 없이 원문 조회까지 실패하면
조회 실패 사실을 명시해야 한다.
"""
import unittest
from unittest.mock import patch

from dart_risk_mcp import server


def _fn():
    f = server.check_disclosure_risk
    return getattr(f, "fn", f)


class TestFetchFailNotice(unittest.TestCase):
    def test_unfetchable_rcept_no_gets_notice(self):
        with patch.object(server, "_DART_API_KEY", "dummy"), \
             patch.object(server, "fetch_document_text", return_value=""), \
             patch.object(server, "resolve_disclosure_row_with_status",
                          return_value=(None, "not_found")), \
             patch.object(server, "resolve_corp_code_from_rcept_no",
                          return_value=""):
            out = _fn()("00000000000000")
        self.assertIn("조회하지 못했습니다", out)
        self.assertIn("해석하지 마세요", out)

    def test_with_report_name_no_notice(self):
        # 제목이 있으면 제목 기반 분석은 유효 — 실패 문구를 붙이지 않는다
        with patch.object(server, "_DART_API_KEY", "dummy"), \
             patch.object(server, "fetch_document_text", return_value=""), \
             patch.object(server, "resolve_disclosure_row_with_status",
                          return_value=(None, "not_found")), \
             patch.object(server, "extract_cb_investors", return_value=[]), \
             patch.object(server, "resolve_corp_code_from_rcept_no",
                          return_value=""):
            out = _fn()("00000000000000", report_name="전환사채권발행결정")
        self.assertNotIn("조회하지 못했습니다", out)


if __name__ == "__main__":
    unittest.main()
