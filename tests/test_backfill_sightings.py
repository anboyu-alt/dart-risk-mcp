import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


def _dt(s):
    return datetime.strptime(s, "%Y-%m-%d")


class TestMakeChunks(unittest.TestCase):
    def test_splits_range_into_chunks(self):
        import scripts.backfill_sightings as bs
        chunks = bs.make_chunks(_dt("2026-06-01"), _dt("2026-06-20"), 7)
        self.assertEqual(
            [(c[0].strftime("%m-%d"), c[1].strftime("%m-%d")) for c in chunks],
            [("06-01", "06-07"), ("06-08", "06-14"), ("06-15", "06-20")])

    def test_single_day_range(self):
        import scripts.backfill_sightings as bs
        chunks = bs.make_chunks(_dt("2026-06-01"), _dt("2026-06-01"), 7)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0][0], chunks[0][1])


class TestRunBackfill(unittest.TestCase):
    def _run(self, tmp, collect_side_effect, start, end, max_funding=9999,
             initial=None):
        import scripts.backfill_sightings as bs
        path = Path(tmp) / "sightings.json"
        if initial is not None:
            path.write_text(json.dumps(initial, ensure_ascii=False), encoding="utf-8")
        with patch.object(bs, "collect_funding_sightings_range",
                          side_effect=collect_side_effect) as mock_collect, \
             patch.object(bs.time, "sleep"):
            summary = bs.run_backfill("key", path, _dt(start), _dt(end),
                                      chunk_days=7, max_funding=max_funding)
        return summary, path, mock_collect

    @staticmethod
    def _stats(funding=1, extracted=0, scanned=10, truncated=False):
        return {"scanned": scanned, "funding": funding,
                "extracted": extracted, "truncated": truncated}

    def test_collects_all_chunks_and_saves_progress(self):
        calls = []

        def _collect(key, bgn, end, **kw):
            calls.append((bgn, end))
            return ([{"name": "홍길동", "corp": "A", "corp_code": f"c{len(calls)}",
                      "rcept_no": f"R{len(calls)}", "date": bgn[:4] + "-" + bgn[4:6],
                      "signals": ["CB_BW"]}],
                    self._stats(funding=2, extracted=1))

        with tempfile.TemporaryDirectory() as tmp:
            summary, path, _ = self._run(tmp, _collect, "2026-06-01", "2026-06-14")
            self.assertEqual(len(calls), 2)                     # 7일 청크 2개
            self.assertEqual(calls[0], ("20260601", "20260607"))  # 과거 → 최신
            self.assertTrue(summary["finished"])
            self.assertEqual(summary["funding"], 4)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["backfill"]["done_until"], "20260614")
            # 두 청크의 sighting이 같은 이름으로 병합됨
            self.assertEqual(len(data["sightings"]["홍길동"]), 2)

    def test_resume_skips_completed_chunks(self):
        calls = []

        def _collect(key, bgn, end, **kw):
            calls.append((bgn, end))
            return ([], self._stats(funding=0))

        initial = {"version": 1, "sightings": {},
                   "backfill": {"done_until": "20260607"}}
        with tempfile.TemporaryDirectory() as tmp:
            summary, _, _ = self._run(tmp, _collect, "2026-06-01", "2026-06-14",
                                      initial=initial)
        self.assertEqual(calls, [("20260608", "20260614")])  # 첫 청크 스킵
        self.assertTrue(summary["finished"])

    def test_budget_stops_and_preserves_progress(self):
        def _collect(key, bgn, end, **kw):
            return ([], self._stats(funding=100))

        with tempfile.TemporaryDirectory() as tmp:
            summary, path, mock_collect = self._run(
                tmp, _collect, "2026-06-01", "2026-06-28", max_funding=150)
        # 청크1(100건) 후 누적 100 < 150 → 청크2 실행(200) → 청크3 진입 전 중단
        self.assertEqual(mock_collect.call_count, 2)
        self.assertFalse(summary["finished"])
        self.assertEqual(summary["done_until"], "20260614")

    def test_zero_scan_chunk_not_marked_done(self):
        # API 장애·쿼터 소진으로 공시 0건이 오면 그 청크를 완료로 마킹하지 않고
        # 중단해야 한다 — 조용한 데이터 구멍 방지 (다음 실행이 재시도)
        calls = []

        def _collect(key, bgn, end, **kw):
            calls.append(bgn)
            return ([], self._stats(funding=0, scanned=0))

        with tempfile.TemporaryDirectory() as tmp:
            summary, path, _ = self._run(tmp, _collect, "2026-06-01", "2026-06-14")
        self.assertEqual(len(calls), 1)               # 첫 청크에서 즉시 중단
        self.assertFalse(summary["finished"])
        self.assertEqual(summary["done_until"], "")   # 완료 마킹 없음
        self.assertIn("2026-06-01", summary["zero_scan"])

    def test_zero_scan_guard_skipped_for_short_chunks(self):
        # 1~2일 청크는 주말·휴일로 정당하게 0건일 수 있어 가드를 적용하지 않는다
        import scripts.backfill_sightings as bs
        calls = []

        def _collect(key, bgn, end, **kw):
            calls.append(bgn)
            return ([], self._stats(funding=0, scanned=0))

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sightings.json"
            with patch.object(bs, "collect_funding_sightings_range",
                              side_effect=_collect), \
                 patch.object(bs.time, "sleep"):
                summary = bs.run_backfill("key", path, _dt("2026-06-06"),
                                          _dt("2026-06-07"), chunk_days=1)
        self.assertEqual(len(calls), 2)               # 두 청크 모두 진행
        self.assertTrue(summary["finished"])
        self.assertEqual(summary["done_until"], "20260607")

    def test_summary_counts_multi_corp_names(self):
        def _collect(key, bgn, end, **kw):
            return ([{"name": "홍길동", "corp": "A", "corp_code": "c1",
                      "rcept_no": "R1", "date": "2026-06", "signals": []},
                     {"name": "홍길동", "corp": "B", "corp_code": "c2",
                      "rcept_no": "R2", "date": "2026-06", "signals": []},
                     {"name": "외톨이", "corp": "A", "corp_code": "c1",
                      "rcept_no": "R3", "date": "2026-06", "signals": []}],
                    self._stats(funding=3, extracted=3))

        with tempfile.TemporaryDirectory() as tmp:
            summary, _, _ = self._run(tmp, _collect, "2026-06-01", "2026-06-07")
        self.assertEqual(summary["names_total"], 2)
        self.assertEqual(summary["names_multi"], 1)  # 홍길동만 2개사+


