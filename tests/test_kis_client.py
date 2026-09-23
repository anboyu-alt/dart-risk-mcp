"""한국투자증권(KIS) Open API 시세 경로 — 코어(`kis_client`)와 서버 배선.

실제 KIS는 부르지 않는다(conftest 가드가 호스트째 막는다 — 토큰 발급이 1분
1회로 제한돼 실제 키로 테스트가 돌면 제작자의 토큰을 갈아엎는다). 응답 모양은
2026-09-23 실측(임시 브랜치 GitHub Actions) 그대로다 — `kis_client` 모듈 설명 참고.
"""
from __future__ import annotations

import datetime as dt
import json

import pytest

import dart_risk_mcp.core.kis_client as kc
import dart_risk_mcp.server as srv
from dart_risk_mcp.core import FETCH_OK
from dart_risk_mcp.core.market_context import price_breaks, window_overview


# ── 실측 행(CSA 코스믹 083660, 원주가) ────────────────────────────────────
# 2026-08-25 매매거래정지(거래량 0·종가 전일 그대로) → 08-26 2:1 기준가 조정
# (종가 1,859 · 전일대비 +429 → 기준가 1,430 = 2,860의 절반).
def _raw(date, close, diff, sign, vol, val="0"):
    return {"stck_bsop_date": date, "stck_clpr": str(close), "prdy_vrss": str(diff),
            "prdy_vrss_sign": sign, "acml_vol": str(vol), "acml_tr_pbmn": str(val),
            "flng_cls_code": "00", "prtt_rate": "0.00", "mod_yn": "N"}


CSA_0825 = _raw("20260825", 2860, 0, "0", 0)
CSA_0826 = _raw("20260826", 1859, 429, "1", 235816, 435106801)
CSA_0827 = _raw("20260827", 1912, 53, "2", 2185748, 4821907514)
CSA_0922 = _raw("20260922", 1552, -64, "5", 36115, 56794598)


class TestNormalize:
    def test_부호_있는_전일대비로_기준가_대비_등락률을_만든다(self):
        row = kc._normalize_kis_row(CSA_0922)
        assert row["close"] == 1552 and row["volume"] == 36115
        assert row["fluc_rt"] == round(-64 / (1552 + 64) * 100, 2)

    def test_기준가_조정일은_원값_종가가_아니라_기준가_대비다(self):
        row = kc._normalize_kis_row(CSA_0826)
        assert row["fluc_rt"] == 30.0          # 429 / 1430

    def test_하락_부호인데_양수로_오면_뒤집는다(self):
        row = kc._normalize_kis_row(_raw("20260101", 950, 50, "5", 1))
        assert row["fluc_rt"] == round(-50 / 1000 * 100, 2)

    def test_KIS에_없는_필드는_None이고_출처_표지가_있다(self):
        row = kc._normalize_kis_row(CSA_0922)
        assert row["mktcap"] is None and row["list_shrs"] is None and row["sect"] is None
        assert row["src"] == "kis"

    def test_기준가_조정일을_price_breaks가_잡는다(self):
        rows = [{**kc._normalize_kis_row(r), "gap_before": False}
                for r in (CSA_0825, CSA_0826, CSA_0827)]
        br = price_breaks(rows)
        assert [b["date"] for b in br] == ["20260826"]
        assert abs(br[0]["adj"] - 0.5) < 1e-9


# ── 페이징 ────────────────────────────────────────────────────────────────

def _weekdays(start, end):
    d, e, out = dt.datetime.strptime(start, "%Y%m%d"), dt.datetime.strptime(end, "%Y%m%d"), []
    while d <= e:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += dt.timedelta(days=1)
    return out


def _fake_pages(all_dates, *, fail_on_call=None):
    """최신순 100행씩 주는 가짜 일봉 — 종료일(end_dd) 이하만 준다."""
    calls = []

    def _fn(stock_code, start_dd, end_dd, app_key, app_secret):
        calls.append((start_dd, end_dd))
        if fail_on_call is not None and len(calls) == fail_on_call:
            return None
        picked = sorted((d for d in all_dates if start_dd <= d <= end_dd), reverse=True)[:100]
        return [_raw(d, 1000, 0, "3", 10) for d in picked]
    return _fn, calls


@pytest.fixture
def fixed_today(monkeypatch):
    monkeypatch.setattr(kc, "_today_str", lambda: "20260923")


