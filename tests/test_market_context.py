# -*- coding: utf-8 -*-
"""market_context.py 순수 함수 테스트."""
from datetime import datetime, timedelta

import pytest

from dart_risk_mcp.core import market_context as mc


def _d(base: str, offset: int) -> str:
    """base(YYYYMMDD)에서 offset일 뒤 날짜를 YYYYMMDD로."""
    dt = datetime.strptime(base, "%Y%m%d") + timedelta(days=offset)
    return dt.strftime("%Y%m%d")


def _row(base, offset, close=10000, fluc_rt=0.0, volume=100000, value=None,
         mktcap=50_000_000_000, list_shrs=10_000_000):
    return {
        "date": _d(base, offset),
        "close": close,
        "fluc_rt": fluc_rt,
        "volume": volume,
        "value": value,
        "mktcap": mktcap,
        "list_shrs": list_shrs,
    }


BASE = "20260101"


def _build_rows(n_before_baseline_extra=0, baseline=90, pre=5, post=5,
                 event_offset=None, **row_kwargs):
    """baseline+pre개의 사전 거래일 + (event) + post개의 사후 거래일을 만든다.

    offset 0..baseline+pre-1 이 기준선+직전창, event_offset(기본
    baseline+pre)이 사건일, 그 뒤 post개가 사후창.
    """
    if event_offset is None:
        event_offset = baseline + pre
    rows = []
    for i in range(event_offset + post + 1):
        rows.append(_row(BASE, i, **row_kwargs))
    return rows, _d(BASE, event_offset)


# --------------------------------------------------------------------------
# event_window_facts
# --------------------------------------------------------------------------


def test_normal_window():
    rows, event_date = _build_rows(baseline=60, pre=5, post=5)
    result = mc.event_window_facts(rows, event_date, pre=5, post=5, baseline=60)
    assert result is not None
    assert result["event_date"] == event_date
    assert result["d0_date"] == event_date
    assert result["d0_shifted"] is False
    assert result["days_pre_avail"] == 5
    assert result["days_post_avail"] == 5
    assert result["baseline_avail"] == 60
    assert result["pre_partial"] is False
    assert result["post_partial"] is False
    assert result["baseline_note"] is None
    # 모든 종가가 동일하므로 등락률은 0
    assert result["pre_return_pct"] == pytest.approx(0.0)
    assert result["post_return_pct"] == pytest.approx(0.0)
    # 거래량도 동일하므로 배수는 1
    assert result["pre_vol_ratio"] == pytest.approx(1.0)
    assert result["d0_vol_ratio"] == pytest.approx(1.0)
    assert result["turnover_note"] is None
    assert result["mktcap_d0"] == 50_000_000_000


def test_d0_shifted_when_event_date_is_holiday():
    """사건일이 휴장일(rows에 없는 날짜)이면 다음 거래일이 D0이 된다."""
    rows, event_date = _build_rows(baseline=25, pre=5, post=5)
    # event_date 자체를 스킵한 rows를 만든다 (그 날짜만 제거)
    rows_wo_event = [r for r in rows if r["date"] != event_date]
    result = mc.event_window_facts(rows_wo_event, event_date, pre=5, post=5, baseline=25)
    assert result is not None
    assert result["d0_shifted"] is True
    assert result["d0_date"] > event_date


def test_post_partial_when_window_runs_out_at_end():
    """조회 창이 사건일 뒤 3거래일에서 끝나면 post는 3건만 채워진다."""
    rows, event_date = _build_rows(baseline=25, pre=5, post=3, event_offset=30)
    result = mc.event_window_facts(rows, event_date, pre=5, post=5, baseline=25)
    assert result is not None
    assert result["days_post_avail"] == 3
    assert result["post_partial"] is True


def test_pre_partial_when_window_starts_near_event():
    """사건일 앞에 거래일이 2건뿐이면 pre_return_pct는 계산되고 pre_partial True."""
    rows = [_row(BASE, i) for i in range(2)]
    event_date = _d(BASE, 2)
    rows.append(_row(BASE, 2))
    result = mc.event_window_facts(rows, event_date, pre=5, post=5, baseline=60)
    assert result is not None
    assert result["days_pre_avail"] == 2
    assert result["pre_partial"] is True
    # 2행이면 pre_return_pct 계산 가능(첫/끝 종가 동일하므로 0)
    assert result["pre_return_pct"] == pytest.approx(0.0)


