# -*- coding: utf-8 -*-
"""backfill_renames 옛 사명 쓰레기 게이트 (2026-08-04 감사 A-4).

공개 corp-aliases 경로는 과잉 캡처 쓰레기("Co., Ltd." 통째 캡처,
"상호변경안내" 문구 캡처 등 실측 5건)를 `is_valid_alias_record`로 거르는데,
private corp_renames 경로(backfill_renames)는 게이트가 없어 쓰레기 옛
사명이 `_legacy_name_index` → `reconcile_corp_renames`의 fold 해석 입력으로
흘러 오병합 가능성이 있었다. 단, 이 경로의 옛 사명은 법인 표기가 남은
원형("한솔시큐어 주식회사")이라 표기 제거(strip_corp_form) 후 검증한다.
"""
import unittest

from scripts.backfill_renames import extract_renames_from_text


class TestOldNameGate(unittest.TestCase):
    def test_garbage_olds_dropped(self):
        txt = (
            "1. 변경 전 국문: HANSOL SECURE Co., Ltd. AND SOMETHING LONG 영문 "
            "변경 후 국문: 새회사 영문 NEW"
        )
        olds, after = extract_renames_from_text(txt)
        self.assertEqual(olds, set())  # 영문 행 통째 캡처 — 게이트가 걸러야 함
        self.assertEqual(after, "새회사")

    def test_notice_phrase_capture_dropped(self):
        txt = "변경 전: 상호변경안내 → 변경 후 국문: 새회사 영문 NEW"
        olds, _ = extract_renames_from_text(txt)
        self.assertEqual(olds, set())

    def test_valid_old_with_corp_suffix_kept(self):
        # 이 경로의 정상 캡처는 법인 표기가 남는다 — 게이트가 이를
        # 쓰레기로 오인해 거르면 안 된다(공개 경로와의 차이점)
        txt = "과거 상호변경 내역 변경 전: 한솔시큐어 주식회사 → 변경 후: 한솔피엔에스"
        olds, _ = extract_renames_from_text(txt, fallback_after="한솔피엔에스")
        self.assertIn("한솔시큐어 주식회사", olds)

    def test_short_english_market_name_kept(self):
        txt = "1. 변경 전 국문: DGP 영문 변경 후 국문: 새회사 영문 NEW"
        olds, _ = extract_renames_from_text(txt)
        self.assertEqual(olds, {"DGP"})


if __name__ == "__main__":
    unittest.main()