class TestFetchSeries:
    def test_1년이_3콜이고_전_구간을_덮는다(self, monkeypatch, fixed_today):
        dates = _weekdays("20250923", "20260922")
        fn, calls = _fake_pages(dates)
        monkeypatch.setattr(kc, "kis_get_daily", fn)
        out = kc.fetch_price_series_kis("083660", "K", "20250923", "20260922", "k", "s")
        assert len(calls) == 3
        assert len(out["rows"]) == len(dates)
        assert out["days_uncovered"] == [] and not out["fetch_failed"]
        assert out["days_fetched"] == out["days_requested"] == len(dates)
        assert out["source"] == "kis" and out["no_share_data"] is True
        assert [r["date"] for r in out["rows"]] == sorted(dates)

    def test_이어받기는_가장_오래된_날짜_전날로(self, monkeypatch, fixed_today):
        dates = _weekdays("20250923", "20260922")
        fn, calls = _fake_pages(dates)
        monkeypatch.setattr(kc, "kis_get_daily", fn)
        kc.fetch_price_series_kis("083660", "K", "20250923", "20260922", "k", "s")
        first_oldest = sorted(dates, reverse=True)[99]
        assert calls[1][1] == (dt.datetime.strptime(first_oldest, "%Y%m%d")
                               - dt.timedelta(days=1)).strftime("%Y%m%d")

    def test_중간_실패는_받은_것만_보이고_오래된_쪽을_미조회로(self, monkeypatch, fixed_today):
        dates = _weekdays("20250923", "20260922")
        fn, _ = _fake_pages(dates, fail_on_call=2)
        monkeypatch.setattr(kc, "kis_get_daily", fn)
        out = kc.fetch_price_series_kis("083660", "K", "20250923", "20260922", "k", "s")
        assert len(out["rows"]) == 100
        assert not out["fetch_failed"] and out["partial_failed"]
        oldest = out["rows"][0]["date"]
        assert out["days_uncovered"] == [d for d in dates if d < oldest]

    def test_첫_콜부터_실패면_실패(self, monkeypatch, fixed_today):
        fn, _ = _fake_pages([], fail_on_call=1)
        monkeypatch.setattr(kc, "kis_get_daily", fn)
        out = kc.fetch_price_series_kis("083660", "K", "20260901", "20260922", "k", "s")
        assert out["fetch_failed"] and out["rows"] == []
        assert out["days_uncovered"] == _weekdays("20260901", "20260922")

    def test_오늘_행은_장중_자료라_빼고_pending으로(self, monkeypatch, fixed_today):
        dates = _weekdays("20260915", "20260923")
        fn, _ = _fake_pages(dates)
        monkeypatch.setattr(kc, "kis_get_daily", fn)
        out = kc.fetch_price_series_kis("083660", "K", "20260915", "20260923", "k", "s")
        assert "20260923" not in [r["date"] for r in out["rows"]]
        assert out["days_pending"] == ["20260923"]

    def test_상장_전_구간은_미조회가_아니다(self, monkeypatch, fixed_today):
        dates = _weekdays("20260801", "20260922")   # 8월 상장 — 창은 1월부터
        fn, calls = _fake_pages(dates)
        monkeypatch.setattr(kc, "kis_get_daily", fn)
        out = kc.fetch_price_series_kis("083660", "K", "20260101", "20260922", "k", "s")
        assert len(calls) == 1 and out["days_uncovered"] == []

    def test_비대상_시장과_키_없음(self):
        assert kc.fetch_price_series_kis("1", "N", "20260101", "20260102", "k", "s")["unsupported_market"]
        out = kc.fetch_price_series_kis("1", "Y", "20260101", "20260102", "", "")
        assert out["missing_key"] and out["fetch_failed"]


# ── KRX 빈 날 메우기 ──────────────────────────────────────────────────────

def _krx_row(date, sect="중견기업부"):
    return {"date": date, "close": 1000, "fluc_rt": 0.0, "volume": 10, "value": 1,
            "mktcap": 30_000_000_000, "list_shrs": 1_000_000, "sect": sect, "gap_before": False}


