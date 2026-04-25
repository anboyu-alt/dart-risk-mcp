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

from .signals import CAPITAL_EVENT_KEYS, DILUTIVE_CAPITAL_EVENTS, NON_DILUTIVE_CAPITAL_EVENTS

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

# v0.8.0: 감사의견 이력 엔드포인트 3종 --------------------------------
_AUDIT_OPINION_URLS = {
    "opinion":       f"{DART_BASE}/accnutAdtorNmNdAdtOpinion.json",        # 2020025
    "audit_service": f"{DART_BASE}/adtServcCnclsSttus.json",               # 2020026
    "non_audit":     f"{DART_BASE}/accnutAdtorNonAdtServcCnclsSttus.json", # 2020027
}

_audit_history_cache: dict[tuple, tuple[float, dict]] = {}
_AUDIT_CACHE_MAX = 20
_AUDIT_CACHE_TTL = 600

_NON_AUDIT_THRESHOLD = 0.30   # 비감사용역 비중 30% 이상 경고
_AUDITOR_CHANGE_WINDOW = 3    # 3년 내 2회 이상 교체 경고

# v0.8.0: 미상환 채무증권 잔액 엔드포인트 5종 -------------------------
_DEBT_BALANCE_URLS = {
    "corporate_bond":   f"{DART_BASE}/cprndNrdmpBlce.json",              # 회사채
    "short_term_bond":  f"{DART_BASE}/srtpdPsndbtNrdmpBlce.json",        # 단기사채
    "commercial_paper": f"{DART_BASE}/entrprsBilScritsNrdmpBlce.json",   # 기업어음
    "new_capital":      f"{DART_BASE}/newCaplScritsNrdmpBlce.json",      # 신종자본증권
    "cnd_capital":      f"{DART_BASE}/cndlCaplScritsNrdmpBlce.json",     # 조건부자본증권
}

_debt_balance_cache: dict[tuple, tuple[float, dict]] = {}
_DEBT_CACHE_MAX = 20
_DEBT_CACHE_TTL = 600

_CB_ROLLOVER_YOY_THRESHOLD = 0.10   # 10% 이내 변동 = 평탄
_CB_ROLLOVER_YEARS_REQUIRED = 3     # 3년 연속
_CB_ROLLOVER_EVENTS_REQUIRED = 2    # 같은 기간 CB/BW 발행 2건 이상


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