def test_pre_return_pct_none_when_fewer_than_two_pre_rows():
    rows = [_row(BASE, 0)]
    event_date = _d(BASE, 1)
    rows.append(_row(BASE, 1))
    result = mc.event_window_facts(rows, event_date, pre=5, post=5, baseline=60)
    assert result is not None
    assert result["days_pre_avail"] == 1
    assert result["pre_return_pct"] is None


def test_baseline_insufficient_gives_none_ratios_and_note():
    rows, event_date = _build_rows(baseline=10, pre=5, post=5)
    result = mc.event_window_facts(rows, event_date, pre=5, post=5, baseline=60,
                                    min_baseline=20)
    assert result is not None
    assert result["baseline_avail"] == 10
    assert result["pre_vol_ratio"] is None
    assert result["d0_vol_ratio"] is None
    assert result["baseline_note"] == "기준선 10거래일 (최소 20)"


def test_baseline_zero_average_volume():
    rows, event_date = _build_rows(baseline=30, pre=5, post=5, volume=0)
    result = mc.event_window_facts(rows, event_date, pre=5, post=5, baseline=30,
                                    min_baseline=20)
    assert result is not None
    assert result["baseline_avail"] == 30
    assert result["pre_vol_ratio"] is None
    assert result["d0_vol_ratio"] is None
    assert result["baseline_note"] == "기준선 평균 거래량이 0입니다"


def test_turnover_none_when_list_shrs_missing_or_zero():
    rows, event_date = _build_rows(baseline=30, pre=5, post=5, list_shrs=0)
    result = mc.event_window_facts(rows, event_date, pre=5, post=5, baseline=30,
                                    min_baseline=20)
    assert result is not None
    assert result["turnover_pre_pct"] is None
    assert result["turnover_d0_pct"] is None
    assert result["turnover_note"] is not None

    # list_shrs가 None인 경우도 동일하게 처리된다
    rows2, event_date2 = _build_rows(baseline=30, pre=5, post=5, list_shrs=None)
    result2 = mc.event_window_facts(rows2, event_date2, pre=5, post=5, baseline=30,
                                     min_baseline=20)
    assert result2["turnover_pre_pct"] is None
    assert result2["turnover_d0_pct"] is None


def test_close_none_mixed_in_pre_and_post():
    rows, event_date = _build_rows(baseline=30, pre=5, post=5)
    # pre_rows의 첫 행 종가를 None으로
    for r in rows:
        pass
    idx_event = [i for i, r in enumerate(rows) if r["date"] == event_date][0]
    rows[idx_event - 5]["close"] = None  # pre_rows[0]
    result = mc.event_window_facts(rows, event_date, pre=5, post=5, baseline=30,
                                    min_baseline=20)
    assert result["pre_return_pct"] is None

    # d0 종가가 None이면 post_return_pct도 None
    rows2, event_date2 = _build_rows(baseline=30, pre=5, post=5)
    idx_event2 = [i for i, r in enumerate(rows2) if r["date"] == event_date2][0]
    rows2[idx_event2]["close"] = None
    result2 = mc.event_window_facts(rows2, event_date2, pre=5, post=5, baseline=30,
                                     min_baseline=20)
    assert result2["post_return_pct"] is None
    assert result2["d0_close"] is None


def test_event_after_last_row_returns_none():
    rows = [_row(BASE, i) for i in range(10)]
    event_date = _d(BASE, 100)
    result = mc.event_window_facts(rows, event_date)
    assert result is None


def test_empty_rows_returns_none():
    result = mc.event_window_facts([], "20260101")
    assert result is None


# --------------------------------------------------------------------------
# align_alerts_with_events
# --------------------------------------------------------------------------


def test_align_alerts_boundary_inclusive_and_exclusive():
    designated = "20260301"
    alerts = [{"kind": "caution", "name": "테스트", "designated": designated,
               "announced": designated, "released": None}]
    events_in_bounds = [
        {"rcept_dt": mc.date8_add_days(designated, 10), "rcept_no": "1", "key": "CB_BW"},
        {"rcept_dt": mc.date8_add_days(designated, -10), "rcept_no": "2", "key": "3PCA"},
    ]
    event_out_of_bounds = {
        "rcept_dt": mc.date8_add_days(designated, 11), "rcept_no": "3", "key": "AUDIT"
    }
    events = events_in_bounds + [event_out_of_bounds]
    result = mc.align_alerts_with_events(alerts, events, days=10)
    assert len(result) == 1
    matched_ids = [e["rcept_no"] for e in result[0]["events"]]
    assert matched_ids == ["2", "1"]  # rcept_dt 오름차순
    assert "3" not in matched_ids


