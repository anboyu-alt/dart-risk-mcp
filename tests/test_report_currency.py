"""보고 통화가 원화가 아닌 회사를 「원화(원)」이라 단정하지 않는지 잠근다.

## 11조원짜리 회사가 81억원으로 읽혔다

25개사 표본에서 **두산밥캣이 USD로 보고**한다(2026-08-27 실측 — 재무제표
749행 중 30행이 USD). 그런데 도구 꼬리말은 이렇게 단정하고 있었다.

    ⚠️ 금액 단위는 원화(원)이며 DART 공시 기준입니다.

    • 자산총계: 8,169,804,000     ← 81.7억 **달러**(≈11조원)인데
                                    원으로 읽으면 81억원이다

`compare_financials`는 더 나쁘다 — 원화 회사와 달러 회사를 나란히 놓고
「원화(원)」이라 적으면 비교 자체가 성립하지 않는다.

`LOAN_ADVANCE_SURGE`의 임계 **10억원**도 원화 기준이다. $10억은 1.3조원이라
그대로 들이대면 자릿수가 통째로 다르다 — 원화가 아니면 판정하지 않고
그 사실을 남긴다(금액은 그대로 사실 표기).
"""
import pytest

import dart_risk_mcp.server as srv
from dart_risk_mcp.core.dart_client import detect_financial_anomaly, fs_currency
from dart_risk_mcp.server import _currency_footer


class TestFsCurrency:
    def test_다수결로_고른다(self):
        rows = [{"currency": "USD"}, {"currency": "USD"}, {"currency": "KRW"}]
        assert fs_currency(rows) == "USD"

    @pytest.mark.parametrize("rows", [[], None, [{"currency": ""}], [{}]])
    def test_없으면_빈_문자열(self, rows):
        assert fs_currency(rows) == ""

    def test_대소문자를_모은다(self):
        assert fs_currency([{"currency": "usd"}]) == "USD"


class TestFooter:
    @pytest.mark.parametrize("c", ["", "KRW", "krw"])
    def test_원화면_종전_문구(self, c):
        assert _currency_footer(c) == "⚠️ 금액 단위는 원화(원)이며 DART 공시 기준입니다."

    def test_원화가_아니면_밝힌다(self):
        f = _currency_footer("USD")
        assert "USD" in f and "원화가 아닙니다" in f


def _summary(rows):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(srv, "_DART_API_KEY", "k")
        mp.setattr(srv, "resolve_corp",
                   lambda q, k: ("두산밥캣", {"corp_code": "00164788",
                                           "stock_code": "241560"}))
        mp.setattr(srv, "fetch_financial_statements", lambda *a, **kw: rows)
        return srv.get_financial_summary("두산밥캣", "2024")


_USD = [{"fs_div": "CFS", "fs_nm": "연결재무제표", "account_nm": "자산총계",
         "thstrm_amount": "8,169,804,000", "frmtrm_amount": "1",
         "bsns_year": "2024", "currency": "USD"}]
_KRW = [dict(_USD[0], currency="KRW")]


class TestSummary:
    def test_머리글에_통화가_붙는다(self):
        assert "보고 통화: **USD**" in _summary(_USD)

    def test_원화면_군더더기를_붙이지_않는다(self):
        assert "보고 통화" not in _summary(_KRW)

    def test_꼬리말이_원화라고_단정하지_않는다(self):
        out = _summary(_USD)
        assert "금액 단위는 원화(원)" not in out
        assert "USD" in out


class TestCompare:
    def test_통화가_섞이면_비교하지_말라고_적는다(self):
        rows = [dict(_USD[0], corp_code="00164788"),
                dict(_KRW[0], corp_code="00126380")]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(srv, "_DART_API_KEY", "k")
            mp.setattr(srv, "resolve_corp",
                       lambda q, k: (q, {"corp_code": {"두산밥캣": "00164788"}
                                         .get(q, "00126380"), "stock_code": "x"}))
            mp.setattr(srv, "fetch_multi_financial", lambda *a, **kw: rows)
            out = srv.compare_financials(["두산밥캣", "삼성전자"], "2024")
        assert "회사마다 다릅니다" in out
        assert "USD" in out and "KRW" in out


class TestThreshold:
    def _run(self, currency):
        cur = {"매출채권": 1, "재고자산": 1, "당기순이익": 1,
               "영업활동현금흐름": 1, "자본총계": 10, "자본금": 1}
        la = {"bs_current_total": 5_000_000_000, "bs_prior_total": 1,
              "bs_items": [], "cf_items": [], "currency": currency}
        return detect_financial_anomaly(cur, dict(cur), loan_advance=la)

    def test_원화면_종전대로_발화한다(self):
        flags, _ = self._run("KRW")
        assert "LOAN_ADVANCE_SURGE" in flags

    def test_원화가_아니면_판정하지_않는다(self):
        flags, metrics = self._run("USD")
        assert "LOAN_ADVANCE_SURGE" not in flags
        m = [x for x in metrics if "대여금" in x.get("name", "")][0]
        assert m["unit"] == "USD"
        assert "USD" in m.get("note", "")
