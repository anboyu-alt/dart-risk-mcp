"""Phase C 분류 회귀 테스트. LLM은 호출하지 않고 프롬프트 구성·응답 파싱만 검증."""
import json
import unittest

from dart_risk_mcp.core.taxonomy import TAXONOMY
from scripts.catalog import classify


class TestPrompt(unittest.TestCase):
    def test_includes_all_45_taxonomy_ids(self):
        prompt = classify.build_taxonomy_prompt(TAXONOMY)
        for tid in TAXONOMY:
            self.assertIn(tid, prompt, f"{tid} 누락")

    def test_includes_new_eight_types(self):
        prompt = classify.build_taxonomy_prompt(TAXONOMY)
        for tid in ("2.7", "2.8", "3.6", "3.7", "5.6", "5.7", "5.8", "8.5"):
            self.assertIn(tid, prompt)

    def test_instructs_empty_list_when_unmapped(self):
        prompt = classify.build_taxonomy_prompt(TAXONOMY)
        self.assertIn("빈 배열", prompt)


class TestParseScreen(unittest.TestCase):
    def test_parses_keep_true(self):
        got = classify.parse_screen_response('{"keep": true, "category_hint": "1"}')
        self.assertTrue(got["keep"])
        self.assertEqual(got["category_hint"], "1")

    def test_parses_keep_false(self):
        self.assertFalse(classify.parse_screen_response('{"keep": false}')["keep"])

    def test_tolerates_code_fence(self):
        got = classify.parse_screen_response('```json\n{"keep": true}\n```')
        self.assertTrue(got["keep"])

    def test_malformed_defaults_to_keep_false(self):
        self.assertFalse(classify.parse_screen_response("설명만 있고 JSON 없음")["keep"])


class TestParseClassify(unittest.TestCase):
    _GOOD = json.dumps({
        "taxonomy_ids": ["1.1", "9.9"],
        "techniques": ["리픽싱 남용"],
        "sanctions": ["과징금"],
        "laws": ["자본시장법"],
        "summary": "요약",
        "confidence": "high",
    }, ensure_ascii=False)

    def test_drops_unknown_taxonomy_ids(self):
        got = classify.parse_classify_response(self._GOOD)
        self.assertEqual(got["taxonomy_ids"], ["1.1"])  # 9.9는 존재하지 않음

    def test_keeps_list_fields(self):
        got = classify.parse_classify_response(self._GOOD)
        self.assertEqual(got["techniques"], ["리픽싱 남용"])
        self.assertEqual(got["confidence"], "high")

    def test_unmapped_returns_empty_ids(self):
        got = classify.parse_classify_response('{"taxonomy_ids": [], "summary": "신종 수법"}')
        self.assertEqual(got["taxonomy_ids"], [])
        self.assertEqual(got["summary"], "신종 수법")

    def test_malformed_yields_empty_record(self):
        got = classify.parse_classify_response("JSON 아님")
        self.assertEqual(got["taxonomy_ids"], [])
        self.assertEqual(got["confidence"], "low")


if __name__ == "__main__":
    unittest.main()
