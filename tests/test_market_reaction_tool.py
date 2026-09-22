"""`track_market_reaction`(도구 34) — 공시 전후 시장 반응.

DART fetcher·`fetch_price_series`·`fetch_market_alerts`를 전부 monkeypatch해
네트워크 없이 검증한다 — 실제 KRX/KIND 호출은 `tests/test_krx_client.py`·
`tests/test_kind_client.py`가 단위로, `tests/test_market_context.py`가 순수
계산 함수를 각각 이미 잠그고 있다. 이 파일은 **server.py 배선**(인자 검증,
키 없음/코넥스/실패 분기, 렌더 형식, 판정 어휘 부재)만 본다.

`@pytest.mark.usefixtures("no_structured_dart")`로 이 도구가 부르지 않는
구조화 fetcher가 실수로 새지 않게 한다(conftest 관례).
"""
from __future__ import annotations

import datetime as dt

import pytest

import dart_risk_mcp.server as srv
from dart_risk_mcp.core import FETCH_ERROR, FETCH_OK

pytestmark = pytest.mark.usefixtures("no_structured_dart")


def _resolve_corp_stub(name, key):
    return ("테스트기업", {"corp_code": "00000001", "stock_code": "005930"})


def _resolve_corp_no_stock(name, key):
    return ("비상장기업", {"corp_code": "00000002", "stock_code": ""})


def _company_info(corp_cls: str):
    def _fn(corp_code, key):
        return {"corp_cls": corp_cls, "corp_name": "테스트기업"}
    return _fn


def _mk_disclosure(report_nm, rcept_no="20260201000001", rcept_dt="20260201"):
    return {
        "report_nm": report_nm, "rcept_no": rcept_no, "rcept_dt": rcept_dt,
        "corp_code": "00000001", "corp_name": "테스트기업", "flr_nm": "테스트기업",
    }


def _disclosures_stub(rows):
    return lambda *a, **kw: (rows, FETCH_OK)


def _synth_price_rows(start: str, end: str, *, base_close=10000, step=10):
    """평일만 담은 합성 시세 rows(krx_client.fetch_price_series 산출 모양)."""
    rows = []
    d = dt.datetime.strptime(start, "%Y%m%d")
    end_d = dt.datetime.strptime(end, "%Y%m%d")
    close = base_close
    while d <= end_d:
        if d.weekday() < 5:
            rows.append({
                "date": d.strftime("%Y%m%d"), "close": close, "fluc_rt": 1.0,
                "volume": 100000, "value": 1_000_000_000,
                "mktcap": close * 1_000_000, "list_shrs": 1_000_000,
            })
            close += step
        d += dt.timedelta(days=1)
    return rows


def _price_series_stub(rows, *, fetch_failed=False, days_uncovered=None,
                        quota_hit=False, unsupported_market=False,
                        missing_key=False):
    def _fn(stock_code, corp_cls, start_dd, end_dd, api_key, budget=80):
        picked = [r for r in rows if start_dd <= r["date"] <= end_dd]
        return {
            "rows": [] if fetch_failed else picked,
            "days_requested": len(picked),
            "days_fetched": len(picked),
            "days_cached": 0,
            "days_uncovered": days_uncovered or [],
            "quota_hit": quota_hit,
            "fetch_failed": fetch_failed,
            "api_id": "stk_bydd_trd",
            "unsupported_market": unsupported_market,
            "missing_key": missing_key,
        }
    return _fn


def _alerts_stub(alerts=None, *, fetch_failed=False, clamped=False, clamp_start=None):
    def _fn(stock_code, start8, end8):
        return {
            "alerts": alerts or [], "by_kind": {}, "clamped": clamped,
            "clamp_start": clamp_start, "failed_kinds": ["caution"] if fetch_failed else [],
            "parse_failed": fetch_failed, "fetch_failed": fetch_failed,
            "source_url": "https://kind.krx.co.kr/investwarn/investattentwarnrisky.do",
        }
    return _fn


