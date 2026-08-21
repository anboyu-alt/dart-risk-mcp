"""패턴 관찰 윈도우 게이트 회귀 테스트 (find_pattern_overlaps).

배경: `timeline_months`는 원래 카드 문구로만 쓰이고 매칭에 관여하지 않아,
5년 스캔에서 2~3년 떨어진 신호가 한 패턴으로 묶이면서 "관찰 윈도우 12개월"이
거짓 표기였다(한탑 002680 실측 — 근거 공시가 2024.01~2026.08에 흩어져 있었다).
"""
import pytest

from dart_risk_mcp.core.taxonomy import (
    CROSS_SIGNAL_PATTERNS,
    find_pattern_overlaps,
    _best_window,
    _window_end,
)


class TestWindowEnd:
    def test_기본_가산(self):
        assert _window_end("20240115", 12) == "20250115"
        assert _window_end("20240115", 6) == "20240715"

    def test_연도_넘김(self):
        assert _window_end("20231231", 1) == "20240131"
        assert _window_end("20231115", 14) == "20250115"

    def test_말일_오버플로는_그달_마지막날로_자름(self):
        assert _window_end("20240131", 1) == "20240229"   # 윤년
        assert _window_end("20230131", 1) == "20230228"   # 평년
        assert _window_end("20240331", 1) == "20240430"

    def test_윤년_계산(self):
        assert _window_end("20000131", 1) == "20000229"   # 400의 배수
        assert _window_end("19000131", 1) == "19000228"   # 100의 배수, 400 아님


class TestBestWindow:
    def test_한_창에_모이면_전부_matched(self):
        seq = {"2.4", "4.3", "7.1"}
        dates = {"2.4": ["20240110"], "4.3": ["20240320"], "7.1": ["20240501"]}
        matched, start, end = _best_window(seq, dates, 12)
        assert matched == seq
        assert start == "20240110"
        assert end == "20250110"

    def test_창_밖_신호는_제외(self):
        seq = {"2.4", "4.3", "7.1"}
        # 7.1만 3년 뒤 — 12개월 창에는 못 들어온다
        dates = {"2.4": ["20240110"], "4.3": ["20240320"], "7.1": ["20270501"]}
        matched, _, _ = _best_window(seq, dates, 12)
        assert matched == {"2.4", "4.3"}

    def test_날짜_없으면_빈_집합(self):
        matched, start, end = _best_window({"2.4"}, {}, 12)
        assert matched == set()
        assert (start, end) == ("", "")

    def test_동수면_최근_창을_택해_결정적(self):
        seq = {"2.4", "4.3"}
        # 두 창(2024/2026) 모두 2개를 담는다 → 관측 도구라 최근 쪽
        dates = {"2.4": ["20240101", "20260101"], "4.3": ["20240201", "20260201"]}
        matched, start, _ = _best_window(seq, dates, 12)
        assert matched == seq
        assert start == "20260101"

    def test_같은_taxonomy_여러_날짜중_하나만_창에_있어도_인정(self):
        seq = {"2.4", "4.3"}
        dates = {"2.4": ["20200101", "20240315"], "4.3": ["20240320"]}
        matched, _, _ = _best_window(seq, dates, 12)
        assert matched == seq


class TestFindPatternOverlapsGate:
    def test_날짜_미전달시_기존_동작_유지(self):
        """하위 호환 — taxonomy_dates=None이면 창 게이트를 적용하지 않는다."""
        tax = ["3.1", "2.4", "4.3", "7.1"]
        before = find_pattern_overlaps(tax, min_overlap=2)
        after = find_pattern_overlaps(tax, min_overlap=2, taxonomy_dates=None)
        strip = lambda rs: [
            {k: v for k, v in r.items()
             if k not in ("window_start", "window_end", "timeline_months")}
            for r in rs
        ]
        assert strip(before) == strip(after)
        assert [r["pattern_id"] for r in before]  # 겹침이 실제로 나온다

    def test_이격된_신호는_패턴에서_탈락(self):
        """3.1과 2.4가 4년 떨어져 있으면 어떤 패턴 창에도 함께 못 들어온다."""
        tax = ["3.1", "2.4"]
        far = {"3.1": ["20220101"], "2.4": ["20260101"]}
        assert find_pattern_overlaps(tax, 2, taxonomy_dates=far) == []
        # 대조군: 같은 해면 겹침이 남는다
        near = {"3.1": ["20260101"], "2.4": ["20260301"]}
        assert find_pattern_overlaps(tax, 2, taxonomy_dates=near)

    def test_창밖_신호는_missing으로_이동(self):
        tax = ["3.1", "2.4", "4.3", "7.1"]
        dates = {
            "3.1": ["20260101"], "2.4": ["20260201"],
            "4.3": ["20200101"], "7.1": ["20200101"],   # 6년 전
        }
        got = {r["pattern_id"]: r for r in find_pattern_overlaps(tax, 2, taxonomy_dates=dates)}
        z = got["zombie_ma"]
        # 2026 창(3.1+2.4)과 2020 창(4.3+7.1)이 동수 2개 → 최근 창을 택한다
        assert set(z["matched"]) == {"3.1", "2.4"}
        assert {"4.3", "7.1"} <= set(z["missing"])
        assert z["n_matched"] + len(z["missing"]) == z["n_total"]

    def test_창_경계값_포함(self):
        """창 종료일 당일은 창 안이고, 하루만 넘어도 밖이다(경계 포함).

        timeline_months 값은 실측으로 재보정되는 값이라(2026-08-21, 250개사)
        테스트가 특정 숫자에 매달리지 않도록 패턴에서 직접 읽는다."""
        tax = ["3.1", "2.4"]
        # 3.1+2.4를 함께 요구하는 패턴 중 창이 가장 짧은 것이 경계를 정한다
        cands = [
            p for p in CROSS_SIGNAL_PATTERNS.values()
            if {"3.1", "2.4"} <= set(p["signal_sequence"])
        ]
        months = min(p["timeline_months"] for p in cands)
        base = "20200101"
        exact = {"3.1": [base], "2.4": [_window_end(base, months)]}
        assert find_pattern_overlaps(tax, 2, taxonomy_dates=exact)

        end = _window_end(base, months)
        over_day = f"{end[:6]}{int(end[6:8]) + 1:02d}"   # 하루 초과
        over = {"3.1": [base], "2.4": [over_day]}
        assert find_pattern_overlaps(tax, 2, taxonomy_dates=over) == []

    def test_결과에_창_메타가_실린다(self):
        tax = ["3.1", "2.4"]
        dates = {"3.1": ["20260101"], "2.4": ["20260301"]}
        r = find_pattern_overlaps(tax, 2, taxonomy_dates=dates)[0]
        assert r["window_start"] == "20260101"
        assert r["window_end"] == _window_end("20260101", r["timeline_months"])
        assert r["timeline_months"] == CROSS_SIGNAL_PATTERNS[r["pattern_id"]]["timeline_months"]

    def test_matched와_missing은_항상_signal_sequence를_분할(self):
        tax = ["3.1", "2.4", "4.3", "7.1", "1.2", "2.7"]
        dates = {t: ["20260101"] for t in tax}
        for r in find_pattern_overlaps(tax, 2, taxonomy_dates=dates):
            assert set(r["matched"]) | set(r["missing"]) == set(r["signal_sequence"])
            assert not (set(r["matched"]) & set(r["missing"]))
