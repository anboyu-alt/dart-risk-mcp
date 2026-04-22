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
    """429/5xx 지수 백오프 재시도 (최대 3회). 3회 후에도 4xx/5xx면 raise_for_status."""
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
    if last is not None and last.status_code >= 400:
        last.raise_for_status()
    return last  # type: ignore


# ── DART API 상태코드 ─────────────────────────────────────────────
_DART_WARN_STATUS = {"020", "800", "900"}
_DART_STATUS_MSG = {
    "013": "데이터 없음",
    "020": "요청 한도 초과 — API 쿼터를 확인하세요",
    "800": "시스템 점검 중",
    "900": "API 키 오류 또는 권한 없음",
}


def _log_dart_status(status: str, context: str = "") -> None:
    """DART status 코드에 따라 적절한 레벨로 로그 기록."""
    msg = _DART_STATUS_MSG.get(status, f"알 수 없는 오류 (status={status})")
    if status in _DART_WARN_STATUS:
        log.warning("DART API [%s]: %s", context, msg)
    else:
        log.debug("DART API [%s]: %s", context, msg)


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

        zf = zipfile.ZipFile(io.BytesIO(resp.content), metadata_encoding="cp949")
        xml_bytes = zf.read(zf.namelist()[0])
        zf.close()

        root = ET.fromstring(xml_bytes.decode("utf-8", errors="replace"))
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

    while page_no <= 10:
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

        status = data.get("status")
        if status != "000":
            _log_dart_status(status, f"공시목록 corp_code={corp_code}")
            break

        results.extend(data.get("list", []))
        total = int(data.get("total_count", 0))
        if page_no * 100 >= total:
            break
        if page_no >= 10 and len(results) < total:
            log.warning("공시목록 1000건 초과 기업 (corp_code=%s, total=%d) — 일부 누락", corp_code, total)
            break
        page_no += 1
        time.sleep(0.25)

    return results


# ── 시장 전체 공시 조회 ─────────────────────────────────────────

def fetch_market_disclosures(
    api_key: str,
    bgn_de: str,
    end_de: str,
    pblntf_ty: str = "",
    max_pages: int = 10,
) -> list[dict]:
    """DART /list.json을 corp_code 없이 호출해 시장 전체 공시 조회.

    Args:
        api_key: DART API 키
        bgn_de: 시작일 YYYYMMDD
        end_de: 종료일 YYYYMMDD
        pblntf_ty: 공시 유형 (A=정기, B=주요사항, C=발행, D=지분, E=기타, F=외부감사, I=거래소, J=공정위)
        max_pages: 최대 페이지 수 (100건/페이지)
    """
    if not api_key:
        return []

    results: list[dict] = []
    page_no = 1
    while page_no <= max_pages:
        params = {
            "crtfc_key": api_key,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "page_no": page_no,
            "page_count": 100,
        }
        if pblntf_ty:
            params["pblntf_ty"] = pblntf_ty

        try:
            data = _retry("GET", f"{DART_BASE}/list.json", params=params).json()
        except Exception:
            break

        status = data.get("status")
        if status != "000":
            _log_dart_status(status, f"시장공시 {bgn_de}~{end_de} pblntf={pblntf_ty}")
            break

        results.extend(data.get("list", []))
        total = int(data.get("total_count", 0))
        if page_no * 100 >= total:
            break
        if page_no >= max_pages and len(results) < total:
            log.warning("시장공시 %d건 초과 (%s~%s) — 일부 누락", max_pages * 100, bgn_de, end_de)
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

# v0.5.0: fund_usage / major_decision LRU 캐시 ------------------
_fund_usage_cache: dict[tuple, tuple[float, list]] = {}
_FUND_CACHE_MAX = 20
_FUND_CACHE_TTL = 600  # 10분

_major_decision_cache: dict[str, tuple[float, dict]] = {}
_MAJOR_CACHE_MAX = 50
_MAJOR_CACHE_TTL = 600


def _cache_get(cache: dict, key, ttl: int):
    item = cache.get(key)
    if item is None:
        return None
    ts, val = item
    if time.time() - ts > ttl:
        cache.pop(key, None)
        return None
    return val


