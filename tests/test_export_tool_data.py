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
