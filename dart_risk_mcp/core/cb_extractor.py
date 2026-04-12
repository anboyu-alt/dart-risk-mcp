"""CB/BW 인수자 추출

DART 공시 원문 ZIP에서 전환사채·신주인수권부사채의 인수자(매수인) 법인명을 추출한다.
dart-monitor/cb_investor_network.py에서 추출.
"""

import io
import re
import time
import zipfile

import requests

DART_BASE = "https://opendart.fss.or.kr/api"

_INVESTOR_RES = [
    re.compile(r"인수인\s*[：:]\s*([^\n\r\t。,]{2,50})"),
    re.compile(r"매수인\s*[：:]\s*([^\n\r\t。,]{2,50})"),
    re.compile(r"인수자\s*[：:]\s*([^\n\r\t。,]{2,50})"),
    re.compile(r"취득자\s*[：:]\s*([^\n\r\t。,]{2,50})"),
]
_AMOUNT_RE = re.compile(
    r"(?:인수금액|발행금액)\s*[：:]\s*([\d,]+)\s*(?:원|백만원|억원)?"
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_NOISE_NAMES = {"해당없음", "해당 없음", "미정", "미확정", "추후결정", "추후 결정", "해당사항없음"}


def _fetch_text(rcept_no: str, api_key: str) -> str:
    """공시 원문 ZIP에서 텍스트 추출. 인수자 섹션이 뒤에 있을 수 있어 6000자."""
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
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
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
                    text = _HTML_TAG_RE.sub(" ", decoded)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            if text:
                break
        zf.close()
        return text[:6000]
    except Exception:
        return ""


def _clean_name(raw: str) -> str:
    name = raw.strip()
    name = re.split(r"\s{2,}|\t|　", name)[0].strip()
    return name


def extract_cb_investors(rcept_no: str, api_key: str) -> list[dict]:
    """공시 접수번호로 CB/BW 인수자(매수인) 목록을 추출한다.

    Args:
        rcept_no: DART 접수번호 14자리
        api_key: DART API 인증키

    Returns:
        [{"name": "OO투자조합", "amount": "5000000000원"}, ...]
        추출 실패 시 빈 리스트.
    """
    text = _fetch_text(rcept_no, api_key)
    if not text:
        return []

    amount = ""
    am = _AMOUNT_RE.search(text)
    if am:
        amount = am.group(1).replace(",", "") + "원"

    investors: list[dict] = []
    seen: set[str] = set()

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
            investors.append({"name": name, "amount": amount})

    return investors