def _cache_set(cache: dict, key, val, limit: int) -> None:
    if len(cache) >= limit and key not in cache:
        oldest_key = min(cache.items(), key=lambda kv: kv[1][0])[0]
        cache.pop(oldest_key, None)
    cache[key] = (time.time(), val)


# v0.5.0: 자금사용내역 엔드포인트 --------------------------------
_FUND_USAGE_URLS = {
    "public":  f"{DART_BASE}/pssrpCptalUseDtls.json",   # 2020016
    "private": f"{DART_BASE}/prvsrpCptalUseDtls.json",  # 2020017
}

_FUND_DIVERSION_KEYWORDS = (
    "목적 변경", "목적변경", "사용목적 변경",
    "사업 취소", "사업취소", "계획 취소", "계획취소",
    "일반 운영자금", "일반운영자금", "운영자금 전용", "운영자금으로",
    "변경 사용", "변경사용", "유보",
)

# v0.5.0: 주요사항보고서 결정 공시(DS005 2020042~2020053) 라우팅 -
_MAJOR_DECISION_URLS = {
    "business_acq":    f"{DART_BASE}/bsnInhDecsn.json",              # 2020042
    "business_div":    f"{DART_BASE}/bsnTrfDecsn.json",              # 2020043
    "tangible_acq":    f"{DART_BASE}/tgastInhDecsn.json",            # 2020044
    "tangible_div":    f"{DART_BASE}/tgastTrfDecsn.json",            # 2020045
    "stock_acq":       f"{DART_BASE}/otcprStkInvscrInhDecsn.json",   # 2020046
    "stock_div":       f"{DART_BASE}/otcprStkInvscrTrfDecsn.json",   # 2020047
    "bond_acq":        f"{DART_BASE}/stkrtbdInhDecsn.json",          # 2020048
    "bond_div":        f"{DART_BASE}/stkrtbdTrfDecsn.json",          # 2020049
    "merger":          f"{DART_BASE}/cmpMgDecsn.json",               # 2020050
    "demerger":        f"{DART_BASE}/cmpDvDecsn.json",               # 2020051
    "demerger_merger": f"{DART_BASE}/cmpDvmgDecsn.json",             # 2020052
    "stock_exchange":  f"{DART_BASE}/stkExtrDecsn.json",             # 2020053
}

# 보고서명 키워드 → decision_type 매핑 (긴 키워드부터 매칭)
_DECISION_NAME_MAP = [
    ("타법인주식및출자증권양수결정", "stock_acq"),
    ("타법인주식및출자증권양도결정", "stock_div"),
    ("주권관련사채권양수결정",       "bond_acq"),
    ("주권관련사채권양도결정",       "bond_div"),
    ("유형자산양수결정",             "tangible_acq"),
    ("유형자산양도결정",             "tangible_div"),
    ("회사분할합병결정",             "demerger_merger"),
    ("주식교환이전결정",             "stock_exchange"),
    ("회사합병결정",                 "merger"),
    ("회사분할결정",                 "demerger"),
    ("영업양수결정",                 "business_acq"),
    ("영업양도결정",                 "business_div"),
]


def _to_int_safe(v) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(str(v).replace(",", "").replace(" ", ""))
    except (ValueError, TypeError):
        return 0


def _normalize_fund_usage(item: dict, kind: str, year: int) -> dict:
    """공모(rs_*)/사모(mtrpt_*)/구필드를 통합 스키마로 정규화."""
    plan_useprps = (
        item.get("rs_cptal_use_plan_useprps")
        or item.get("mtrpt_cptal_use_plan_useprps")
        or item.get("cptal_use_plan")
        or item.get("on_dclrt_cptal_use_plan")
        or ""
    )
    plan_amount = _to_int_safe(
        item.get("rs_cptal_use_plan_prcure_amount")
        or item.get("mtrpt_cptal_use_plan_prcure_amount")
        or item.get("pay_amount")
    )
    real_dtls_cn = (
        item.get("real_cptal_use_dtls_cn")
        or item.get("real_cptal_use_sttus")
        or ""
    )
    return {
        "kind": kind,
        "year": year,
        "tm": str(item.get("tm", "")),
        "pay_de": str(item.get("pay_de", "")),
        "pay_amount": _to_int_safe(item.get("pay_amount")),
        "plan_useprps": str(plan_useprps).strip(),
        "plan_amount": plan_amount,
        "real_dtls_cn": str(real_dtls_cn).strip(),
        "real_dtls_amount": _to_int_safe(item.get("real_cptal_use_dtls_amount")),
        "dffrnc_resn": str(item.get("dffrnc_occrrnc_resn") or "").strip(),
    }