def fetch_financial_statements_all(
    corp_code: str,
    api_key: str,
    year: str,
    report_type: str = "annual",
    fs_div: str = "CFS",
) -> list[dict]:
    """전체 계정 과목을 반환하는 재무제표 (매출채권·재고자산 등 포함).

    Endpoint: /api/fnlttSinglAcntAll.json
    fnlttSinglAcnt.json이 주요 10개 계정만 반환하는 것과 달리 전체 XBRL 계정 과목을 포함.

    Args:
        corp_code: 8자리 법인코드
        api_key: DART API 키
        year: 사업연도 (예: "2024")
        report_type: "annual" | "half" | "q1" | "q3"
        fs_div: "CFS"(연결) | "OFS"(별도). 연결 우선 시도 후 없으면 호출측에서 OFS 재시도 권장.

    Returns:
        list of account dicts. 실패 시 [].
    """
    if not api_key or not corp_code or not year:
        return []
    if report_type not in _VALID_REPORT_TYPES:
        log.warning("지원하지 않는 report_type: %r (허용값: %s)", report_type, sorted(_VALID_REPORT_TYPES))
        return []
    reprt_code = _REPORT_CODES[report_type]
    try:
        resp = _retry(
            "GET", f"{DART_BASE}/fnlttSinglAcntAll.json",
            params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bsns_year": year,
                "reprt_code": reprt_code,
                "fs_div": fs_div,
            },
            timeout=30,
        )
        data = resp.json()
    except Exception as e:
        log.debug("전체 재무제표 조회 실패 (%s/%s): %s", corp_code, fs_div, e)
        return []
    if data.get("status") != "000":
        _log_dart_status(data.get("status", "?"), f"전체 재무제표({fs_div}) corp_code={corp_code}")
        return []
    return data.get("list", []) or []


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
    """DART 5% 대량보유 + 최대주주(연·분기) + 변동내역 + 임원·주요주주 자기주식 시계열 조회.

    엔드포인트:
      - elestock.json (5% 대량보유, 전체 이력 — 1회 호출)
      - hyslrSttus.json (최대주주 현황, 연·분기별)
      - hyslrChgSttus.json (최대주주 변동현황, 연·분기별) — v0.8.6 신규
      - tesstkAcqsDspsSttus.json (임원·주요주주 자기주식 취득·처분 현황, 연·분기별) — v0.8.6 신규

    분기 reprt_code 4종(11011 사업·11012 반기·11013 1분기·11014 3분기)을
    각 연도별로 모두 호출한다. status≠000 응답은 조용히 스킵한다.

    Returns:
        List of holding records. 각 레코드에 `source` 키:
          "elestock" | "hyslr" | "hyslr_chg" | "exec_treasury"
    """
    if not api_key:
        return []
    current_year = datetime.now().year
    years = [str(current_year - i) for i in range(lookback_years + 1)]
    quarter_codes = ("11011", "11012", "11013", "11014")

    records: list[dict] = []

    # 1) 5% 대량보유 (elestock은 전체 이력 반환 — 1회만 호출)
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

    # 2~4) DS002 정기보고서 형식 — 연도 × 분기 코드 루프
    periodic_endpoints: tuple[tuple[str, str], ...] = (
        ("hyslrSttus", "hyslr"),
        ("hyslrChgSttus", "hyslr_chg"),
        ("tesstkAcqsDspsSttus", "exec_treasury"),
    )
    for year in years:
        for ep_path, source_label in periodic_endpoints:
            for reprt_code in quarter_codes:
                try:
                    resp = _retry(
                        "GET", f"{DART_BASE}/{ep_path}.json",
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
                            rec["source"] = source_label
                            rec["bsns_year"] = year
                            rec["reprt_code"] = reprt_code
                            records.append(rec)
                    else:
                        _log_dart_status(
                            data.get("status", "?"),
                            f"{ep_path} year={year} reprt={reprt_code} corp_code={corp_code}",
                        )
                except Exception as e:
                    log.debug(
                        "%s 조회 실패 year=%s reprt=%s (%s): %s",
                        ep_path, year, reprt_code, corp_code, e,
                    )

    records.sort(key=lambda r: r.get("rcept_dt", r.get("bsns_year", "")), reverse=True)
    return records


# v0.8.6: 임원·대주주 매도 + 인접 부정 공시 패턴 검출용 부정 신호 키 집합
_NEGATIVE_DISCLOSURE_KEYS: frozenset[str] = frozenset({
    "AUDIT", "INSOLVENCY", "EMBEZZLE", "INQUIRY",
    "GOING_CONCERN", "DISCLOSURE_VIOL", "DEBT_RESTR",
})


def detect_insider_pre_disclosure(
    insider_records: list[dict],
    signal_events: list[dict],
    window_days: int = 30,
) -> list[dict]:
    """임원·대주주 매도 직후 ±window_days 내 부정 공시 패턴 검출.

    Args:
        insider_records: track_insider_trading의 시계열 항목.
            각 dict는 holder, rcept_dt(YYYYMMDD), delta_pct(음수=매도, 양수=매수)를 가진다.
        signal_events: match_signals 등으로 추출한 공시 신호 이벤트.
            각 dict는 key(신호 키), rcept_dt(YYYYMMDD)를 가진다.
        window_days: 매도일 기준 전후 윈도우 일수(기본 30).

    Returns:
        flag dict 리스트. 각 항목은
          {"holder": str, "sell_date": str, "delta_pct": float,
           "disclosure_key": str, "disclosure_date": str,
           "report_nm": str, "days_gap": int}
        형식. 매도(delta_pct<0)가 없거나 부정 공시가 윈도우 밖이면 빈 리스트.
    """
    if not insider_records or not signal_events:
        return []

    # YYYYMMDD 문자열 → datetime 파서
    def _parse(d: str) -> datetime | None:
        if not d:
            return None
        s = str(d)[:8]
        if len(s) != 8 or not s.isdigit():
            return None
        try:
            return datetime.strptime(s, "%Y%m%d")
        except ValueError:
            return None

    # 부정 공시만 추려 (날짜, key, report_nm) 튜플로 인덱싱
    negative: list[tuple[datetime, str, str]] = []
    for ev in signal_events:
        if ev.get("key") not in _NEGATIVE_DISCLOSURE_KEYS:
            continue
        d = _parse(ev.get("rcept_dt"))
        if d is None:
            continue
        negative.append((d, ev["key"], ev.get("report_nm", "")))

    if not negative:
        return []

    flags: list[dict] = []
    for rec in insider_records:
        delta = rec.get("delta_pct", 0.0)
        try:
            delta_f = float(delta)
        except (TypeError, ValueError):
            continue
        if delta_f >= 0:
            continue  # 매수 또는 변동 없음 → 패턴 비대상
        sell_date = _parse(rec.get("rcept_dt"))
        if sell_date is None:
            continue
        for disc_date, disc_key, report_nm in negative:
            gap = abs((disc_date - sell_date).days)
            if gap <= window_days:
                flags.append({
                    "holder": rec.get("holder", "미상"),
                    "sell_date": rec.get("rcept_dt", ""),
                    "delta_pct": delta_f,
                    "disclosure_key": disc_key,
                    "disclosure_date": disc_date.strftime("%Y%m%d"),
                    "report_nm": report_nm,
                    "days_gap": gap,
                })
                break  # 같은 매도 이벤트에 대해 중복 플래그 방지
    return flags


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
    corp_code: str = "",
    corp_cls: str = "",  # kept for backward compat, not sent to DART when corp_code provided
) -> dict:
    """DS005 12개 결정 공시를 구조화 필드로 반환. 실패 시 {"error": ...}.

    decision_type 미지정 시 빈 결과를 안내 메시지로 반환한다(rcept_no만으로
    보고서명을 역조회하는 API가 없어 호출자가 명시해야 한다).

    corp_code 제공 시 corp_code+날짜 범위로 조회 후 rcept_no 필터 (DART 필수 파라미터 대응).
    corp_code 미제공 시 rcept_no 단독 조회 시도 (일부 DS005 엔드포인트는 지원).
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
    # DS005 엔드포인트들도 corp_code+날짜 방식이 더 안정적 — corp_code 있으면 활용
    if corp_code and len(rcept_no) >= 8:
        rcpt_date = rcept_no[:8]
        endpoint_path = url.split("/api/", 1)[-1]  # e.g. "bsnInhDecsn.json"
        params = {"crtfc_key": api_key, "corp_code": corp_code,
                  "bgn_de": rcpt_date, "end_de": rcpt_date}
        try:
            data = _retry("GET", url, params=params).json()
        except Exception as e:
            return {"error": f"DART 조회 실패: {e}"}
        if data.get("status") == "000":
            lst = data.get("list") or []
            matched = [r for r in lst if r.get("rcept_no") == rcept_no]
            if matched:
                result = _normalize_decision(matched[0], dtype, url)
                result["flags"] = _detect_decision_anomaly(result)
                _cache_set(_major_decision_cache, rcept_no, result, _MAJOR_CACHE_MAX)
                return result
            # corp_code 조회로 해당 날짜 데이터는 있으나 이 rcept_no가 없음
            return {"error": "해당 공시에 구조화 데이터가 없습니다."}
        # status 비정상 — rcept_no 단독 폴백 시도
        _log_dart_status(data.get("status", "?"), f"{dtype} corp={corp_code} rcept={rcept_no}")

    # corp_code 없거나 corp_code 조회 실패 → rcept_no 단독 시도 (일부 DS005 지원)
    params_fallback = {"crtfc_key": api_key, "rcept_no": rcept_no}
    try:
        data = _retry("GET", url, params=params_fallback).json()
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


def detect_capital_churn(events: list[dict], lookback_years: int) -> dict:
    """
    12개월 슬라이딩 윈도우 판정:
      (A) 희석성 자본 이벤트 ≥ 3건 → CAPITAL_CHURN
      (B) 희석성 ≥ 2건 AND 비희석성 ≥ 2건 → CAPITAL_CHURN
      그 외(비희석성만 반복, 부족) → 플래그 없음

    Args:
        events: match_signals 반환 이벤트 리스트. 각 항목은
                {"key", "rcept_dt" (YYYYMMDD), "is_amendment", ...}.
        lookback_years: 조회 기간(년). 메타에만 기록.

    Returns:
        {
            "max_12m_count": int,          # 전체 자본 이벤트 12개월 최대 카운트
            "max_dilutive_12m": int,       # 희석성 12개월 최대 카운트
            "max_non_dilutive_12m": int,   # 비희석성 12개월 최대 카운트
            "total_events": int,
            "by_year": dict[str, int],
            "events": list[dict],
            "flags": list[str],
            "lookback_years": int,
        }
    """
    # 1) 자본 이벤트만 필터 + 정정공시 제외
    caps: list[dict] = []
    for e in events or []:
        if e.get("key") not in CAPITAL_EVENT_KEYS:
            continue
        if e.get("is_amendment"):
            continue
        caps.append(e)

    # 2) rcept_dt 오름차순 정렬
    caps.sort(key=lambda e: (e.get("rcept_dt") or "00000000"))

    # 3) 날짜 파싱 (잘못된 포맷은 스킵). 각 이벤트의 희석/비희석 속성 보존.
    parsed: list[tuple[datetime, str, bool]] = []  # (date, key, is_dilutive)
    for e in caps:
        raw = (e.get("rcept_dt") or "")[:8]
        try:
            d = datetime.strptime(raw, "%Y%m%d")
        except ValueError:
            continue
        key = e.get("key") or ""
        parsed.append((d, key, key in DILUTIVE_CAPITAL_EVENTS))

    # 4) 365일 슬라이딩 윈도우에서 전체/희석/비희석 최대 카운트
    max_total = 0
    max_dil = 0
    max_non = 0
    window_hits: list[tuple[int, int]] = []  # (dil, non) per window
    for i, (start, _, _) in enumerate(parsed):
        end = start + timedelta(days=365)
        dil = 0
        non = 0
        for d, _, is_dil in parsed[i:]:
            if start <= d <= end:
                if is_dil:
                    dil += 1
                else:
                    non += 1
        tot = dil + non
        if tot > max_total:
            max_total = tot
        if dil > max_dil:
            max_dil = dil
        if non > max_non:
            max_non = non
        window_hits.append((dil, non))

    # 5) 연도별 집계
    by_year: dict[str, int] = {}
    for e in caps:
        y = (e.get("rcept_dt") or "")[:4]
        if y:
            by_year[y] = by_year.get(y, 0) + 1

    # 6) 플래그 판정 — 단일 윈도우 내에서 조건 (A) 또는 (B) 충족 여부
    flagged = False
    for dil, non in window_hits:
        if dil >= 3:
            flagged = True
            break
        if dil >= 2 and non >= 2:
            flagged = True
            break
    flags = ["CAPITAL_CHURN"] if flagged else []

    return {
        "max_12m_count": max_total,
        "max_dilutive_12m": max_dil,
        "max_non_dilutive_12m": max_non,
        "total_events": len(caps),
        "by_year": by_year,
        "events": caps,
        "flags": flags,
        "lookback_years": lookback_years,
    }


_FS_ALIASES = {
    "매출": ["매출액", "영업수익"],
    "매출채권": ["매출채권", "매출채권및기타채권"],
    "재고자산": ["재고자산"],
    "영업현금흐름": ["영업활동현금흐름", "영업활동으로인한현금흐름"],
    "당기순이익": ["당기순이익", "당기순이익(손실)"],
    "자본총계": ["자본총계"],
    "자본금": ["자본금"],
}


def _pick_account(fs: dict, names: list[str]):
    """fs dict에서 names 우선순위대로 첫 유효 값을 반환. 없으면 None."""
    for n in names:
        v = fs.get(n)
        if v is not None:
            return v
    return None


def detect_financial_anomaly(
    current: dict,
    prior: dict,
    current_indx: dict | None = None,
    prior_indx: dict | None = None,
) -> tuple[list[str], list[dict]]:
    """
    당기·전기 재무 dict를 받아 4개 이상 지표 판정.

    Args:
        current: 당기 재무 {account_nm: int, ...}
        prior: 전기 재무 {account_nm: int, ...}
        current_indx: (v0.8.8) 당기 fnlttSinglIndx 결과 {idx_nm: float, ...}.
        prior_indx: (v0.8.8) 전기 fnlttSinglIndx 결과. 둘 다 주어지면
            핵심 지표 7종에 대한 YoY 변동률 metric을 추가한다(절대 임계 없음, flagged=False).

    Returns:
        (flags, metrics)
        flags: ["AR_SURGE", "INVENTORY_SURGE", "CASH_GAP", "CAPITAL_IMPAIRMENT"] 부분집합
        metrics: [{"name", "current", "prior", "delta", "unit", "flagged"} ...]
                 v0.8.8: indx 기반 항목은 source="indx", delta_pct(float|None) 키를 가짐.
    """
    flags: list[str] = []
    metrics: list[dict] = []

    rev_c = _pick_account(current, _FS_ALIASES["매출"])
    rev_p = _pick_account(prior, _FS_ALIASES["매출"])
    ar_c = _pick_account(current, _FS_ALIASES["매출채권"])
    ar_p = _pick_account(prior, _FS_ALIASES["매출채권"])
    inv_c = _pick_account(current, _FS_ALIASES["재고자산"])
    inv_p = _pick_account(prior, _FS_ALIASES["재고자산"])
    ni_c = _pick_account(current, _FS_ALIASES["당기순이익"])
    ocf_c = _pick_account(current, _FS_ALIASES["영업현금흐름"])
    eq_c = _pick_account(current, _FS_ALIASES["자본총계"])
    cap_c = _pick_account(current, _FS_ALIASES["자본금"])

    # AR_SURGE
    if rev_c and rev_p and ar_c is not None and ar_p is not None and rev_c > 0 and rev_p > 0:
        r_c = ar_c / rev_c * 100
        r_p = ar_p / rev_p * 100
        delta = r_c - r_p
        m = {"name": "매출채권/매출", "current": r_c, "prior": r_p, "delta": delta, "unit": "%", "flagged": False}
        if delta >= 10:
            flags.append("AR_SURGE")
            m["flagged"] = True
        metrics.append(m)

    # INVENTORY_SURGE
    if rev_c and rev_p and inv_c is not None and inv_p is not None and rev_c > 0 and rev_p > 0:
        r_c = inv_c / rev_c * 100
        r_p = inv_p / rev_p * 100
        delta = r_c - r_p
        m = {"name": "재고자산/매출", "current": r_c, "prior": r_p, "delta": delta, "unit": "%", "flagged": False}
        if delta >= 10:
            flags.append("INVENTORY_SURGE")
            m["flagged"] = True
        metrics.append(m)

    # CASH_GAP
    if ni_c is not None and ocf_c is not None:
        m = {"name": "순이익 vs 영업현금흐름", "current_ni": ni_c, "current_ocf": ocf_c, "flagged": False}
        if ni_c > 0 and ocf_c < 0:
            flags.append("CASH_GAP")
            m["flagged"] = True
        metrics.append(m)

    # CAPITAL_IMPAIRMENT
    if eq_c is not None and cap_c is not None and cap_c > 0:
        ratio = eq_c / cap_c * 100
        m = {"name": "자본총계/자본금", "current": ratio, "unit": "%", "flagged": False}
        if ratio < 200:
            flags.append("CAPITAL_IMPAIRMENT")
            m["flagged"] = True
        metrics.append(m)

    # v0.8.8: fnlttSinglIndx YoY 추세 (절대 임계 없음, 사실 표기만)
    if current_indx and prior_indx:
        for idx_nm in _CORE_INDX_NAMES:
            cv = current_indx.get(idx_nm)
            pv = prior_indx.get(idx_nm)
            if cv is None or pv is None:
                continue
            try:
                cv_f = float(cv)
                pv_f = float(pv)
            except (TypeError, ValueError):
                continue
            unit = _INDX_UNIT.get(idx_nm, "%")
            delta_pct: float | None
            if pv_f == 0:
                delta_pct = None
            else:
                delta_pct = (cv_f - pv_f) / abs(pv_f) * 100
            metrics.append({
                "name": idx_nm,
                "source": "indx",
                "current": cv_f,
                "prior": pv_f,
                "delta_pct": delta_pct,
                "unit": unit,
                "flagged": False,
            })

    return flags, metrics


# v0.8.8: fnlttSinglIndx 핵심 지표 7종 (사용자 출력에 표기) -----------------
_CORE_INDX_NAMES: tuple[str, ...] = (
    "순이익률",
    "자기자본비율",
    "부채비율",
    "유동비율",
    "매출액증가율(YoY)",
    "매출채권회전율",
    "재고자산회전율",
)

_INDX_UNIT: dict[str, str] = {
    "순이익률": "%",
    "자기자본비율": "%",
    "부채비율": "%",
    "유동비율": "%",
    "매출액증가율(YoY)": "%",
    "매출채권회전율": "회",
    "재고자산회전율": "회",
}


def _fs_response_to_periods(fs_data: dict) -> tuple[dict, dict]:
    """
    fetch_financial_statements 응답(list of account items) → (current, prior) 두 기간 dict.

    DART fnlttSinglAcnt.json 응답은 {"status": "000", "list": [{"account_nm": "매출액",
    "thstrm_amount": "12,345", "frmtrm_amount": "10,000", ...}, ...]}.
    연결(CFS) 우선, 없으면 별도(OFS) 값을 채움.
    """
    current: dict = {}
    prior: dict = {}

    def _parse(s):
        if s is None:
            return None
        s = str(s).replace(",", "").replace(" ", "").strip()
        if not s or s in ("-", "null"):
            return None
        # 괄호는 음수 표기
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        try:
            return int(s)
        except ValueError:
            try:
                return int(float(s))
            except ValueError:
                return None

    for item in fs_data.get("list", []) if isinstance(fs_data, dict) else []:
        name = (item.get("account_nm") or "").strip()
        if not name:
            continue
        cur_v = _parse(item.get("thstrm_amount"))
        pri_v = _parse(item.get("frmtrm_amount"))
        # 이미 채워진 키는 덮어쓰지 않음 (CFS가 먼저 나오는 DART 관행 활용)
        if cur_v is not None and name not in current:
            current[name] = cur_v
        if pri_v is not None and name not in prior:
            prior[name] = pri_v
    return current, prior


def _fetch_decision_filtered(endpoint: str, rcept_no: str, api_key: str, corp_code: str) -> dict:
    """공통 헬퍼: corp_code + rcept_date 범위로 결정공시 엔드포인트를 조회하고 rcept_no로 필터.

    DART의 cvbdIsDecsn / bdwtIsDecsn / piicDecsn 등은 rcept_no 단독 조회를 지원하지 않아
    status:100 필수값 누락 오류를 반환한다. corp_code + bgn_de + end_de (날짜 = rcept_no 앞 8자리)
    로 조회한 뒤, 결과를 rcept_no로 필터링한다.

    반환 dict에는 원본 응답에서 list만 rcept_no 매치 결과로 교체. 실패/빈 응답 시 {}.
    """
    if not api_key or not corp_code or not rcept_no or len(rcept_no) < 8:
        return {}
    rcpt_date = rcept_no[:8]
    url = f"{DART_BASE}/{endpoint}"
    params = {"crtfc_key": api_key, "corp_code": corp_code,
              "bgn_de": rcpt_date, "end_de": rcpt_date}
    try:
        resp = _retry("get", url, params=params, timeout=10)
        data = resp.json()
        if data.get("status") != "000":
            _log_dart_status(data.get("status", "?"), f"{endpoint} rcept={rcept_no}")
            return {}
        lst = data.get("list") or []
        matched = [r for r in lst if r.get("rcept_no") == rcept_no]
        return {**data, "list": matched} if matched else {}
    except Exception as e:
        log.debug("%s 조회 실패 (rcept=%s corp=%s): %s", endpoint, rcept_no, corp_code, e)
        return {}


def fetch_cb_issue_decision(rcept_no: str, api_key: str, corp_code: str = "") -> dict:
    """
    /api/cvbdIsDecsn.json — 전환사채권 발행결정 공시 상세.

    corp_code 지정 시 corp_code+날짜 범위로 조회 후 rcept_no 필터(DART 필수 파라미터 대응).
    corp_code 미지정 시 빈 dict 반환 (HTML 폴백으로 진행).
    Returns full response dict on success, empty dict on any error/non-000 status.
    """
    if not corp_code:
        return {}
    return _fetch_decision_filtered("cvbdIsDecsn.json", rcept_no, api_key, corp_code)


def fetch_bw_issue_decision(rcept_no: str, api_key: str, corp_code: str = "") -> dict:
    """/api/bdwtIsDecsn.json — 신주인수권부사채권 발행결정 공시 상세.

    corp_code 지정 시 corp_code+날짜 범위로 조회 후 rcept_no 필터.
    """
    if not corp_code:
        return {}
    return _fetch_decision_filtered("bdwtIsDecsn.json", rcept_no, api_key, corp_code)


def fetch_eb_issue_decision(rcept_no: str, api_key: str, corp_code: str = "") -> dict:
    """/api/exbdIsDecsn.json — 교환사채권 발행결정 공시 상세.

    corp_code 지정 시 corp_code+날짜 범위로 조회 후 rcept_no 필터.
    """
    if not corp_code:
        return {}
    return _fetch_decision_filtered("exbdIsDecsn.json", rcept_no, api_key, corp_code)


def fetch_piic_decision(rcept_no: str, api_key: str, corp_code: str = "") -> dict:
    """/api/piicDecsn.json — 유상증자 결정 공시 상세.

    corp_code 지정 시 corp_code+날짜 범위로 조회 후 rcept_no 필터.
    """
    if not corp_code:
        return {}
    return _fetch_decision_filtered("piicDecsn.json", rcept_no, api_key, corp_code)


def fetch_fric_decision(rcept_no: str, api_key: str, corp_code: str = "") -> dict:
    """/api/fricDecsn.json — 무상증자 결정 공시 상세.

    corp_code 지정 시 corp_code+날짜 범위로 조회 후 rcept_no 필터.
    """
    if not corp_code:
        return {}
    return _fetch_decision_filtered("fricDecsn.json", rcept_no, api_key, corp_code)


def fetch_pifric_decision(rcept_no: str, api_key: str, corp_code: str = "") -> dict:
    """/api/pifricDecsn.json — 유무상증자 결정 공시 상세.

    corp_code 지정 시 corp_code+날짜 범위로 조회 후 rcept_no 필터.
    """
    if not corp_code:
        return {}
    return _fetch_decision_filtered("pifricDecsn.json", rcept_no, api_key, corp_code)


# ═══════════════════════════════════════════════════════════════════
# v0.8.0: 감사의견 이력 + 미상환 채무증권 잔액 (구조화 엔드포인트)
# ═══════════════════════════════════════════════════════════════════

def _safe_int(v) -> int | None:
    """문자열/None → int. 콤마·공백 제거. 실패 시 None."""
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    if not s or s in {"-", "N/A"}:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def _safe_int_from_de(de: str) -> int | None:
    """'YYYY-MM-DD' 또는 'YYYYMMDD' → 연도(int). 실패 시 None."""
    if not de:
        return None
    s = str(de).replace("-", "").replace(".", "")[:4]
    return _safe_int(s)


def fetch_audit_opinion_history(
    corp_code: str,
    api_key: str,
    lookback_years: int = 5,
) -> dict:
    """감사의견·감사인 교체·비감사용역 통합 조회.

    3개 엔드포인트(`accnutAdtorNmNdAdtOpinion`, `adtServcCnclsSttus`,
    `accnutAdtorNonAdtServcCnclsSttus`)를 결합해 연도별 감사의견·감사인·
    보수를 한 dict로 반환합니다. 일부 엔드포인트가 실패해도 남은 값으로
    구성해 graceful degradation.

    반환:
        {
            "opinions": [{"year": int, "opinion": str, "auditor": str,
                          "tenure_years": int, "audit_fee_okwon": int,
                          "non_audit_fee_okwon": int}],
            "auditor_changes": [{"from_year": int, "to_year": int,
                                 "from": str, "to": str}],
            "independence_warnings": [str, ...],
        }
    """
    empty = {"opinions": [], "auditor_changes": [], "independence_warnings": []}
    if not corp_code or not api_key:
        return empty

    if not isinstance(lookback_years, int) or not (1 <= lookback_years <= 10):
        lookback_years = 5

    cache_key = (corp_code, lookback_years)
    cached = _cache_get(_audit_history_cache, cache_key, _AUDIT_CACHE_TTL)
    if cached is not None:
        return cached

    current_year = datetime.now().year
    cutoff = current_year - lookback_years

    # DART 엔드포인트는 bsns_year+reprt_code 필수: 연도×엔드포인트 루프
    raw: dict[str, list] = {k: [] for k in _AUDIT_OPINION_URLS}
    for year_int in range(cutoff + 1, current_year + 1):
        for kind, url in _AUDIT_OPINION_URLS.items():
            try:
                resp = _retry("GET", url, params={
                    "crtfc_key": api_key,
                    "corp_code": corp_code,
                    "bsns_year": str(year_int),
                    "reprt_code": "11011",
                }, timeout=15)
                data = resp.json() if resp is not None else {}
                if data.get("status") == "000":
                    raw[kind].extend(data.get("list", []))
            except Exception:
                continue

    def _year_of_item(item: dict) -> int | None:
        """DART 응답의 bsns_year는 '제34기(당기)' 같은 한글 표현이므로
        stlm_dt(결산일)에서 연도를 추출한다. 폴백으로 bsns_year 숫자 시도."""
        y = _safe_int_from_de(item.get("stlm_dt", ""))
        if y is not None:
            return y
        return _safe_int(item.get("bsns_year"))

    by_year: dict[int, dict] = {}
    for item in raw.get("opinion", []):
        y = _year_of_item(item)
        if y is None or y < cutoff:
            continue
        by_year.setdefault(y, {"year": y})
        # 동일 연도 내 (연결/별도) 중복 엔트리 중 비어있지 않은 값을 우선
        op_new = (item.get("adt_opinion") or "").strip()
        ad_new = (item.get("adtor") or "").strip()
        if op_new and not by_year[y].get("opinion"):
            by_year[y]["opinion"] = op_new
        elif "opinion" not in by_year[y]:
            by_year[y]["opinion"] = op_new
        if ad_new and not by_year[y].get("auditor"):
            by_year[y]["auditor"] = ad_new
        elif "auditor" not in by_year[y]:
            by_year[y]["auditor"] = ad_new

    # DART servc_mendng는 '130,000200,000600,000\n9.600' 처럼 값이 공백 없이
    # 뭉쳐 있어 안전한 숫자 파싱이 불가능하다. v0.8.0에서는 non_audit 금액을
    # 집계하지 않고 계약 존재 여부만 카운트한다. 정교한 파싱은 v0.8.1.
    _NON_AUDIT_MAX_PER_ITEM = 10_000_000_000  # 1조원 초과 = 파싱 오류로 간주

    def _extract_numbers(s) -> list[int]:
        if s is None:
            return []
        import re
        # 각 라인/공백을 분리자로 사용, 라인 내 콤마-숫자 그룹만 단일 값으로 인정
        out: list[int] = []
        for line in re.split(r"[\s\n]+", str(s)):
            m = re.fullmatch(r"[\d,]+(?:\.\d+)?", line)
            if not m:
                continue
            n = _safe_int(line)
            if n is not None and 0 < n < _NON_AUDIT_MAX_PER_ITEM:
                out.append(n)
        return out

    for item in raw.get("audit_service", []):
        y = _year_of_item(item)
        if y is None or y < cutoff:
            continue
        by_year.setdefault(y, {"year": y, "opinion": "", "auditor": ""})
        # mendng='-'인 경우 계약/실제집행 보수 필드로 폴백
        fee = (_safe_int(item.get("mendng"))
               or _safe_int(item.get("adt_cntrct_dtls_mendng"))
               or _safe_int(item.get("real_exc_dtls_mendng"))
               or 0)
        if fee > by_year[y].get("audit_fee_okwon", 0):
            by_year[y]["audit_fee_okwon"] = fee

    non_audit_by_year: dict[int, int] = {}
    for item in raw.get("non_audit", []):
        y = _safe_int_from_de(item.get("cntrct_cncls_de", ""))
        if y is None or y < cutoff:
            continue
        # mendng 단일 값이 없으면 servc_mendng 다중 값의 합계 사용
        direct = _safe_int(item.get("mendng"))
        if direct is not None:
            amount = direct
        else:
            amount = sum(_extract_numbers(item.get("servc_mendng")))
        non_audit_by_year[y] = non_audit_by_year.get(y, 0) + amount
    for y, amount in non_audit_by_year.items():
        by_year.setdefault(y, {"year": y, "opinion": "", "auditor": ""})
        by_year[y]["non_audit_fee_okwon"] = amount

    # opinions(최신 순) + tenure_years
    opinions = []
    for y in sorted(by_year.keys(), reverse=True):
        e = by_year[y]
        opinions.append({
            "year": e.get("year", y),
            "opinion": e.get("opinion", ""),
            "auditor": e.get("auditor", ""),
            "tenure_years": 0,
            "audit_fee_okwon": e.get("audit_fee_okwon", 0),
            "non_audit_fee_okwon": e.get("non_audit_fee_okwon", 0),
        })
    # 과거→최신 방향으로 같은 감사인 연속 횟수 누적
    asc_for_tenure = sorted(opinions, key=lambda x: x["year"])
    prev_auditor = None
    run = 0
    tenure_by_year: dict[int, int] = {}
    for o in asc_for_tenure:
        if o["auditor"] and o["auditor"] == prev_auditor:
            run += 1
        else:
            run = 1
        tenure_by_year[o["year"]] = run
        prev_auditor = o["auditor"]
    for o in opinions:
        o["tenure_years"] = tenure_by_year.get(o["year"], 0)

    # 감사인 교체 이벤트(과거 → 최신)
    auditor_changes = []
    asc = sorted(opinions, key=lambda x: x["year"])
    for i in range(1, len(asc)):
        prev_a = asc[i-1]["auditor"]
        cur_a = asc[i]["auditor"]
        if prev_a and cur_a and prev_a != cur_a:
            auditor_changes.append({
                "from_year": asc[i-1]["year"],
                "to_year": asc[i]["year"],
                "from": prev_a,
                "to": cur_a,
            })

    # 독립성 경고
    warnings: list[str] = []
    for o in opinions:
        af = o.get("audit_fee_okwon", 0)
        naf = o.get("non_audit_fee_okwon", 0)
        if af + naf > 0:
            ratio = naf / (af + naf)
            if ratio >= _NON_AUDIT_THRESHOLD:
                warnings.append(f"{o['year']} 비감사용역 비중 {int(ratio*100)}%")

    result = {
        "opinions": opinions,
        "auditor_changes": auditor_changes,
        "independence_warnings": warnings,
    }
    _cache_set(_audit_history_cache, cache_key, result, _AUDIT_CACHE_MAX)
    return result


def fetch_debt_balance(
    corp_code: str,
    api_key: str,
    year: str = "",
) -> dict:
    """채무증권 5종 미상환 잔액 통합.

    5개 엔드포인트(`cprndNrdmpBlce`, `srtpdPsndbtNrdmpBlce`,
    `entrprsBilScritsNrdmpBlce`, `newCaplScritsNrdmpBlce`,
    `cndlCaplScritsNrdmpBlce`)를 합산해 채무증권 종류별 잔액과 만기
    구간을 반환. 일부 실패해도 graceful degradation.

    반환:
        {
            "year": int,
            "by_kind": {"corporate_bond": {"total": int, "maturity_under_1y": int}, ...},
            "total": int,
            "maturity_1y_share": float,
            "equity_ratio": float | None,
        }
    """
    empty = {"year": None, "by_kind": {}, "total": 0,
             "maturity_1y_share": 0.0, "equity_ratio": None}
    if not corp_code or not api_key:
        return empty

    if not year:
        year = str(datetime.now().year - 1)

    cache_key = (corp_code, year)
    cached = _cache_get(_debt_balance_cache, cache_key, _DEBT_CACHE_TTL)
    if cached is not None:
        return cached

    by_kind: dict[str, dict] = {}
    total = 0
    maturity_1y = 0

    for kind, url in _DEBT_BALANCE_URLS.items():
        try:
            resp = _retry("GET", url, params={
                "crtfc_key": api_key,
                "corp_code": corp_code,
                "bsns_year": year,
                "reprt_code": "11011",  # 사업보고서
            }, timeout=15)
            data = resp.json() if resp is not None else {}
        except Exception:
            continue
        if data.get("status") != "000":
            continue

        kind_total = 0
        kind_1y = 0
        for item in data.get("list", []):
            amt = _safe_int(item.get("remndr_amount")) or 0
            kind_total += amt
            within = _safe_int(item.get("remndr_within1y_amount")) or 0
            kind_1y += within

        if kind_total > 0:
            by_kind[kind] = {"total": kind_total, "maturity_under_1y": kind_1y}
            total += kind_total
            maturity_1y += kind_1y

    maturity_share = maturity_1y / total if total > 0 else 0.0
    result = {
        "year": _safe_int(year),
        "by_kind": by_kind,
        "total": total,
        "maturity_1y_share": maturity_share,
        "equity_ratio": None,
    }
    _cache_set(_debt_balance_cache, cache_key, result, _DEBT_CACHE_MAX)
    return result


def detect_debt_rollover(
    balances: list[tuple[int, int]],
    events: list[dict],
) -> str | None:
    """3년 연속 잔액 YoY <10% AND 같은 기간 CB/BW 발행 ≥2건 → 'CB_ROLLOVER'.

    Args:
        balances: [(year, total_balance), ...] 최소 3개 연도.
        events: 자본 이벤트 목록. 각 항목은 "key"·"rcept_dt" 필드 필요.

    Returns:
        조건 충족 시 문자열 "CB_ROLLOVER", 아니면 None.
    """
    if len(balances) < _CB_ROLLOVER_YEARS_REQUIRED:
        return None

    asc = sorted(balances, key=lambda x: x[0])
    recent = asc[-_CB_ROLLOVER_YEARS_REQUIRED:]

    for i in range(1, len(recent)):
        prev = recent[i-1][1]
        cur = recent[i][1]
        if prev <= 0:
            return None
        yoy = abs(cur - prev) / prev
        if yoy >= _CB_ROLLOVER_YOY_THRESHOLD:
            return None

    start_year = recent[0][0]
    cb_events = [
        e for e in events
        if e.get("key") == "CB_BW"
        and _safe_int_from_de(e.get("rcept_dt", "")) is not None
        and (_safe_int_from_de(e.get("rcept_dt", "")) or 0) >= start_year
    ]
    if len(cb_events) < _CB_ROLLOVER_EVENTS_REQUIRED:
        return None

    return "CB_ROLLOVER"


# v0.8.7: 자사주 결정 4종 통합 ---------------------------------------
_TREASURY_DECISION_ENDPOINTS: tuple[tuple[str, str, str, str], ...] = (
    # (path, key, decision_type, 한글 라벨)
    ("tsstkAqDecsn",         "TREASURY",       "acq",        "자사주 취득 결정"),
    ("tsstkDpDecsn",         "TREASURY",       "disp",       "자사주 처분 결정"),
    ("tsstkAqTrctrCnsDecsn", "TREASURY_TRUST", "trust_cons", "자사주 신탁계약 체결"),
    ("tsstkAqTrctrCcDecsn",  "TREASURY_TRUST", "trust_canc", "자사주 신탁계약 해지"),
)

_treasury_decisions_cache: dict[tuple, tuple[float, list]] = {}
_TREASURY_CACHE_MAX = 20
_TREASURY_CACHE_TTL = 600  # 10분


def fetch_treasury_decisions(
    corp_code: str,
    api_key: str,
    lookback_years: int = 3,
) -> list[dict]:
    """자사주 취득·처분·신탁 결정 4개 엔드포인트 통합 조회 (v0.8.7).

    매핑:
      - tsstkAqDecsn         → key=TREASURY,       decision_type=acq        (자사주 취득)
      - tsstkDpDecsn         → key=TREASURY,       decision_type=disp       (자사주 처분)
      - tsstkAqTrctrCnsDecsn → key=TREASURY_TRUST, decision_type=trust_cons (신탁 체결)
      - tsstkAqTrctrCcDecsn  → key=TREASURY_TRUST, decision_type=trust_canc (신탁 해지)

    각 이벤트:
        {
          "key":            "TREASURY" | "TREASURY_TRUST",
          "decision_type":  "acq" | "disp" | "trust_cons" | "trust_canc",
          "rcept_no":       "YYYYMMDDxxxxxx",
          "rcept_dt":       "YYYYMMDD" (응답 누락 시 rcept_no[:8]로 폴백),
          "report_nm":      "자사주 취득 결정" 등 한글 라벨,
          "raw":            원본 응답 dict,
        }

    빈 corp_code/api_key는 빈 리스트. 일부 엔드포인트 실패는 다른 이벤트를 막지 않는다.
    """
    if not corp_code or not api_key:
        return []

    cache_key = (corp_code, lookback_years)
    cached = _cache_get(_treasury_decisions_cache, cache_key, _TREASURY_CACHE_TTL)
    if cached is not None:
        return cached

    end = datetime.now()
    start = end - timedelta(days=max(1, lookback_years) * 365)
    bgn_de = start.strftime("%Y%m%d")
    end_de = end.strftime("%Y%m%d")

    events: list[dict] = []
    for ep_path, key, dtype, label in _TREASURY_DECISION_ENDPOINTS:
        try:
            resp = _retry(
                "GET", f"{DART_BASE}/{ep_path}.json",
                params={
                    "crtfc_key": api_key,
                    "corp_code": corp_code,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                },
            )
            data = resp.json()
            if data.get("status") != "000":
                _log_dart_status(data.get("status", "?"),
                                 f"{ep_path} corp_code={corp_code}")
                continue
            for item in data.get("list") or []:
                rcept_no = (item.get("rcept_no") or "").strip()
                rcept_dt = (item.get("rcept_dt") or "").strip()
                if not rcept_dt and len(rcept_no) >= 8 and rcept_no[:8].isdigit():
                    rcept_dt = rcept_no[:8]
                if not rcept_dt or len(rcept_dt) < 8:
                    continue
                events.append({
                    "key": key,
                    "decision_type": dtype,
                    "rcept_no": rcept_no,
                    "rcept_dt": rcept_dt[:8],
                    "report_nm": item.get("report_nm") or label,
                    "raw": item,
                })
        except Exception as e:
            log.debug("%s 조회 실패 (%s): %s", ep_path, corp_code, e)

    events.sort(key=lambda e: e["rcept_dt"])
    _cache_set(_treasury_decisions_cache, cache_key, events, _TREASURY_CACHE_MAX)
    return events


# v0.8.8: fnlttSinglIndx (단일회사 주요 재무지표) 통합 ----------------------
_INDX_CL_CODES: tuple[str, ...] = (
    "M210000",  # 수익성
    "M220000",  # 안정성
    "M230000",  # 성장성
    "M240000",  # 활동성
)

_company_indicators_cache: dict[tuple, tuple[float, dict]] = {}
_INDX_CACHE_MAX = 40
_INDX_CACHE_TTL = 600  # 10분


def fetch_company_indicators(
    corp_code: str,
    api_key: str,
    bsns_year: str,
    reprt_code: str = "11011",
) -> dict[str, float]:
    """단일회사 주요 재무지표(`fnlttSinglIndx`)를 4개 카테고리로 호출해 합친다.

    카테고리:
      - M210000 수익성 (순이익률 등)
      - M220000 안정성 (자기자본비율·부채비율·유동비율 등)
      - M230000 성장성 (매출액증가율 등)
      - M240000 활동성 (매출채권회전율·재고자산회전율 등)

    Returns:
        {idx_nm: float, ...} flat dict. idx_val이 None이거나 숫자 변환 불가한
        항목은 제외. 일부 cl_code 실패는 다른 결과를 막지 않는다.
    """
    if not corp_code or not api_key or not bsns_year:
        return {}

    cache_key = (corp_code, bsns_year, reprt_code)
    cached = _cache_get(_company_indicators_cache, cache_key, _INDX_CACHE_TTL)
    if cached is not None:
        return cached

    merged: dict[str, float] = {}
    for cl in _INDX_CL_CODES:
        try:
            resp = _retry(
                "GET", f"{DART_BASE}/fnlttSinglIndx.json",
                params={
                    "crtfc_key": api_key,
                    "corp_code": corp_code,
                    "bsns_year": bsns_year,
                    "reprt_code": reprt_code,
                    "idx_cl_code": cl,
                },
            )
            data = resp.json()
            if data.get("status") != "000":
                _log_dart_status(data.get("status", "?"),
                                 f"fnlttSinglIndx cl={cl} corp_code={corp_code}")
                continue
            for item in data.get("list") or []:
                nm = (item.get("idx_nm") or "").strip()
                raw = item.get("idx_val")
                if not nm or raw is None:
                    continue
                try:
                    merged[nm] = float(str(raw).replace(",", "").strip())
                except (TypeError, ValueError):
                    continue
        except Exception as e:
            log.debug("fnlttSinglIndx cl=%s 조회 실패 (%s): %s", cl, corp_code, e)

    _cache_set(_company_indicators_cache, cache_key, merged, _INDX_CACHE_MAX)
    return merged


# v0.9.0: 부실 후속 4종 통합 (#7) ----------------------------------------
_DISTRESS_ENDPOINTS: tuple[tuple[str, str], ...] = (
    # (path, subtype)
    ("dfOcr",       "default"),         # 부도발생
    ("bsnSp",       "business_susp"),   # 영업정지
    ("ctrcvsBgrq",  "rehabilitation"),  # 회생절차 개시신청
    ("dsRsOcr",     "dissolution"),     # 해산사유 발생
)

_distress_events_cache: dict[tuple, tuple[float, list]] = {}
_DISTRESS_CACHE_MAX = 20
_DISTRESS_CACHE_TTL = 600


def _distress_summary(item: dict, subtype: str) -> str:
    """부실 이벤트의 한 줄 요약 — 사실 표기만."""
    if subtype == "default":
        cn = item.get("df_cn") or "부도"
        amt = item.get("df_amt") or ""
        bnk = item.get("df_bnk") or ""
        parts = [cn]
        if amt:
            parts.append(f"금액 {amt}")
        if bnk:
            parts.append(f"은행 {bnk}")
        return " · ".join(parts)
    if subtype == "business_susp":
        cn = item.get("bsnsp_cn") or item.get("bsnsp_rs") or "영업정지"
        return cn
    if subtype == "rehabilitation":
        return item.get("rs") or item.get("ctrcvs_rs") or "회생절차 개시신청"
    if subtype == "dissolution":
        return item.get("ds_rs") or "해산사유 발생"
    return ""


def fetch_distress_events(
    corp_code: str,
    api_key: str,
    lookback_years: int = 3,
) -> list[dict]:
    """부도·영업정지·회생절차·해산사유 4개 엔드포인트 통합 (v0.9.0).

    각 이벤트:
        {
          "key":      "DISTRESS_EVENT",
          "subtype":  "default" | "business_susp" | "rehabilitation" | "dissolution",
          "rcept_no": "YYYYMMDDxxxxxx",
          "rcept_dt": "YYYYMMDD" (응답 누락 시 rcept_no[:8]로 폴백),
          "summary":  "한 줄 요약 (한국어)",
          "raw":      원본 응답 dict,
        }

    빈 corp_code/api_key는 빈 리스트. 일부 엔드포인트 실패는 격리.
    """
    if not corp_code or not api_key:
        return []

    cache_key = (corp_code, lookback_years)
    cached = _cache_get(_distress_events_cache, cache_key, _DISTRESS_CACHE_TTL)
    if cached is not None:
        return cached

    end = datetime.now()
    start = end - timedelta(days=max(1, lookback_years) * 365)
    bgn_de = start.strftime("%Y%m%d")
    end_de = end.strftime("%Y%m%d")

    events: list[dict] = []
    for ep_path, subtype in _DISTRESS_ENDPOINTS:
        try:
            resp = _retry(
                "GET", f"{DART_BASE}/{ep_path}.json",
                params={
                    "crtfc_key": api_key,
                    "corp_code": corp_code,
                    "bgn_de": bgn_de,
                    "end_de": end_de,
                },
            )
            data = resp.json()
            if data.get("status") != "000":
                _log_dart_status(data.get("status", "?"),
                                 f"{ep_path} corp_code={corp_code}")
                continue
            for item in data.get("list") or []:
                rcept_no = (item.get("rcept_no") or "").strip()
                rcept_dt = (item.get("rcept_dt") or "").strip()
                if not rcept_dt and len(rcept_no) >= 8 and rcept_no[:8].isdigit():
                    rcept_dt = rcept_no[:8]
                if not rcept_dt or len(rcept_dt) < 8:
                    continue
                events.append({
                    "key": "DISTRESS_EVENT",
                    "subtype": subtype,
                    "rcept_no": rcept_no,
                    "rcept_dt": rcept_dt[:8],
                    "summary": _distress_summary(item, subtype),
                    "raw": item,
                })
        except Exception as e:
            log.debug("%s 조회 실패 (%s): %s", ep_path, corp_code, e)

    events.sort(key=lambda e: e["rcept_dt"])
    _cache_set(_distress_events_cache, cache_key, events, _DISTRESS_CACHE_MAX)
    return events


# v0.9.0: 배당 이상 (#10) -----------------------------------------------
_dividend_history_cache: dict[tuple, tuple[float, list]] = {}
_DIVIDEND_CACHE_MAX = 20
_DIVIDEND_CACHE_TTL = 600


def fetch_dividend_history(
    corp_code: str,
    api_key: str,
    lookback_years: int = 3,
) -> list[dict]:
    """`alotMatter`(배당에 관한 사항)을 분기 4코드 × N년 호출.

    각 record는 원본 필드(`se`/`stock_knd`/`thstrm`/`frmtrm`/`lwfr`/`stlm_dt`) +
    `bsns_year`/`reprt_code`/`rcept_no`/`rcept_dt`(있으면).
    """
    if not corp_code or not api_key:
        return []

    cache_key = (corp_code, lookback_years)
    cached = _cache_get(_dividend_history_cache, cache_key, _DIVIDEND_CACHE_TTL)
    if cached is not None:
        return cached

    current_year = datetime.now().year
    years = [str(current_year - i) for i in range(max(1, lookback_years) + 1)]
    quarter_codes = ("11011", "11012", "11013", "11014")

    records: list[dict] = []
    for year in years:
        for reprt_code in quarter_codes:
            try:
                resp = _retry(
                    "GET", f"{DART_BASE}/alotMatter.json",
                    params={
                        "crtfc_key": api_key,
                        "corp_code": corp_code,
                        "bsns_year": year,
                        "reprt_code": reprt_code,
                    },
                )
                data = resp.json()
                if data.get("status") != "000":
                    _log_dart_status(data.get("status", "?"),
                                     f"alotMatter year={year} reprt={reprt_code} corp_code={corp_code}")
                    continue
                for item in data.get("list") or []:
                    rec = dict(item)
                    rec["bsns_year"] = year
                    rec["reprt_code"] = reprt_code
                    records.append(rec)
            except Exception as e:
                log.debug("alotMatter year=%s reprt=%s 조회 실패 (%s): %s",
                          year, reprt_code, corp_code, e)

    _cache_set(_dividend_history_cache, cache_key, records, _DIVIDEND_CACHE_MAX)
    return records


def detect_dividend_drain(
    dividend_records: list[dict],
    current_fs: dict | None,
) -> list[dict]:
    """적자 시점 배당 유출(DIVIDEND_DRAIN) 패턴 검출.

    Args:
        dividend_records: fetch_dividend_history 결과.
        current_fs: 당기 재무 dict (`{account_nm: int}`).
            `당기순이익`을 보고 음수일 때만 검사.

    Returns:
        flag dict 리스트:
          {"bsns_year", "se", "dividend": float, "net_income": int}
        매 record마다 최대 1건. 적자 + 양수 배당이 동시에 만족돼야 플래그.
    """
    if not dividend_records or not current_fs:
        return []
    ni = _pick_account(current_fs, _FS_ALIASES.get("당기순이익", ["당기순이익"]))
    if ni is None or ni >= 0:
        return []

    flags: list[dict] = []
    seen_year: set[str] = set()
    for rec in dividend_records:
        se = rec.get("se") or ""
        # "주당 현금배당금(원)" 같은 항목만 대상으로 한다(주식배당·지급대상 등은 제외).
        if "현금배당금" not in se:
            continue
        raw = rec.get("thstrm") or "0"
        try:
            div = float(str(raw).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
        if div <= 0:
            continue
        year = rec.get("bsns_year") or ""
        # 같은 연도 중복 방지(분기 4회 호출 노이즈)
        if year and year in seen_year:
            continue
        if year:
            seen_year.add(year)
        flags.append({
            "bsns_year": year,
            "se": se,
            "dividend": div,
            "net_income": ni,
        })
    return flags
