"""Phase B 본문 확보 회귀 테스트.

실측 전제(2026-08-16 후속): fileSn 번호와 첨부 종류의 대응은 연도별로
뒤집힌다(2011~2019년 1=PDF/2=HWP, 2023~2026년 1=HWP/2=PDF) — 번호로 종류를
추정할 수 없다. `parse_attachment_urls`는 모든 첨부 URL을 fileSn 순으로만
반환하고, 실제 종류 판별은 `extract_full`이 매직바이트로 한다. HWP는 ZIP이
아니라 표준 라이브러리로 파싱할 수 없으므로 본문 확보는 PDF(optional
pypdf) 또는 게시판 페이지 요약에 의존한다.
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

    def test_attachment_urls_ordered_by_filesn(self):
        urls = extract.parse_attachment_urls(self.html)
        self.assertEqual(len(urls), 2)
        self.assertTrue(urls[0].endswith("fileSn=1&bbsId="))
        self.assertTrue(urls[1].endswith("fileSn=2&bbsId="))
        self.assertTrue(urls[0].startswith("https://www.fss.or.kr/"))

    def test_amp_entities_decoded(self):
        urls = extract.parse_attachment_urls(self.html)
        for u in urls:
            self.assertNotIn("&amp;", u)


class TestFileSnMultiDigit(unittest.TestCase):
    """fileSn 두 자리 이상(첨부 10개 이상) 정렬 회귀 테스트.

    예전 정규식(`fileSn=(\\d)`)은 fileSn을 한 자리만 캡처해 fileSn=10이 "1"로
    잘리는 버그가 있었다(2026-08-17 전체 브랜치 리뷰에서 발견, `fileSn=(\\d+)`로
    수정됨). 지금은 번호로 종류를 추정하지 않고 fileSn 오름차순 정렬만 하므로,
    이 정렬이 문자열이 아니라 숫자 비교여야 한다는 것이 이 테스트의 핵심이다
    (문자열 정렬이면 "10"이 "2"보다 앞에 온다).
    """

    def test_regex_captures_full_multidigit_number(self):
        matches = extract._FILE_LINK.findall(
            '<a href="/x/fileDown.do?fileSn=10&bbsId=">a</a>'
        )
        self.assertEqual(matches[0][1], "10")

    def test_two_digit_filesn_sorted_numerically_not_lexically(self):
        html = (
            '<a href="/fss/cmmn/file/fileDown.do?menuNo=200218&amp;atchFileId=X'
            '&amp;fileSn=10&amp;bbsId=">첨부10</a>'
            '<a href="/fss/cmmn/file/fileDown.do?menuNo=200218&amp;atchFileId=X'
            '&amp;fileSn=2&amp;bbsId=">보도자료.pdf</a>'
        )
        urls = extract.parse_attachment_urls(html)
        self.assertEqual(len(urls), 2)
        self.assertTrue(urls[0].endswith("fileSn=2&bbsId="))
        self.assertTrue(urls[1].endswith("fileSn=10&bbsId="))

    def test_all_attachments_returned_regardless_of_filesn_value(self):
        html = (
            '<a href="/fss/cmmn/file/fileDown.do?menuNo=200218&amp;atchFileId=X'
            '&amp;fileSn=1&amp;bbsId=">보도자료.hwp</a>'
            '<a href="/fss/cmmn/file/fileDown.do?menuNo=200218&amp;atchFileId=X'
            '&amp;fileSn=10&amp;bbsId=">첨부10</a>'
        )
        urls = extract.parse_attachment_urls(html)
        self.assertEqual(len(urls), 2)
        self.assertTrue(urls[0].endswith("fileSn=1&bbsId="))
        self.assertTrue(urls[1].endswith("fileSn=10&bbsId="))


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


class _StubPage:
    """pypdf Page 스텁: 생성 시 받은 텍스트를 그대로 extract_text()로 돌려준다."""

    def __init__(self, text: str):
        self._text = text

    def extract_text(self):
        return self._text


class _StubPDFReader:
    """pypdf PdfReader 스텁.

    테스트 fetch가 돌려주는 바이트는 `b"%PDF" + 실제텍스트.encode()` 형태라고
    약속한다 — 매직바이트 뒤를 그대로 "추출된 텍스트"로 되돌려줘서, 실제 PDF
    바이너리를 만들지 않고도 extract_full의 선택 로직(가장 긴 텍스트 선택,
    50자 미만 실패)을 검증할 수 있게 한다.
    """

    def __init__(self, buf):
        data = buf.read()
        text = data[4:].decode("utf-8", errors="ignore")
        self.pages = [_StubPage(text)]


class TestExtractFull(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(extract, "PdfReader", _StubPDFReader)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleep_patcher = mock.patch.object(extract.time, "sleep")
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)

    def test_returns_none_when_pypdf_missing(self):
        rec = {"attachment_urls": ["https://www.fss.or.kr/p.pdf"]}
        calls = []

        def fetch(u):
            calls.append(u)
            return b"%PDF" + ("긴 본문 텍스트입니다 " * 10).encode()

        with mock.patch.object(extract, "PYPDF_AVAILABLE", False):
            self.assertIsNone(extract.extract_full(rec, fetch=fetch))
        self.assertEqual(calls, [], "pypdf 미설치면 다운로드조차 하면 안 된다")

    def test_returns_none_on_fetch_failure(self):
        rec = {"attachment_urls": ["https://www.fss.or.kr/p.pdf"]}

        def boom(url):
            raise OSError("timeout")

        self.assertIsNone(extract.extract_full(rec, fetch=boom))

    def test_returns_none_without_pdf_url(self):
        self.assertIsNone(extract.extract_full({}, fetch=lambda u: b""))

    def test_finds_pdf_when_first_attachment_is_hwp_second_is_pdf(self):
        long_text = "실제 보도자료 본문입니다 " * 10  # 50자 이상

        def fetch(url):
            if "fileSn=1" in url:
                return b"\xd0\xcf\x11\xe0" + b"hwp-binary-garbage"
            return b"%PDF" + long_text.encode()

        rec = {"attachment_urls": [
            "https://x/fileDown.do?fileSn=1",
            "https://x/fileDown.do?fileSn=2",
        ]}
        got = extract.extract_full(rec, fetch=fetch)
        self.assertIsNotNone(got)
        self.assertIn("실제 보도자료", got)

    def test_finds_pdf_when_first_attachment_is_pdf_second_is_hwp(self):
        """순서 무관 확인 — 이번 수정의 핵심(기존엔 fileSn=2 고정 가정이었다)."""
        long_text = "실제 보도자료 본문입니다 " * 10

        def fetch(url):
            if "fileSn=1" in url:
                return b"%PDF" + long_text.encode()
            return b"\xd0\xcf\x11\xe0" + b"hwp-binary-garbage"

        rec = {"attachment_urls": [
            "https://x/fileDown.do?fileSn=1",
            "https://x/fileDown.do?fileSn=2",
        ]}
        got = extract.extract_full(rec, fetch=fetch)
        self.assertIsNotNone(got)
        self.assertIn("실제 보도자료", got)

    def test_picks_longest_text_among_multiple_pdfs(self):
        short_text = "표지만 있는 짧은 문서 " * 3
        long_text = "본문이 충분히 긴 정식 보도자료 문서입니다 " * 20

        def fetch(url):
            if "fileSn=1" in url:
                return b"%PDF" + short_text.encode()
            return b"%PDF" + long_text.encode()

        rec = {"attachment_urls": [
            "https://x/fileDown.do?fileSn=1",
            "https://x/fileDown.do?fileSn=2",
        ]}
        got = extract.extract_full(rec, fetch=fetch)
        self.assertEqual(got, " ".join(long_text.split()))

    def test_short_text_treated_as_scanned_image(self):
        def fetch(url):
            return b"%PDF" + "짧음".encode()  # 50자 미만

        rec = {"attachment_urls": ["https://x/fileDown.do?fileSn=1"]}
        self.assertIsNone(extract.extract_full(rec, fetch=fetch))

    def test_all_hwp_attachments_returns_none(self):
        def fetch(url):
            return b"\xd0\xcf\x11\xe0" + b"hwp-binary-garbage"

        rec = {"attachment_urls": [
            "https://x/fileDown.do?fileSn=1",
            "https://x/fileDown.do?fileSn=2",
        ]}
        self.assertIsNone(extract.extract_full(rec, fetch=fetch))


if __name__ == "__main__":
    unittest.main()
