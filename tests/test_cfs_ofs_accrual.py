"""연결/별도 순이익 괴리(CFS_OFS_REVERSAL) + 발생액 비율 테스트 (PR-2, kreports 재설계 이식)."""
import unittest

from dart_risk_mcp.core.dart_client import (
    detect_financial_anomaly,
    extract_cfs_ofs_ni,
    _parse_fs_amount,
)
from dart_risk_mcp.core.explain import flag_to_prose


def _metric(metrics, name):
    for m in metrics:
        if m["name"] == name:
            return m
    return None


class TestAccrualRatio(unittest.TestCase):
    def test_accrual_ratio_metric_present(self):
        cur = {"당기순이익": 100, "영업활동현금흐름": 40}
        pri = {"당기순이익": 100, "영업활동현금흐름": 90}
        flags, metrics = detect_financial_anomaly(cur, pri)
        m = _metric(metrics, "발생액 비율")
        self.assertIsNotNone(m)
        self.assertAlmostEqual(m["current"], 60.0)  # (100-40)/100
        self.assertAlmostEqual(m["prior"], 10.0)    # (100-90)/100
        self.assertAlmostEqual(m["delta"], 50.0)

    def test_accrual_ratio_never_flags(self):
        # 사실 표기 전용 — 아무리 커도 flag 없음 (v0.8.5 원칙)
        cur = {"당기순이익": 100, "영업활동현금흐름": -500}
        flags, metrics = detect_financial_anomaly(cur, {})
        m = _metric(metrics, "발생액 비율")
        self.assertIsNotNone(m)
        self.assertFalse(m["flagged"])
        self.assertNotIn("ACCRUAL", " ".join(flags))

    def test_accrual_skipped_when_ni_zero_or_missing(self):
        flags, metrics = detect_financial_anomaly({"당기순이익": 0, "영업활동현금흐름": 10}, {})
        self.assertIsNone(_metric(metrics, "발생액 비율"))
        flags, metrics = detect_financial_anomaly({"영업활동현금흐름": 10}, {})
        self.assertIsNone(_metric(metrics, "발생액 비율"))

    def test_prior_optional(self):
        cur = {"당기순이익": 100, "영업활동현금흐름": 40}
        _, metrics = detect_financial_anomaly(cur, {})
        m = _metric(metrics, "발생액 비율")
        self.assertIsNotNone(m)
        self.assertNotIn("prior", m)


class TestCfsOfsReversal(unittest.TestCase):
    def test_no_args_no_metric(self):
        # 하위 호환: 인자 미전달 시 종전과 동일 (metric·flag 모두 없음)
        flags, metrics = detect_financial_anomaly({}, {})
        self.assertIsNone(_metric(metrics, "연결/별도 당기순이익"))
        self.assertNotIn("CFS_OFS_REVERSAL", flags)

    def test_normal_large_cap_not_flagged(self):
        # 라이브 검증 사례: 삼성전자 연결 34.45조 > 별도 23.58조 — 정상, 플래그 없음
        flags, metrics = detect_financial_anomaly(
            {}, {}, cfs_ni=34_451_351_000_000, ofs_ni=23_582_565_000_000)
        m = _metric(metrics, "연결/별도 당기순이익")
        self.assertIsNotNone(m)
        self.assertFalse(m["flagged"])
        self.assertNotIn("CFS_OFS_REVERSAL", flags)

    def test_reversal_flagged(self):
        # 별도 100 > 연결 50 — 종속회사 합산 손실 → 플래그
        flags, metrics = detect_financial_anomaly({}, {}, cfs_ni=50, ofs_ni=100)
        m = _metric(metrics, "연결/별도 당기순이익")
        self.assertTrue(m["flagged"])
        self.assertIn("CFS_OFS_REVERSAL", flags)

    def test_small_reversal_not_flagged(self):
        # 격차 10% 미만이면 노이즈로 보고 플래그 없음
        flags, _ = detect_financial_anomaly({}, {}, cfs_ni=95, ofs_ni=100)
        self.assertNotIn("CFS_OFS_REVERSAL", flags)

    def test_reversal_with_negative_cfs(self):
        # 별도 흑자인데 연결 적자 — 가장 뚜렷한 역전
        flags, _ = detect_financial_anomaly({}, {}, cfs_ni=-30, ofs_ni=100)
        self.assertIn("CFS_OFS_REVERSAL", flags)

    def test_ofs_zero_no_crash(self):
        flags, metrics = detect_financial_anomaly({}, {}, cfs_ni=50, ofs_ni=0)
        m = _metric(metrics, "연결/별도 당기순이익")
        self.assertIsNotNone(m)
        self.assertIsNone(m["gap_pct"])

    def test_prose_exists(self):
        title, body = flag_to_prose(
            "CFS_OFS_REVERSAL", {"current_cfs": 50, "current_ofs": 100})
        self.assertIn("연결", title)
        self.assertIn("50", body)
        self.assertIn("100", body)