class TestFill:
    def _krx_series(self, got, uncovered, pending=()):
        return {"rows": [_krx_row(d) for d in got], "days_requested": len(got) + len(uncovered),
                "days_fetched": len(got), "days_cached": 0, "days_uncovered": list(uncovered),
                "days_pending": list(pending), "quota_hit": False, "fetch_failed": True,
                "api_id": "ksq_bydd_trd"}

    def test_못_받은_날만_KIS로_채우고_KRX_행은_그대로(self, monkeypatch, fixed_today):
        days = _weekdays("20260901", "20260922")
        got, unc = days[5:], days[:5]
        fn, calls = _fake_pages(days)
        monkeypatch.setattr(kc, "kis_get_daily", fn)
        out = kc.fill_series_with_kis(self._krx_series(got, unc), "083660", "K", "k", "s")
        assert calls[0] == (unc[0], unc[-1])          # 빈 구간만 조회
        assert [r["date"] for r in out["rows"]] == days
        assert all(r.get("src") == "kis" for r in out["rows"][:5])
        assert all(r["mktcap"] for r in out["rows"][5:])
        assert out["days_uncovered"] == [] and not out["fetch_failed"]
        assert out["source"] == "krx+kis" and out["kis_days"] == 5
        assert out["days_fetched"] == len(days)
        assert not any(r["gap_before"] for r in out["rows"])

    def test_KIS가_실패하면_KRX_그대로에_실패_표시만(self, monkeypatch, fixed_today):
        days = _weekdays("20260901", "20260922")
        fn, _ = _fake_pages([], fail_on_call=1)
        monkeypatch.setattr(kc, "kis_get_daily", fn)
        base = self._krx_series(days[5:], days[:5])
        out = kc.fill_series_with_kis(base, "083660", "K", "k", "s")
        assert out["rows"] == base["rows"] and out["days_uncovered"] == days[:5]
        assert out["kis_fill_failed"] and out["source"] == "krx"

    def test_빈_날이_없으면_부르지_않는다(self, monkeypatch):
        called = []
        monkeypatch.setattr(kc, "kis_get_daily", lambda *a: called.append(a))
        base = {**self._krx_series(["20260901"], []), "fetch_failed": False}
        out = kc.fill_series_with_kis(base, "083660", "K", "k", "s")
        assert called == [] and out["source"] == "krx"

    def test_섞인_시계열에서_소속부_이동을_지어내지_않는다(self, monkeypatch, fixed_today):
        days = _weekdays("20260901", "20260922")
        fn, _ = _fake_pages(days)
        monkeypatch.setattr(kc, "kis_get_daily", fn)
        # KRX 행 사이에 KIS 행이 끼어도(소속부 None) 소속부 이동이 생기면 안 된다.
        base = self._krx_series(days[:3] + days[8:], days[3:8])
        out = kc.fill_series_with_kis(base, "083660", "K", "k", "s")
        ov = window_overview(out["rows"])
        assert ov["sect_changes"] == []
        assert ov["mktcap_days"] == len(days) - 5


# ── 토큰 ──────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload

    def json(self):
        return self._p


