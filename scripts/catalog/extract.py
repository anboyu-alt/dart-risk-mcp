"""Phase B — 보도자료 본문 확보.

실측(2026-08-16, 표본 5건): 금감원 첨부는 fileSn=1이 구형 HWP(OLE 복합문서,
매직 D0CF11E0)이고 fileSn=2가 PDF다. HWP는 ZIP이 아니라 zipfile로 열 수 없고,
문서뷰어(viewType=BODY)는 vod2 이미지 렌더러라 텍스트가 없다. 따라서 전문은
PDF에서만 얻을 수 있으며 pypdf가 필요하다.

비용 통제를 위해 진입점을 둘로 나눈다:
- extract_light: 전량 대상, 의존성 없음. 게시판 페이지 본문(실측 505~1,097자)
- extract_full : 1차 스크리닝 통과분만. PDF 다운로드 + pypdf
"""
from __future__ import annotations

import html as html_mod
import io
import re

import requests

try:  # pypdf는 scripts 전용 optional 의존성
    from pypdf import PdfReader

    PYPDF_AVAILABLE = True
except ImportError:  # 미설치 환경에서도 요약 모드로 완주한다
    PdfReader = None  # type: ignore[assignment]
    PYPDF_AVAILABLE = False

_BASE = "https://www.fss.or.kr"
_TIMEOUT = 30
_HEADERS = {"User-Agent": "dart-risk-mcp catalog builder"}

# 본문 영역: <div class="bd-view"> ~ 다음 네비게이션/푸터 직전
_BODY_BLOCK = re.compile(
    r'<div[^>]*class="[^"]*bd-view[^"]*"[\s\S]*?'
    r'(?=<div[^>]*class="[^"]*bd-view-nav|<footer)',
    re.I,
)
_SCRIPT_STYLE = re.compile(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", re.I)
_TAG = re.compile(r"<[^>]+>")
_FILE_LINK = re.compile(r'href="([^"]*fileDown\.do\?[^"]*fileSn=(\d)[^"]*)"', re.I)


_REPLACEMENT_CHAR = "�"
_REPLACEMENT_RATIO_LIMIT = 0.01


def decode_page(raw: bytes) -> tuple[str, bool]:
    """페이지 바이트를 디코딩한다. 반환: (텍스트, 신뢰 가능 여부).

    레포 관례(dart_client._decode_zip_file)대로 utf-8 → euc-kr → cp949를 차례로
    시도한다. 셋 다 실패하면 errors="replace"로 살려내되, 대체 문자(U+FFFD)가
    본문에 과다하면 신뢰 불가로 표시한다 — 조용히 오염된 본문이 정상 본문인 척
    분류 단계로 흘러가는 것을 막기 위함이다.
    """
    if not raw:
        return "", True
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc), True
        except UnicodeDecodeError:
            continue
    text = raw.decode("utf-8", errors="replace")
    ratio = text.count(_REPLACEMENT_CHAR) / len(text) if text else 0.0
    return text, ratio <= _REPLACEMENT_RATIO_LIMIT


def _clean_html(fragment: str) -> str:
    text = _SCRIPT_STYLE.sub(" ", fragment)
    text = _TAG.sub(" ", text)
    text = html_mod.unescape(text)
    return " ".join(text.split())


def parse_page_body(page_html: str) -> str:
    """게시판 상세 페이지에서 본문 영역 텍스트를 뽑는다."""
    block = _BODY_BLOCK.search(page_html)
    return _clean_html(block.group(0) if block else "")


def parse_attachment_urls(page_html: str) -> dict[str, str]:
    """첨부 다운로드 URL을 fileSn 기준으로 분류한다(1=HWP, 2=PDF)."""
    out: dict[str, str] = {}
    for href, sn in _FILE_LINK.findall(page_html):
        url = html_mod.unescape(href)
        if not url.startswith("http"):
            url = _BASE + url
        out["hwp" if sn == "1" else "pdf"] = url
    return out


def _default_fetch(url: str) -> bytes:
    resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def extract_light(record: dict, fetch=None) -> dict:
    """전량 대상 본문 확보. 페이지 본문 → 실패 시 제목+요약.

    record를 변형하지 않고 body/body_source/body_chars/attachment_urls를 더한 새 dict 반환.
    """
    fetch = fetch or _default_fetch
    out = dict(record)
    body, source = "", "title_only"

    url = (record.get("url") or "").strip()
    if url:
        try:
            page, trusted = decode_page(fetch(url))
            if trusted:
                body = parse_page_body(page)
                if body:
                    source = "page"
                    out["attachment_urls"] = parse_attachment_urls(page)
            # trusted=False: 오염된 디코딩 결과는 쓰지 않는다 — 아래 title_only 폴백으로 낙하
        except Exception:
            # 네트워크·디코딩 실패는 폴백으로 흡수한다(파이프라인을 멈추지 않음)
            body = ""

    if not body:
        body = " ".join(x for x in (record.get("title"), record.get("summary")) if x).strip()
        source = "title_only"

    out["body"] = body
    out["body_source"] = source
    out["body_chars"] = len(body)
    return out


def extract_full(record: dict, fetch=None) -> str | None:
    """PDF 전문 추출. pypdf 미설치·URL 부재·다운로드 실패 시 None."""
    if not PYPDF_AVAILABLE:
        return None
    pdf_url = (record.get("attachment_urls") or {}).get("pdf")
    if not pdf_url:
        return None
    fetch = fetch or _default_fetch
    try:
        data = fetch(pdf_url)
        reader = PdfReader(io.BytesIO(data))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception:
        return None
    text = " ".join(" ".join(pages).split())
    return text or None
