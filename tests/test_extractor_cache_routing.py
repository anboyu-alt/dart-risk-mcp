"""cb_extractor / investor_extractor의 캐시 우회 수정 검증.

두 모듈의 `_fetch_text` / `_fetch_rights_html_text`는 과거 `requests.get`을
직접 호출해 `dart_client._retry`의 선택적 HTTP 캐시 훅을 우회했다. 이 우회는
1) 같은 rcept_no ZIP을 신호 매칭 경로(fetch_disclosure_full)와 인수자 추출
   경로가 각각 따로 받아 2중 다운로드를 유발하고,
2) 429/5xx 지수 백오프 재시도를 못 받아 일시 오류에 바로 빈 문자열을
   반환하는 문제가 있었다.

이 테스트는 `_retry` 경유로 바뀐 뒤 (a) 캐시가 실제로 연결되는지,
(b) 4xx/5xx에서 기존 "빈 문자열 반환, 예외 전파 없음" 동작이 보존되는지,
(c) 캐시 미설정(None) 상태에서도 정상 동작하는지를 확인한다.

캐시는 **이 파일 안의 가짜 구현**을 쓴다. 예전에는 SE(`se_server.http_cache`)
의 것을 빌려 썼는데, SE를 폐기하면서(2026-08-23) 테스트가 그쪽에 묶여 있으면
같이 죽는다. 검증 대상은 어디까지나 **core의 시임**(`set_http_cache`)과
추출기의 `_retry` 경유 여부이므로, 계약(get/put 2메서드)만 만족하는 최소
구현으로 충분하다.
"""

import io
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from dart_risk_mcp.core import cb_extractor, dart_client, investor_extractor


class FakeHttpCache:
    """core가 요구하는 캐시 계약의 최소 구현.

    계약(dart_client 주석): `get(url, params) -> (status, headers, body) | None`
    과 `put(url, params, status, headers, body) -> None`. 키 계산은 주입 측
    책임이고, **params dict를 변형하면 안 된다**.
    """

    def __init__(self):
        self._store: dict = {}

    @staticmethod
    def _key(url, params):
        # crtfc_key(사용자 키)는 키에서 뺀다 — 주입 측 책임(계약).
        safe = {k: v for k, v in (params or {}).items() if k != "crtfc_key"}
        return (url, tuple(sorted(safe.items())))

    def get(self, url, params):
        return self._store.get(self._key(url, params))

    def put(self, url, params, status, headers, body):
        self._store[self._key(url, params)] = (status, headers, body)


def _make_zip_bytes(inner_name: str = "test.xml", content: str = "<XML>테스트 원문 내용</XML>") -> bytes:
    """PK 매직바이트로 시작하는 진짜 인메모리 ZIP 생성 (캐시 저장 조건)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(inner_name, content.encode("utf-8"))
    return buf.getvalue()


def _fake_response(status_code: int, content: bytes = b"") -> MagicMock:
    """requests.Response를 흉내내는 가짜 응답 (실제 네트워크 호출 없음)."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.headers = {"Content-Type": "application/zip"} if status_code == 200 else {}

    def _raise():
        if status_code >= 400:
            raise dart_client.requests.exceptions.HTTPError(f"{status_code} 오류")

    resp.raise_for_status.side_effect = _raise
    return resp