def _wire(monkeypatch, *, disclosures=None, price_rows=None, price_kwargs=None,
          alerts=None, alerts_kwargs=None, corp_cls="Y", resolve_corp=None,
          dart_key="testkey", krx_key="krxkey"):
    monkeypatch.setattr(srv, "_DART_API_KEY", dart_key)
    monkeypatch.setattr(srv, "_KRX_API_KEY", krx_key)
    monkeypatch.setattr(srv, "resolve_corp", resolve_corp or _resolve_corp_stub)
    monkeypatch.setattr(srv, "fetch_company_info", lambda *a, **k: _company_info(corp_cls)(*a, **k))
    if disclosures is not None:
        monkeypatch.setattr(srv, "fetch_company_disclosures_with_status",
                             _disclosures_stub(disclosures))
    monkeypatch.setattr(
        srv, "fetch_price_series",
        _price_series_stub(price_rows or [], **(price_kwargs or {})),
    )
    monkeypatch.setattr(
        srv, "fetch_market_alerts",
        _alerts_stub(alerts, **(alerts_kwargs or {})),
    )


_CB_TITLE = "주요사항보고서(전환사채권발행결정)"
_SHARE_TITLE = "주요사항보고서(최대주주변경)"


class TestKeyGuards:
    def test_dart_키_없으면_안내(self, monkeypatch):
        monkeypatch.setattr(srv, "_DART_API_KEY", "")
        import os
        monkeypatch.delenv("DART_API_KEY", raising=False)
        out = srv.track_market_reaction("테스트기업")
        assert "DART_API_KEY" in out
        assert out.startswith("❌")

    def test_krx_키_없으면_안내(self, monkeypatch):
        monkeypatch.setattr(srv, "_DART_API_KEY", "testkey")
        monkeypatch.setattr(srv, "_KRX_API_KEY", "")
        import os
        monkeypatch.delenv("KRX_API_KEY", raising=False)
        out = srv.track_market_reaction("테스트기업")
        assert "KRX_API_KEY" in out
        assert "openapi.krx.co.kr" in out
        assert out.startswith("❌")


class TestUnsupportedMarket:
    def test_코넥스는_대상이_아니다(self, monkeypatch):
        _wire(monkeypatch, corp_cls="N", disclosures=[_mk_disclosure(_CB_TITLE)])
        out = srv.track_market_reaction("테스트기업")
        assert out.startswith("❌")
        assert "코넥스" in out or "KRX Open API 조회 대상이" in out

    def test_비상장은_대상이_아니다(self, monkeypatch):
        _wire(monkeypatch, resolve_corp=_resolve_corp_no_stock)
        out = srv.track_market_reaction("비상장기업")
        assert out.startswith("❌")
        assert "비상장" in out


class TestNormalTable:
    def test_정상_표와_첫줄_형식(self, monkeypatch):
        rows = _synth_price_rows("20260101", "20260220")
        disclosures = [
            _mk_disclosure(_CB_TITLE, rcept_no="1" * 14, rcept_dt="20260115"),
            _mk_disclosure(_SHARE_TITLE, rcept_no="2" * 14, rcept_dt="20260201"),
        ]
        _wire(monkeypatch, disclosures=disclosures, price_rows=rows)
        out = srv.track_market_reaction("테스트기업")

        first_line = out.splitlines()[0]
        assert first_line == "📈 **테스트기업** (005930) — 공시 전후 시장 반응 (365일)"
        assert "## ① 사건별 시세·거래량 대조" in out
        assert "## ② 🚨 시장경보 이력 (KIND)" in out
        assert "## ③ 📊 창 개괄" in out
        assert "2026.01.15" in out
        assert "2026.02.01" in out
        assert "한국거래소 통계정보" in out

    def test_이_창에는_없음(self, monkeypatch):
        """KIND가 정상 응답했는데 경보가 0건이면 "없음"이지 "확인 불가"가 아니다."""
        rows = _synth_price_rows("20260101", "20260220")
        disclosures = [_mk_disclosure(_CB_TITLE)]
        _wire(monkeypatch, disclosures=disclosures, price_rows=rows, alerts=[])
        out = srv.track_market_reaction("테스트기업")
        assert "이 창에는 시장경보 지정 이력이 없습니다" in out
        assert "확인 불가" not in out

    def test_확인_불가(self, monkeypatch):
        """KIND 응답 자체가 실패하면 "없음"이 아니라 "확인 불가"다."""
        rows = _synth_price_rows("20260101", "20260220")
        disclosures = [_mk_disclosure(_CB_TITLE)]
        _wire(monkeypatch, disclosures=disclosures, price_rows=rows,
              alerts_kwargs={"fetch_failed": True})
        out = srv.track_market_reaction("테스트기업")
        assert "확인 불가" in out
        assert "이 창에는 시장경보 지정 이력이 없습니다" not in out

    def test_kind_경보와_공시_정렬(self, monkeypatch):
        rows = _synth_price_rows("20260101", "20260220")
        disclosures = [_mk_disclosure(_CB_TITLE, rcept_dt="20260201", rcept_no="9" * 14)]
        alerts = [{
            "kind": "caution", "name": "테스트기업", "reason": "매매관여과다종목",
            "announced": "20260202", "designated": "20260203",
        }]
        _wire(monkeypatch, disclosures=disclosures, price_rows=rows, alerts=alerts)
        out = srv.track_market_reaction("테스트기업")
        assert "「투자주의」 지정" in out
        assert "매매관여과다종목" in out
        assert "±10일 안 관찰 공시" in out