def test_align_alerts_sorted_by_designated_descending():
    alerts = [
        {"kind": "caution", "name": "A", "designated": "20260101"},
        {"kind": "warning", "name": "B", "designated": "20260301"},
        {"kind": "risk", "name": "C", "designated": "20260201"},
    ]
    result = mc.align_alerts_with_events(alerts, [], days=10)
    designated_order = [r["alert"]["designated"] for r in result]
    assert designated_order == ["20260301", "20260201", "20260101"]


def test_align_alerts_no_events():
    alerts = [{"kind": "caution", "name": "A", "designated": "20260101"}]
    result = mc.align_alerts_with_events(alerts, [], days=10)
    assert result[0]["events"] == []


def test_align_alerts_missing_designated_matches_nothing():
    alerts = [{"kind": "caution", "name": "A", "designated": None}]
    events = [{"rcept_dt": "20260101", "rcept_no": "1"}]
    result = mc.align_alerts_with_events(alerts, events, days=10)
    assert result[0]["events"] == []


# --------------------------------------------------------------------------
# window_overview
# --------------------------------------------------------------------------


def test_window_overview_empty_rows_returns_none():
    assert mc.window_overview([]) is None


def test_window_overview_basic_high_low_and_thresholds():
    rows = [
        # 등락률은 원값과 맞게 둔다 — 어긋나면 기준가 조정(불연속)으로 읽혀 창 등락이 비는 것이 맞다
        _row(BASE, 0, close=1000, mktcap=25_000_000_000),
        _row(BASE, 1, close=1500, fluc_rt=50.0, mktcap=25_000_000_000),
        _row(BASE, 2, close=900, fluc_rt=-40.0, mktcap=15_000_000_000),  # under 20bn threshold
        _row(BASE, 3, close=2000, fluc_rt=122.22, mktcap=25_000_000_000),
    ]
    result = mc.window_overview(rows)
    assert result is not None
    assert result["start_close"] == 1000
    assert result["end_close"] == 2000
    assert result["window_return_pct"] == pytest.approx(100.0)
    assert result["high_close"] == 2000
    assert result["high_date"] == _d(BASE, 3)
    assert result["low_close"] == 900
    assert result["low_date"] == _d(BASE, 2)
    assert result["days"] == 4
    # close < 1000 규정선: 종가 900인 거래일 1건, 1000은 미만이 아니므로 제외
    assert result["days_close_under_1000"] == 1
    # mktcap < 200억 규정선: 1건 (15,000,000,000)
    assert result["days_mktcap_under_20bn"] == 1
    assert result["avg_turnover_pct"] is not None
    assert result["turnover_days"] == 4


def test_window_overview_close_none_rows_excluded_from_high_low():
    rows = [
        _row(BASE, 0, close=None),
        _row(BASE, 1, close=1500),
        _row(BASE, 2, close=None),
    ]
    result = mc.window_overview(rows)
    assert result["high_close"] == 1500
    assert result["low_close"] == 1500
    assert result["start_close"] is None
    assert result["window_return_pct"] is None


def test_window_overview_all_close_none():
    rows = [_row(BASE, 0, close=None), _row(BASE, 1, close=None)]
    result = mc.window_overview(rows)
    assert result["high_close"] is None
    assert result["low_close"] is None
    assert result["high_date"] is None
    assert result["low_date"] is None


def test_window_overview_turnover_none_when_no_list_shrs():
    rows = [_row(BASE, i, list_shrs=None) for i in range(3)]
    result = mc.window_overview(rows)
    assert result["avg_turnover_pct"] is None
    assert result["turnover_days"] == 0


# --------------------------------------------------------------------------
# date8_add_days
# --------------------------------------------------------------------------


def test_date8_add_days():
    assert mc.date8_add_days("20260101", 10) == "20260111"
    assert mc.date8_add_days("20260101", -1) == "20251231"
    assert mc.date8_add_days("20260101", 0) == "20260101"


