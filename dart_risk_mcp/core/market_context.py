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


def _dot_date(date8) -> str:
    """YYYYMMDD → YYYY.MM.DD (8자리가 아니면 그대로)."""
    d = str(date8 or "")
    return f"{d[:4]}.{d[4:6]}.{d[6:]}" if len(d) == 8 and d.isdigit() else d


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


PRICE_BREAK_TOL_PCT = 1.0       # 원값 등락과 KRX 등락률(FLUC_RT)이 이만큼(%p) 어긋나면 기준가 조정일
PRICE_BREAK_SHARE_UP = 1.8      # (등락률이 없을 때의 보조 규칙) 주식수가 이 배수를 넘겨 늘면 점프
PRICE_BREAK_SHARE_DOWN = 0.55   # 이 비율 이하로 줄면 점프
PRICE_BREAK_PRODUCT_MAX = 1.4   # 늘어난 쪽: 주식수비×종가비가 이 값 이하면 가격이 역비례(분할·무상증자 권리락)
PRICE_BREAK_PRODUCT_MIN = 0.7   # 줄어든 쪽: 이 값을 넘으면 가격이 역비례(병합·감자)


def price_breaks(rows: list[dict]) -> list[dict]:
    """연속 거래일 사이에서 **KRX가 기준가를 조정한 날**(종가 불연속)을 찾는다.

    KRX 일별매매정보의 `FLUC_RT`는 전일 **기준가** 대비 등락률이라, 액면분할·
    병합·감자·무상증자·유상증자 권리락·인적분할 재상장처럼 기준가가 조정된 날은
    원값 종가 비교(`close/prev_close`)와 어긋난다. 그 어긋남이 곧 사실이다 —
    캐시 1년 전 종목 실측(2026-09-23): 연속 거래일 쌍 1,428,842개 중
    |원값−등락률| < 0.02%p가 99.9%이고, 1%p를 넘는 것은 815건. 그중 **394건(48%)은
    상장주식수가 그대로**라(유상증자 권리락 000500 −31.9% vs +22.5% · 무상감자
    재개 002210 +85% vs −7.5% · 삼성바이오로직스 인적분할 재상장 20251124 +46.5%
    vs −0.45%) 주식수 점프만 보던 첫 판(313건)은 절반을 놓쳤다.

    반환 원소 `{"date", "adj", "share_ratio"}` — `adj`는 기준가 ÷ 전일 종가
    (5:1 분할 0.20 · 5:1 병합 5.00 · 권리락 0.7 안팎), `share_ratio`는 그날 상장
    주식수 ÷ 전일(없으면 None). 등락률이 없는 행은 보조 규칙(주식수 점프 + 종가
    역비례)으로 본다. `gap_before`(그 앞 거래일이 미조회)인 행은 전일이 아닌
    날과 비교하게 되므로 건너뛴다 — 며칠치 움직임을 하루 등락률과 견주면 없는
    불연속을 만든다. 종가가 없는 행은 판정하지 않는다.
    """
    out = []
    prev = None
    for row in rows:
        close = row.get("close")
        if row.get("gap_before"):
            prev = None
        if close is None or close <= 0:
            prev = None
            continue
        if prev is not None:
            pclose, pls = prev
            ls = row.get("list_shrs")
            share_ratio = (ls / pls) if (ls and pls) else None
            fr = row.get("fluc_rt")
            hit = False
            adj = None
            if fr is not None:
                raw_pct = (close / pclose - 1) * 100
                if abs(raw_pct - fr) >= PRICE_BREAK_TOL_PCT and (1 + fr / 100) > 0:
                    base_price = close / (1 + fr / 100)
                    adj = base_price / pclose
                    hit = True
            elif share_ratio is not None and (
                share_ratio >= PRICE_BREAK_SHARE_UP or share_ratio <= PRICE_BREAK_SHARE_DOWN
            ):
                product = share_ratio * (close / pclose)
                if (share_ratio >= PRICE_BREAK_SHARE_UP and product <= PRICE_BREAK_PRODUCT_MAX) or (
                    share_ratio <= PRICE_BREAK_SHARE_DOWN and product >= PRICE_BREAK_PRODUCT_MIN
                ):
                    adj = close / pclose
                    hit = True
            if hit:
                out.append({"date": row.get("date"), "adj": adj, "share_ratio": share_ratio})
        prev = (close, row.get("list_shrs"))
    return out


