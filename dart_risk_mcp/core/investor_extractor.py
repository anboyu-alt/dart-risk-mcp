"""유상·유무상증자 공시에서 인수인 목록 추출.

구조화 엔드포인트(`piicDecsn`, `pifricDecsn`)를 사용해
`actnmn`(인수인명), `actsen`(인수인구분), `fric_tisstk_fta`(납입금액) 필드를 읽는다.
무상증자(`fricDecsn`)는 인수인 개념이 없어 여기서 호출하지 않는다.
"""

import re
from .dart_client import fetch_piic_decision, fetch_pifric_decision

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
        results.append({
            "name": name,
            "type": (row.get("actsen") or "").strip(),
            "amount": (row.get("fric_tisstk_fta") or row.get("bd_fta") or "").strip(),
            "source": "rights_offering",
        })
    return results


def extract_rights_offering_investors(rcept_no: str, api_key: str) -> list[dict]:
    """
    유상증자·유무상증자 공시에서 인수인 목록 추출.

    Args:
        rcept_no: 공시 접수번호 (14자리)
        api_key: DART API 인증키

    Returns:
        [{"name": 인수인명, "type": 인수인구분, "amount": 납입금액, "source": "rights_offering"}, ...]
        결과가 없으면 빈 리스트.
    """
    # 1) 유상증자 결정 시도
    data = fetch_piic_decision(rcept_no, api_key)
    investors = _parse_list(data)
    if investors:
        return investors

    # 2) 유무상증자 결정 시도
    data = fetch_pifric_decision(rcept_no, api_key)
    investors = _parse_list(data)
    return investors
