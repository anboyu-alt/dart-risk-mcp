"""DART 전자공시 API 클라이언트

기업명 → corp_code 조회, 공시 목록 조회, 공시 원문 텍스트 추출.
의존성: requests 만 사용.
"""

import io
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import requests

log = logging.getLogger(__name__)

DART_BASE = "https://opendart.fss.or.kr/api"
_CACHE_DIR = Path.home() / ".cache" / "dart-risk-mcp"


def _retry(method: str, url: str, **kwargs) -> requests.Response:
    """429/5xx 지수 백오프 재시도 (최대 3회)."""
    kwargs.setdefault("timeout", 15)
    last: requests.Response | None = None
    for i in range(3):
        try:
            last = requests.request(method, url, **kwargs)
            if last.status_code not in (429, 500, 502, 503, 504):
                return last
            if i < 2:
                time.sleep(min(2 ** i, 10))
        except requests.RequestException as e:
            if i == 2:
                raise
            time.sleep(min(2 ** i, 10))
    return last  # type: ignore


# ── Corp code 캐시 ──────────────────────────────────────────────

_corp_cache: dict = {}


def _load_corp_codes(api_key: str) -> None:
    """DART corpCode.xml에서 기업명 → corp_code 매핑 로드. 파일 캐시 24시간."""
    global _corp_cache

    cache_file = _CACHE_DIR / "corp_codes.json"
    if cache_file.exists() and (time.time() - cache_file.stat().st_mtime) < 86400:
        with open(cache_file, encoding="utf-8") as f:
            _corp_cache = json.load(f)
        return

    if not api_key:
        return

    try:
        resp = _retry("GET", f"{DART_BASE}/corpCode.xml",
                      params={"crtfc_key": api_key})
        if resp.status_code != 200:
            return

        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        xml_bytes = zf.read(zf.namelist()[0])
        zf.close()

        root = ET.fromstring(xml_bytes.decode("utf-8"))
        for item in root.findall(".//list"):
            name  = (item.findtext("corp_name")  or "").strip()
            code  = (item.findtext("corp_code")   or "").strip()
            stock = (item.findtext("stock_code")  or "").strip()
            if name and code:
                _corp_cache[name] = {"corp_code": code, "stock_code": stock}

        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(_corp_cache, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Corp code 로드 실패: %s", e)


def resolve_corp(query: str, api_key: str) -> tuple[str, dict] | None:
    """기업명 또는 종목코드(6자리) → (정식 기업명, {corp_code, stock_code}).

    부분 매칭 지원 — '삼성바이오' 입력 시 '삼성바이오로직스' 반환.
    """
    if not _corp_cache:
        _load_corp_codes(api_key)

    # 정확히 일치
    if query in _corp_cache:
        return query, _corp_cache[query]

    # 종목코드 6자리
    if re.match(r"^\d{6}$", query):
        for name, info in _corp_cache.items():
            if info.get("stock_code") == query:
                return name, info

    # 부분 매칭
    matches = [(k, v) for k, v in _corp_cache.items() if query in k]
    if len(matches) == 1:
        return matches[0]
    if matches:
        matches.sort(key=lambda x: len(x[0]))
        return matches[0]

    return None


# ── 공시 목록 ──────────────────────────────────────────────────

def fetch_company_disclosures(
    corp_code: str,
    api_key: str,
    lookback_days: int = 90,
) -> list[dict]:
    """특정 기업의 DART 공시 목록 조회."""
    if not api_key:
        return []

    now = datetime.now()
    results: list[dict] = []
    page_no = 1

    while page_no <= 5:
        params = {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bgn_de": (now - timedelta(days=lookback_days)).strftime("%Y%m%d"),
            "end_de": now.strftime("%Y%m%d"),
            "page_no": page_no,
            "page_count": 100,
        }
        try:
            data = _retry("GET", f"{DART_BASE}/list.json", params=params).json()
        except Exception:
            break

        if data.get("status") != "000":
            break

        results.extend(data.get("list", []))
        if page_no * 100 >= int(data.get("total_count", 0)):
            break
        page_no += 1
        time.sleep(0.25)

    return results


# ── 공시 원문 텍스트 ────────────────────────────────────────────

_TAG_RE  = re.compile(r"<[^>]+>")
_ENT_RE  = re.compile(r"&[a-zA-Z#0-9]+;")
_STYE_RE = re.compile(r"<style[^>]*>.*?</style>", re.DOTALL | re.IGNORECASE)
_SCRP_RE = re.compile(r"<script[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)

# ZIP 인메모리 캐시: rcept_no → (timestamp, raw_bytes)
_zip_cache: dict[str, tuple[float, bytes]] = {}
_ZIP_CACHE_MAX = 5
_ZIP_CACHE_TTL = 600  # 10분


def _fetch_document_zip(rcept_no: str, api_key: str) -> zipfile.ZipFile | None:
    """DART document.xml에서 ZIP 다운로드. 인메모리 캐시 적용 (최대 5건, TTL 10분)."""
    now = time.time()

    # 캐시 확인
    if rcept_no in _zip_cache:
        ts, raw = _zip_cache[rcept_no]
        if now - ts < _ZIP_CACHE_TTL:
            try:
                return zipfile.ZipFile(io.BytesIO(raw))
            except zipfile.BadZipFile:
                del _zip_cache[rcept_no]

    if not api_key:
        return None

    try:
        resp = _retry(
            "GET", f"{DART_BASE}/document.xml",
            params={"crtfc_key": api_key, "rcept_no": rcept_no},
            timeout=30,
        )
        if resp.status_code != 200:
            return None

        ct = resp.headers.get("Content-Type", "")
        if "application/json" in ct or ct.startswith("text/"):
            return None

        raw = resp.content
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            return None

        # LRU: 오래된 항목 제거
        if len(_zip_cache) >= _ZIP_CACHE_MAX:
            oldest = min(_zip_cache, key=lambda k: _zip_cache[k][0])
            del _zip_cache[oldest]

        _zip_cache[rcept_no] = (now, raw)
        return zf

    except Exception as e:
        log.debug("ZIP 다운로드 실패 (%s): %s", rcept_no, e)
        return None


def _decode_zip_file(zf: zipfile.ZipFile, name: str) -> str:
    """ZIP 내 파일을 여러 인코딩으로 시도하여 문자열로 반환."""
    raw = zf.read(name)
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def fetch_document_text(rcept_no: str, api_key: str, max_chars: int = 3000) -> str:
    """DART 공시 원문 ZIP에서 텍스트 추출 (기존 호환 함수).

    document.xml API → ZIP 해제 → XML/HTML 파싱 → 태그 제거 → 텍스트 반환.
    """
    zf = _fetch_document_zip(rcept_no, api_key)
    if not zf:
        return ""

    try:
        xml_content = ""
        for name in zf.namelist():
            if name.lower().endswith((".xml", ".html", ".htm")):
                xml_content = _decode_zip_file(zf, name)
                if xml_content:
                    break
        zf.close()

        if not xml_content:
            return ""

        text = _STYE_RE.sub(" ", xml_content)
        text = _SCRP_RE.sub(" ", text)
        text = _TAG_RE.sub(" ", text)
        text = _ENT_RE.sub(" ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars]
    except Exception as e:
        log.debug("원문 조회 실패 (%s): %s", rcept_no, e)
        return ""


# ── 구조 보존 HTML → 텍스트 변환 ───────────────────────────────

# HTML 엔티티 디코딩 테이블
_HTML_ENTITIES = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
    "&apos;": "'", "&nbsp;": " ", "&middot;": "·", "&bull;": "•",
    "&hellip;": "…", "&mdash;": "—", "&ndash;": "–",
    "&laquo;": "«", "&raquo;": "»",
}
_NUMERIC_ENT_RE = re.compile(r"&#(\d+);|&#x([0-9a-fA-F]+);")
_NAMED_ENT_RE = re.compile(r"&[a-zA-Z]+;")


def _decode_html_entities(text: str) -> str:
    """HTML 엔티티 디코딩."""
    def replace_numeric(m: re.Match) -> str:
        if m.group(1):
            return chr(int(m.group(1)))
        return chr(int(m.group(2), 16))

    text = _NUMERIC_ENT_RE.sub(replace_numeric, text)
    for ent, ch in _HTML_ENTITIES.items():
        text = text.replace(ent, ch)
    text = _NAMED_ENT_RE.sub(" ", text)
    return text


def _extract_tag_content(html: str, tag: str) -> list[str]:
    """특정 태그의 내용 리스트 반환 (중첩 없는 단순 태그용)."""
    pattern = re.compile(
        rf"<{tag}[^>]*>(.*?)</{tag}>", re.DOTALL | re.IGNORECASE
    )
    return [m.group(1) for m in pattern.finditer(html)]


def _strip_tags(text: str) -> str:
    """모든 HTML 태그 제거 후 공백 정리."""
    text = _TAG_RE.sub("", text)
    return _decode_html_entities(text).strip()


def _table_to_markdown(table_html: str) -> str:
    """HTML 테이블을 마크다운 테이블 형식으로 변환."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_html, re.DOTALL | re.IGNORECASE)
    if not rows:
        return _strip_tags(table_html)

    md_rows = []
    for i, row in enumerate(rows):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.DOTALL | re.IGNORECASE)
        cell_texts = [re.sub(r"\s+", " ", _strip_tags(c)).strip() for c in cells]
        if not any(cell_texts):
            continue
        md_rows.append("| " + " | ".join(cell_texts) + " |")
        if i == 0:
            md_rows.append("|" + "|".join(["---"] * len(cell_texts)) + "|")

    return "\n".join(md_rows)


def _html_to_structured_text(html: str) -> str:
    """HTML → 마크다운 형식 구조 보존 텍스트 변환.

    <h1>~<h6> → # 마크다운 헤더
    <table> → 파이프(|) 구분 마크다운 테이블
    <li> → - 항목
    <br>, </p> → 줄바꿈
    <b>, <strong> → **볼드**
    <style>, <script> → 제거
    외부 라이브러리 없이 regex + 문자열 처리로 구현.
    """
    # style, script 제거
    text = _STYE_RE.sub("", html)
    text = _SCRP_RE.sub("", text)

    # 테이블 → 마크다운 (먼저 처리)
    def replace_table(m: re.Match) -> str:
        return "\n\n" + _table_to_markdown(m.group(0)) + "\n\n"

    text = re.sub(r"<table[^>]*>.*?</table>", replace_table, text, flags=re.DOTALL | re.IGNORECASE)

    # 헤더 변환
    for level in range(1, 7):
        prefix = "#" * level + " "
        text = re.sub(
            rf"<h{level}[^>]*>(.*?)</h{level}>",
            lambda m, p=prefix: f"\n\n{p}{_strip_tags(m.group(1))}\n",
            text, flags=re.DOTALL | re.IGNORECASE,
        )

    # 볼드
    text = re.sub(r"<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>",
                  lambda m: f"**{_strip_tags(m.group(1))}**",
                  text, flags=re.DOTALL | re.IGNORECASE)

    # 리스트 아이템
    text = re.sub(r"<li[^>]*>(.*?)</li>",
                  lambda m: f"\n- {_strip_tags(m.group(1))}",
                  text, flags=re.DOTALL | re.IGNORECASE)

    # 단락/줄바꿈
    text = re.sub(r"</p>|</div>|</tr>|<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # 나머지 태그 제거
    text = _TAG_RE.sub("", text)

    # 엔티티 디코딩
    text = _decode_html_entities(text)

    # 공백 정리 (연속 줄바꿈은 최대 2개로)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip()


# ── 공시 원문 전체 조회 (단일 호출) ────────────────────────────

def fetch_disclosure_full(rcept_no: str, api_key: str, max_chars: int = 8000) -> dict:
    """DART 공시 원문 전체를 구조 보존 텍스트로 반환한다.

    ZIP 내 HTML/XML 파일 중 가장 큰 파일을 주 문서로 선정한다.

    Returns:
        {
            "files": list[str],      # ZIP 내 전체 파일 목록
            "main_file": str,        # 선정된 주 문서 파일명
            "text": str,             # 구조 보존 텍스트 (max_chars 이하)
            "char_count": int,       # 원본 전체 글자수
            "truncated": bool,       # 잘림 여부
        }
    """
    max_chars = min(max_chars, 20000)
    empty = {"files": [], "main_file": "", "text": "", "char_count": 0, "truncated": False}

    zf = _fetch_document_zip(rcept_no, api_key)
    if not zf:
        return empty

    try:
        all_files = zf.namelist()
        doc_files = [
            n for n in all_files
            if n.lower().endswith((".xml", ".html", ".htm"))
        ]

        if not doc_files:
            zf.close()
            return {**empty, "files": all_files}

        # 가장 큰 파일을 주 문서로 선정
        main_file = max(doc_files, key=lambda n: zf.getinfo(n).file_size)
        raw_html = _decode_zip_file(zf, main_file)
        zf.close()

        if not raw_html:
            return {**empty, "files": all_files, "main_file": main_file}

        full_text = _html_to_structured_text(raw_html)
        char_count = len(full_text)
        truncated = char_count > max_chars

        return {
            "files": all_files,
            "main_file": main_file,
            "text": full_text[:max_chars],
            "char_count": char_count,
            "truncated": truncated,
        }
    except Exception as e:
        log.debug("원문 전체 조회 실패 (%s): %s", rcept_no, e)
        return empty


# ── 문서 섹션 목록 ──────────────────────────────────────────────

_HEADING_RE = re.compile(
    r"<(?:h[1-4]|SECTION-\d+)[^>]*>(.*?)</(?:h[1-4]|SECTION-\d+)>",
    re.DOTALL | re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)


def list_document_sections(rcept_no: str, api_key: str) -> list[dict]:
    """DART 공시 ZIP 내 파일별 섹션(목차) 구조 반환.

    Returns:
        [
            {
                "file_index": 0,
                "filename": "xxx.html",
                "char_length": 12345,
                "sections": [
                    {"id": "s0", "title": "I. 회사의 개요", "char_offset": 0},
                    ...
                ]
            }
        ]
    """
    zf = _fetch_document_zip(rcept_no, api_key)
    if not zf:
        return []

    result = []
    doc_files = [n for n in zf.namelist() if n.lower().endswith((".xml", ".html", ".htm"))]

    for file_index, filename in enumerate(doc_files):
        content = _decode_zip_file(zf, filename)
        if not content:
            continue

        sections = []
        sec_id = 0

        # 문서 제목
        title_m = _TITLE_RE.search(content)
        doc_title = _strip_tags(title_m.group(1)) if title_m else filename

        # 섹션 헤딩 추출
        for m in _HEADING_RE.finditer(content):
            title = _strip_tags(m.group(1)).strip()
            if title and len(title) < 200:
                sections.append({
                    "id": f"f{file_index}s{sec_id}",
                    "title": title,
                    "char_offset": m.start(),
                })
                sec_id += 1

        # 섹션이 없으면 파일 전체를 하나의 섹션으로
        if not sections:
            sections.append({
                "id": f"f{file_index}s0",
                "title": doc_title,
                "char_offset": 0,
            })

        result.append({
            "file_index": file_index,
            "filename": filename,
            "doc_title": doc_title,
            "char_length": len(content),
            "sections": sections,
        })

    zf.close()
    return result


# ── 페이지네이션 문서 내용 조회 ────────────────────────────────

def _split_pages(text: str, page_size: int) -> list[str]:
    """텍스트를 단락 경계에서 page_size 단위로 분할."""
    pages = []
    start = 0
    total = len(text)

    while start < total:
        end = start + page_size
        if end >= total:
            pages.append(text[start:])
            break

        # 단락 경계(\n\n) 탐색 (뒤에서 앞으로)
        split_pos = text.rfind("\n\n", start, end)
        if split_pos == -1 or split_pos <= start:
            # 줄바꿈 경계 탐색
            split_pos = text.rfind("\n", start, end)
        if split_pos == -1 or split_pos <= start:
            split_pos = end

        pages.append(text[start:split_pos].rstrip())
        start = split_pos + 1

    return [p for p in pages if p.strip()]


def fetch_document_content(
    rcept_no: str,
    api_key: str,
    file_index: int = 0,
    section_id: str | None = None,
    page: int = 1,
    page_size: int = 4000,
) -> dict:
    """DART 공시 원문을 구조 보존 텍스트로 반환 (페이지네이션 지원).

    Args:
        rcept_no: DART 접수번호
        api_key: DART API 키
        file_index: ZIP 내 파일 인덱스 (0부터)
        section_id: 특정 섹션 ID (list_document_sections 결과의 id 값, None이면 전체)
        page: 페이지 번호 (1부터)
        page_size: 페이지당 글자 수 (1000~8000)

    Returns:
        {
            "content": str,
            "page": int,
            "total_pages": int,
            "has_more": bool,
            "filename": str,
            "doc_title": str,
        }
    """
    page_size = max(1000, min(8000, page_size))
    page = max(1, page)

    zf = _fetch_document_zip(rcept_no, api_key)
    if not zf:
        return {"content": "", "page": 1, "total_pages": 0, "has_more": False,
                "filename": "", "doc_title": ""}

    doc_files = [n for n in zf.namelist() if n.lower().endswith((".xml", ".html", ".htm"))]
    if file_index >= len(doc_files):
        file_index = 0

    filename = doc_files[file_index] if doc_files else ""
    raw_html = _decode_zip_file(zf, filename) if filename else ""
    zf.close()

    if not raw_html:
        return {"content": "", "page": 1, "total_pages": 0, "has_more": False,
                "filename": filename, "doc_title": ""}

    # 섹션 필터링
    content_html = raw_html
    if section_id:
        # 섹션 ID에서 파일/섹션 인덱스 파싱
        sec_m = re.match(r"f(\d+)s(\d+)$", section_id)
        if sec_m:
            f_idx = int(sec_m.group(1))
            s_idx = int(sec_m.group(2))
            # 해당 파일의 섹션 목록에서 offset 구하기
            headings = list(_HEADING_RE.finditer(raw_html))
            if s_idx < len(headings):
                start_pos = headings[s_idx].start()
                end_pos = headings[s_idx + 1].start() if s_idx + 1 < len(headings) else len(raw_html)
                content_html = raw_html[start_pos:end_pos]

    # 구조 보존 변환
    structured = _html_to_structured_text(content_html)

    # 제목 추출
    title_m = _TITLE_RE.search(raw_html)
    doc_title = _strip_tags(title_m.group(1)) if title_m else filename

    # 페이지 분할
    pages = _split_pages(structured, page_size)
    total_pages = max(1, len(pages))
    page = min(page, total_pages)
    content = pages[page - 1] if pages else ""

    return {
        "content": content,
        "page": page,
        "total_pages": total_pages,
        "has_more": page < total_pages,
        "filename": filename,
        "doc_title": doc_title,
    }


# ── 기업 개요 조회 ─────────────────────────────────────────────

def fetch_company_info(corp_code: str, api_key: str) -> dict:
    """DART /company.json — 기업 기본 프로필 조회.

    Returns:
        {"corp_name", "ceo_nm", "corp_cls", "adres", "induty_code",
         "est_dt", "acc_mt", "stock_code", ...} or empty dict
    """
    if not api_key:
        return {}
    try:
        resp = _retry(
            "GET", f"{DART_BASE}/company.json",
            params={"crtfc_key": api_key, "corp_code": corp_code},
        )
        data = resp.json()
        if data.get("status") == "000":
            return data
    except Exception as e:
        log.debug("기업 개요 조회 실패 (%s): %s", corp_code, e)
    return {}


# ── 재무제표 조회 ──────────────────────────────────────────────

# 보고서 코드: 11011=사업보고서, 11012=반기, 11013=1분기, 11014=3분기
_REPORT_CODES = {"annual": "11011", "semi": "11012", "q1": "11013", "q3": "11014"}


def fetch_financial_statements(
    corp_code: str,
    api_key: str,
    year: str = "",
    report_type: str = "annual",
) -> list[dict]:
    """DART /fnlttSinglAcnt.json — 단일 기업 주요 재무제표.

    Args:
        corp_code: DART 기업 코드
        api_key: DART API 키
        year: 사업연도 (빈 문자열이면 전년도)
        report_type: "annual", "semi", "q1", "q3"

    Returns: [{account_nm, thstrm_amount, frmtrm_amount, bfefrmtrm_amount, ...}]
    """
    if not api_key:
        return []
    if not year:
        year = str(datetime.now().year - 1)
    reprt_code = _REPORT_CODES.get(report_type, "11011")

    try:
        resp = _retry(
            "GET", f"{DART_BASE}/fnlttSinglAcnt.json",
            params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bsns_year": year,
                "reprt_code": reprt_code,
                "fs_div": "CFS",  # 연결재무제표 우선
            },
        )
        data = resp.json()
        if data.get("status") == "000":
            return data.get("list", [])
        # 연결재무제표 없으면 개별재무제표
        resp = _retry(
            "GET", f"{DART_BASE}/fnlttSinglAcnt.json",
            params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bsns_year": year,
                "reprt_code": reprt_code,
                "fs_div": "OFS",
            },
        )
        data = resp.json()
        if data.get("status") == "000":
            return data.get("list", [])
    except Exception as e:
        log.debug("재무제표 조회 실패 (%s): %s", corp_code, e)
    return []


def fetch_multi_financial(
    corp_codes: list[str],
    api_key: str,
    year: str = "",
    report_type: str = "annual",
) -> list[dict]:
    """DART /fnlttMultiAcnt.json — 다중 기업 재무 비교 (최대 100개).

    Returns: [{corp_code, corp_name, account_nm, thstrm_amount, ...}]
    """
    if not api_key or not corp_codes:
        return []
    if not year:
        year = str(datetime.now().year - 1)
    reprt_code = _REPORT_CODES.get(report_type, "11011")

    try:
        resp = _retry(
            "GET", f"{DART_BASE}/fnlttMultiAcnt.json",
            params={
                "crtfc_key": api_key,
                "corp_code": ",".join(corp_codes[:100]),
                "bsns_year": year,
                "reprt_code": reprt_code,
            },
        )
        data = resp.json()
        if data.get("status") == "000":
            return data.get("list", [])
    except Exception as e:
        log.debug("다중 재무제표 조회 실패: %s", e)
    return []


# ── 최대주주/대량보유 현황 ─────────────────────────────────────

def fetch_shareholder_status(
    corp_code: str,
    api_key: str,
    year: str = "",
    report_type: str = "annual",
) -> dict:
    """DART 최대주주 + 5% 대량보유 통합 조회.

    Returns:
        {
            "major_holders": [...],   # /hyslrSttus.json 결과
            "bulk_holders": [...],    # /majorstock.json 결과
        }
    """
    if not api_key:
        return {"major_holders": [], "bulk_holders": []}
    if not year:
        year = str(datetime.now().year - 1)
    reprt_code = _REPORT_CODES.get(report_type, "11011")

    result: dict = {"major_holders": [], "bulk_holders": []}

    # 최대주주 현황
    try:
        resp = _retry(
            "GET", f"{DART_BASE}/hyslrSttus.json",
            params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bsns_year": year,
                "reprt_code": reprt_code,
            },
        )
        data = resp.json()
        if data.get("status") == "000":
            result["major_holders"] = data.get("list", [])
    except Exception as e:
        log.debug("최대주주 조회 실패 (%s): %s", corp_code, e)

    # 5% 대량보유
    try:
        resp = _retry(
            "GET", f"{DART_BASE}/majorstock.json",
            params={"crtfc_key": api_key, "corp_code": corp_code},
        )
        data = resp.json()
        if data.get("status") == "000":
            result["bulk_holders"] = data.get("list", [])
    except Exception as e:
        log.debug("대량보유 조회 실패 (%s): %s", corp_code, e)

    return result