@pytest.fixture
def token_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(kc, "_resolve_corp_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(kc, "_token_mem", {})
    return tmp_path


class TestToken:
    def test_한번_발급하면_메모리와_디스크에서_재사용(self, monkeypatch, token_dir):
        posts = []
        exp = (dt.datetime.now() + dt.timedelta(hours=20)).strftime("%Y-%m-%d %H:%M:%S")

        def _post(url, json=None, timeout=None):
            posts.append(url)
            return _Resp(200, {"access_token": "T1", "access_token_token_expired": exp,
                               "expires_in": 86400, "token_type": "Bearer"})
        monkeypatch.setattr(kc.requests, "post", _post)
        assert kc.kis_access_token("APPKEY", "SECRET") == "T1"
        assert kc.kis_access_token("APPKEY", "SECRET") == "T1"
        kc._token_mem.clear()
        assert kc.kis_access_token("APPKEY", "SECRET") == "T1"   # 디스크
        assert len(posts) == 1

    def test_캐시_파일에_앱키가_남지_않는다(self, monkeypatch, token_dir):
        monkeypatch.setattr(kc.requests, "post", lambda *a, **k: _Resp(
            200, {"access_token": "T1", "expires_in": 86400}))
        kc.kis_access_token("APPKEY-SECRET-VALUE", "SECRET")
        files = list((token_dir / "kis").glob("*.json"))
        assert len(files) == 1
        body = files[0].read_text(encoding="utf-8")
        assert "APPKEY-SECRET-VALUE" not in files[0].name and "APPKEY-SECRET-VALUE" not in body
        assert "SECRET" not in json.loads(body)

    def test_만료_표기는_KST로_읽는다(self):
        epoch = kc._parse_expiry({"access_token_token_expired": "2026-09-24 23:13:17"}, 0)
        kst = dt.timezone(dt.timedelta(hours=9))
        assert epoch == dt.datetime(2026, 9, 24, 23, 13, 17, tzinfo=kst).timestamp()

    def test_만료된_토큰이면_한_번만_새로_받아_다시_부른다(self, monkeypatch, token_dir):
        tokens = iter(["OLD", "NEW"])
        monkeypatch.setattr(kc.requests, "post", lambda *a, **k: _Resp(
            200, {"access_token": next(tokens), "expires_in": 86400}))
        seen = []

        def _get(url, headers=None, params=None, timeout=None):
            seen.append(headers["authorization"])
            if headers["authorization"].endswith("OLD"):
                return _Resp(500, {"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "기간이 만료된 token"})
            return _Resp(200, {"rt_cd": "0", "output2": [CSA_0922]})
        monkeypatch.setattr(kc.requests, "get", _get)
        monkeypatch.setattr(kc.time, "sleep", lambda s: None)
        rows = kc.kis_get_daily("083660", "20260901", "20260922", "APPKEY", "SECRET")
        assert rows == [CSA_0922]
        assert seen[-1] == "Bearer NEW"

    def test_토큰_발급_실패면_None(self, monkeypatch, token_dir):
        monkeypatch.setattr(kc.requests, "post", lambda *a, **k: _Resp(403, {}))
        assert kc.kis_access_token("APPKEY", "SECRET") is None
        assert kc.kis_get_daily("083660", "20260901", "20260922", "APPKEY", "SECRET") is None


# ── 서버 배선 ────────────────────────────────────────────────────────────

pytestmark = pytest.mark.usefixtures("no_structured_dart")


def _kis_series_rows(start, end):
    out = []
    for i, d in enumerate(_weekdays(start, end)):
        out.append({"date": d, "close": 1000 + i, "fluc_rt": 0.1, "volume": 1000,
                    "value": 1, "mktcap": None, "list_shrs": None, "sect": None,
                    "src": "kis", "gap_before": False})
    return out


class TestServerSource:
    def test_KRX만_있으면_KIS를_부르지_않는다(self, monkeypatch):
        monkeypatch.setattr(srv, "fetch_price_series", lambda *a, **k: {"rows": [], "days_uncovered": ["20260901"]})
        monkeypatch.setattr(srv, "fill_series_with_kis", lambda *a, **k: pytest.fail("KIS 호출"))
        monkeypatch.setattr(srv, "fetch_price_series_kis", lambda *a, **k: pytest.fail("KIS 호출"))
        srv._market_series("005930", "Y", "20260101", "20260922", "krx", budget=1)

    def test_둘_다_있으면_KRX_뒤에_KIS로_메운다(self, monkeypatch):
        monkeypatch.setattr(srv, "_KIS_APP_KEY", "k")
        monkeypatch.setattr(srv, "_KIS_APP_SECRET", "s")
        monkeypatch.setattr(srv, "fetch_price_series", lambda *a, **k: {"rows": [], "src": "krx"})
        seen = []
        monkeypatch.setattr(srv, "fill_series_with_kis", lambda series, *a: seen.append(a) or {"filled": True})
        assert srv._market_series("005930", "Y", "20260101", "20260922", "krx", budget=1) == {"filled": True}
        assert seen == [("005930", "Y", "k", "s")]

    def test_KIS만_있으면_KIS_단독(self, monkeypatch):
        monkeypatch.setattr(srv, "_KIS_APP_KEY", "k")
        monkeypatch.setattr(srv, "_KIS_APP_SECRET", "s")
        monkeypatch.setattr(srv, "fetch_price_series", lambda *a, **k: pytest.fail("KRX 호출"))
        monkeypatch.setattr(srv, "fetch_price_series_kis", lambda *a, **k: {"source": "kis"})
        assert srv._market_series("005930", "Y", "20260101", "20260922", "", budget=1)["source"] == "kis"

    def test_앱키만_있고_시크릿이_없으면_KIS가_아니다(self, monkeypatch):
        monkeypatch.setattr(srv, "_KIS_APP_KEY", "k")
        assert srv._kis_credentials() is None


def _wire_kis_only(monkeypatch, rows):
    monkeypatch.setattr(srv, "_DART_API_KEY", "testkey")
    monkeypatch.setattr(srv, "_KIS_APP_KEY", "k")
    monkeypatch.setattr(srv, "_KIS_APP_SECRET", "s")
    monkeypatch.setattr(srv, "resolve_corp", lambda *a: ("테스트기업", {"corp_code": "00000001", "stock_code": "083660"}))
    monkeypatch.setattr(srv, "fetch_company_info", lambda *a, **k: {"corp_cls": "K"})
    monkeypatch.setattr(srv, "fetch_company_disclosures_with_status", lambda *a, **k: ([{
        "report_nm": "주요사항보고서(전환사채권발행결정)", "rcept_no": "20260801000001",
        "rcept_dt": "20260801", "corp_code": "00000001", "corp_name": "테스트기업",
        "flr_nm": "테스트기업"}], FETCH_OK))
    monkeypatch.setattr(srv, "fetch_price_series", lambda *a, **k: pytest.fail("KRX 호출"))
    monkeypatch.setattr(srv, "fetch_price_series_kis", lambda *a, **k: {
        "rows": rows, "days_requested": len(rows), "days_fetched": len(rows), "days_cached": 0,
        "days_uncovered": [], "days_pending": [], "quota_hit": False, "fetch_failed": False,
        "api_id": "kis_daily", "source": "kis", "no_share_data": True})
    monkeypatch.setattr(srv, "fetch_market_alerts", lambda *a, **k: {
        "alerts": [], "clamped": False, "fetch_failed": False})


class TestKisOnlyRender:
    def test_KIS_단독_출력은_출처를_밝히고_KRX라_부르지_않는다(self, monkeypatch):
        _wire_kis_only(monkeypatch, _kis_series_rows("20260420", "20260812"))
        out = srv.track_market_reaction("테스트기업")
        assert out.startswith("📈")
        assert "한국투자증권 Open API" in out
        assert "한국거래소 통계정보" not in out
        assert "KRX 발표 전" not in out and "호출 예산" not in out
        # 회전율 없음은 한 번만 밝힌다 — 사건 각주로 되풀이하지 않는다.
        assert out.count("회전율·시총은 비워 둡니다") == 1
        assert "상장주식수가 없어 회전율을 계산할 수 없는" not in out
        assert "시가총액: -" not in out

    def test_KIS_단독이면_시총_대조를_0거래일로_적지_않는다(self, monkeypatch):
        rows = _kis_series_rows("20260420", "20260812")
        rows = [dict(r, close=900) for r in rows]          # 주가 미달이 발화하도록
        _wire_kis_only(monkeypatch, rows)
        out = srv.track_market_reaction("테스트기업")
        assert "시총 대조 불가" in out
        assert "시총 미달 0거래일" not in out

    def test_흡수_블록도_KIS로_돈다(self, monkeypatch):
        _wire_kis_only(monkeypatch, _kis_series_rows("20260420", "20260812"))
        lines = srv._market_reaction_block(
            [{"key": "CB_BW", "label": "CB", "rcept_dt": "20260801", "is_amendment": False}],
            "083660", "K", "", lookback_days=365,
        )
        text = "\n".join(lines)
        assert "공시 전후 시장 반응" in text and "한국투자증권 Open API" in text
        assert "KRX_API_KEY 환경변수가 설정되지 않았습니다" not in text

    def test_둘_다_없으면_두_길을_모두_안내한다(self, monkeypatch):
        monkeypatch.setattr(srv, "_DART_API_KEY", "testkey")
        out = srv.track_market_reaction("테스트기업")
        assert out.startswith("❌ KRX_API_KEY 환경변수가 설정되지 않았습니다")
        assert "KIS_APP_KEY" in out and "KIS_APP_SECRET" in out


class TestMixedRender:
    def test_섞인_시계열은_출처를_둘_다_밝히고_회전율_각주를_되풀이하지_않는다(self, monkeypatch):
        _wire_kis_only(monkeypatch, [])
        monkeypatch.setattr(srv, "_KRX_API_KEY", "krx")
        kis_rows = _kis_series_rows("20260420", "20260731")
        krx_rows = [dict(r, mktcap=30_000_000_000, list_shrs=1_000_000, src=None)
                    for r in _kis_series_rows("20260801", "20260812")]
        monkeypatch.setattr(srv, "fetch_price_series", lambda *a, **k: {"rows": krx_rows})
        monkeypatch.setattr(srv, "fill_series_with_kis", lambda *a, **k: {
            "rows": kis_rows + krx_rows, "days_requested": 80, "days_fetched": 80,
            "days_cached": 0, "days_uncovered": [], "days_pending": [], "quota_hit": False,
            "fetch_failed": False, "source": "krx+kis", "kis_days": len(kis_rows)})
        out = srv.track_market_reaction("테스트기업")
        assert "한국거래소 통계정보" in out and "한국투자증권 Open API" in out
        assert out.count("KRX로 못 받은") == 1
        assert "상장주식수가 없어 회전율을 계산할 수 없는" not in out