# --------------------------------------------------------------------------
# 어휘 가드 — 판정 낱말 부재
# --------------------------------------------------------------------------


def test_no_judgment_words_in_source():
    import inspect

    source = inspect.getsource(mc)
    for word in ("급등", "급락", "이상", "과열", "위험"):
        assert word not in source, f"판정 어휘 '{word}'가 market_context.py에 있습니다"


# ---------------------------------------------------------------- 거래량 0·소속부 (2026-09-22 라이브 실측 반영)

def test_zero_volume_days_counted_in_event_window():
    """매매거래정지 종목(제이스코홀딩스 실측: 96거래일 전부 거래량 0·종가 고정)은
    등락 0%·배수 None만으로는 「조용한 시장」으로 읽힌다 — 창 안 거래량 0인
    거래일 수와 D0 무거래를 따로 센다."""
    rows = [_row(BASE, i, close=521, volume=0) for i in range(80)]
    f = mc.event_window_facts(rows, _d(BASE, 70))
    assert f["zero_volume_days"] == 11 and f["window_days"] == 11
    assert f["d0_no_trade"] is True
    assert f["baseline_note"] == "기준선 평균 거래량이 0입니다"

    rows2 = [_row(BASE, i) for i in range(80)]
    f2 = mc.event_window_facts(rows2, _d(BASE, 70))
    assert f2["zero_volume_days"] == 0 and f2["d0_no_trade"] is False


def test_overview_counts_zero_volume_and_tracks_sect_changes():
    rows = [_row(BASE, i) for i in range(6)]
    for r in rows[:3]:
        r["sect"] = "중견기업부"
    for r in rows[3:]:
        r["sect"] = "관리종목(소속부없음)"
    rows[1]["volume"] = 0
    rows[4]["volume"] = 0
    ov = mc.window_overview(rows)
    assert ov["days_zero_volume"] == 2
    assert ov["sect_start"] == "중견기업부" and ov["sect_end"] == "관리종목(소속부없음)"
    assert ov["sect_changes"] == [{"date": _d(BASE, 3), "from": "중견기업부",
                                   "to": "관리종목(소속부없음)"}]


def test_overview_sect_absent_for_kospi_rows():
    """유가증권 행은 `sect`가 없거나 None — 변동 없음으로 나와야 한다."""
    ov = mc.window_overview([_row(BASE, i) for i in range(3)])
    assert ov["sect_start"] is None and ov["sect_changes"] == []


# ---------------------------------------------------------------- 종가 불연속 (2026-09-23 실측 반영)

def _split_rows(n_before=70, n_after=10, ratio=5.0):
    """n_before일 뒤 1:ratio 액면분할 — 종가 ÷ratio·주식수 ×ratio. 분할일의 KRX
    등락률은 조정 기준이라 0.0(원값 비교는 -80%)."""
    rows = [_row(BASE, i, close=100000, volume=1000, list_shrs=1_000_000) for i in range(n_before)]
    rows += [_row(BASE, n_before + i, close=20000, volume=5000, list_shrs=5_000_000) for i in range(n_after)]
    return rows


def test_price_breaks_split_vs_rights_issue():
    rows = _split_rows()
    b = mc.price_breaks(rows)
    assert len(b) == 1 and b[0]["date"] == _d(BASE, 70)
    assert b[0]["adj"] == pytest.approx(0.2) and b[0]["share_ratio"] == pytest.approx(5.0)
    # 유상증자 신주상장: 주식수 ×3.5인데 등락률이 원값과 같다 → 불연속 아님
    rows2 = [_row(BASE, 0, close=3780, list_shrs=3_290_720),
             _row(BASE, 1, close=3400, fluc_rt=-10.05, list_shrs=11_399_543)]
    assert mc.price_breaks(rows2) == []
    # 병합 뒤 무상증자(CSA 코스믹 실측: 2,860 → 1,859, 주식수 ×2) → 불연속
    rows3 = [_row(BASE, 0, close=2860, list_shrs=7_109_265),
             _row(BASE, 1, close=1859, fluc_rt=0.5, list_shrs=14_218_530)]
    b3 = mc.price_breaks(rows3)
    assert len(b3) == 1 and b3[0]["share_ratio"] == pytest.approx(2.0)
    # 종가 없는 행은 판정하지 않는다
    rows4 = [_row(BASE, 0, close=None, list_shrs=None), _row(BASE, 1, close=100, list_shrs=10)]
    assert mc.price_breaks(rows4) == []


