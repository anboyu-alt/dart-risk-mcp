"""ZIP 안전 가드(_is_zip_safe) — ZIP bomb 방어 검증.

DART document.xml ZIP은 인메모리로만 읽으므로 Zip Slip(경로 탈출)은 위협이
아니고, 압축해제 크기 폭탄(ZIP bomb)만 방어한다: 엔트리 수·개별 엔트리
크기·총 압축해제 크기 3중 상한.
"""
import io
import unittest
import zipfile
from unittest.mock import MagicMock, patch

from dart_risk_mcp.core import dart_client


def _make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestIsZipSafe(unittest.TestCase):
    def test_normal_zip_is_safe(self):
        zf = zipfile.ZipFile(io.BytesIO(_make_zip({"doc.xml": b"<x/>"})))
        self.assertTrue(dart_client._is_zip_safe(zf))

    def test_too_many_entries_rejected(self):
        raw = _make_zip({f"f{i}.txt": b"x" for i in range(11)})
        zf = zipfile.ZipFile(io.BytesIO(raw))
        self.assertFalse(dart_client._is_zip_safe(zf, max_entries=10))

    def test_oversized_entry_rejected(self):
        raw = _make_zip({"big.xml": b"0" * 2048})
        zf = zipfile.ZipFile(io.BytesIO(raw))
        self.assertFalse(dart_client._is_zip_safe(zf, max_entry_size=1024))

    def test_total_uncompressed_size_rejected(self):
        # 개별 엔트리는 상한 이하지만 합계가 상한 초과
        raw = _make_zip({"a.xml": b"0" * 600, "b.xml": b"0" * 600})
        zf = zipfile.ZipFile(io.BytesIO(raw))
        self.assertFalse(
            dart_client._is_zip_safe(zf, max_entry_size=1024, max_total_size=1000)
        )


class TestFetchDocumentZipGuard(unittest.TestCase):
    def setUp(self):
        dart_client._zip_cache.clear()

    @staticmethod
    def _mock_resp(raw: bytes):
        resp = MagicMock()
        resp.status_code = 200
        resp.headers = {"Content-Type": "application/zip"}
        resp.content = raw
        return resp

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_unsafe_zip_returns_none_and_not_cached(self, mock_retry):
        raw = _make_zip({f"f{i}.xml": b"x" for i in range(5)})
        mock_retry.return_value = self._mock_resp(raw)
        with patch.object(dart_client, "_ZIP_MAX_ENTRIES", 3):
            self.assertIsNone(dart_client._fetch_document_zip("20260101000001", "KEY"))
        self.assertNotIn("20260101000001", dart_client._zip_cache)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_safe_zip_passes_and_cached(self, mock_retry):
        raw = _make_zip({"doc.xml": b"<x/>"})
        mock_retry.return_value = self._mock_resp(raw)
        zf = dart_client._fetch_document_zip("20260101000002", "KEY")
        self.assertIsNotNone(zf)
        self.assertIn("20260101000002", dart_client._zip_cache)


if __name__ == "__main__":
    unittest.main()