def _break_label(b: dict) -> str:
    """각주용 한 토막 — `2026.08.04 기준가 ×15.00 (주식수 ×0.07)`."""
    txt = f"{_dot_date(b['date'])} 기준가 ×{b['adj']:.2f}"
    sr = b.get("share_ratio")
    if sr is not None and (sr >= PRICE_BREAK_SHARE_UP or sr <= PRICE_BREAK_SHARE_DOWN):
        txt += f" (주식수 ×{sr:.2f})"
    return txt


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

    # --- 종가 불연속(액면분할·병합·무상증자 권리락) ---
    # KRX의 FLUC_RT는 조정 기준(LS ELECTRIC 5:1 분할일 +13.71%)인데 우리 등락은
    # 원값 종가 비교라 그날을 건너뛰면 -77%가 나온다(2026-09-23 실측, 1년 전 종목
    # 주식수 점프 550건 중 가격 역비례 313건). 그 구간의 비교는 내지 않고 사실만 적는다.
    span_rows = baseline_rows + pre_rows + [d0_row] + post_rows
    breaks = price_breaks(span_rows)
    pre_span = (pre_rows[0].get("date"), pre_rows[-1].get("date")) if len(pre_rows) >= 2 else None
    post_span = (d0_date, post_rows[-1].get("date")) if post_rows else None
    base_span = (baseline_rows[0].get("date"), d0_date) if baseline_rows else None

    def _hit(span):
        return span is not None and any(span[0] < b["date"] <= span[1] for b in breaks)

    pre_break, post_break, base_break = _hit(pre_span), _hit(post_span), _hit(base_span)

    # --- 등락률 ---
    pre_return_pct = None
    if len(pre_rows) >= 2 and not pre_break:
        first_close = pre_rows[0].get("close")
        last_close = pre_rows[-1].get("close")
        if first_close is not None and last_close is not None and first_close != 0:
            pre_return_pct = (last_close - first_close) / first_close * 100

    post_return_pct = None
    d0_close = d0_row.get("close")
    if post_rows and not post_break:
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
    elif base_break:
        # 분할 뒤 주식수가 N배면 거래량도 N배 — 기준선과 창의 거래량 단위가 다르다.
        # 날짜·배율을 여기 적는다(창 밖·기준선 안의 변동은 아래 price_break_note에
        # 오르지 않으므로 이 줄이 유일한 근거다).
        baseline_note = "기준선 안 기준가 조정(" + " · ".join(
            _break_label(b) for b in breaks if base_span[0] < b["date"] <= base_span[1]
        ) + ")으로 거래량 단위가 달라 배수를 내지 않습니다"
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
    # ⚠ `_row_turnover_pct`는 이미 퍼센트(volume/list_shrs*100)를 낸다 —
    # 여기서 다시 ×100을 하면 이중으로 곱해진다(2026-09-22 실측으로 발견:
    # 거래량 10만·상장주식수 100만인 합성 데이터에서 하루 회전율 10%가
    # 5거래일 합에서 5000%로 찍혔다). `window_overview`의 같은 이름 계산은
    # 이 곱이 없어 값이 맞다 — 같은 파일 안에서 갈려 있었다.
    turnover_note = None
    turnover_pre_pct = None
    pre_turnovers = [_row_turnover_pct(r) for r in pre_rows]
    if pre_rows and all(t is not None for t in pre_turnovers):
        turnover_pre_pct = sum(pre_turnovers)
    turnover_d0_pct = _row_turnover_pct(d0_row)

    if turnover_pre_pct is None or turnover_d0_pct is None:
        turnover_note = "상장주식수가 없어 회전율을 계산할 수 없는 거래일이 있습니다"

    # --- 거래량 0인 거래일 (매매거래정지 등) ---
    # 라이브 실측(2026-09-22): 제이스코홀딩스는 5개월 96거래일이 전부 거래량 0
    # (관리종목·매매거래정지)이고 종가가 521원으로 고정돼 있었다. 등락 0%·배수
    # None만 적으면 「조용한 시장」으로 읽히므로 그 사실을 따로 센다.
    window_rows = pre_rows + [d0_row] + post_rows
    zero_volume_days = sum(1 for r in window_rows if r.get("volume") == 0)

    # ⚠ 이 각주는 **등락을 내지 않은 경우에만** 붙는다 — 기준선 안(창 밖)의 변동은
    # 거래량 배수만 막고 등락은 그대로 내므로(위 baseline_note), 거기까지 「전후
    # 비교 생략」이라 적으면 화면에 찍힌 등락과 각주가 서로 다른 말을 한다
    # (CSA 코스믹 09-10 사건 실측: 08-04 병합이 기준선 안인데 「-5.8%/+0.7%」 옆에
    # 「생략」이 붙었다).
    price_break_note = None
    window_breaks = [
        b for b in breaks
        if (pre_span and pre_span[0] < b["date"] <= pre_span[1])
        or (post_span and post_span[0] < b["date"] <= post_span[1])
    ]
    if window_breaks:
        price_break_note = "창 안 KRX 기준가 조정으로 종가가 불연속: " + " · ".join(
            _break_label(b) for b in window_breaks
        ) + " (분할·병합·감자·무상증자·유상증자 권리락 등 — 그 전후 등락은 조정 전 원값이라 내지 않았습니다)"

    return {
        "price_breaks": breaks,
        "price_break_note": price_break_note,
        "zero_volume_days": zero_volume_days,
        "window_days": len(window_rows),
        "d0_no_trade": d0_row.get("volume") == 0,
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

    breaks = price_breaks(rows)
    window_return_pct = None
    if not breaks and start_close is not None and end_close is not None and start_close != 0:
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

    days_zero_volume = sum(1 for row in rows if row.get("volume") == 0)

    # 코스닥 소속부 시계열 — 「관리종목(소속부없음)」 편입·해제가 날짜별로 보인다
    # (실측: 제이스코홀딩스 2025-09 중견기업부 → 2026-09 관리종목). 유가증권은
    # 값이 없어(None) 변동도 없다.
    sect_changes = []
    prev_sect = rows[0].get("sect")
    for row in rows[1:]:
        cur = row.get("sect")
        if cur != prev_sect:
            sect_changes.append({"date": row.get("date"), "from": prev_sect, "to": cur})
            prev_sect = cur

    return {
        "price_breaks": breaks,
        "days_zero_volume": days_zero_volume,
        "sect_start": rows[0].get("sect"),
        "sect_end": end_row.get("sect"),
        "sect_changes": sect_changes,
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
