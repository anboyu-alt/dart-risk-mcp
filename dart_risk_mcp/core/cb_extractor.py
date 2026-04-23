"""CB/BW 인수자 추출

DART 공시 원문 ZIP에서 전환사채·신주인수권부사채의 인수자(매수인) 법인명을 추출한다.
dart-monitor/cb_investor_network.py에서 추출.

v0.7.0: 구조화 엔드포인트(cvbdIsDecsn / bdwtIsDecsn / exbdIsDecsn) 우선 시도,
전부 실패 시 HTML 파싱으로 폴백.
v0.7.1: corp_code 필수 파라미터화(DART API corp_code+날짜 방식), HTML 테이블 추출 강화.
"""

import io
import logging
import re
import zipfile

import requests

log = logging.getLogger(__name__)

from .dart_client import (
    fetch_cb_issue_decision,
    fetch_bw_issue_decision,
    fetch_eb_issue_decision,
)

DART_BASE = "https://opendart.fss.or.kr/api"

_INVESTOR_RES = [
    re.compile(r"인수인\s*[：:]\s*([^\n\r\t。,，;./()（）\[\]]{2,50})"),
    re.compile(r"매수인\s*[：:]\s*([^\n\r\t。,，;./()（）\[\]]{2,50})"),
    re.compile(r"인수자\s*[：:]\s*([^\n\r\t。,，;./()（）\[\]]{2,50})"),
    re.compile(r"취득자\s*[：:]\s*([^\n\r\t。,，;./()（）\[\]]{2,50})"),
]
_AMOUNT_RE = re.compile(
    r"(?:인수금액|발행금액)\s*[：:]\s*([\d,]+)\s*(?:원|백만원|억원)?"
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_NOISE_NAMES = {"해당없음", "해당 없음", "미정", "미확정", "추후결정", "추후 결정", "해당사항없음"}

# 구조화 응답에서도 공백 이름 필터에 사용
_BLANK_PATTERNS = {"", "-", "–", "—", "·", "해당없음", "해당 없음"}

# 대상자별 사채발행내역 / 유상증자 제3자배정 섹션 헤더
_CB_SECTION_RE = re.compile(r"【특정인에\s*대한\s*대상자별\s*사채발행내역】")
_RIGHTS_SECTION_RE = re.compile(r"【제3자배정\s*대상자별\s*선정경위[^】]*】")

# DART HTML 스키마 상수 — TE 셀 ACODE 속성으로 컬럼 식별
#   CB: ISSU_NM(대상자명), ISSU_AMT(금액), RLT(관계)
#   Rights: PART(대상자), ALL_CNT(배정주식수), RLT(관계)
_CB_NAME_ACODE = "ISSU_NM"
_CB_AMOUNT_ACODE = "ISSU_AMT"
_RIGHTS_NAME_ACODE = "PART"
_RIGHTS_AMOUNT_ACODE = "ALL_CNT"

# TE 셀 파싱: <TE ... ACODE="X" ...>content</TE>
_TE_CELL_RE = re.compile(
    r'<TE\b[^>]*\bACODE="([^"]+)"[^>]*>(.*?)</TE>',
    re.IGNORECASE | re.DOTALL,
)


def _fetch_text(rcept_no: str, api_key: str) -> str:
    """공시 원문 ZIP에서 텍스트 추출.

    인수자 섹션(【특정인에 대한 대상자별 사채발행내역】 / 【제3자배정 대상자별 ...】)은
    실제 샘플에서 23,000자 이후 등장하는 경우가 있어 전체 텍스트를 반환한다.
    (구 6,000자·20,000자 상한은 섹션 누락 원인 — v0.7.1에서 제거.)
    """
    if not api_key:
        return ""
    try:
        resp = requests.get(
            f"{DART_BASE}/document.xml",
            params={"crtfc_key": api_key, "rcept_no": rcept_no},
            timeout=30,
        )
        if resp.status_code != 200:
            return ""
        zf = zipfile.ZipFile(io.BytesIO(resp.content), metadata_encoding="cp949")
        names = zf.namelist()
        targets = [n for n in names if n.endswith(".xml")] + \
                  [n for n in names if n.endswith(".html") or n.endswith(".htm")]
        if not targets:
            targets = names
        text = ""
        for name in targets:
            raw = zf.read(name)
            for enc in ("utf-8", "euc-kr", "cp949"):
                try:
                    decoded = raw.decode(enc)
                    text = decoded  # 태그 제거는 호출자에서 수행
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            if text:
                break
        zf.close()
        return text
    except Exception:
        return ""


def _clean_name(raw: str) -> str:
    name = raw.strip()
    name = re.split(r"\s{2,}|\t|　", name)[0].strip()
    return name


def _clean_name_structured(raw: str) -> str:
    """구조화 응답용 이름 정규화 (연속 공백 단일화)."""
    if not raw:
        return ""
    return re.sub(r"\s+", " ", str(raw)).strip()


def _parse_structured(data: dict) -> list[dict]:
    """구조화 엔드포인트 응답을 표준 dict 목록으로 변환."""
    results = []
    if not data:
        return results
    for row in data.get("list", []) or []:
        name = _clean_name_structured(row.get("actnmn", ""))
        if name in _BLANK_PATTERNS:
            continue
        results.append({
            "name": name,
            "type": (row.get("actsen") or "").strip(),
            "amount": (row.get("bd_fta") or "").strip(),
        })
    return results


def _extract_investor_table(
    text: str,
    section_re: re.Pattern,
    name_acode: str = _CB_NAME_ACODE,
    amount_acode: str = _CB_AMOUNT_ACODE,
) -> list[dict]:
    """DART HTML에서 대상자명 테이블을 파싱해 인수인 목록 반환.

    DART 표준 공시 HTML은 `<TE ACODE="X">content</TE>` 구조로 컬럼을 명시한다.
    섹션 헤더(예: 【특정인에 대한 대상자별 사채발행내역】) 이후 6,000자 창에서
    `name_acode`를 가진 셀만 뽑아 인수자명으로, `amount_acode`를 금액으로 사용한다.

    Args:
        text: 원본 HTML (태그 포함)
        section_re: 섹션 헤더 정규식
        name_acode: 인수자명 컬럼 ACODE (CB=ISSU_NM, Rights=PART)
        amount_acode: 금액 컬럼 ACODE (CB=ISSU_AMT, Rights=ALL_CNT)
    """
    m = section_re.search(text)
    if not m:
        return []
    # 섹션 헤더 이후 넉넉한 창. 다음 섹션(【) 이전까지만 사용.
    window = text[m.end():m.end() + 6000]
    next_section = re.search(r"【[^】]{2,80}】", window)
    if next_section:
        window = window[:next_section.start()]

    # 모든 TE 셀을 ACODE 순서대로 수집 — 행 경계는 ACODE 반복 주기로 추론
    cells = []
    for tm in _TE_CELL_RE.finditer(window):
        acode = tm.group(1).strip().upper()
        inner = _HTML_TAG_RE.sub(" ", tm.group(2))
        cells.append((acode, re.sub(r"\s+", " ", inner).strip()))

    if not cells:
        return []

    # ACODE 반복 주기로 행 분리
    # (row 시작 = name_acode 등장마다)
    rows: list[dict] = []
    current: dict = {}
    for acode, content in cells:
        if acode == name_acode.upper():
            # 새 행 시작
            if current:
                rows.append(current)
            current = {"name": content, "amount": ""}
        elif acode == amount_acode.upper() and current:
            current["amount"] = content
    if current:
        rows.append(current)

    # 잡음 이름 필터
    results: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        name = row.get("name", "").strip()
        if not (2 <= len(name) <= 60):
            continue
        if name in _NOISE_NAMES or name in seen:
            continue
        # 숫자/기호만인 경우 제외
        if re.fullmatch(r"[\d,.\s\-주원%\(\)]+", name):
            continue
        seen.add(name)
        results.append({"name": name, "type": "", "amount": row.get("amount", "")})
        if len(results) >= 20:  # 안전 상한
            break

    return results


def _legacy_html_extract(rcept_no: str, api_key: str) -> list[dict]:
    """HTML 파싱 기반 인수자 추출 (폴백 경로).

    1) 기존 인수인: 레이블 regex 패턴 시도 (하위 호환)
    2) 【특정인에 대한 대상자별 사채발행내역】 섹션 테이블 파싱
    두 결과를 합산 후 이름 기준 중복 제거.
    """
    raw_text = _fetch_text(rcept_no, api_key)
    if not raw_text:
        return []

    # 태그 제거 텍스트 (기존 regex 경로용)
    text = _HTML_TAG_RE.sub(" ", raw_text)

    amount = ""
    am = _AMOUNT_RE.search(text)
    if am:
        amount = am.group(1).replace(",", "") + "원"

    investors: list[dict] = []
    seen: set[str] = set()

    # 1) 기존 인수인: / 매수인: 패턴
    for pat in _INVESTOR_RES:
        for m in pat.finditer(text):
            name = _clean_name(m.group(1))
            if len(name) < 2 or len(name) > 50:
                continue
            if re.fullmatch(r"[\d\s,.\-]+", name):
                continue
            if name in _NOISE_NAMES or name in seen:
                continue
            seen.add(name)
            investors.append({"name": name, "type": "", "amount": amount})

    # 2) 사채발행내역 테이블 (원본 HTML 사용 — 태그 구조 필요)
    table_results = _extract_investor_table(raw_text, _CB_SECTION_RE)
    for rec in table_results:
        if rec["name"] not in seen:
            seen.add(rec["name"])
            if amount and not rec["amount"]:
                rec = {**rec, "amount": amount}
            investors.append(rec)

    return investors


def extract_cb_investors(rcept_no: str, api_key: str, corp_code: str = "") -> list[dict]:
    """CB/BW/EB 발행결정 공시에서 인수인 목록 추출.

    v0.7.1: corp_code 인자 추가. corp_code 있으면 구조화 엔드포인트(corp_code+날짜 방식)
    시도 후 HTML 폴백. corp_code 없으면 즉시 HTML 폴백.

    Args:
        rcept_no: DART 접수번호 14자리
        api_key: DART API 인증키
        corp_code: DART 기업 코드 (8자리). 없으면 HTML 경로만 사용.

    Returns:
        [{"name": 인수인명, "type": 인수인구분, "amount": 인수금액}, ...]
        추출 실패 시 빈 리스트.
    """
    if corp_code:
        for fetch_fn in (
            fetch_cb_issue_decision,
            fetch_bw_issue_decision,
            fetch_eb_issue_decision,
        ):
            try:
                data = fetch_fn(rcept_no, api_key, corp_code)
            except Exception:
                continue
            investors = _parse_structured(data)
            if investors:
                return investors

        log.debug(
            "cb_extractor: structured endpoints returned no investors for %s (corp=%s), falling back to HTML",
            rcept_no, corp_code,
        )

    # 구조화 전부 실패 또는 corp_code 없음 → HTML 폴백
    return _legacy_html_extract(rcept_no, api_key)


__all__ = ["extract_cb_investors"]
