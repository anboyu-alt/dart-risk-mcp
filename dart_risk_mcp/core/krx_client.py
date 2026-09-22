"""KRX Open API 클라이언트 — 일별 시세 조회, 날짜별 디스크 캐시, 일일 호출 계수.

DART 공시만으로는 「무슨 일이 있었는가」까지만 안다. 「공시 전후 시장이 어떻게
움직였는가」(등락률·거래량·회전율)를 사실로 붙이기 위해 KRX Open API(사용자 본인
키)를 쓴다. **점수·등급·판정은 하지 않는다**(v0.8.5 원칙) — 이 모듈은 순수
조회·캐시 계층이고, 임계값·해석은 이 파일의 범위 밖이다.

의존성: requests + 표준 라이브러리만(프로젝트 규칙).

설계 근거: docs/superpowers/specs/2026-09-22-krx-market-reaction-design.md
「core/krx_client.py」절.

## 하루 단위·시장 전체 응답

KRX Open API는 종목별 기간 조회가 없다 — 하루를 물으면 그날 시장 전체(수천
종목)가 온다. 그래서 **날짜별로 시장 전체를 디스크에 캐시**한다. 한 회사를
조회하며 받은 하루치는 다른 회사를 조회할 때도 그대로 쓸 수 있다(두 번째
회사부터는 그 날짜에 대해 0콜).

## 실패는 캐시하지 않는다

DART 클라이언트(`dart_client.py`)와 같은 원칙이다 — 한도 초과·점검 같은 일시적
실패를 캐시에 붙들면 한도가 풀린 뒤에도 같은 거짓말(빈 데이터)이 남는다.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import requests

from .dart_client import _resolve_corp_cache_dir

log = logging.getLogger(__name__)

KRX_BASE = "https://data-dbg.krx.co.kr/svc/apis/sto"

# DART corp_cls("Y"=유가증권·"K"=코스닥·"N"=코넥스·"E"=기타) → KRX apiId.
# N·E는 이번 범위 밖(스펙 「KRX Open API」 절 — 유가·코스닥 일별매매정보만 승인).
KRX_API_IDS = {"Y": "stk_bydd_trd", "K": "ksq_bydd_trd"}

KRX_DAILY_CAP = 10_000   # 약관 제8조 ④ — 키당 1일 10,000회
KRX_SOFT_CAP = 9_000     # 배치 cron·다른 소비처 몫을 남겨 두는 자체 여유
# 도구 1회 호출당 네트워크 콜 상한. 실측(2026-09-22, 제작자 키): 콜당 중앙값
# 1.04초(코스닥 596KB · 유가 293KB), 동시 5콜까지 429 없음(10콜 wall 2.4초).
# 동시 4로 120콜 ≈ 30초 — 대기 예산 1분 안. 1년(≈245거래일)은 한 번에 못 채우고
# 남는 날은 `days_uncovered`로 알린다(캐시가 쌓이면 다음 호출이 이어 받는다).
KRX_CALL_BUDGET = 120
KRX_CONCURRENCY = 4      # 실측 5까지 스로틀 없음 — 여유 하나를 뺐다
# ⚠ 빈 응답(`OutBlock_1: []`)은 휴장일과 **발표 전**을 구분하지 않는다. 실측(2026-09-23
# 00:42 KST): 전 거래일(09-22)이 아직 빈 배열이었고 첫 판은 그것을 휴장일로 **영구
# 캐시**했다(두 시장 모두 — 손으로 지웠다). 최근 이 일수 안의 빈 응답은 캐시하지 않고
# `days_pending`으로 알린다. 7일이면 추석·설 연휴(최장 6일)를 덮는다.
KRX_EMPTY_GRACE_DAYS = 7

# 캐시에 남기는 필드 8종만 — 저장 용량과 「원문 그대로」 원칙의 절충.
KRX_KEEP_FIELDS = (
    "ISU_CD", "TDD_CLSPRC", "FLUC_RT", "ACC_TRDVOL", "ACC_TRDVAL",
    "MKTCAP", "LIST_SHRS", "SECT_TP_NM",
)


# ── 경로 ──────────────────────────────────────────────────────────

def _krx_root() -> Path:
    """`_resolve_corp_cache_dir()/krx` — corp_codes.json과 같은 캐시 루트 아래."""
    return _resolve_corp_cache_dir() / "krx"


def _cache_path(api_id: str, bas_dd: str) -> Path:
    return _krx_root() / api_id / f"{bas_dd}.json.gz"


def _quota_path(date_str: str) -> Path:
    return _krx_root() / f"quota_{date_str}.json"


def _today_str() -> str:
    """기기 로컬 날짜(YYYYMMDD). `dart_client`가 `datetime.now()`를 기기 로컬로
    쓰는 것과 같은 관례 — MCP는 사용자 기기에서 사용자 키로 돈다."""
    return datetime.now().strftime("%Y%m%d")


# ── 디스크 캐시 ───────────────────────────────────────────────────

def _read_cache(api_id: str, bas_dd: str) -> "dict | None":
    """캐시 히트면 `{"rows": [...]}` 또는 `{"empty": True}`, 미스·손상이면 None.

    손상 파일을 읽다 나는 예외는 미스로 접는다 — 캐시는 성능 최적화일 뿐이라
    구현의 버그가 실제 조회를 막으면 안 된다(dart_client._retry의 HTTP 캐시와
    같은 태도).
    """
    path = _cache_path(api_id, bas_dd)
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        log.warning("KRX 캐시 읽기 실패, 네트워크로 폴백: %s/%s", api_id, bas_dd)
    return None


def _write_cache(api_id: str, bas_dd: str, payload: dict) -> None:
    """임시 파일에 쓰고 교체한다(원자적, `watchlist.save_watchlist`와 같은 관례).

    쓰기 실패는 예외를 던지지 않는다 — 캐시는 부가 기능이라 실패해도 이번
    조회 결과(이미 받은 응답)에는 영향이 없어야 한다.
    """
    path = _cache_path(api_id, bas_dd)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        log.warning("KRX 캐시 쓰기 실패: %s/%s", api_id, bas_dd)


# ── 일일 호출 계수 ─────────────────────────────────────────────────

def _quota_count(date_str: str) -> int:
    path = _quota_path(date_str)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return int(data.get("calls", 0))
    except Exception:
        return 0


def _quota_increment(date_str: str) -> int:
    """실제 네트워크 호출 1회를 계수에 반영하고 새 값을 반환한다.

    파일 I/O 실패는 조용히 무시한다(계수 파일이 소프트캡을 정확히 지키지
    못하는 것이 요청 자체를 죽이는 것보다 낫다).
    """
    new = _quota_count(date_str) + 1
    path = _quota_path(date_str)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"calls": new}, f)
        os.replace(tmp, path)
    except Exception:
        log.warning("KRX 계수 파일 갱신 실패: %s", date_str)
    return new


# ── KRX Open API 호출 ────────────────────────────────────────────

def krx_get_daily(api_id: str, bas_dd: str, api_key: str) -> "list[dict] | None":
    """KRX Open API에서 하루치 시장 전체 시세를 받는다.

    실패(401·비JSON·`OutBlock_1` 부재·재시도 소진)면 None — 호출부가 이걸
    캐시하면 안 된다. 정상이면 `OutBlock_1` 리스트(휴장일은 빈 리스트).

    로그에 헤더·키(`AUTH_KEY`)·응답 본문을 남기지 않는다 — dart_client._retry가
    `crtfc_key`를 로그에 남기지 않는 것과 같은 이유.
    """
    url = f"{KRX_BASE}/{api_id}"
    resp = None
    for i in range(3):
        try:
            resp = requests.get(
                url,
                params={"basDd": bas_dd},
                headers={"AUTH_KEY": api_key},
                timeout=15,
            )
        except requests.RequestException:
            log.warning("KRX 요청 실패(예외): api_id=%s bas_dd=%s", api_id, bas_dd)
            return None
        if resp.status_code not in (429, 500, 502, 503, 504):
            break
        if i < 2:
            time.sleep(min(2 ** i, 10))

    if resp is None or resp.status_code != 200:
        status = resp.status_code if resp is not None else None
        log.warning("KRX 요청 실패(status=%s): api_id=%s bas_dd=%s", status, api_id, bas_dd)
        return None

    try:
        data = resp.json()
    except ValueError:
        log.warning("KRX 응답이 JSON이 아니다: api_id=%s bas_dd=%s", api_id, bas_dd)
        return None

    if not isinstance(data, dict):
        return None

    out_block = data.get("OutBlock_1")
    if not isinstance(out_block, list):
        log.warning("KRX 응답에 OutBlock_1이 없다: api_id=%s bas_dd=%s", api_id, bas_dd)
        return None
    return out_block


# ── 정규화 ────────────────────────────────────────────────────────

def _to_number(value):
    """콤마 제거 후 int/float, 못 읽으면 None. 값이 이미 숫자면 그대로."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    s = str(value).replace(",", "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return float(s)
        except ValueError:
            return None


