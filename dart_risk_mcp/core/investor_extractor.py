"""유상·유무상증자 공시에서 인수인 목록 추출.

구조화 엔드포인트(`piicDecsn`, `pifricDecsn`)를 사용해
`actnmn`(인수인명), `actsen`(인수인구분), `fric_tisstk_fta`(납입금액) 필드를 읽는다.
무상증자(`fricDecsn`)는 인수인 개념이 없어 여기서 호출하지 않는다.

v0.7.1: corp_code 파라미터 추가 + HTML 테이블 폴백(【제3자배정 대상자별 선정경위...】).
"""

import io
import logging
import re
import zipfile

import requests

from .dart_client import fetch_piic_decision, fetch_pifric_decision
from .cb_extractor import (
    _extract_investor_table,
    _RIGHTS_SECTION_RE,
    _RIGHTS_NAME_ACODE,
    _RIGHTS_AMOUNT_ACODE,
    _HTML_TAG_RE,
    DART_BASE,
)

log = logging.getLogger(__name__)

__all__ = ["extract_rights_offering_investors"]

_BLANK_PATTERNS = {"", "-", "\u2013", "\u2014", "\u00b7", "\ud574\ub2f9\uc5c6\uc74c", "\ud574\ub2f9 \uc5c6\uc74c"}


def _clean_name(raw: str) -> str:
    """인수인명 정규화 — 다중 공백 단일화, 양끝 공백 제거."""
    if not raw:
        return ""
    s = re.sub(r"\s+", " ", str(raw)).strip()
    return s


def _parse_list(data: dict) -> list[dict]:
    """DART 응답 dict에서 인수인 레코드 리스트 추출."""
    results = []
    if not data:
        return results
    for row in data.get("list", []) or []:
        name = _clean_name(row.get("actnmn", ""))
        if name in _BLANK_PATTERNS:
            continue
        # piicDecsn은 piic_tisstk_fta, pifricDecsn은 fric_tisstk_fta 필드 사용
        amount = (
            row.get("piic_tisstk_fta")
            or row.get("fric_tisstk_fta")
            or row.get("bd_fta")
            or ""
        )
        results.append({
            "name": name,
            "type": (row.get("actsen") or "").strip(),
            "amount": amount.strip() if isinstance(amount, str) else str(amount),
            "source": "rights_offering",
        })
    return results


def _fetch_rights_html_text(rcept_no: str, api_key: str) -> str:
    """유상증자 공시 원문 ZIP에서 원본 HTML 텍스트(태그 포함) 반환.

    HTML 구조(태그)는 _extract_investor_table이 사용하므로 태그 제거 전 반환.
    인수인 섹션은 문서 후반에 등장할 수 있어 전체 텍스트를 반환한다
    (v0.7.1: 구 20,000자 상한은 섹션 누락 원인 — 제거).
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
                    text = decoded
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            if text:
                break
        zf.close()
        return text
    except Exception:
        return ""


def _html_fallback(rcept_no: str, api_key: str) -> list[dict]:
    """HTML에서 【제3자배정 대상자별 선정경위...】 테이블 파싱으로 인수인 추출."""
    raw_text = _fetch_rights_html_text(rcept_no, api_key)
    if not raw_text:
        return []
    results = _extract_investor_table(
        raw_text,
        _RIGHTS_SECTION_RE,
        name_acode=_RIGHTS_NAME_ACODE,
        amount_acode=_RIGHTS_AMOUNT_ACODE,
    )
    # source 태그 부착
    return [{**r, "source": "rights_offering"} for r in results]


def extract_rights_offering_investors(rcept_no: str, api_key: str, corp_code: str = "") -> list[dict]:
    """
    유상증자·유무상증자 공시에서 인수인 목록 추출.

    v0.7.1: corp_code 추가. corp_code 있으면 구조화 엔드포인트(corp_code+날짜 방식)
    시도 후 HTML 폴백. corp_code 없으면 즉시 HTML 폴백.

    Args:
        rcept_no: 공시 접수번호 (14자리)
        api_key: DART API 인증키
        corp_code: DART 기업 코드 (8자리). 없으면 HTML 경로만 사용.

    Returns:
        [{"name": 인수인명, "type": 인수인구분, "amount": 납입금액, "source": "rights_offering"}, ...]
        결과가 없으면 빈 리스트.
    """
    if corp_code:
        # 1) 유상증자 결정 시도 (corp_code+날짜 방식)
        data = fetch_piic_decision(rcept_no, api_key, corp_code)
        investors = _parse_list(data)
        if investors:
            return investors

        # 2) 유무상증자 결정 시도
        data = fetch_pifric_decision(rcept_no, api_key, corp_code)
        investors = _parse_list(data)
        if investors:
            return investors

        log.debug(
            "investor_extractor: structured endpoints empty for %s (corp=%s), falling back to HTML",
            rcept_no, corp_code,
        )

    # 구조화 실패 또는 corp_code 없음 → HTML 폴백
    return _html_fallback(rcept_no, api_key)