class TestExtractCfsOfsNi(unittest.TestCase):
    ROWS = [
        {"fs_div": "CFS", "account_nm": "자산총계", "thstrm_amount": "999"},
        {"fs_div": "CFS", "account_nm": "당기순이익(손실)", "thstrm_amount": "34,451,351,000,000"},
        {"fs_div": "CFS", "account_nm": "당기순이익(손실)", "thstrm_amount": "1"},  # 중복 행은 첫 값 유지
        {"fs_div": "OFS", "account_nm": "당기순이익(손실)", "thstrm_amount": "23,582,565,000,000"},
    ]

    def test_extract_pair(self):
        cfs, ofs = extract_cfs_ofs_ni(self.ROWS)
        self.assertEqual(cfs, 34_451_351_000_000)
        self.assertEqual(ofs, 23_582_565_000_000)

    def test_missing_cfs(self):
        cfs, ofs = extract_cfs_ofs_ni([r for r in self.ROWS if r["fs_div"] == "OFS"])
        self.assertIsNone(cfs)
        self.assertEqual(ofs, 23_582_565_000_000)

    def test_empty_and_none(self):
        self.assertEqual(extract_cfs_ofs_ni([]), (None, None))
        self.assertEqual(extract_cfs_ofs_ni(None), (None, None))

    def test_non_ni_accounts_ignored(self):
        rows = [{"fs_div": "CFS", "account_nm": "지배기업 소유주 귀속 당기순이익부속명세",
                 "thstrm_amount": "7"}]
        self.assertEqual(extract_cfs_ofs_ni(rows), (None, None))


class TestParseFsAmount(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(_parse_fs_amount("12,345"), 12345)
        self.assertEqual(_parse_fs_amount("(500)"), -500)
        self.assertIsNone(_parse_fs_amount("-"))
        self.assertIsNone(_parse_fs_amount(None))
        self.assertIsNone(_parse_fs_amount("null"))
        self.assertEqual(_parse_fs_amount("1.0"), 1)


class TestBackwardCompat(unittest.TestCase):
    def test_two_arg_call_flags_unchanged(self):
        # 기존 호출부(server.py:380,1061)와 동일한 2-인자 호출 —
        # 새 플래그(CFS_OFS_REVERSAL)가 절대 나오지 않아야 _v6_labels KeyError 없음
        cur = {"매출액": 100, "매출채권": 90, "재고자산": 80,
               "당기순이익": 10, "영업활동현금흐름": -5,
               "자본총계": 50, "자본금": 100}
        pri = {"매출액": 100, "매출채권": 10, "재고자산": 10}
        flags, _ = detect_financial_anomaly(cur, pri)
        self.assertNotIn("CFS_OFS_REVERSAL", flags)
        for f in flags:
            self.assertIn(f, ("AR_SURGE", "INVENTORY_SURGE", "CASH_GAP", "CAPITAL_IMPAIRMENT"))


if __name__ == "__main__":
    unittest.main()
