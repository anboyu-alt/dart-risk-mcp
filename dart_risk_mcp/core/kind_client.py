"""KIND(한국거래소 상장공시시스템) 시장경보 조회 — 투자주의·경고·위험 3종.

DART API에는 시장경보(투자주의/경고/위험 종목 지정)가 없다(전수 확인 — 지수·
주식·증권상품·채권·파생·일반상품·ESG뿐). 이 정보는 KIND 웹 화면에만 있고
공식 API가 없어 **비공식 웹 파싱**으로 받는다. 관리종목·불성실공시·조회공시·
매매거래정지는 DART `list.json`이 거래소공시로 이미 담고 있어(기존 신호
`INQUIRY`·`WATCH_ISSUE`·`DELISTING_RISK`·`DISCLOSURE_VIOL`) 이 모듈은
시장경보 3종만 다룬다. 판정·점수 없음(v0.8.5 원칙) — 사실만 반환한다.

의존성: `requests`만 사용(프로젝트 규칙 — 외부 라이브러리 추가 금지).
HTML 파싱은 regex + 문자열 처리로 한다.

실측 근거: `docs/superpowers/specs/2026-09-22-krx-market-reaction-design.md`
「KIND 시장경보」절, `tests/fixtures/kind/*.html`(실제 응답 원문 8종).
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

import requests

KIND_ALERT_URL = "https://kind.krx.co.kr/investwarn/investattentwarnrisky.do"

# key -> (menuIndex, forward)
KIND_ALERT_KINDS: dict[str, tuple[str, str]] = {
    "caution": ("1", "invstcautnisu_sub"),
    "warning": ("2", "invstwarnisu_sub"),
    "risk": ("3", "invstriskisu_sub"),
}

# 실측(2026-09-22): 창이 3년을 넘으면 KIND가 시스템 부하를 이유로 본문 길이
# 0을 돌려준다(2025-08-18 제한 공지). 정확히 3년째 경계에서 걸리는 것을
# 피하려고 여유를 살짝 안쪽으로 둔다 — 그 여유가 `_KIND_WINDOW_MARGIN_DAYS`.
KIND_MAX_WINDOW_DAYS = 365 * 3
_KIND_WINDOW_MARGIN_DAYS = 5

KIND_PAGE_SIZE = 100
# 한 종목이 시장경보 100건을 3페이지(300건) 넘기는 사례는 실측에 없다 —
# 상한을 걸어 두되 원문 ZIP처럼 비용이 드는 자원은 아니라 넉넉히 잡는다.
KIND_MAX_PAGES = 3

_EXPECTED_COLUMNS: dict[str, list[str]] = {
    "caution": ["번호", "종목명", "유형", "공시일", "지정일"],
    "warning": ["번호", "종목명", "공시일", "지정일", "해제일"],
    "risk": ["번호", "종목명", "공시일", "지정일", "해제일"],
}

_TITLE_RE = re.compile(r'fn_InitTitle\("([^"]*)"')
_TOTAL_RE = re.compile(r"전체\s*<em>([\d,]+)</em>\s*건")
_TBODY_RE = re.compile(r"<tbody>(.*?)</tbody>", re.DOTALL)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
_TD_RE = re.compile(r"<td([^>]*)>(.*?)</td>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_ATTR_DQ_RE = re.compile(r'title="([^"]*)"')
_TITLE_ATTR_SQ_RE = re.compile(r"title='([^']*)'")
_ALT_ATTR_RE = re.compile(r"alt='([^']+)'")
_DATE_DASH_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_EMPTY_MARK = "조회된 결과값이 없습니다"

# 10분 메모리 캐시 — dart_client._cache_get/_cache_set과 같은 관례
# (동시 작업 중인 다른 파일과의 결합을 피하려고 이 모듈 안에 자체 복제한다).
_alert_cache: dict[tuple, tuple[float, dict]] = {}
_ALERT_CACHE_MAX = 50
_ALERT_CACHE_TTL = 600


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


def _strip_tags(html_fragment: str) -> str:
    return _TAG_RE.sub("", html_fragment or "").strip()


def _extract_title(attrs: str, inner: str) -> str:
    m = _TITLE_ATTR_DQ_RE.search(attrs or "")
    if not m:
        m = _TITLE_ATTR_SQ_RE.search(attrs or "")
    if m:
        return m.group(1).strip()
    return _strip_tags(inner)


def _extract_market(inner: str) -> str | None:
    m = _ALT_ATTR_RE.search(inner or "")
    return m.group(1) if m else None


def _date8(text: str) -> str | None:
    text = (text or "").strip()
    m = _DATE_DASH_RE.match(text)
    if not m:
        return None
    return "".join(m.groups())


def _parse_date8(d: str):
    try:
        return datetime.strptime(d, "%Y%m%d")
    except (ValueError, TypeError):
        return None


def _fmt_date_dash(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _fmt_date8(dt: datetime) -> str:
    return dt.strftime("%Y%m%d")


def _parse_rows(tbody_html: str, kind: str) -> list[dict]:
    records: list[dict] = []
    for tr_match in _TR_RE.finditer(tbody_html):
        block = tr_match.group(1)
        cells = _TD_RE.findall(block)
        if len(cells) < 5:
            # 결과없음 행(colspan 단일 td)·헤더 빈 행은 여기서 걸러진다.
            continue

        name_attrs, name_inner = cells[1]
        name = _extract_title(name_attrs, name_inner)
        market = _extract_market(name_inner)

        if kind == "caution":
            reason = _strip_tags(cells[2][1])
            announced = _date8(_strip_tags(cells[3][1]))
            designated = _date8(_strip_tags(cells[4][1]))
            record: dict = {
                "kind": kind,
                "name": name,
                "reason": reason,
                "announced": announced,
                "designated": designated,
            }
        else:
            announced = _date8(_strip_tags(cells[2][1]))
            designated = _date8(_strip_tags(cells[3][1]))
            released = _date8(_strip_tags(cells[4][1]))
            record = {
                "kind": kind,
                "name": name,
                "announced": announced,
                "designated": designated,
                "released": released,
            }

        if market:
            record["market"] = market

        records.append(record)

    return records


def parse_kind_alert_table(html: str, kind: str) -> tuple[list[dict], dict]:
    """KIND 시장경보 표 HTML을 파싱한다. 순수 함수(네트워크 호출 없음).

    반환: (레코드 목록, {"total", "parse_failed", "empty", "columns"}).

    열 배치는 응답 꼬리의 `fn_InitTitle(...)` 문자열로 검증한다 — 기대와
    다르면(구조 변경·알 수 없는 kind) `parse_failed=True`로 표시하고 빈
    목록을 돌려준다. 본문 길이 0(창 3년 초과 등)도 같은 취급이다.
    「조회된 결과값이 없습니다」는 실패가 아니라 정상적인 빈 결과다.
    """
    if not html or not html.strip():
        return [], {"total": None, "parse_failed": True, "empty": False, "columns": []}

    expected = _EXPECTED_COLUMNS.get(kind)
    title_match = _TITLE_RE.search(html)
    columns = [c.strip() for c in title_match.group(1).split(",")] if title_match else []

    if expected is None or not title_match or columns != expected:
        return [], {"total": None, "parse_failed": True, "empty": False, "columns": columns}

    total: int | None = None
    total_match = _TOTAL_RE.search(html)
    if total_match:
        total = int(total_match.group(1).replace(",", ""))

    if _EMPTY_MARK in html:
        return [], {
            "total": total if total is not None else 0,
            "parse_failed": False,
            "empty": True,
            "columns": columns,
        }

    tbody_match = _TBODY_RE.search(html)
    tbody_html = tbody_match.group(1) if tbody_match else html
    records = _parse_rows(tbody_html, kind)

    return records, {"total": total, "parse_failed": False, "empty": False, "columns": columns}


def _fetch_one_kind(
    stock_code: str,
    kind: str,
    menu_index: str,
    forward: str,
    start_date_fmt: str,
    end_date_fmt: str,
) -> tuple[list[dict], bool]:
    """한 시장경보 종류를 최대 KIND_MAX_PAGES페이지까지 받는다.

    반환: (레코드 목록, failed). failed는 요청 예외·비200·parse_failed
    어느 쪽이든 True — 형제 함수들과 같은 "실패 사유를 세분화하지 않고
    그 종류를 통째로 미확인 처리" 관례.
    """
    records: list[dict] = []
    page = 1

    while page <= KIND_MAX_PAGES:
        form = {
            "method": "investattentwarnriskySub",
            "forward": forward,
            "menuIndex": menu_index,
            "marketType": "",
            "searchCorpName": "",
            "repIsuSrtCd": f"A{stock_code}",
            "searchCodeType": "char",
            "startDate": start_date_fmt,
            "endDate": end_date_fmt,
            "currentPageSize": str(KIND_PAGE_SIZE),
            "pageIndex": str(page),
            "orderMode": "4",
            "orderStat": "D",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{KIND_ALERT_URL}?method=investattentwarnriskyMain",
            "User-Agent": "Mozilla/5.0",
        }

        try:
            resp = requests.post(KIND_ALERT_URL, data=form, headers=headers, timeout=20)
        except requests.RequestException:
            return records, True

        if resp.status_code != 200:
            return records, True

        page_records, meta = parse_kind_alert_table(resp.text, kind)
        if meta.get("parse_failed"):
            return records, True

        records.extend(page_records)

        total = meta.get("total")
        if total is None or total <= page * KIND_PAGE_SIZE:
            break
        page += 1

    return records, False


def fetch_market_alerts(stock_code: str, start_date8: str, end_date8: str) -> dict:
    """종목의 시장경보(투자주의·경고·위험) 이력을 조회한다.

    반환: {"alerts": [지정일 내림차순], "by_kind": {"caution","warning","risk"},
    "clamped", "clamp_start", "failed_kinds", "parse_failed", "fetch_failed",
    "source_url"}. 어느 한 종류라도 실패해도 나머지 결과는 그대로 싣는다.
    못 받은(fetch_failed) 결과는 캐시하지 않는다.
    """
    cache_key = (stock_code, start_date8, end_date8)
    cached = _cache_get(_alert_cache, cache_key, _ALERT_CACHE_TTL)
    if cached is not None:
        return cached

    start_dt = _parse_date8(start_date8)
    end_dt = _parse_date8(end_date8)

    clamped = False
    clamp_start: str | None = None
    if start_dt and end_dt:
        window_limit = KIND_MAX_WINDOW_DAYS - _KIND_WINDOW_MARGIN_DAYS
        if (end_dt - start_dt).days > window_limit:
            start_dt = end_dt - timedelta(days=window_limit)
            clamped = True
            clamp_start = _fmt_date8(start_dt)

    start_date_fmt = _fmt_date_dash(start_dt) if start_dt else start_date8
    end_date_fmt = _fmt_date_dash(end_dt) if end_dt else end_date8

    all_alerts: list[dict] = []
    by_kind: dict[str, int] = {}
    failed_kinds: list[str] = []

    for kind, (menu_index, forward) in KIND_ALERT_KINDS.items():
        records, failed = _fetch_one_kind(
            stock_code, kind, menu_index, forward, start_date_fmt, end_date_fmt
        )
        by_kind[kind] = len(records)
        all_alerts.extend(records)
        if failed:
            failed_kinds.append(kind)

    all_alerts.sort(key=lambda r: r.get("designated") or "", reverse=True)

    fetch_failed = bool(failed_kinds)
    result = {
        "alerts": all_alerts,
        "by_kind": by_kind,
        "clamped": clamped,
        "clamp_start": clamp_start,
        "failed_kinds": failed_kinds,
        # 이 모듈에서 "요청 실패"와 "구조 변경으로 인한 파싱 실패"를 개별
        # kind 단위로 구분하지 않는다(_fetch_one_kind가 통째로 실패 처리) —
        # 실패가 하나라도 있으면 parse_failed도 함께 True로 둔다.
        "parse_failed": fetch_failed,
        "fetch_failed": fetch_failed,
        "source_url": KIND_ALERT_URL,
    }

    if not fetch_failed:
        _cache_set(_alert_cache, cache_key, result, _ALERT_CACHE_MAX)

    return result