class TestPartialAndQuota:
    def test_days_uncovered_고지(self, monkeypatch):
        rows = _synth_price_rows("20260101", "20260220")
        disclosures = [_mk_disclosure(_CB_TITLE)]
        _wire(monkeypatch, disclosures=disclosures, price_rows=rows,
              price_kwargs={"days_uncovered": ["20260102", "20260103"]})
        out = srv.track_market_reaction("테스트기업")
        assert "2일 미조회" in out

    def test_quota_hit_고지(self, monkeypatch):
        rows = _synth_price_rows("20260101", "20260220")
        disclosures = [_mk_disclosure(_CB_TITLE)]
        _wire(monkeypatch, disclosures=disclosures, price_rows=rows,
              price_kwargs={"quota_hit": True})
        out = srv.track_market_reaction("테스트기업")
        assert "일일 호출 한도" in out

    def test_fetch_failed는_없다가_아니라_실패다(self, monkeypatch):
        disclosures = [_mk_disclosure(_CB_TITLE)]
        _wire(monkeypatch, disclosures=disclosures, price_rows=[],
              price_kwargs={"fetch_failed": True})
        out = srv.track_market_reaction("테스트기업")
        assert "불러오지 못했습니다" in out
        assert "자료가 없다는 뜻이 아닙니다" in out


class TestRceptNo:
    def test_rcept_no_단건(self, monkeypatch):
        rows = _synth_price_rows("20260101", "20260220")
        _wire(monkeypatch, price_rows=rows)
        out = srv.track_market_reaction("테스트기업", rcept_no="20260201000001")
        assert "접수번호 20260201000001 전후" in out.splitlines()[0]
        assert "2026.02.01" in out

    def test_rcept_no_형식_오류(self, monkeypatch):
        _wire(monkeypatch)
        out = srv.track_market_reaction("테스트기업", rcept_no="abc")
        assert out.startswith("❌")


class TestNoEvents:
    def test_관찰_신호_없으면_대조할_사건이_없다(self, monkeypatch):
        _wire(monkeypatch, disclosures=[])
        out = srv.track_market_reaction("테스트기업")
        assert "대조할 사건이 없습니다" in out


