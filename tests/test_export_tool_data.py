"""라이브 리스크 도구용 데이터 codegen(scripts/export_tool_data.py) 검증.

signals.py·taxonomy.py를 유일한 진실로 두고 docs/tool/signals-data.json을
생성한다. 공개 아티팩트에는 내부 점수(score)·패턴 등급(severity)이
포함되면 안 된다 (v0.8.5 무점수 원칙의 공개 데이터 확장).
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from export_tool_data import build_signals_data  # noqa: E402

from dart_risk_mcp.core.signals import (  # noqa: E402
    SIGNAL_TYPES,
    CAPITAL_EVENT_KEYS,
)


class TestBuildSignalsData(unittest.TestCase):
    def setUp(self):
        self.data = build_signals_data()

    def test_all_signal_types_exported(self):
        self.assertEqual(len(self.data["signals"]), len(SIGNAL_TYPES))
        keys = {s["key"] for s in self.data["signals"]}
        self.assertIn("CB_BW", keys)
        self.assertIn("GOING_CONCERN", keys)

    def test_no_internal_score_or_severity(self):
        for s in self.data["signals"]:
            self.assertNotIn("score", s)
        for p in self.data["patterns"]:
            self.assertNotIn("severity", p)
            self.assertNotIn("field_evidence", p)

    def test_signal_fields_and_category(self):
        s = next(x for x in self.data["signals"] if x["key"] == "CB_BW")
        self.assertEqual(s["label"], "CB/BW발행")
        self.assertIn("전환사채", s["keywords"])
        self.assertEqual(s["category"], 1)
        # 카테고리 라벨 맵 (1~8 + 0=기타)
        self.assertEqual(self.data["categories"]["1"], "CB/채권")
        self.assertEqual(self.data["categories"]["8"], "위기/부실")
        # '시장조작'은 단정적 표현이라 공개 라벨은 '시장감시'로 (2026-07 UX 결정)
        self.assertEqual(self.data["categories"]["7"], "시장감시")

    def test_category_uses_heaviest_taxonomy(self):
        # 복수 taxonomy 매핑 신호는 무거운 쪽(높은 카테고리 번호)을 대표로.
        # EMBEZZLE ['5.3','8.1'] → 8(위기/부실), INQUIRY ['4.3','7.1'] → 7(시장조작).
        by_key = {s["key"]: s for s in self.data["signals"]}
        self.assertEqual(by_key["EMBEZZLE"]["category"], 8)
        self.assertEqual(by_key["INQUIRY"]["category"], 7)
        # 패턴 대조용으로 전체 taxonomy 목록도 보존
        self.assertIn("8.1", by_key["EMBEZZLE"]["taxonomies"])
        self.assertIn("5.3", by_key["EMBEZZLE"]["taxonomies"])

    def test_signals_sorted_by_internal_weight(self):
        # 배열 순서 = 내부 우선순위 (숫자 score는 미노출). 헤드라인 선정에 사용.
        scores = {s["key"]: s["score"] for s in SIGNAL_TYPES}
        exported = [s["key"] for s in self.data["signals"]]
        self.assertEqual(exported,
                         sorted(exported, key=lambda k: -scores[k]))

    def test_signal_prose_exported(self):
        by_key = {s["key"]: s for s in self.data["signals"]}
        self.assertIn("횡령", by_key["EMBEZZLE"]["prose"])
        self.assertIn("자사주", by_key["TREASURY"]["prose"])

    def test_fs_aliases_exported(self):
        fa = self.data["fs_aliases"]
        for k in ("매출", "영업이익", "당기순이익", "자본총계", "자본금",
                  "이익잉여금"):
            self.assertIn(k, fa)
            self.assertIsInstance(fa[k], list)
        # 이익잉여금은 결손금 병기 표기도 흡수해야 함
        self.assertIn("이익잉여금(결손금)", fa["이익잉여금"])

    def test_patterns_exported_with_sequence(self):
        p = next(x for x in self.data["patterns"] if x["key"] == "zombie_ma")
        self.assertTrue(p["description"])
        self.assertIsInstance(p["signal_sequence"], list)
        self.assertGreater(p["timeline_months"], 0)

    def test_capital_keys_and_amendment_regex(self):
        self.assertEqual(sorted(self.data["capital_event_keys"]),
                         sorted(CAPITAL_EVENT_KEYS))
        # JS RegExp로 그대로 쓸 수 있는 문자열
        self.assertTrue(self.data["amendment_pattern"].startswith("^"))

    def test_json_serializable(self):
        json.dumps(self.data, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
