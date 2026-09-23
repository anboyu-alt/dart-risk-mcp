"""한국투자증권(KIS) Open API 클라이언트 — 종목 일봉(원주가)으로 시세 구간을 채운다.

KRX Open API(`krx_client.py`)는 **하루 단위·시장 전체** 응답이라 한 회사 1년에
약 245콜이 들고, 호출이 몰리면 IP가 약 10분 403으로 막힌다(2026-09-23 실측).
KIS 일봉 API는 **종목·기간 단위**라 같은 1년이 **3콜**이다(최신순 100행씩).
대신 일자별 **시가총액·상장주식수·코스닥 소속부가 없다** — 그래서 회전율·시총은
KIS로 채울 수 없다. 이 모듈은 KRX와 **같은 반환 모양**을 돌려주고, 없는 필드는
`None`으로 두어 소비처(`market_context`)가 "계산할 수 없다"를 사실로 적게 한다.

**점수·등급·판정은 하지 않는다**(v0.8.5 원칙) — 순수 조회 계층이다.

## 실측 계약 (2026-09-23, 제작자 실전 계좌 앱키 · GitHub Actions 임시 브랜치)

- 토큰 `POST /oauth2/tokenP` → `access_token`·`access_token_token_expired`
  (`"2026-09-24 23:13:17"`)·`expires_in`=86400. 재발급을 자주 하면 안 되므로
  디스크에 캐시하고 만료 10분 전까지 재사용한다.
- 일봉 `GET /uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice`
  (`tr_id=FHKST03010100`) — `output2`가 **최신순 최대 100행**. 이어 받기는 가장
  오래된 날짜 −1일을 새 종료일로 준다(CSA 코스믹 1년 = 100·100·43행 3콜, 243거래일).
- `FID_ORG_ADJ_PRC="1"`이 **원주가**, `"0"`이 수정주가다. 원주가를 쓴다 — KRX
  `TDD_CLSPRC`·`ACC_TRDVOL`이 원값이라 섞어도 뜻이 같다. CSA 코스믹 2026-08-04:
  원주가 종가 3,045·거래량 56,342 ↔ 수정주가 1,522·112,684.
- `prdy_vrss`는 **부호가 붙어** 온다(`"-64"`, 부호코드 5=하락). 그리고 전일
  **기준가** 대비다 — CSA 코스믹 2026-08-26 원주가 종가 1,859·`prdy_vrss` +429라
  기준가가 1,430(전일 종가 2,860의 절반)이다. 즉 KRX `FLUC_RT`와 같은 뜻이고,
  `market_context.price_breaks`가 기준가 조정일을 그대로 잡는다.
- 매매거래정지일은 행이 **거래량 0·종가 전일 그대로**로 온다(CSA 코스믹
  2026-08-25) — KRX와 같다. 휴장일은 행이 없다.
- 25콜 연속 13.9초·실패 0 — 초당 한도(실전 20건/초)에 닿지 않는다.
- ⚠ 응답의 `flng_cls_code`(락구분)·`prtt_rate`(분할비율)는 분할일에도
  `00`·`0.00`이었다 — 기준가 조정을 알려 주지 않으므로 읽지 않는다.

## 약관 경계

KIS Open API도 제공받은 정보를 제3자에게 제공할 수 없다(KRX 약관 제11조 ②와
같은 부류). MCP는 사용자 기기에서 사용자 본인 키로 돌므로 해당 없지만,
**공개 뷰어에는 운영자 키로 받은 KIS 시세를 싣지 않는다**.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .dart_client import _resolve_corp_cache_dir
from .krx_client import KRX_API_IDS, _to_number, _today_str, _weekday_candidates

log = logging.getLogger(__name__)

KIS_BASE = "https://openapi.koreainvestment.com:9443"
KIS_TOKEN_PATH = "/oauth2/tokenP"
KIS_DAILY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
KIS_DAILY_TR_ID = "FHKST03010100"
KIS_PAGE_ROWS = 100          # 일봉 응답 한 번의 최대 행 수(실측)
# 한 번의 조회에서 부를 일봉 콜 상한 — 30콜이면 3,000거래일(약 12년). 도구 창은
# 5년+100일이라 실제로는 닿지 않는다. 닿으면 남는 오래된 날을 `days_uncovered`로 알린다.
KIS_MAX_CALLS = 30
# 토큰을 만료 이만큼 전부터는 새로 받는다(초) — 긴 조회 중간에 만료되지 않게.
KIS_TOKEN_MARGIN_SEC = 600
KIS_SOURCE_LABEL = "한국투자증권 Open API"

_token_lock = threading.Lock()
_token_mem: dict[str, tuple[str, float]] = {}


# ── 토큰 ──────────────────────────────────────────────────────────

def _key_fingerprint(app_key: str) -> str:
    """캐시 파일 이름에 쓸 앱키 지문 — 키 자체는 디스크·로그에 남기지 않는다."""
    return hashlib.sha256(app_key.encode("utf-8")).hexdigest()[:16]


def _token_path(app_key: str) -> Path:
    return _resolve_corp_cache_dir() / "kis" / f"token_{_key_fingerprint(app_key)}.json"


def _parse_expiry(payload: dict, now: float) -> float:
    """만료 시각(epoch). `access_token_token_expired`(KST 표기)를 먼저 읽고, 못 읽으면
    `expires_in`(초)로, 그것도 없으면 보수적으로 1시간.

    ⚠ 표기는 시간대 없이 KST다 — 기기 로컬로 읽으면 UTC 기기(CI)에서 9시간 늦게
    만료된 것으로 알아 낡은 토큰을 쓴다. KST로 못 박는다."""
    raw = str(payload.get("access_token_token_expired") or "").strip()
    if raw:
        try:
            return (datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
                    .replace(tzinfo=timezone(timedelta(hours=9))).timestamp())
        except ValueError:
            pass
    try:
        return now + int(payload.get("expires_in"))
    except (TypeError, ValueError):
        return now + 3600


def _read_token_file(app_key: str) -> "tuple[str, float] | None":
    try:
        with open(_token_path(app_key), encoding="utf-8") as f:
            data = json.load(f)
        tok, exp = data.get("access_token"), float(data.get("expires_at", 0))
        if tok:
            return tok, exp
    except Exception:
        pass
    return None


def _write_token_file(app_key: str, token: str, expires_at: float) -> None:
    """원자적 교체(`krx_client._write_cache`와 같은 관례). 실패해도 조회는 계속한다."""
    path = _token_path(app_key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"access_token": token, "expires_at": expires_at}, f)
        os.replace(tmp, path)
    except Exception:
        log.warning("KIS 토큰 캐시 쓰기 실패")


def _drop_token(app_key: str) -> None:
    _token_mem.pop(_key_fingerprint(app_key), None)
    try:
        _token_path(app_key).unlink()
    except Exception:
        pass


def kis_access_token(app_key: str, app_secret: str, *, force: bool = False) -> "str | None":
    """접근 토큰. 메모리 → 디스크 → 발급 순으로 찾는다. 실패면 None.

    KIS는 토큰 재발급 빈도를 제한한다(1분 1회 안내) — 매 호출 발급하면 두 번째
    호출부터 거절된다. 그래서 24시간 유효한 토큰을 기기 캐시에 두고 재사용한다.
    로그에 앱키·시크릿·토큰을 남기지 않는다.
    """
    if not app_key or not app_secret:
        return None
    fp = _key_fingerprint(app_key)
    now = time.time()
    with _token_lock:
        if not force:
            hit = _token_mem.get(fp) or _read_token_file(app_key)
            if hit and hit[1] - now > KIS_TOKEN_MARGIN_SEC:
                _token_mem[fp] = hit
                return hit[0]
        try:
            resp = requests.post(
                KIS_BASE + KIS_TOKEN_PATH,
                json={"grant_type": "client_credentials", "appkey": app_key, "appsecret": app_secret},
                timeout=15,
            )
        except requests.RequestException:
            log.warning("KIS 토큰 발급 요청 실패(예외)")
            return None
        if resp.status_code != 200:
            log.warning("KIS 토큰 발급 실패(status=%s)", resp.status_code)
            return None
        try:
            payload = resp.json()
        except ValueError:
            log.warning("KIS 토큰 응답이 JSON이 아니다")
            return None
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            log.warning("KIS 토큰 응답에 access_token이 없다")
            return None
        expires_at = _parse_expiry(payload, now)
        _token_mem[fp] = (token, expires_at)
        _write_token_file(app_key, token, expires_at)
        return token


# ── 일봉 ──────────────────────────────────────────────────────────

def kis_get_daily(
    stock_code: str, start_dd: str, end_dd: str, app_key: str, app_secret: str,
) -> "list[dict] | None":
    """원주가 일봉 한 페이지(최신순 최대 100행). 실패면 None.

    토큰 만료로 거절되면 한 번만 새 토큰으로 다시 부른다.
    """
    for attempt in range(2):
        token = kis_access_token(app_key, app_secret, force=attempt > 0)
        if not token:
            return None
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": KIS_DAILY_TR_ID,
            "custtype": "P",
            "content-type": "application/json; charset=utf-8",
        }
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_DATE_1": start_dd,
            "FID_INPUT_DATE_2": end_dd,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "1",   # 원주가 — 위 모듈 설명 참고
        }
        resp = None
        for i in range(3):
            try:
                resp = requests.get(KIS_BASE + KIS_DAILY_PATH, headers=headers, params=params, timeout=15)
            except requests.RequestException:
                log.warning("KIS 일봉 요청 실패(예외): %s %s~%s", stock_code, start_dd, end_dd)
                return None
            if resp.status_code not in (429, 500, 502, 503, 504):
                break
            if i < 2:
                time.sleep(min(2 ** i, 10))
        if resp is None:
            return None
        try:
            data = resp.json()
        except ValueError:
            log.warning("KIS 일봉 응답이 JSON이 아니다(status=%s)", resp.status_code)
            return None
        if not isinstance(data, dict):
            return None
        if data.get("rt_cd") == "0" and resp.status_code == 200:
            out = data.get("output2")
            if not isinstance(out, list):
                return None
            return [r for r in out if isinstance(r, dict) and r.get("stck_bsop_date")]
        msg_cd = str(data.get("msg_cd") or "")
        # EGW00123(기간 만료 토큰)·EGW00121(유효하지 않은 토큰) — 캐시가 낡았다.
        if attempt == 0 and msg_cd in ("EGW00123", "EGW00121"):
            _drop_token(app_key)
            continue
        log.warning("KIS 일봉 실패(status=%s msg_cd=%s)", resp.status_code, msg_cd)
        return None
    return None


def _normalize_kis_row(raw: dict) -> dict:
    """KIS 일봉 한 행 → KRX `_normalize_row`와 같은 키.

    등락률은 KRX `FLUC_RT`와 같은 뜻(전일 기준가 대비)으로 만든다 — `prdy_vrss`가
    기준가 대비 차이라 `기준가 = 종가 − prdy_vrss`. 부호코드가 하락(4·5)인데 값이
    양수로 온 행은 음수로 뒤집는다(실측은 이미 음수였지만 서식이 바뀌어도 방향이
    뒤집히지 않게). 시총·상장주식수·소속부는 이 API에 없다 — `None`.
    """
    close = _to_number(raw.get("stck_clpr"))
    diff = _to_number(raw.get("prdy_vrss"))
    if diff is not None and str(raw.get("prdy_vrss_sign") or "") in ("4", "5") and diff > 0:
        diff = -diff
    fluc = None
    if close is not None and diff is not None:
        base = close - diff
        if base > 0:
            fluc = round(diff / base * 100, 2)
    return {
        "date": str(raw.get("stck_bsop_date")),
        "close": close,
        "fluc_rt": fluc,
        "volume": _to_number(raw.get("acml_vol")),
        "value": _to_number(raw.get("acml_tr_pbmn")),
        "mktcap": None,
        "list_shrs": None,
        "sect": None,
        # 출처 표지 — KRX 행과 섞일 때 `window_overview`가 소속부 이동을 KRX 행으로만
        # 보게 한다(KIS에는 소속부가 없어 None이 「(없음)」으로 읽히면 안 된다).
        "src": "kis",
    }


def _prev_day(date8: str) -> str:
    return (datetime.strptime(date8, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")


def fetch_price_series_kis(
    stock_code: str,
    corp_cls: str,
    start_dd: str,
    end_dd: str,
    app_key: str,
    app_secret: str,
    *,
    max_calls: int = KIS_MAX_CALLS,
) -> dict:
    """`krx_client.fetch_price_series`와 **같은 키**로 시세 구간을 돌려준다.

    최신 쪽부터 100행씩 이어 받는다 — 상한·실패로 멈추면 남는 쪽은 KRX 경로와
    같이 **오래된 날짜**이고 `days_uncovered`에 적는다. 받은 구간 안에서 행이 없는
    평일은 휴장일이다(KIS는 휴장일 행을 주지 않는다 — 빈틈이 아니다).

    오늘 행은 장중 부분 자료일 수 있어 빼고 `days_pending`에 적는다(KRX 경로가
    오늘을 캐시하지 않는 것과 같은 태도). 캐시는 두지 않는다 — 1년이 3콜이다.
    """
    base = {
        "rows": [], "days_requested": 0, "days_fetched": 0, "days_cached": 0,
        "days_uncovered": [], "days_pending": [], "quota_hit": False,
        "fetch_failed": False, "api_id": "kis_daily", "source": "kis",
        "no_share_data": True,
    }
    if corp_cls not in KRX_API_IDS:
        return {**base, "api_id": None, "unsupported_market": True}
    if not (app_key and app_secret):
        return {**base, "fetch_failed": True, "missing_key": True}

    candidates = _weekday_candidates(start_dd, end_dd)
    today = _today_str()
    by_date: dict[str, dict] = {}
    cursor = end_dd
    covered_from = None       # 이 날짜(포함) 이후는 받은 구간
    failed = False
    calls = 0
    while calls < max_calls:
        page = kis_get_daily(stock_code, start_dd, cursor, app_key, app_secret)
        calls += 1
        if page is None:
            failed = True
            break
        for raw in page:
            row = _normalize_kis_row(raw)
            if start_dd <= row["date"] <= end_dd:
                by_date[row["date"]] = row
        dates = sorted(r["stck_bsop_date"] for r in page)
        if not dates or len(page) < KIS_PAGE_ROWS or dates[0] <= start_dd:
            covered_from = start_dd      # 끝까지 받았다(상장 전 구간 포함)
            break
        covered_from = dates[0]
        cursor = _prev_day(dates[0])
    if covered_from is None:
        covered_from = "99999999"         # 첫 콜부터 실패 — 전부 미조회

    pending: list[str] = []
    if today in by_date:
        by_date.pop(today)
        pending.append(today)
    uncovered = [d for d in candidates if d < covered_from]
    fetched = [d for d in candidates if d >= covered_from and d not in pending]

    rows = [{**by_date[d], "gap_before": False} for d in sorted(by_date)]
    return {
        **base,
        "rows": rows,
        "days_requested": len(candidates),
        "days_fetched": len(fetched),
        "days_uncovered": uncovered,
        "days_pending": pending,
        # 받은 행이 하나라도 있으면 보여 준다 — 뒤(오래된 쪽)가 끊긴 사실은
        # `days_uncovered`와 `partial_failed`가 말한다. 아무것도 못 받았을 때만 실패.
        "fetch_failed": failed and not rows,
        "partial_failed": failed and bool(rows),
        "calls": calls,
    }


def fill_series_with_kis(
    series: dict,
    stock_code: str,
    corp_cls: str,
    app_key: str,
    app_secret: str,
) -> dict:
    """KRX 시세 구간이 **못 받은 날**(호출 예산·실패·발표 전)을 KIS 원주가 일봉으로 채운다.

    KRX가 받은 날은 그대로 둔다 — 시총·상장주식수·소속부가 KRX에만 있다. KIS로
    채운 날은 그 셋이 `None`이라 회전율·시총이 그날만 빠지고, `market_context`가
    그 사실을 각주로 적는다. 둘 다 원값 종가·원값 거래량·기준가 대비 등락률이라
    한 시계열에 섞어도 뜻이 같다(모듈 설명 참고).

    KIS 조회가 실패하면 KRX 결과를 그대로 돌려주고 `kis_fill_failed`만 표시한다.
    """
    unknown = sorted(set(series.get("days_uncovered") or []) | set(series.get("days_pending") or []))
    if not unknown or series.get("unsupported_market"):
        return {**series, "source": series.get("source") or "krx"}

    kis = fetch_price_series_kis(stock_code, corp_cls, unknown[0], unknown[-1], app_key, app_secret)
    kis_unknown = set(kis.get("days_uncovered") or []) | set(kis.get("days_pending") or [])
    if kis.get("fetch_failed") and not kis.get("rows"):
        return {**series, "source": series.get("source") or "krx", "kis_fill_failed": True}

    resolved = {d for d in unknown if d not in kis_unknown}
    by_date = {r["date"]: {k: v for k, v in r.items() if k != "gap_before"} for r in series.get("rows", [])}
    kis_days = 0
    for r in kis.get("rows", []):
        if r["date"] in resolved and r["date"] not in by_date:
            by_date[r["date"]] = {k: v for k, v in r.items() if k != "gap_before"}
            kis_days += 1

    remaining_uncovered = [d for d in series.get("days_uncovered") or [] if d not in resolved]
    remaining_pending = [d for d in series.get("days_pending") or [] if d not in resolved]
    unknown_left = set(remaining_uncovered) | set(remaining_pending)
    rows = []
    prev = None
    for d in sorted(by_date):
        rows.append({
            **by_date[d],
            "gap_before": bool(prev) and any(prev < u < d for u in unknown_left),
        })
        prev = d

    return {
        **series,
        "rows": rows,
        "days_fetched": (series.get("days_fetched") or 0) + len(resolved),
        "days_uncovered": remaining_uncovered,
        "days_pending": remaining_pending,
        # 실패한 날이 KIS로 전부 메워졌으면 더는 실패가 아니다.
        "fetch_failed": bool(series.get("fetch_failed")) and bool(remaining_uncovered),
        "source": "krx+kis" if kis_days else (series.get("source") or "krx"),
        "kis_days": kis_days,
        "kis_fill_failed": bool(kis.get("fetch_failed") or kis.get("partial_failed")),
    }