def _detect_fund_anomaly(rec: dict) -> list[str]:
    flags: list[str] = []
    if rec["plan_amount"] > 0 and (
        rec["real_dtls_amount"] == 0 or not rec["real_dtls_cn"]
    ):
        flags.append("FUND_UNREPORTED")
    dffrnc = rec["dffrnc_resn"]
    if dffrnc and any(kw in dffrnc for kw in _FUND_DIVERSION_KEYWORDS):
        flags.append("FUND_DIVERSION")
    return flags


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
            zf = zipfile.ZipFile(io.BytesIO(raw), metadata_encoding="cp949")
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
        _log_dart_status(data.get("status", "?"), f"기업개요 corp_code={corp_code}")
    except Exception as e:
        log.debug("기업 개요 조회 실패 (%s): %s", corp_code, e)
    return {}


# ── 재무제표 조회 ──────────────────────────────────────────────

# 보고서 코드: 11011=사업보고서, 11012=반기, 11013=1분기, 11014=3분기
_REPORT_CODES = {"annual": "11011", "half": "11012", "q1": "11013", "q3": "11014"}
_VALID_REPORT_TYPES = frozenset(_REPORT_CODES)


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
        report_type: "annual", "half", "q1", "q3"

    Returns: [{account_nm, thstrm_amount, frmtrm_amount, bfefrmtrm_amount, ...}]
    """
    if not api_key:
        return []
    if report_type not in _VALID_REPORT_TYPES:
        log.warning("지원하지 않는 report_type: %r (허용값: %s)", report_type, sorted(_VALID_REPORT_TYPES))
        return []
    if not year:
        year = str(datetime.now().year - 1)
    reprt_code = _REPORT_CODES[report_type]

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
        _log_dart_status(data.get("status", "?"), f"재무제표(CFS) corp_code={corp_code}")
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
        _log_dart_status(data.get("status", "?"), f"재무제표(OFS) corp_code={corp_code}")
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
    reprt_code = _REPORT_CODES.get(report_type, _REPORT_CODES["annual"])

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
        _log_dart_status(data.get("status", "?"), "다중재무제표")
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
        else:
            _log_dart_status(data.get("status", "?"), f"최대주주 corp_code={corp_code}")
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
        else:
            _log_dart_status(data.get("status", "?"), f"대량보유 corp_code={corp_code}")
    except Exception as e:
        log.debug("대량보유 조회 실패 (%s): %s", corp_code, e)

    return result


def fetch_executive_compensation(
    corp_code: str,
    api_key: str,
    year: str = "",
    report_type: str = "annual",
) -> dict:
    """DART 임원 보수 현황 통합 조회.

    Returns:
        {
            "high_pay":     [...],  # 5억 이상 고액수령자 (/hmvAuditAllSttus.json)
            "individual":   [...],  # 개인별 보수 현황 (/indvdlByPay.json)
            "unregistered": [...],  # 미등기임원 보수 (/unrstExctvMendngSttus.json)
            "agm_limit":    [...],  # 주총 승인 보수한도 (/hmvAuditIndvdlBySttus.json)
        }
    """
    if not api_key:
        return {"high_pay": [], "individual": [], "unregistered": [], "agm_limit": []}
    if not year:
        year = str(datetime.now().year - 1)
    reprt_code = _REPORT_CODES.get(report_type, "11011")

    params_base = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": year,
        "reprt_code": reprt_code,
    }
    result: dict = {"high_pay": [], "individual": [], "unregistered": [], "agm_limit": []}
    endpoints = [
        ("high_pay", "hmvAuditAllSttus.json"),
        ("individual", "indvdlByPay.json"),
        ("unregistered", "unrstExctvMendngSttus.json"),
        ("agm_limit", "hmvAuditIndvdlBySttus.json"),
    ]
    for key, ep in endpoints:
        try:
            resp = _retry("GET", f"{DART_BASE}/{ep}", params=params_base)
            data = resp.json()
            if data.get("status") == "000":
                result[key] = data.get("list", [])
            else:
                _log_dart_status(data.get("status", "?"), f"{ep} corp_code={corp_code}")
        except Exception as e:
            log.debug("%s 조회 실패 (%s): %s", ep, corp_code, e)
    return result


def fetch_insider_timeline(
    corp_code: str,
    api_key: str,
    lookback_years: int = 2,
) -> list[dict]:
    """DART 5% 대량보유 + 최대주주 변동 시계열 조회.

    여러 연도의 elestock.json / hyslrSttus.json 을 묶어
    보고일 기준 정렬한 목록을 반환한다.

    Returns:
        List of holding records with added "source" key ("elestock"|"hyslr")
    """
    if not api_key:
        return []
    current_year = datetime.now().year
    years = [str(current_year - i) for i in range(lookback_years + 1)]
    reprt_code = "11011"

    records: list[dict] = []

    # 5% 대량보유 (elestock은 전체 이력 반환 — 1회만 호출)
    try:
        resp = _retry(
            "GET", f"{DART_BASE}/elestock.json",
            params={"crtfc_key": api_key, "corp_code": corp_code},
        )
        data = resp.json()
        if data.get("status") == "000":
            for rec in data.get("list", []):
                rec = dict(rec)
                rec["source"] = "elestock"
                records.append(rec)
        else:
            _log_dart_status(data.get("status", "?"), f"elestock corp_code={corp_code}")
    except Exception as e:
        log.debug("elestock 조회 실패 (%s): %s", corp_code, e)

    # 최대주주 현황 (연도별)
    for year in years:
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
                for rec in data.get("list", []):
                    rec = dict(rec)
                    rec["source"] = "hyslr"
                    rec["bsns_year"] = year
                    records.append(rec)
            else:
                _log_dart_status(data.get("status", "?"), f"hyslrSttus year={year} corp_code={corp_code}")
        except Exception as e:
            log.debug("hyslrSttus 조회 실패 year=%s (%s): %s", year, corp_code, e)

    records.sort(key=lambda r: r.get("rcept_dt", r.get("bsns_year", "")), reverse=True)
    return records


def fetch_fund_usage(
    corp_code: str,
    api_key: str,
    lookback_years: int = 3,
) -> list[dict]:
    """공모/사모 자금사용내역(DS002 2020016/17)을 lookback_years만큼 조회해 정규화 반환.

    각 레코드에 `flags` 키(FUND_DIVERSION·FUND_UNREPORTED)가 부착된다.
    API 호출 실패 또는 status!="000"인 연도·보고서 코드는 조용히 스킵한다.
    """
    cache_key = (corp_code, lookback_years)
    cached = _cache_get(_fund_usage_cache, cache_key, _FUND_CACHE_TTL)
    if cached is not None:
        return cached

    from datetime import date
    current_year = date.today().year
    results: list[dict] = []

    for yr in range(current_year - lookback_years, current_year + 1):
        for kind, url in _FUND_USAGE_URLS.items():
            for reprt_code in ("11011", "11012", "11013", "11014"):
                params = {
                    "crtfc_key": api_key,
                    "corp_code": corp_code,
                    "bsns_year": str(yr),
                    "reprt_code": reprt_code,
                }
                try:
                    data = _retry("GET", url, params=params).json()
                except Exception:
                    continue
                if data.get("status") != "000":
                    continue
                for item in data.get("list", []):
                    rec = _normalize_fund_usage(item, kind, yr)
                    rec["flags"] = _detect_fund_anomaly(rec)
                    results.append(rec)

    _cache_set(_fund_usage_cache, cache_key, results, _FUND_CACHE_MAX)
    return results


def resolve_decision_type(report_name: str) -> str:
    """보고서명에서 decision_type을 자동 판별. 판별 실패 시 빈 문자열."""
    import re
    nm = re.sub(r"\[[^\]]*\]", "", report_name or "")
    nm = nm.replace(" ", "").replace("·", "").replace(",", "")
    for keyword, dtype in _DECISION_NAME_MAP:
        if keyword in nm:
            return dtype
    return ""


def _normalize_decision(raw: dict, dtype: str, url: str) -> dict:
    """결정 공시 원본을 공통 스키마로 정규화."""
    counterparty = (
        raw.get("dlptn_cmpnm")
        or raw.get("dlptn_rl_cmpn")
        or raw.get("mg_ctrcmp_cmpnm")
        or raw.get("dvcmp_cmpnm")
        or ""
    )
    amount = _to_int_safe(
        raw.get("inh_pp")
        or raw.get("trf_pp")
        or raw.get("trfg_pp")
        or raw.get("mg_rt")
        or raw.get("dlptn_cpt")
    )
    asset_ratio_raw = (
        raw.get("inhdamount_totalast_rt")
        or raw.get("trfamount_totalast_rt")
        or raw.get("totalast_rt")
        or "0"
    )
    try:
        asset_ratio = float(str(asset_ratio_raw).replace("%", "").strip() or 0)
    except ValueError:
        asset_ratio = 0.0

    related = False
    for k in ("ftc_stt_atn", "rl_cmpn_atn", "speclt_pson_atn"):
        v = str(raw.get(k) or "").strip()
        if v in ("예", "Y", "해당", "있음"):
            related = True
            break
    if not related:
        rel_text = str(raw.get("dlptn_rl_cmpn") or "")
        if any(s in rel_text for s in ("특수관계", "계열회사", "관계회사", "자회사", "최대주주")):
            related = True

    external_eval = str(raw.get("exevl_atn") or "").strip() in (
        "예", "Y", "해당", "실시",
    )

    return {
        "decision_type": dtype,
        "endpoint": url,
        "counterparty": str(counterparty).strip(),
        "amount": amount,
        "asset_ratio": asset_ratio,
        "related_party": related,
        "external_eval": external_eval,
        "bddd": str(raw.get("bddd") or raw.get("dcrdd") or "").strip(),
        "raw": raw,
    }


def _detect_decision_anomaly(result: dict) -> list[str]:
    flags: list[str] = []
    if result["related_party"] and result["asset_ratio"] >= 10.0:
        flags.append("DECISION_RELATED_PARTY")
    if result["asset_ratio"] >= 30.0:
        flags.append("DECISION_OVERSIZED")
    if (not result["external_eval"]) and result["amount"] >= 5_000_000_000:
        flags.append("DECISION_NO_EXTVAL")
    return flags


def fetch_major_decision(
    rcept_no: str,
    api_key: str,
    decision_type: str = "",
) -> dict:
    """DS005 12개 결정 공시를 구조화 필드로 반환. 실패 시 {"error": ...}.

    decision_type 미지정 시 빈 결과를 안내 메시지로 반환한다(rcept_no만으로
    보고서명을 역조회하는 API가 없어 호출자가 명시해야 한다).
    """
    if not isinstance(rcept_no, str) or len(rcept_no) != 14 or not rcept_no.isdigit():
        return {"error": f"rcept_no는 14자리 숫자여야 합니다: {rcept_no!r}"}

    cached = _cache_get(_major_decision_cache, rcept_no, _MAJOR_CACHE_TTL)
    if cached is not None and cached.get("decision_type") == (decision_type or cached.get("decision_type")):
        return cached

    dtype = decision_type
    if not dtype or dtype not in _MAJOR_DECISION_URLS:
        return {
            "error": (
                "decision_type 미지정 또는 알 수 없는 값. 지원 타입: "
                + ", ".join(_MAJOR_DECISION_URLS.keys())
            )
        }

    url = _MAJOR_DECISION_URLS[dtype]
    params = {"crtfc_key": api_key, "rcept_no": rcept_no}
    try:
        data = _retry("GET", url, params=params).json()
    except Exception as e:
        return {"error": f"DART 조회 실패: {e}"}

    if data.get("status") != "000":
        return {
            "error": (
                f"DART status={data.get('status')}: "
                f"{data.get('message', '')}"
            )
        }
    items = data.get("list", [])
    if not items:
        return {"error": "해당 공시에 구조화 데이터가 없습니다."}

    result = _normalize_decision(items[0], dtype, url)
    result["flags"] = _detect_decision_anomaly(result)
    _cache_set(_major_decision_cache, rcept_no, result, _MAJOR_CACHE_MAX)
    return result