class TestExtractorCacheRouting(unittest.TestCase):
    """cb_extractor / investor_extractor가 _retry(캐시 훅 포함) 경유로 요청하는지 검증."""

    def setUp(self):
        # 테스트마다 알려진 기준 상태(캐시 없음)에서 시작한다.
        dart_client.set_http_cache(None)

    def tearDown(self):
        # 다른 테스트 파일에 영향을 주지 않도록 반드시 원복한다.
        dart_client.set_http_cache(None)

    # ── 1) 캐시 연결 (핵심) ─────────────────────────────────────

    def test_cb_extractor_fetch_text_hits_cache_on_second_call(self):
        dart_client.set_http_cache(FakeHttpCache())
        zip_bytes = _make_zip_bytes()
        mock_request = MagicMock(return_value=_fake_response(200, zip_bytes))

        with patch.object(dart_client.requests, "request", mock_request):
            first = cb_extractor._fetch_text("20260101000001", "testkey")
            second = cb_extractor._fetch_text("20260101000001", "testkey")

        self.assertEqual(mock_request.call_count, 1, "두 번째 호출은 캐시 적중이어야 하며 네트워크를 타면 안 된다")
        self.assertIn("테스트 원문 내용", first)
        self.assertEqual(first, second)

    def test_investor_extractor_fetch_rights_html_text_hits_cache_on_second_call(self):
        dart_client.set_http_cache(FakeHttpCache())
        zip_bytes = _make_zip_bytes()
        mock_request = MagicMock(return_value=_fake_response(200, zip_bytes))

        with patch.object(dart_client.requests, "request", mock_request):
            first = investor_extractor._fetch_rights_html_text("20260101000002", "testkey")
            second = investor_extractor._fetch_rights_html_text("20260101000002", "testkey")

        self.assertEqual(mock_request.call_count, 1, "두 번째 호출은 캐시 적중이어야 하며 네트워크를 타면 안 된다")
        self.assertIn("테스트 원문 내용", first)
        self.assertEqual(first, second)

    # ── 2) 4xx: 예외 없이 빈 문자열 반환 (기존 동작 보존) ────────

    def test_cb_extractor_fetch_text_4xx_returns_empty_without_exception(self):
        mock_request = MagicMock(return_value=_fake_response(404))
        with patch.object(dart_client.requests, "request", mock_request):
            result = cb_extractor._fetch_text("20260101000003", "testkey")
        self.assertEqual(result, "")

    def test_investor_extractor_fetch_rights_html_text_4xx_returns_empty_without_exception(self):
        mock_request = MagicMock(return_value=_fake_response(404))
        with patch.object(dart_client.requests, "request", mock_request):
            result = investor_extractor._fetch_rights_html_text("20260101000004", "testkey")
        self.assertEqual(result, "")

    # ── 3) 5xx 재시도 소진: 예외가 except Exception에 흡수돼 빈 문자열 ──

    def test_cb_extractor_fetch_text_5xx_exhausted_returns_empty(self):
        mock_request = MagicMock(return_value=_fake_response(500))
        with patch.object(dart_client.requests, "request", mock_request), \
             patch.object(dart_client.time, "sleep", MagicMock()):
            result = cb_extractor._fetch_text("20260101000005", "testkey")
        self.assertEqual(result, "")
        self.assertEqual(mock_request.call_count, 3, "429/5xx는 최대 3회까지 재시도해야 한다")

    def test_investor_extractor_fetch_rights_html_text_5xx_exhausted_returns_empty(self):
        mock_request = MagicMock(return_value=_fake_response(500))
        with patch.object(dart_client.requests, "request", mock_request), \
             patch.object(dart_client.time, "sleep", MagicMock()):
            result = investor_extractor._fetch_rights_html_text("20260101000006", "testkey")
        self.assertEqual(result, "")
        self.assertEqual(mock_request.call_count, 3, "429/5xx는 최대 3회까지 재시도해야 한다")

    # ── 4) 캐시 미설정(None) — MCP 서버 기본 상태에서도 정상 동작 ──

    def test_cb_extractor_fetch_text_works_without_cache(self):
        zip_bytes = _make_zip_bytes()
        mock_request = MagicMock(return_value=_fake_response(200, zip_bytes))
        with patch.object(dart_client.requests, "request", mock_request):
            result = cb_extractor._fetch_text("20260101000007", "testkey")
        self.assertIn("테스트 원문 내용", result)
        self.assertEqual(mock_request.call_count, 1)

    def test_investor_extractor_fetch_rights_html_text_works_without_cache(self):
        zip_bytes = _make_zip_bytes()
        mock_request = MagicMock(return_value=_fake_response(200, zip_bytes))
        with patch.object(dart_client.requests, "request", mock_request):
            result = investor_extractor._fetch_rights_html_text("20260101000008", "testkey")
        self.assertIn("테스트 원문 내용", result)
        self.assertEqual(mock_request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
