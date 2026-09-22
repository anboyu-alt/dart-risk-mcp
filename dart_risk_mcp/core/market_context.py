# -*- coding: utf-8 -*-
"""공시 전후 시장 반응 — 사실 계산 (순수 함수).

이 모듈은 KRX 일별매매정보(krx_client)·KIND 시장경보(kind_client)가 이미
받아 온 값을 사실로만 계산한다. 네트워크 호출·파일 I/O가 없고, 표준
라이브러리만 쓴다.

**판정하지 않는다(v0.8.5)** — 임계값을 정하지 않고 등락률·배수·회전율·일수를
그대로 반환한다. "값이 없다"와 "계산할 수 없다"를 구분해, 계산이 불가능하면
그 값을 None으로 두고 사유를 별도 문자열(`*_note`)에 사실로 남긴다.

관리종목 지정요건의 시가총액·주가 규정선(`MGMT_ISSUE_MKTCAP_KRW`·
`MGMT_ISSUE_PRICE_KRW`)은 이 도구가 정한 임계가 아니라 금융당국 규정 수치를
그대로 옮긴 것이다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

# 관리종목 지정요건의 규정 수치이며 이 도구의 임계가 아니다.
# ⚠ 단위는 원(KRX 명세 기준으로 가정) — 0단계 실측으로 단위 확인 필요.
MGMT_ISSUE_MKTCAP_KRW = 20_000_000_000
MGMT_ISSUE_PRICE_KRW = 1000

_DATE_FMT = "%Y%m%d"


def date8_add_days(date8: str, n: int) -> str:
    """YYYYMMDD 문자열에 n일을 더한(음수면 뺀) YYYYMMDD 문자열을 반환한다."""
    d = datetime.strptime(date8, _DATE_FMT)
    return (d + timedelta(days=n)).strftime(_DATE_FMT)


def _calendar_days_between(a: str, b: str) -> int:
    """두 YYYYMMDD 문자열 사이의 달력일 차이(절댓값)."""
    da = datetime.strptime(a, _DATE_FMT)
    db = datetime.strptime(b, _DATE_FMT)
    return abs((da - db).days)


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _row_turnover_pct(row: dict) -> float | None:
    """한 거래일 행의 거래량/상장주식수 ×100. 계산 불가하면 None."""
    volume = row.get("volume")
    list_shrs = row.get("list_shrs")
    if volume is None or list_shrs is None or list_shrs == 0:
        return None
    return volume / list_shrs * 100


def event_window_facts(
    rows: list[dict],
    event_date8: str,
    *,
    pre: int = 5,
    post: int = 5,
    baseline: int = 60,
    min_baseline: int = 20,
) -> dict | None:
    """사건일(공시 접수일) 전후 거래일 창의 사실을 계산한다.

    rows는 날짜 오름차순의 거래일 행만 담아야 한다(휴장일 없음). D0은
    event_date8과 같거나 그 뒤인 첫 거래일이다 — event_date8 자체가
    휴장일이면 다음 거래일로 밀리고 그 사실을 `d0_shifted`에 남긴다.

    D0 이후 거래일이 하나도 없으면(사건일이 조회 범위를 벗어나면) None을
    반환한다 — "값이 0"과 "계산할 수 없다"를 구분하기 위함이다.
    """
    d0_idx = None
    for i, row in enumerate(rows):
        if row.get("date", "") >= event_date8:
            d0_idx = i
            break
    if d0_idx is None:
        return None

    d0_row = rows[d0_idx]
    d0_date = d0_row.get("date")
    d0_shifted = d0_date != event_date8

    pre_start = max(0, d0_idx - pre)
    pre_rows = rows[pre_start:d0_idx]
    pre_partial = len(pre_rows) < pre

    baseline_end = pre_start
    baseline_start = max(0, baseline_end - baseline)
    baseline_rows = rows[baseline_start:baseline_end]

    post_end = min(len(rows), d0_idx + 1 + post)
    post_rows = rows[d0_idx + 1 : post_end]
    post_partial = len(post_rows) < post

    # --- 등락률 ---
    pre_return_pct = None
    if len(pre_rows) >= 2:
        first_close = pre_rows[0].get("close")
        last_close = pre_rows[-1].get("close")
        if first_close is not None and last_close is not None and first_close != 0:
            pre_return_pct = (last_close - first_close) / first_close * 100

    post_return_pct = None
    d0_close = d0_row.get("close")
    if post_rows:
        last_post_close = post_rows[-1].get("close")
        if d0_close is not None and last_post_close is not None and d0_close != 0:
            post_return_pct = (last_post_close - d0_close) / d0_close * 100

    # --- 거래량 배수 (기준선 대비) ---
    baseline_avail = len(baseline_rows)
    baseline_note = None
    pre_vol_ratio = None
    d0_vol_ratio = None

    if baseline_avail < min_baseline:
        baseline_note = f"기준선 {baseline_avail}거래일 (최소 {min_baseline})"
    else:
        baseline_vols = [
            r.get("volume") for r in baseline_rows if r.get("volume") is not None
        ]
        baseline_avg = _avg(baseline_vols) if baseline_vols else None
        if baseline_avg is None:
            baseline_note = "기준선 거래량 자료가 없습니다"
        elif baseline_avg == 0:
            baseline_note = "기준선 평균 거래량이 0입니다"
        else:
            pre_vols = [r.get("volume") for r in pre_rows if r.get("volume") is not None]
            pre_avg = _avg(pre_vols) if pre_vols else None
            if pre_avg is not None:
                pre_vol_ratio = pre_avg / baseline_avg
            d0_volume = d0_row.get("volume")
            if d0_volume is not None:
                d0_vol_ratio = d0_volume / baseline_avg

    # --- 회전율 ---
    turnover_note = None
    turnover_pre_pct = None
    pre_turnovers = [_row_turnover_pct(r) for r in pre_rows]
    if pre_rows and all(t is not None for t in pre_turnovers):
        turnover_pre_pct = sum(pre_turnovers) * 100
    turnover_d0_pct = _row_turnover_pct(d0_row)
    if turnover_d0_pct is not None:
        turnover_d0_pct = turnover_d0_pct * 100

    if turnover_pre_pct is None or turnover_d0_pct is None:
        turnover_note = "상장주식수가 없어 회전율을 계산할 수 없는 거래일이 있습니다"

    return {
        "event_date": event_date8,
        "d0_date": d0_date,
        "d0_shifted": d0_shifted,
        "d0_close": d0_close,
        "d0_fluc_rt": d0_row.get("fluc_rt"),
        "pre_return_pct": pre_return_pct,
        "post_return_pct": post_return_pct,
        "pre_vol_ratio": pre_vol_ratio,
        "d0_vol_ratio": d0_vol_ratio,
        "baseline_note": baseline_note,
        "turnover_pre_pct": turnover_pre_pct,
        "turnover_d0_pct": turnover_d0_pct,
        "turnover_note": turnover_note,
        "mktcap_d0": d0_row.get("mktcap"),
        "days_pre_avail": len(pre_rows),
        "days_post_avail": len(post_rows),
        "baseline_avail": baseline_avail,
        "post_partial": post_partial,
        "pre_partial": pre_partial,
    }


def align_alerts_with_events(
    alerts: list[dict], observed_events: list[dict], days: int = 10
) -> list[dict]:
    """경보 지정일 ±days 안의 관찰 공시를 경보마다 묶는다.

    경보는 지정일(`designated`) 내림차순으로 정렬해 반환한다. 각 경보에
    딸린 공시는 rcept_dt 오름차순이다. 경계는 달력일 기준(거래일 아님)이며
    양 끝을 포함한다.
    """
    sorted_alerts = sorted(
        alerts, key=lambda a: a.get("designated") or "", reverse=True
    )
    result = []
    for alert in sorted_alerts:
        designated = alert.get("designated")
        matched = []
        if designated:
            for ev in observed_events:
                rcept_dt = ev.get("rcept_dt")
                if not rcept_dt:
                    continue
                if _calendar_days_between(rcept_dt, designated) <= days:
                    matched.append(ev)
        matched.sort(key=lambda e: e.get("rcept_dt") or "")
        result.append({"alert": alert, "events": matched})
    return result


def window_overview(rows: list[dict]) -> dict | None:
    """조회 창 전체의 시가·종가·고저·회전율·시총 개괄.

    빈 rows는 None을 반환한다. 종가가 없는 행은 고가·저가 계산에서
    제외한다(값이 없는 것과 0인 것을 구분하기 위함).
    """
    if not rows:
        return None

    start_row = rows[0]
    end_row = rows[-1]
    start_close = start_row.get("close")
    end_close = end_row.get("close")

    window_return_pct = None
    if start_close is not None and end_close is not None and start_close != 0:
        window_return_pct = (end_close - start_close) / start_close * 100

    high_close = None
    high_date = None
    low_close = None
    low_date = None
    for row in rows:
        close = row.get("close")
        if close is None:
            continue
        if high_close is None or close > high_close:
            high_close = close
            high_date = row.get("date")
        if low_close is None or close < low_close:
            low_close = close
            low_date = row.get("date")

    turnovers = []
    for row in rows:
        t = _row_turnover_pct(row)
        if t is not None:
            turnovers.append(t)
    turnover_days = len(turnovers)
    avg_turnover_pct = (sum(turnovers) / turnover_days) if turnover_days else None

    days_mktcap_under_20bn = sum(
        1
        for row in rows
        if row.get("mktcap") is not None and row["mktcap"] < MGMT_ISSUE_MKTCAP_KRW
    )
    days_close_under_1000 = sum(
        1
        for row in rows
        if row.get("close") is not None and row["close"] < MGMT_ISSUE_PRICE_KRW
    )

    return {
        "start_date": start_row.get("date"),
        "start_close": start_close,
        "end_date": end_row.get("date"),
        "end_close": end_close,
        "window_return_pct": window_return_pct,
        "high_close": high_close,
        "high_date": high_date,
        "low_close": low_close,
        "low_date": low_date,
        "avg_turnover_pct": avg_turnover_pct,
        "turnover_days": turnover_days,
        "end_mktcap": end_row.get("mktcap"),
        "days": len(rows),
        "days_mktcap_under_20bn": days_mktcap_under_20bn,
        "days_close_under_1000": days_close_under_1000,
    }