def test_price_breaks_uses_fluc_rt_not_share_count():
    """주식수가 그대로인 기준가 조정(유상증자 권리락·감자 재개)도 잡는다 — 실측
    000500 20260630 원값 -31.9% vs 등락률 +22.51%, 002210 20260730 +85% vs -7.5%."""
    rows = [_row(BASE, 0, close=1000, list_shrs=100), _row(BASE, 1, close=681, fluc_rt=22.51, list_shrs=100)]
    b = mc.price_breaks(rows)
    assert len(b) == 1 and b[0]["share_ratio"] == pytest.approx(1.0)
    assert b[0]["adj"] == pytest.approx(681 / 1.2251 / 1000, rel=1e-3)
    # 1%p 안의 어긋남은 반올림·기준가 소폭 조정이라 잡지 않는다
    rows_ok = [_row(BASE, 0, close=1000), _row(BASE, 1, close=1010, fluc_rt=1.0)]
    assert mc.price_breaks(rows_ok) == []
    # 앞 거래일이 미조회면(gap_before) 며칠치 움직임을 하루 등락률과 견주지 않는다
    rows_gap = [_row(BASE, 0, close=1000), dict(_row(BASE, 3, close=1200, fluc_rt=2.0), gap_before=True)]
    assert mc.price_breaks(rows_gap) == []
    # 등락률이 없으면 보조 규칙(주식수 점프 + 종가 역비례)
    rows_nofr = [_row(BASE, 0, close=100000, list_shrs=1_000_000),
                 _row(BASE, 1, close=20000, fluc_rt=None, list_shrs=5_000_000)]
    assert mc.price_breaks(rows_nofr)[0]["adj"] == pytest.approx(0.2)
    rows_nofr2 = [_row(BASE, 0, close=3780, list_shrs=3_290_720),
                  _row(BASE, 1, close=3400, fluc_rt=None, list_shrs=11_399_543)]
    assert mc.price_breaks(rows_nofr2) == []


def test_event_window_nulls_returns_across_split():
    """분할이 D-5~D-1 안에 있으면 pre 등락을, 기준선~D0 사이에 있으면 거래량 배수를
    내지 않는다 — 원값 비교는 -80%·×5 같은 거짓을 만든다."""
    rows = _split_rows()
    # 사건일 = 분할 3일 뒤 → pre 창(D-5..D-1)에 분할일이 든다
    f = mc.event_window_facts(rows, _d(BASE, 73))
    assert f["pre_return_pct"] is None
    assert f["pre_vol_ratio"] is None and f["d0_vol_ratio"] is None
    assert "기준가 조정" in f["baseline_note"]
    assert f["price_breaks"][0]["date"] == _d(BASE, 70)
    assert "불연속" in f["price_break_note"] and "주식수 ×5.00" in f["price_break_note"]
    # post 창은 분할 뒤라 정상 계산
    assert f["post_return_pct"] == pytest.approx(0.0)
    # 분할이 기준선 안(창 밖)이면 등락은 내고 거래량 배수만 막는다 — 각주도 등락을
    # 「생략」이라 적지 않는다(CSA 코스믹 09-10 사건 실측으로 잡은 자기모순)
    h = mc.event_window_facts(rows, _d(BASE, 78))
    assert h["pre_return_pct"] is not None and h["price_break_note"] is None
    assert h["pre_vol_ratio"] is None and "기준가 조정" in h["baseline_note"]
    # 사건일이 분할 훨씬 뒤(기준선도 분할 뒤)면 아무것도 막지 않는다
    rows_long = _split_rows(n_before=5, n_after=90)
    g = mc.event_window_facts(rows_long, _d(BASE, 90))
    assert g["price_breaks"] == [] and g["pre_return_pct"] is not None


def test_window_overview_split_disables_window_return():
    rows = _split_rows()
    ov = mc.window_overview(rows)
    assert ov["window_return_pct"] is None
    assert ov["price_breaks"][0]["adj"] == pytest.approx(0.2)
    # 최고·최저는 원값 그대로(고지는 렌더가 붙인다)
    assert ov["high_close"] == 100000 and ov["low_close"] == 20000