def _normalize_row(date8: str, raw: dict) -> dict:
    return {
        "date": date8,
        "close": _to_number(raw.get("TDD_CLSPRC")),
        "fluc_rt": _to_number(raw.get("FLUC_RT")),
        "volume": _to_number(raw.get("ACC_TRDVOL")),
        "value": _to_number(raw.get("ACC_TRDVAL")),
        "mktcap": _to_number(raw.get("MKTCAP")),
        "list_shrs": _to_number(raw.get("LIST_SHRS")),
        # 코스닥 소속부 — 실측(2026-09-22)에 「관리종목(소속부없음)」·
        # 「투자주의환기종목(소속부없음)」이 그대로 온다(유가증권은 늘 빈 문자열).
        # 날짜별로 바뀌므로(제이스코홀딩스 2025-09 중견기업부 → 2026-09 관리종목)
        # 시계열 사실로 쓸 수 있다.
        "sect": (raw.get("SECT_TP_NM") or "").strip() or None,
    }


def _weekday_candidates(start_dd: str, end_dd: str) -> "list[str]":
    """start~end(포함) 사이의 월~금 날짜를 오름차순으로 나열한다."""
    start = datetime.strptime(start_dd, "%Y%m%d")
    end = datetime.strptime(end_dd, "%Y%m%d")
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def _empty_series_result(*, api_id, fetch_failed, **extra) -> dict:
    base = {
        "rows": [],
        "days_requested": 0,
        "days_fetched": 0,
        "days_cached": 0,
        "days_uncovered": [],
        "days_pending": [],
        "quota_hit": False,
        "fetch_failed": fetch_failed,
        "api_id": api_id,
    }
    base.update(extra)
    return base


