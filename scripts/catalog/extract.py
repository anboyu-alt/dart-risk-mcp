"""Phase B — 보도자료 본문 확보.

초기 실측(2026-08-16, 표본 5건 — 전부 2023~2024년)은 fileSn=1이 구형
HWP(OLE 복합문서, 매직 D0CF11E0)이고 fileSn=2가 PDF라고 결론지었지만, 이는
연도 편향이었다. 표본을 넓혀보니(2026-08-16 후속) **fileSn 번호와 파일
종류의 대응 자체가 시기에 따라 뒤집힌다**:

    2011~2019년:  fileSn=1 → PDF,  fileSn=2 → HWP
    2023~2026년:  fileSn=1 → HWP,  fileSn=2 → PDF

그래서 종류를 번호로 추정하지 않는다 — 상세 페이지의 모든 첨부 URL을 받아
(`parse_attachment_urls`), 실제로 받아본 뒤 **매직바이트**로 판별한다
(`extract_full`). PDF는 `%PDF`(25504446), 구형 HWP는 D0CF11E0(OLE 복합문서),
hwpx 등 ZIP 계열은 504B0304로 시작한다 — HWP 계열은 어차피 표준 라이브러리로
파싱할 수 없어 건너뛴다. 문서뷰어(viewType=BODY)도 vod2 이미지 렌더러라
텍스트가 없어 대상에서 제외한다. 따라서 전문은 PDF에서만 얻을 수 있으며
pypdf가 필요하다.

비용 통제를 위해 진입점을 둘로 나눈다:
- extract_light: 전량 대상, 의존성 없음. 게시판 페이지 본문(실측 505~1,097자)
- extract_full : 1차 스크리닝 통과분만. 첨부 전체 다운로드 + 매직바이트 판별 + pypdf
"""
from __future__ import annotations

import html as html_mod
import io
import re
import time

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
_FILE_LINK = re.compile(r'href="([^"]*fileDown\.do\?[^"]*fileSn=(\d+)[^"]*)"', re.I)


_REPLACEMENT_CHAR = "�"
_REPLACEMENT_RATIO_LIMIT = 0.01

# 첨부 다운로드 사이의 대기(게시판 부하 완화). export_batches._SLEEP과 동일 관례.
_SLEEP = 0.25

# 매직바이트: PDF는 "%PDF", 구형 HWP(OLE 복합문서)는 D0CF11E0, hwpx 등 ZIP
# 계열은 504B0304로 시작한다. PDF만 pypdf로 열고 나머지는 건너뛴다.
_PDF_MAGIC = b"%PDF"

# 스캔 이미지 PDF는 텍스트 레이어가 없어 pypdf가 거의 아무것도 못 뽑는다.
# 진단 표본(20건) 기준 정상 추출본은 수백~수천 자, 스캔본은 0자로 격차가
# 뚜렷했다 — 50자는 그 사이 어디에도 걸리지 않는 여유 임계값이다.
_MIN_TEXT_CHARS = 50


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


def parse_attachment_urls(page_html: str) -> list[str]:
    """상세 페이지의 모든 첨부 다운로드 URL을 fileSn 오름차순으로 반환한다.

    fileSn 번호로 파일 종류를 추정하지 않는다 — 종류는 실제로 받아본 뒤
    매직바이트로 판별한다(`extract_full`). fileSn은 첨부 개수만큼 두 자리
    이상도 나올 수 있어(예: 10개 이상 첨부한 보도자료의 fileSn=10) 숫자
    비교로 정렬한다(문자열 정렬이면 "10"이 "2"보다 앞에 온다).
    """
    items: list[tuple[int, str]] = []
    for href, sn in _FILE_LINK.findall(page_html):
        url = html_mod.unescape(href)
        if not url.startswith("http"):
            url = _BASE + url
        items.append((int(sn), url))
    items.sort(key=lambda pair: pair[0])
    return [url for _, url in items]


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
    """첨부 중 매직바이트로 PDF를 찾아 전문을 추출한다.

    fileSn으로 종류를 추정하지 않는다(모듈 docstring 참고 — 연도별로 1/2의
    대응이 뒤집힌다). 각 첨부의 앞 4바이트를 읽어 PDF(%PDF)인 것만 pypdf로
    연다. HWP·hwpx 등은 매직바이트 단계에서 건너뛴다(다운로드는 하되 파싱은
    안 함 — 종류를 미리 알 방법이 없다). 첨부가 여럿이면 추출 텍스트가 가장
    긴 것을 쓴다(같은 문서의 다른 판본일 수 있고, 짧은 쪽이 표지만인 경우가
    있다). 텍스트가 `_MIN_TEXT_CHARS` 미만이면 스캔 이미지 PDF로 보고 실패
    (None) 취급한다.

    pypdf 미설치면 다운로드조차 하지 않고 즉시 None(무의미한 트래픽 방지).
    개별 첨부의 다운로드·파싱 실패는 흡수하고 다음 첨부로 넘어간다 — 한 건의
    실패가 배치 전체를 멈추면 안 된다.
    """
    if not PYPDF_AVAILABLE:
        return None
    urls = record.get("attachment_urls") or []
    if not urls:
        return None
    fetch = fetch or _default_fetch

    best = ""
    for i, url in enumerate(urls):
        if i:
            time.sleep(_SLEEP)  # 게시판 부하 완화 — 요청 간 대기
        try:
            data = fetch(url)
            if data[:4] != _PDF_MAGIC:
                continue  # HWP(D0CF11E0)·hwpx(504B0304) 등은 건너뛴다
            reader = PdfReader(io.BytesIO(data))
            pages = [(p.extract_text() or "") for p in reader.pages]
        except Exception:
            continue
        text = " ".join(" ".join(pages).split())
        if len(text) > len(best):
            best = text

    return best if len(best) >= _MIN_TEXT_CHARS else None
