"""Phase C 분류 회귀 테스트. LLM은 호출하지 않고 프롬프트 구성·응답 파싱만 검증."""
import json
import unittest
from unittest.mock import MagicMock, patch

import requests as requests_lib

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


def _fake_response(status_code: int, text: str = "ok", headers: dict | None = None) -> MagicMock:
    """call_anthropic이 쓰는 requests.Response 표면(status_code/headers/json/
    raise_for_status)만 흉내 낸 더블. 실제 네트워크 호출 없음."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests_lib.HTTPError(f"{status_code}")
    else:
        resp.raise_for_status.return_value = None
    resp.json.return_value = {"content": [{"type": "text", "text": text}]}
    return resp


class TestCallAnthropicRetry(unittest.TestCase):
    """call_anthropic의 429/5xx 재시도·백오프·페이싱을 검증한다.
    requests.post와 time.sleep을 patch해 실제 네트워크·대기 없이 돈다."""

    @patch("scripts.catalog.classify.time.sleep")
    @patch("scripts.catalog.classify.requests.post")
    def test_200_succeeds_without_retry(self, mock_post, mock_sleep):
        mock_post.return_value = _fake_response(200, text="hello")
        got = classify.call_anthropic("sys", "user", "key")
        self.assertEqual(got, "hello")
        self.assertEqual(mock_post.call_count, 1)

    @patch("scripts.catalog.classify.time.sleep")
    @patch("scripts.catalog.classify.requests.post")
    def test_429_then_200_retries_and_succeeds(self, mock_post, mock_sleep):
        mock_post.side_effect = [_fake_response(429), _fake_response(200, text="ok")]
        got = classify.call_anthropic("sys", "user", "key")
        self.assertEqual(got, "ok")
        self.assertEqual(mock_post.call_count, 2)

    @patch("scripts.catalog.classify.time.sleep")
    @patch("scripts.catalog.classify.requests.post")
    def test_persistent_429_raises_after_max_retries(self, mock_post, mock_sleep):
        mock_post.return_value = _fake_response(429)
        with self.assertRaises(requests_lib.HTTPError):
            classify.call_anthropic("sys", "user", "key")
        # 초기 시도 1회 + 재시도 _MAX_RETRIES회 = 상한
        self.assertEqual(mock_post.call_count, classify._MAX_RETRIES + 1)

    @patch("scripts.catalog.classify.time.sleep")
    @patch("scripts.catalog.classify.requests.post")
    def test_5xx_follows_same_retry_path_as_429(self, mock_post, mock_sleep):
        mock_post.side_effect = [_fake_response(503), _fake_response(200, text="ok")]
        got = classify.call_anthropic("sys", "user", "key")
        self.assertEqual(got, "ok")
        self.assertEqual(mock_post.call_count, 2)

    @patch("scripts.catalog.classify.time.sleep")
    @patch("scripts.catalog.classify.requests.post")
    def test_retry_after_header_overrides_backoff(self, mock_post, mock_sleep):
        mock_post.side_effect = [
            _fake_response(429, headers={"Retry-After": "2"}),
            _fake_response(200, text="ok"),
        ]
        classify.call_anthropic("sys", "user", "key")
        waited = [c.args[0] for c in mock_sleep.call_args_list if c.args]
        self.assertIn(2.0, waited)

    @patch("scripts.catalog.classify.time.sleep")
    @patch("scripts.catalog.classify.requests.post")
    def test_400_is_not_retried(self, mock_post, mock_sleep):
        mock_post.return_value = _fake_response(400)
        with self.assertRaises(requests_lib.HTTPError):
            classify.call_anthropic("sys", "user", "key")
        self.assertEqual(mock_post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
