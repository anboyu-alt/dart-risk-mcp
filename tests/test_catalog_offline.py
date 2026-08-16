"""오프라인 분류 경로 회귀 테스트.

1차는 API, 2차는 세션(서브에이전트)이 담당한다. 세션이 쓴 JSONL은 API 응답보다
형식이 흔들리므로 병합 전 검증이 필수다 — 검증 없이 build_md에 넘기면
taxonomy id 오타 하나로 그 유형의 사례가 조용히 사라진다(이 레포의 '죽은 배선' 8회 전례).
"""
import unittest

from dart_risk_mcp.core.taxonomy import TAXONOMY
from scripts.catalog import export_batches, merge_batches

_SCREENED = [
    {"id": "1", "date": "2024-01-18", "title": "불공정거래 조사결과 조치", "dept": "조사1국",
     "url": "https://x.invalid/1", "keep": True, "category_hint": "7"},
    {"id": "2", "date": "2024-02-01", "title": "선물회사 영업실적", "dept": "금융투자감독국",
     "url": "https://x.invalid/2", "keep": False, "category_hint": ""},
    {"id": "3", "date": "2024-03-05", "title": "공시위반 법인 조치", "dept": "기업공시국",
     "url": "https://x.invalid/3", "keep": True, "category_hint": "4"},
]


class TestBuildBatches(unittest.TestCase):
    def test_only_kept_records_batched(self):
        batches = export_batches.build_batches(_SCREENED, size=10)
        ids = [r["id"] for b in batches for r in b]
        self.assertEqual(ids, ["1", "3"])

    def test_batch_size_respected(self):
        many = [dict(_SCREENED[0], id=str(i)) for i in range(25)]
        batches = export_batches.build_batches(many, size=10)
        self.assertEqual([len(b) for b in batches], [10, 10, 5])

    def test_empty_input(self):
        self.assertEqual(export_batches.build_batches([], size=10), [])


class TestValidateRecord(unittest.TestCase):
    def _ok(self):
        return {"id": "1", "date": "2024-01-18", "title": "T", "url": "u",
                "taxonomy_ids": ["7.1"], "techniques": ["가장납입"], "sanctions": [],
                "laws": ["자본시장법"], "summary": "요약", "confidence": "high",
                "body_source": "pdf"}

    def test_valid_record_passes(self):
        self.assertEqual(merge_batches.validate_record(self._ok(), TAXONOMY, {"1"}), [])

    def test_unknown_taxonomy_id_rejected(self):
        rec = dict(self._ok(), taxonomy_ids=["9.9"])
        errs = merge_batches.validate_record(rec, TAXONOMY, {"1"})
        self.assertTrue(any("9.9" in e for e in errs))

    def test_unknown_id_rejected(self):
        errs = merge_batches.validate_record(self._ok(), TAXONOMY, {"999"})
        self.assertTrue(any("id" in e for e in errs))

    def test_missing_required_field_rejected(self):
        rec = self._ok()
        del rec["summary"]
        self.assertTrue(merge_batches.validate_record(rec, TAXONOMY, {"1"}))

    def test_wrong_type_rejected(self):
        rec = dict(self._ok(), taxonomy_ids="7.1")   # 리스트여야 함
        self.assertTrue(merge_batches.validate_record(rec, TAXONOMY, {"1"}))

    def test_empty_taxonomy_ids_is_valid(self):
        # 미매핑은 오류가 아니라 갭 리포트의 입력이다
        rec = dict(self._ok(), taxonomy_ids=[])
        self.assertEqual(merge_batches.validate_record(rec, TAXONOMY, {"1"}), [])


class TestMerge(unittest.TestCase):
    def test_screened_out_records_carried_through(self):
        # _SCREENED에는 keep=True가 둘(id 1, 3) 있다 — "결과 없음이 오류"
        # 원칙과 충돌하지 않도록 둘 다 결과를 채워 넣고 screened_out 합류만 본다
        # (누락 보고 자체는 test_missing_result_reported가 전담한다).
        results = [
            {"id": "1", "date": "2024-01-18", "title": "T", "url": "u",
             "taxonomy_ids": ["7.1"], "techniques": [], "sanctions": [], "laws": [],
             "summary": "s", "confidence": "high", "body_source": "pdf"},
            {"id": "3", "date": "2024-03-05", "title": "T2", "url": "u2",
             "taxonomy_ids": [], "techniques": [], "sanctions": [], "laws": [],
             "summary": "s2", "confidence": "low", "body_source": "pdf"},
        ]
        merged, errors = merge_batches.merge(results, _SCREENED, TAXONOMY)
        self.assertEqual(errors, [])
        by_id = {r["id"]: r for r in merged}
        self.assertIn("2", by_id)                      # keep=False → screened_out으로 합류
        self.assertTrue(by_id["2"].get("screened_out"))
        self.assertEqual(by_id["1"]["taxonomy_ids"], ["7.1"])

    def test_missing_result_reported(self):
        # keep=True인데 결과가 없는 건은 오류로 보고돼야 한다(조용히 빠지면 안 됨)
        merged, errors = merge_batches.merge([], _SCREENED, TAXONOMY)
        self.assertTrue(any("3" in e for e in errors))

    def test_invalid_record_does_not_reach_output(self):
        bad = [{"id": "1", "taxonomy_ids": ["9.9"]}]
        merged, errors = merge_batches.merge(bad, _SCREENED, TAXONOMY)
        self.assertTrue(errors)
        self.assertNotIn("1", {r["id"] for r in merged if not r.get("screened_out")})


if __name__ == "__main__":
    unittest.main()