class TestShouldSendReport(unittest.TestCase):
    def test_sends_when_work_done_or_unfinished(self):
        import scripts.backfill_sightings as bs
        self.assertTrue(bs.should_send_report({"done_chunks": 3, "finished": True}))
        self.assertTrue(bs.should_send_report({"done_chunks": 0, "finished": False}))

    def test_skips_noop_rerun_after_completion(self):
        # 완료 후 스케줄 잔여 발화 → 조용히 종료 (메일 스팸 방지)
        import scripts.backfill_sightings as bs
        self.assertFalse(bs.should_send_report({"done_chunks": 0, "finished": True}))


class TestBackfillReport(unittest.TestCase):
    def test_report_shows_progress_and_warnings(self):
        import scripts.backfill_sightings as bs
        summary = {"done_chunks": 3, "done_until": "20260614", "funding": 120,
                   "extracted": 45, "names_total": 40, "names_multi": 4,
                   "truncated_chunks": ["2026-06-08"], "finished": False}
        r = bs.build_backfill_report(summary, _dt("2026-06-01"), _dt("2026-06-28"))
        self.assertIn("자금조달 공시 120건", r)
        self.assertIn("미완", r)
        self.assertIn("2개사+ 등장 4명", r)
        self.assertIn("목록 상한 도달 청크: 2026-06-08", r)

    def test_report_marks_completion(self):
        import scripts.backfill_sightings as bs
        summary = {"done_chunks": 5, "done_until": "20260628", "funding": 200,
                   "extracted": 80, "names_total": 60, "names_multi": 7,
                   "truncated_chunks": [], "finished": True}
        r = bs.build_backfill_report(summary, _dt("2026-06-01"), _dt("2026-06-28"))
        self.assertIn("전 구간 완료", r)
        self.assertNotIn("목록 상한", r)


if __name__ == "__main__":
    unittest.main()
