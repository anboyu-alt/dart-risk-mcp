"""search_market_disclosures 날짜 청크 스캔 — 조용한 절단 실사고 회귀 테스트.

실사고(2026-08-05): 한 호출(max_pages=10, 1,000건)로 30일 창을 덮으려다
시장 일평균 ~500건에 2~3일 만에 상한 도달 — DART가 최신순으로 주므로
"최근 30일" 스캔이 실제로는 최근 1~2일만 검토하고, asset_transfer 30일
스캔이 7/22 유형자산양수를 놓쳤다. 2일 청크 순회 + 절단 청크 정직 보고로
수정. 이 테스트는 청크 순회·중복 제거·절단 보고를 네트워크 없이 검증한다.
"""
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import dart_risk_mcp.server as server


def _disc(rcept_no, date, name="유형자산양수결정"):
    return {"rcept_no": rcept_no, "rcept_dt": date, "corp_name": "테스트사",
            "report_nm": name, "corp_code": "00000001", "stock_code": "000001"}


class TestMarketScanChunking(unittest.TestCase):
    def setUp(self):
        self._key_patch = patch.object(server, "_DART_API_KEY", "dummy-key")
        self._key_patch.start()
        self.addCleanup(self._key_patch.stop)

    def test_thirty_day_window_is_chunked_and_covers_old_dates(self):
        calls = []
        # 창 초반(오래된 쪽)에 놓이되 경계를 넘지 않는 날짜를 오늘 기준으로
        # 계산한다. 예전에는 "20260722"를 하드코딩했는데, 스캔 창은 오늘
        # 기준으로 굴러가므로 그 날짜가 창 밖으로 밀려나면(2026-08-21에
        # 실제로 발생 — 창이 20260723~20260821이 되며 하루 차이로 이탈)
        # 제품 회귀가 없는데도 영구히 실패한다.
        old_date = (datetime.now() - timedelta(days=25)).strftime("%Y%m%d")

        def fake_fetch(api_key, bgn_de, end_de, pblntf_ty="", max_pages=10):
            calls.append((bgn_de, end_de))
            # 오래된 청크에만 존재하는 공시 — 절단됐다면 이 공시를 놓친다
            if bgn_de <= old_date <= end_de:
                return [_disc("R_OLD", old_date)]
            return []

        with patch.object(server, "fetch_market_disclosures", side_effect=fake_fetch):
            with patch.object(server, "datetime", wraps=datetime) as _:
                # v1.18.1: 30일은 대기 예산을 넘어 분기 안내가 먼저 나온다.
                # 이 테스트가 검증하려는 것은 절단 회귀이므로 실행을 확정한다.
                out = server.search_market_disclosures(
                    "fund_outflow", days=30, confirm_long=True)

        # v1.18.1: 하루 청크로 직행한다(2일 묶음의 92%가 상한에 닿아 어차피
        # 재분할됐다 — 1년 코퍼스 실측). 30일이면 30회.
        self.assertEqual(len(calls), 30, calls)
        self.assertTrue(all(b == e for b, e in calls), calls)
        # 날짜 범위가 연속(구멍 없음)
        for (b1, e1), (b2, e2) in zip(calls, calls[1:]):
            next_day = (datetime.strptime(e1, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
            self.assertEqual(b2, next_day)
        # 창 초반(오래된 날짜)의 공시가 결과에 포함 — 절단 회귀 방지의 핵심
        self.assertIn("R_OLD", out)

    def test_duplicate_rcept_across_chunks_deduped(self):
        def fake_fetch(api_key, bgn_de, end_de, pblntf_ty="", max_pages=10):
            return [_disc("R_DUP", bgn_de)]

        with patch.object(server, "fetch_market_disclosures", side_effect=fake_fetch):
            out = server.search_market_disclosures("fund_outflow", days=4)
        # 청크마다 같은 rcept가 와도 1건으로 집계
        self.assertEqual(out.count("R_DUP"), 1)

    def test_truncated_chunk_is_reported_honestly(self):
        def fake_fetch(api_key, bgn_de, end_de, pblntf_ty="", max_pages=10):
            # 상한(max_pages*100) 정확히 채운 청크 = 절단 가능
            return [_disc(f"R{bgn_de}{i}", bgn_de, name="일반공시") for i in range(max_pages * 100)]

        with patch.object(server, "fetch_market_disclosures", side_effect=fake_fetch):
            out = server.search_market_disclosures("asset_transfer", days=2)
        self.assertIn("절단", out)

    def test_no_truncation_note_when_under_cap(self):
        def fake_fetch(api_key, bgn_de, end_de, pblntf_ty="", max_pages=10):
            return [_disc(f"R{bgn_de}", bgn_de, name="일반공시")]

        with patch.object(server, "fetch_market_disclosures", side_effect=fake_fetch):
            out = server.search_market_disclosures("asset_transfer", days=2)
        self.assertNotIn("절단", out)


if __name__ == "__main__":
    unittest.main()
