"""Phase B 본문 확보 회귀 테스트.

실측 전제(2026-08-16): 금감원 첨부는 fileSn=1이 구형 HWP(OLE, D0CF11E0),
fileSn=2가 PDF다. HWP는 ZIP이 아니라 표준 라이브러리로 파싱할 수 없으므로
본문 확보는 PDF(optional pypdf) 또는 게시판 페이지 요약에 의존한다.
"""
import unittest
from pathlib import Path
from unittest import mock

from scripts.catalog import extract

_FIXTURE = Path(__file__).parent / "fixtures" / "catalog" / "fss_view_page.html"


class TestParsePage(unittest.TestCase):
    def setUp(self):
        self.html = _FIXTURE.read_text(encoding="utf-8")

    def test_body_text_extracted(self):
        body = extract.parse_page_body(self.html)
        self.assertIn("신규사업 진출을 공시했으나", body)
        self.assertIn("불공정거래 혐의로 조사", body)

    def test_body_excludes_nav_and_footer(self):
        body = extract.parse_page_body(self.html)
        self.assertNotIn("이전글", body)
        self.assertNotIn("다음글", body)

    def test_attachment_urls_by_filesn(self):
        urls = extract.parse_attachment_urls(self.html)
        self.assertTrue(urls["hwp"].endswith("fileSn=1&bbsId="))
        self.assertTrue(urls["pdf"].endswith("fileSn=2&bbsId="))
        self.assertTrue(urls["pdf"].startswith("https://www.fss.or.kr/"))

    def test_amp_entities_decoded(self):
        urls = extract.parse_attachment_urls(self.html)
        self.assertNotIn("&amp;", urls["pdf"])


class TestDecodePage(unittest.TestCase):
    """디코딩 헬퍼 회귀 테스트 (fix round 1 — 오염된 본문의 조용한 통과 방지)."""

    def test_utf8_bytes_decoded_trusted(self):
        raw = "정상 utf-8 텍스트".encode("utf-8")
        text, trusted = extract.decode_page(raw)
        self.assertEqual(text, "정상 utf-8 텍스트")
        self.assertTrue(trusted)

    def test_euckr_bytes_decoded_trusted(self):
        raw = "금융감독원 불공정거래 조사".encode("euc-kr")
        text, trusted = extract.decode_page(raw)
        self.assertEqual(text, "금융감독원 불공정거래 조사")
        self.assertTrue(trusted)

    def test_undecodable_bytes_marked_untrusted(self):
        raw = b"\xff\xfe\xff\xfe" * 50
        text, trusted = extract.decode_page(raw)
        self.assertFalse(trusted)

    def test_low_replacement_ratio_stays_trusted(self):
        # 선두 1바이트만 세 인코딩 모두에서 깨지고 나머지는 멀쩡한 긴 본문
        raw = b"\x80" + ("정상 텍스트 " * 50).encode("utf-8")
        text, trusted = extract.decode_page(raw)
        self.assertTrue(trusted)
        self.assertLessEqual(text.count("�") / len(text), 0.01)


class TestExtractLight(unittest.TestCase):
    def test_uses_page_body_when_available(self):
        html = _FIXTURE.read_text(encoding="utf-8")
        rec = {"url": "https://www.fss.or.kr/x", "title": "제목", "summary": "요약"}
        got = extract.extract_light(rec, fetch=lambda u: html.encode("utf-8"))
        self.assertEqual(got["body_source"], "page")
        self.assertIn("신규사업", got["body"])
        self.assertEqual(got["body_chars"], len(got["body"]))

    def test_falls_back_to_title_when_fetch_fails(self):
        rec = {"url": "https://www.fss.or.kr/x", "title": "제목", "summary": "요약본문"}
        def boom(url):
            raise OSError("network down")
        got = extract.extract_light(rec, fetch=boom)
        self.assertEqual(got["body_source"], "title_only")
        self.assertIn("제목", got["body"])
        self.assertIn("요약본문", got["body"])

    def test_no_url_falls_back_without_fetch(self):
        rec = {"url": "", "title": "제목", "summary": "요약"}
        got = extract.extract_light(rec, fetch=lambda u: b"")
        self.assertEqual(got["body_source"], "title_only")

    def test_falls_back_to_title_on_undecodable_page(self):
        rec = {"url": "https://www.fss.or.kr/x", "title": "제목", "summary": "요약본문"}
        garbage = b"\xff\xfe\xff\xfe" * 50
        got = extract.extract_light(rec, fetch=lambda u: garbage)
        self.assertEqual(got["body_source"], "title_only")
        self.assertIn("제목", got["body"])
        self.assertIn("요약본문", got["body"])
        self.assertNotIn("attachment_urls", got)

    def test_extracts_body_from_euckr_encoded_page(self):
        html = _FIXTURE.read_text(encoding="utf-8")
        rec = {"url": "https://www.fss.or.kr/x", "title": "제목", "summary": "요약"}
        got = extract.extract_light(rec, fetch=lambda u: html.encode("euc-kr"))
        self.assertEqual(got["body_source"], "page")
        self.assertIn("신규사업", got["body"])


class TestExtractFull(unittest.TestCase):
    def test_returns_none_when_pypdf_missing(self):
        rec = {"url": "https://www.fss.or.kr/x",
               "attachment_urls": {"pdf": "https://www.fss.or.kr/p.pdf"}}
        with mock.patch.object(extract, "PYPDF_AVAILABLE", False):
            self.assertIsNone(extract.extract_full(rec, fetch=lambda u: b"%PDF-1.4"))

    def test_returns_none_on_fetch_failure(self):
        rec = {"attachment_urls": {"pdf": "https://www.fss.or.kr/p.pdf"}}
        def boom(url):
            raise OSError("timeout")
        self.assertIsNone(extract.extract_full(rec, fetch=boom))

    def test_returns_none_without_pdf_url(self):
        self.assertIsNone(extract.extract_full({}, fetch=lambda u: b""))


if __name__ == "__main__":
    unittest.main()
