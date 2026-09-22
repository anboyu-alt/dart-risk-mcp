"""`core/krx_client.py` 단위 테스트 — 네트워크 0(`requests.get`/`krx_get_daily` monkeypatch).

캐시 디렉터리는 `tmp_path`로 몬키패치한다(conftest의 mkdtemp 가드는
`tempfile.mkdtemp()`만 잡으므로 `tmp_path` fixture는 걸리지 않는다).
"""

from __future__ import annotations

import gzip
import json

import pytest
import requests

from dart_risk_mcp.core import krx_client as kc


# ---------------------------------------------------------------- 공통 fixture

@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    """krx_client가 쓰는 캐시 루트를 tmp_path 아래로 돌린다."""
    monkeypatch.setattr(kc, "_resolve_corp_cache_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch):
    """기본값: '오늘'을 조회 구간 밖(먼 미래)으로 고정해, 날짜 축 테스트가
    실행 시각에 좌우되지 않게 한다. 오늘 테스트는 개별적으로 재정의한다."""
    monkeypatch.setattr(kc, "_today_str", lambda: "20990101")


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


def _ok(rows):
    return _FakeResponse(200, {"OutBlock_1": rows})


# ---------------------------------------------------------------- krx_get_daily

def test_get_daily_401_returns_none(monkeypatch):
    monkeypatch.setattr(kc.requests, "get",
                         lambda *a, **k: _FakeResponse(401, {"respCode": "401"}))
    assert kc.krx_get_daily("stk_bydd_trd", "20260921", "badkey") is None


def test_get_daily_non_json_returns_none(monkeypatch):
    monkeypatch.setattr(kc.requests, "get", lambda *a, **k: _FakeResponse(200, bad_json=True))
    assert kc.krx_get_daily("stk_bydd_trd", "20260921", "k") is None


def test_get_daily_missing_outblock_returns_none(monkeypatch):
    monkeypatch.setattr(kc.requests, "get", lambda *a, **k: _FakeResponse(200, {"other": []}))
    assert kc.krx_get_daily("stk_bydd_trd", "20260921", "k") is None


def test_get_daily_500_retries_three_times_then_none(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params["basDd"])
        return _FakeResponse(500)

    monkeypatch.setattr(kc.requests, "get", fake_get)
    monkeypatch.setattr(kc.time, "sleep", lambda *_: None)
    assert kc.krx_get_daily("stk_bydd_trd", "20260921", "k") is None
    assert len(calls) == 3


def test_get_daily_429_then_success(monkeypatch):
    attempts = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return _FakeResponse(429)
        return _ok([{"ISU_CD": "005930"}])

    monkeypatch.setattr(kc.requests, "get", fake_get)
    monkeypatch.setattr(kc.time, "sleep", lambda *_: None)
    out = kc.krx_get_daily("stk_bydd_trd", "20260921", "k")
    assert out == [{"ISU_CD": "005930"}]
    assert attempts["n"] == 3


def test_get_daily_network_exception_returns_none(monkeypatch):
    def raiser(*a, **k):
        raise requests.exceptions.ConnectionError("boom")

    monkeypatch.setattr(kc.requests, "get", raiser)
    assert kc.krx_get_daily("stk_bydd_trd", "20260921", "k") is None


def test_get_daily_holiday_empty_list(monkeypatch):
    monkeypatch.setattr(kc.requests, "get", lambda *a, **k: _ok([]))
    assert kc.krx_get_daily("stk_bydd_trd", "20260921", "k") == []


def test_get_daily_no_key_leak_in_url(monkeypatch):
    """AUTH_KEY는 헤더로만 전달되고 쿼리 파라미터는 basDd뿐이다."""
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["params"] = params
        captured["headers"] = headers
        return _ok([])

    monkeypatch.setattr(kc.requests, "get", fake_get)
    kc.krx_get_daily("stk_bydd_trd", "20260921", "secret-key")
    assert captured["params"] == {"basDd": "20260921"}
    assert captured["headers"]["AUTH_KEY"] == "secret-key"


# ---------------------------------------------------------------- fetch_price_series
# 아래는 krx_client.krx_get_daily 자체를 monkeypatch해 캐시·예산·계수 로직만
# 검증한다(krx_get_daily 자체의 HTTP 동작은 위에서 이미 검증했다).

def _install_daily(monkeypatch, by_date: dict, calls: list):
    """date8 -> list[dict] | None 매핑으로 krx_get_daily를 대체한다."""

    def fake_daily(api_id, bas_dd, api_key):
        calls.append(bas_dd)
        return by_date.get(bas_dd)

    monkeypatch.setattr(kc, "krx_get_daily", fake_daily)


def test_unsupported_market_short_circuits(monkeypatch):
    calls = []
    _install_daily(monkeypatch, {}, calls)
    out = kc.fetch_price_series("005930", "N", "20260915", "20260919", "k")
    assert out["unsupported_market"] is True
    assert out["api_id"] is None
    assert out["fetch_failed"] is False
    assert out["rows"] == []
    assert calls == []  # 네트워크 호출 시도조차 없다


def test_missing_key_short_circuits(monkeypatch):
    calls = []
    _install_daily(monkeypatch, {}, calls)
    out = kc.fetch_price_series("005930", "Y", "20260915", "20260919", "")
    assert out["fetch_failed"] is True
    assert out["missing_key"] is True
    assert out["api_id"] == "stk_bydd_trd"
    assert calls == []


def test_cache_miss_then_hit(monkeypatch):
    calls = []
    _install_daily(
        monkeypatch,
        {"20260918": [{"ISU_CD": "005930", "TDD_CLSPRC": "70,000", "FLUC_RT": "1.5",
                       "ACC_TRDVOL": "1,000", "ACC_TRDVAL": "70,000,000",
                       "MKTCAP": "400,000,000,000", "LIST_SHRS": "5,000,000",
                       "SECT_TP_NM": "주권"}]},
        calls,
    )
    # 20260918은 금요일
    out1 = kc.fetch_price_series("005930", "Y", "20260918", "20260918", "k")
    assert out1["days_fetched"] == 1
    assert out1["days_cached"] == 0
    assert len(calls) == 1

    calls.clear()
    out2 = kc.fetch_price_series("005930", "Y", "20260918", "20260918", "k")
    assert out2["days_fetched"] == 0
    assert out2["days_cached"] == 1
    assert calls == []  # 두 번째 호출은 네트워크를 타지 않는다
    assert out2["rows"] == out1["rows"]


def test_holiday_cached_as_empty_marker(monkeypatch, tmp_path):
    calls = []
    _install_daily(monkeypatch, {"20260918": []}, calls)

    out = kc.fetch_price_series("005930", "Y", "20260918", "20260918", "k")
    assert out["days_fetched"] == 1
    assert out["rows"] == []

    cache_file = tmp_path / "krx" / "stk_bydd_trd" / "20260918.json.gz"
    assert cache_file.exists()
    with gzip.open(cache_file, "rt", encoding="utf-8") as f:
        assert json.load(f) == {"empty": True}

    calls.clear()
    out2 = kc.fetch_price_series("005930", "Y", "20260918", "20260918", "k")
    assert out2["days_cached"] == 1
    assert calls == []
    assert out2["rows"] == []


def test_today_not_cached_read_or_write(monkeypatch, tmp_path):
    monkeypatch.setattr(kc, "_today_str", lambda: "20260918")
    calls = []
    _install_daily(
        monkeypatch,
        {"20260918": [{"ISU_CD": "005930", "TDD_CLSPRC": "70000"}]},
        calls,
    )

    out1 = kc.fetch_price_series("005930", "Y", "20260918", "20260918", "k")
    assert out1["days_fetched"] == 1
    cache_file = tmp_path / "krx" / "stk_bydd_trd" / "20260918.json.gz"
    assert not cache_file.exists()  # 오늘은 쓰지 않는다

    calls.clear()
    out2 = kc.fetch_price_series("005930", "Y", "20260918", "20260918", "k")
    assert out2["days_fetched"] == 1  # 오늘은 캐시를 읽지 않으므로 다시 네트워크
    assert out2["days_cached"] == 0
    assert calls == ["20260918"]


def test_failure_401_not_cached_and_flagged(monkeypatch, tmp_path):
    calls = []
    _install_daily(monkeypatch, {"20260918": None}, calls)

    out = kc.fetch_price_series("005930", "Y", "20260918", "20260918", "k")
    assert out["fetch_failed"] is True
    assert out["days_uncovered"] == ["20260918"]
    assert out["days_fetched"] == 0
    cache_file = tmp_path / "krx" / "stk_bydd_trd" / "20260918.json.gz"
    assert not cache_file.exists()


def test_budget_exhausted_leaves_oldest_uncovered(monkeypatch):
    calls = []
    # 2026-09-14(월)~2026-09-18(금) 5거래일
    by_date = {
        d: [{"ISU_CD": "005930", "TDD_CLSPRC": "70000"}]
        for d in ("20260914", "20260915", "20260916", "20260917", "20260918")
    }
    _install_daily(monkeypatch, by_date, calls)

    out = kc.fetch_price_series(
        "005930", "Y", "20260914", "20260918", "k", budget=2,
    )
    assert out["days_requested"] == 5
    assert out["days_fetched"] == 2
    # 최근부터 훑으므로 예산 2개는 18일·17일이 쓰고, 남는(오래된) 3일이 uncovered
    assert out["days_uncovered"] == ["20260914", "20260915", "20260916"]
    assert sorted(calls) == ["20260917", "20260918"]


def test_soft_cap_reached_sets_quota_hit_without_call(monkeypatch, tmp_path):
    monkeypatch.setattr(kc, "KRX_SOFT_CAP", 1)
    calls = []
    _install_daily(
        monkeypatch,
        {"20260918": [{"ISU_CD": "005930", "TDD_CLSPRC": "70000"}]},
        calls,
    )

    # quota 파일을 소프트캡과 같은 값으로 미리 채운다.
    quota_dir = tmp_path / "krx"
    quota_dir.mkdir(parents=True)
    (quota_dir / "quota_20990101.json").write_text(json.dumps({"calls": 1}), encoding="utf-8")

    out = kc.fetch_price_series("005930", "Y", "20260918", "20260918", "k")
    assert out["quota_hit"] is True
    assert out["days_uncovered"] == ["20260918"]
    assert calls == []


def test_quota_file_increments_only_on_network_calls(monkeypatch, tmp_path):
    calls = []
    _install_daily(
        monkeypatch,
        {
            "20260917": [{"ISU_CD": "005930", "TDD_CLSPRC": "70000"}],
            "20260918": [{"ISU_CD": "005930", "TDD_CLSPRC": "70100"}],
        },
        calls,
    )

    # 17일치를 먼저 채워 캐시 히트를 만든다.
    kc.fetch_price_series("005930", "Y", "20260917", "20260917", "k")
    quota_path = tmp_path / "krx" / "quota_20990101.json"
    assert json.loads(quota_path.read_text(encoding="utf-8"))["calls"] == 1

    calls.clear()
    # 17일(캐시 히트) + 18일(신규) 구간을 다시 조회 — 계수는 신규 1건만 는다.
    kc.fetch_price_series("005930", "Y", "20260917", "20260918", "k")
    assert calls == ["20260918"]
    assert json.loads(quota_path.read_text(encoding="utf-8"))["calls"] == 2


def test_only_keep_fields_written_to_cache(monkeypatch, tmp_path):
    calls = []
    _install_daily(
        monkeypatch,
        {"20260918": [{
            "ISU_CD": "005930", "ISU_NM": "삼성전자", "MKT_NM": "KOSPI",
            "TDD_CLSPRC": "70000", "CMPPREVDD_PRC": "500", "FLUC_RT": "0.72",
            "TDD_OPNPRC": "69500", "TDD_HGPRC": "70500", "TDD_LWPRC": "69000",
            "ACC_TRDVOL": "1000", "ACC_TRDVAL": "70000000",
            "MKTCAP": "400000000000", "LIST_SHRS": "5000000",
            "SECT_TP_NM": "주권",
        }]},
        calls,
    )

    kc.fetch_price_series("005930", "Y", "20260918", "20260918", "k")

    cache_file = tmp_path / "krx" / "stk_bydd_trd" / "20260918.json.gz"
    with gzip.open(cache_file, "rt", encoding="utf-8") as f:
        payload = json.load(f)
    row = payload["rows"][0]
    assert set(row.keys()) == set(kc.KRX_KEEP_FIELDS)
    assert "ISU_NM" not in row
    assert "MKT_NM" not in row


def test_rows_ascending_and_normalized(monkeypatch):
    calls = []
    by_date = {
        "20260916": [{"ISU_CD": "005930", "TDD_CLSPRC": "69,500", "FLUC_RT": "-0.5",
                      "ACC_TRDVOL": "900", "ACC_TRDVAL": "62,550,000",
                      "MKTCAP": "398,000,000,000", "LIST_SHRS": "5,000,000"}],
        "20260917": [{"ISU_CD": "005930", "TDD_CLSPRC": "70,000", "FLUC_RT": "0.72",
                      "ACC_TRDVOL": "1,000", "ACC_TRDVAL": "70,000,000",
                      "MKTCAP": "400,000,000,000", "LIST_SHRS": "5,000,000"}],
        "20260918": [{"ISU_CD": "005930", "TDD_CLSPRC": "70,600", "FLUC_RT": "0.86",
                      "ACC_TRDVOL": "1,200", "ACC_TRDVAL": "84,720,000",
                      "MKTCAP": "403,000,000,000", "LIST_SHRS": "5,000,000"}],
    }
    _install_daily(monkeypatch, by_date, calls)

    out = kc.fetch_price_series("005930", "Y", "20260916", "20260918", "k")
    dates = [r["date"] for r in out["rows"]]
    assert dates == ["20260916", "20260917", "20260918"]
    first = out["rows"][0]
    assert first["close"] == 69500
    assert first["fluc_rt"] == -0.5
    assert first["volume"] == 900
    assert first["value"] == 62550000
    assert first["mktcap"] == 398000000000
    assert first["list_shrs"] == 5000000


def test_row_excluded_when_stock_not_in_day(monkeypatch):
    """조회 종목이 그날 시장 응답에 없으면(상장폐지 등) row를 만들지 않는다."""
    calls = []
    _install_daily(monkeypatch, {"20260918": [{"ISU_CD": "000660", "TDD_CLSPRC": "1000"}]}, calls)
    out = kc.fetch_price_series("005930", "Y", "20260918", "20260918", "k")
    assert out["rows"] == []
    assert out["days_fetched"] == 1


def test_weekday_candidates_excludes_weekend():
    # 2026-09-14(월) ~ 2026-09-20(일)
    days = kc._weekday_candidates("20260914", "20260920")
    assert days == ["20260914", "20260915", "20260916", "20260917", "20260918"]


def test_module_importable():
    import dart_risk_mcp.core.krx_client  # noqa: F401


# ---------------------------------------------------------------- 동시 조회·소속부 (2026-09-22 실측 반영)

def test_concurrent_fetch_covers_every_date_and_counts_quota(monkeypatch, _cache_dir):
    """예산 안의 미스 날짜는 전부 한 번씩 조회되고(동시 조회여도 누락·중복 없음),
    계수는 네트워크 시도 수만큼 오른다."""
    seen = []

    def fake(api_id, date8, key):
        seen.append(date8)
        return [{"ISU_CD": "023440", "TDD_CLSPRC": "521", "FLUC_RT": "0.00",
                 "ACC_TRDVOL": "0", "ACC_TRDVAL": "0", "MKTCAP": "46964378481",
                 "LIST_SHRS": "90142761", "SECT_TP_NM": "관리종목(소속부없음)"}]

    monkeypatch.setattr(kc, "krx_get_daily", fake)
    monkeypatch.setattr(kc, "KRX_CONCURRENCY", 4)
    res = kc.fetch_price_series("023440", "K", "20260901", "20260912", "k", budget=100)
    weekdays = kc._weekday_candidates("20260901", "20260912")
    assert sorted(seen) == weekdays and len(seen) == len(set(seen))
    assert res["days_fetched"] == len(weekdays)
    assert kc._quota_count(kc._today_str()) == len(weekdays)
    assert [r["date"] for r in res["rows"]] == weekdays


def test_sect_field_normalized_from_sect_tp_nm(monkeypatch):
    """코스닥 소속부(「관리종목(소속부없음)」)는 `sect`로 실리고, 유가증권의 빈
    문자열은 None이다(실측 2026-09-22: 유가는 늘 빈 문자열)."""
    def fake(api_id, date8, key):
        return [{"ISU_CD": "023440", "TDD_CLSPRC": "521", "SECT_TP_NM": "관리종목(소속부없음)"},
                {"ISU_CD": "005930", "TDD_CLSPRC": "261000", "SECT_TP_NM": ""}]

    monkeypatch.setattr(kc, "krx_get_daily", fake)
    k = kc.fetch_price_series("023440", "K", "20260918", "20260918", "k")
    y = kc.fetch_price_series("005930", "Y", "20260918", "20260918", "k")
    assert k["rows"][0]["sect"] == "관리종목(소속부없음)"
    assert y["rows"][0]["sect"] is None


def test_budget_applies_before_concurrent_fetch(monkeypatch):
    """예산 3이면 정확히 3개 날짜만(최근 셋) 조회하고 나머지는 uncovered."""
    seen = []
    monkeypatch.setattr(kc, "krx_get_daily", lambda a, d, k: (seen.append(d) or []))
    res = kc.fetch_price_series("023440", "K", "20260901", "20260912", "k", budget=3)
    weekdays = kc._weekday_candidates("20260901", "20260912")   # 0912는 토요일
    assert sorted(seen) == weekdays[-3:]
    assert res["days_uncovered"] == weekdays[:-3]


# ---------------------------------------------------------------- 발표 전 빈 응답 (2026-09-23 실측)

def test_recent_empty_response_is_pending_not_cached(monkeypatch, _cache_dir):
    """전 거래일이 아직 빈 배열로 오는 시각(실측 09-23 00:42 KST에 09-22가 빈 응답)이
    있다 — 그것을 휴장일로 영구 캐시하면 그 날짜의 시세가 영원히 사라진다.
    오늘부터 KRX_EMPTY_GRACE_DAYS 안의 빈 응답은 캐시하지 않고 days_pending에 적는다."""
    monkeypatch.setattr(kc, "_today_str", lambda: "20260923")
    monkeypatch.setattr(kc, "krx_get_daily", lambda a, d, k: [])
    res = kc.fetch_price_series("005930", "Y", "20260921", "20260922", "k")
    assert res["days_pending"] == ["20260921", "20260922"]
    assert kc._read_cache("stk_bydd_trd", "20260922") is None
    assert kc._read_cache("stk_bydd_trd", "20260921") is None
    assert res["fetch_failed"] is False and res["days_uncovered"] == []


def test_old_empty_response_is_still_cached_as_holiday(monkeypatch, _cache_dir):
    """유예 밖(8일 이전)의 빈 응답은 휴장일로 캐시한다 — 여기서 바뀌면 안 된다."""
    monkeypatch.setattr(kc, "_today_str", lambda: "20260923")
    monkeypatch.setattr(kc, "krx_get_daily", lambda a, d, k: [])
    res = kc.fetch_price_series("005930", "Y", "20260901", "20260901", "k")
    assert res["days_pending"] == []
    assert kc._read_cache("stk_bydd_trd", "20260901") == {"empty": True}
