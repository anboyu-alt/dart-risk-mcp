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


def fetch_document_text(rcept_no: str, api_key: str, max_chars: int = 3000) -> str:
    """DART 공시 원문 ZIP에서 텍스트 추출.

    document.xml API → ZIP 해제 → XML/HTML 파싱 → 태그 제거 → 텍스트 반환.
    """
    if not api_key:
        return ""
    try:
        resp = _retry(
            "GET", f"{DART_BASE}/document.xml",
            params={"crtfc_key": api_key, "rcept_no": rcept_no},
            timeout=30,
        )
        if resp.status_code != 200:
            return ""

        ct = resp.headers.get("Content-Type", "")
        if "application/json" in ct or ct.startswith("text/"):
            return ""

        try:
            zf = zipfile.ZipFile(io.BytesIO(resp.content))
        except zipfile.BadZipFile:
            return ""

        xml_content = ""
        for name in zf.namelist():
            if name.lower().endswith((".xml", ".html", ".htm")):
                raw = zf.read(name)
                for enc in ("utf-8", "euc-kr", "cp949"):
                    try:
                        xml_content = raw.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
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