# ── 조회 ──────────────────────────────────────────────────────────

def fetch_price_series(
    stock_code: str,
    corp_cls: str,
    start_dd: str,
    end_dd: str,
    api_key: str,
    *,
    budget: int = KRX_CALL_BUDGET,
) -> dict:
    """`stock_code`의 일별 시세를 `start_dd`~`end_dd`(포함) 구간에서 모은다.

    거래일 후보(월~금)를 **최근부터** 훑는다 — 예산·소프트캡이 바닥나면 남는
    쪽은 항상 **오래된 날짜**다(관측 도구라 최근이 더 유용하다는 판단,
    `resolve_disclosure_row_with_status`의 최신순 관례와 반대 — 여기는 하루
    단위로 시장 전체를 캐시하므로 최근을 먼저 채우는 편이 다음 조회에도
    유리하다).

    캐시 히트는 예산·계수 어느 쪽도 소모하지 않는다. 오늘(기기 로컬 날짜)은
    캐시를 읽지도 쓰지도 않는다.
    """
    api_id = KRX_API_IDS.get(corp_cls)
    if api_id is None:
        return _empty_series_result(api_id=None, fetch_failed=False, unsupported_market=True)

    if not api_key:
        return _empty_series_result(api_id=api_id, fetch_failed=True, missing_key=True)

    candidates = _weekday_candidates(start_dd, end_dd)
    days_requested = len(candidates)
    today = _today_str()
    quota_date = today
    quota_exhausted = _quota_count(quota_date) >= KRX_SOFT_CAP

    rows_by_date: dict[str, dict] = {}
    days_fetched = 0
    days_cached = 0
    days_uncovered: list[str] = []
    days_pending: list[str] = []
    fetch_failed = False
    quota_hit = False

    # 1단계 — 최근 날짜부터 캐시를 읽고, 미스는 예산·소프트캡 안에서 조회 대상으로.
    payloads: dict[str, dict] = {}
    to_fetch: list[str] = []
    quota_room = max(0, KRX_SOFT_CAP - _quota_count(quota_date))
    for date8 in reversed(candidates):
        if date8 != today:
            cached = _read_cache(api_id, date8)
            if cached is not None:
                payloads[date8] = cached
                days_cached += 1
                continue
        if quota_exhausted or len(to_fetch) >= quota_room:
            quota_hit = True
            days_uncovered.append(date8)
            continue
        if len(to_fetch) >= budget:
            days_uncovered.append(date8)
            continue
        to_fetch.append(date8)

    # 2단계 — 동시 조회. 실측(2026-09-22)에 동시 5콜까지 스로틀이 없었다.
    # 계수는 시도마다 올린다(캐시 히트는 안 센다). 실패는 캐시하지 않는다.
    if to_fetch:
        for date8 in to_fetch:
            if _quota_increment(quota_date) >= KRX_SOFT_CAP:
                quota_exhausted = True
        workers = max(1, min(KRX_CONCURRENCY, len(to_fetch)))
        if workers == 1:
            fetched = [(d, krx_get_daily(api_id, d, api_key)) for d in to_fetch]
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                fetched = list(zip(
                    to_fetch,
                    ex.map(lambda d: krx_get_daily(api_id, d, api_key), to_fetch),
                ))
        grace_floor = (datetime.strptime(today, "%Y%m%d")
                       - timedelta(days=KRX_EMPTY_GRACE_DAYS)).strftime("%Y%m%d")
        for date8, result in fetched:
            if result is None:
                fetch_failed = True
                days_uncovered.append(date8)
                continue
            days_fetched += 1
            if result:
                kept_rows = [{k: r.get(k) for k in KRX_KEEP_FIELDS} for r in result]
                day_payload = {"rows": kept_rows}
            else:
                day_payload = {"empty": True}
                if date8 >= grace_floor:
                    # 최근 며칠의 빈 응답은 휴장일이 아니라 **발표 전**일 수 있다 —
                    # 캐시하면 영구 휴장일이 된다. 오늘치로만 두고 다음 호출이 다시 본다.
                    days_pending.append(date8)
                    payloads[date8] = day_payload
                    continue
            if date8 != today:
                _write_cache(api_id, date8, day_payload)
            payloads[date8] = day_payload

    for date8, day_payload in payloads.items():
        if day_payload.get("empty"):
            continue
        stock_row = next(
            (r for r in day_payload.get("rows", []) if str(r.get("ISU_CD")) == str(stock_code)),
            None,
        )
        if stock_row is not None:
            rows_by_date[date8] = _normalize_row(date8, stock_row)

    rows = [rows_by_date[d] for d in sorted(rows_by_date)]

    return {
        "rows": rows,
        "days_requested": days_requested,
        "days_fetched": days_fetched,
        "days_cached": days_cached,
        "days_uncovered": sorted(days_uncovered),
        "days_pending": sorted(days_pending),
        "quota_hit": quota_hit,
        "fetch_failed": fetch_failed,
        "api_id": api_id,
    }
