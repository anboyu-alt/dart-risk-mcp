# -*- coding: utf-8 -*-
"""resolve_corp None 가드 회귀 테스트.

resolve_corp는 미존재 기업이면 None을 반환하는데(tuple | None), 9개 도구가
검사 전에 언팩(`corp_name, meta = ...`)하거나 인덱싱(`corp_info[1]`)해
미존재 기업명 입력에 TypeError로 크래시했다(2026-08-04 정적 감사 B-1,
라이브 재현 확인). 모든 회사명 기반 도구는 미존재 기업에 예외 없이
안내 문구를 반환해야 한다.
"""
import inspect
import unittest
from unittest.mock import patch

from dart_risk_mcp import server

TOOLS = [
    "get_executive_compensation", "track_insider_trading",
    "check_disclosure_anomaly", "track_fund_usage", "track_debt_balance",
    "get_affiliate_investments", "get_audit_opinion_history",
    "scan_financial_anomaly", "track_capital_structure",
]


class TestResolveCorpNoneGuard(unittest.TestCase):
    def test_tools_return_notice_when_company_not_found(self):
        for name in TOOLS:
            with self.subTest(tool=name):
                fn = getattr(server, name)
                fn = getattr(fn, "fn", fn)
                with patch.object(server, "resolve_corp", return_value=None), \
                     patch.object(server, "_DART_API_KEY", "dummy"):
                    out = fn("졸리운늑대상사")
                    if inspect.iscoroutine(out):
                        import asyncio
                        out = asyncio.get_event_loop().run_until_complete(out)
                self.assertIsInstance(out, str)
                self.assertIn("찾을 수 없", out)


if __name__ == "__main__":
    unittest.main()