class TestVerdictVocabulary:
    """v0.8.5 — 급등·급락·과열은 아예 쓰지 않는다. 위험·경고는 KIND
    고유 명칭 인용(「투자주의」·「투자경고」·「투자위험」)일 때만 허용한다."""

    def test_금지_어휘가_없다(self, monkeypatch):
        rows = _synth_price_rows("20260101", "20260220")
        disclosures = [_mk_disclosure(_CB_TITLE, rcept_dt="20260201")]
        alerts = [
            {"kind": "warning", "name": "테스트기업", "announced": "20260202",
             "designated": "20260203", "released": None},
        ]
        _wire(monkeypatch, disclosures=disclosures, price_rows=rows, alerts=alerts)
        out = srv.track_market_reaction("테스트기업")
        for banned in ("급등", "급락", "과열"):
            assert banned not in out
        # "위험"·"경고"는 KIND 고유 명칭 인용에서만 등장한다.
        for line in out.splitlines():
            if "위험" in line:
                assert "「투자위험」" in line
            if "경고" in line:
                assert "「투자경고」" in line

    def test_score_grade_hygiene(self, monkeypatch):
        from tests.test_golden_output_hygiene import (
            _SCORE_GRADE_PATTERNS, _SEVERITY_EMOJI,
        )
        import re

        rows = _synth_price_rows("20260101", "20260220")
        disclosures = [_mk_disclosure(_CB_TITLE)]
        _wire(monkeypatch, disclosures=disclosures, price_rows=rows)
        out = srv.track_market_reaction("테스트기업")
        for pattern, desc in _SCORE_GRADE_PATTERNS:
            assert re.search(pattern, out) is None, f"hygiene 패턴({desc})에 걸린다"
        for emoji in _SEVERITY_EMOJI:
            assert emoji not in out


class TestAbsorbedBlocks:
    """analyze_company_risk·build_event_timeline 흡수 블록."""

    def test_analyze_흡수_블록_키_없으면_한줄(self, monkeypatch):
        monkeypatch.setattr(srv, "_DART_API_KEY", "testkey")
        monkeypatch.setattr(srv, "_KRX_API_KEY", "")
        import os
        monkeypatch.delenv("KRX_API_KEY", raising=False)
        monkeypatch.setattr(srv, "resolve_corp", _resolve_corp_stub)
        monkeypatch.setattr(
            srv, "fetch_company_disclosures_with_status",
            lambda *a, **kw: ([_mk_disclosure(_CB_TITLE)], FETCH_OK),
        )
        out = srv.analyze_company_risk("테스트기업")
        assert "공시 전후 시장 반응" in out
        assert "KRX_API_KEY 환경변수가 설정되지 않았습니다" in out

    def test_analyze_흡수_블록_키_있으면_표(self, monkeypatch):
        rows = _synth_price_rows("20260101", "20260220")
        disclosures = [_mk_disclosure(_CB_TITLE, rcept_dt="20260201")]
        _wire(monkeypatch, disclosures=disclosures, price_rows=rows)
        out = srv.analyze_company_risk("테스트기업")
        assert "공시 전후 시장 반응" in out
        assert "D0 등락" in out

    def test_analyze_지도_모드에서는_생략(self, monkeypatch):
        """5년(1825일) 창은 지도 모드(deep=False)라 시장 반응 블록이 없다."""
        rows = _synth_price_rows("20260101", "20260220")
        disclosures = [_mk_disclosure(_CB_TITLE, rcept_dt="20260201")]
        _wire(monkeypatch, disclosures=disclosures, price_rows=rows)
        out = srv.analyze_company_risk("테스트기업", lookback_years=5)
        assert "공시 전후 시장 반응" not in out

    def test_timeline_흡수_블록_키_있으면_표(self, monkeypatch):
        rows = _synth_price_rows("20260101", "20260220")
        disclosures = [_mk_disclosure(_CB_TITLE, rcept_dt="20260201")]
        _wire(monkeypatch, disclosures=disclosures, price_rows=rows)
        out = srv.build_event_timeline("테스트기업")
        assert "공시 전후 시장 반응" in out
        assert "D0 등락" in out

    def test_timeline_지도_모드에서는_생략(self, monkeypatch):
        rows = _synth_price_rows("20260101", "20260220")
        disclosures = [_mk_disclosure(_CB_TITLE, rcept_dt="20260201")]
        _wire(monkeypatch, disclosures=disclosures, price_rows=rows)
        out = srv.build_event_timeline("테스트기업", lookback_years=5)
        assert "공시 전후 시장 반응" not in out
