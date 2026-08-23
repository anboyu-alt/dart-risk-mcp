"""조회 실패와 자료 부재를 구분한다 (2026-08-23).

이 레포의 코딩 규칙은 "API 호출 실패 시 빈 값 반환(예외를 도구 레벨로
전파하지 않음)"이다. 방침 자체는 맞는데, **조용히 빈 값이 되면 "신호 없음"과
구분되지 않는다** — 접수번호 조회에서 이미 겪은 문제다.

에러 경로 감사(50조합)에서 확인: 네트워크 예외·020 한도초과·900 키오류에서
모두 "공시 없음"이라는 화면이 나왔다. 리스크를 알리는 도구에서 "조용하다"와
"못 봤다"가 같은 모양이면 안 된다.
"""
from unittest.mock import patch

import pytest

import dart_risk_mcp.core.dart_client as dc
import dart_risk_mcp.server as srv


class _Resp:
    def __init__(self, status="000", rows=None, total=None):
        self._p = {"status": status, "list": rows or [],
                   "total_count": total if total is not None else len(rows or [])}

    def json(self):
        return self._p


class TestFetchStatus:
    def test_정상_응답은_ok다(self):
        rows = [{"rcept_no": "1", "report_nm": "x"}]
        with patch.object(dc, "_retry", return_value=_Resp(rows=rows)):
            got, st = dc.fetch_company_disclosures_with_status("00126380", "k")
        assert (len(got), st) == (1, dc.FETCH_OK)

    def test_013은_자료_없음이다(self):
        """'그 조건에 자료가 없다'는 확정 답변 — 오류가 아니다."""
        with patch.object(dc, "_retry", return_value=_Resp("013")):
            got, st = dc.fetch_company_disclosures_with_status("00126380", "k")
        assert (got, st) == ([], dc.FETCH_EMPTY)

    @pytest.mark.parametrize("status", ["020", "900", "800"])
    def test_비정상_status는_오류다(self, status):
        with patch.object(dc, "_retry", return_value=_Resp(status)):
            got, st = dc.fetch_company_disclosures_with_status("00126380", "k")
        assert (got, st) == ([], dc.FETCH_ERROR)

    def test_네트워크_예외는_오류다(self):
        with patch.object(dc, "_retry", side_effect=RuntimeError("net")):
            got, st = dc.fetch_company_disclosures_with_status("00126380", "k")
        assert (got, st) == ([], dc.FETCH_ERROR)

    def test_키가_없으면_오류다(self):
        got, st = dc.fetch_company_disclosures_with_status("00126380", "")
        assert (got, st) == ([], dc.FETCH_ERROR)

    def test_빈_정상응답은_자료_없음이다(self):
        with patch.object(dc, "_retry", return_value=_Resp(rows=[])):
            got, st = dc.fetch_company_disclosures_with_status("00126380", "k")
        assert st == dc.FETCH_EMPTY

    def test_부분_성공은_성공이다(self):
        """3페이지를 받다가 끊겼다면 받은 건 유효하다."""
        calls = []

        def fake(method, url, **kw):
            calls.append(1)
            if len(calls) >= 2:
                raise RuntimeError("net")
            return _Resp(rows=[{"rcept_no": str(i)} for i in range(100)], total=500)

        with patch.object(dc, "_retry", side_effect=fake), \
             patch.object(dc.time, "sleep"):
            got, st = dc.fetch_company_disclosures_with_status(
                "00126380", "k", max_pages=5)
        assert st == dc.FETCH_OK
        assert len(got) == 100


class TestBackwardCompat:
    def test_옛_함수는_행만_돌려준다(self):
        rows = [{"rcept_no": "1", "report_nm": "x"}]
        with patch.object(dc, "_retry", return_value=_Resp(rows=rows)):
            got = dc.fetch_company_disclosures("00126380", "k")
        assert isinstance(got, list) and len(got) == 1

    def test_옛_함수는_실패에_빈_리스트다(self):
        with patch.object(dc, "_retry", side_effect=RuntimeError("net")):
            assert dc.fetch_company_disclosures("00126380", "k") == []


class TestToolMessages:
    """도구가 실패를 '공시 없음'으로 말하지 않는지."""

    TOOLS = [
        ("analyze_company_risk", lambda: srv.analyze_company_risk("삼성전자")),
        ("build_event_timeline", lambda: srv.build_event_timeline("삼성전자")),
        ("list_disclosures_by_stock", lambda: srv.list_disclosures_by_stock("005930")),
        ("check_disclosure_anomaly", lambda: srv.check_disclosure_anomaly("삼성전자")),
    ]

    def _run(self, call, status):
        with patch.object(srv, "_DART_API_KEY", "k"), \
             patch.object(srv, "fetch_company_disclosures_with_status",
                          return_value=([], status)), \
             patch.object(srv, "resolve_corp",
                          return_value=("삼성전자", {"corp_code": "00126380",
                                                  "stock_code": "005930"})):
            return call()

    @pytest.mark.parametrize("name,call", TOOLS)
    def test_조회_실패를_알린다(self, name, call):
        out = self._run(call, dc.FETCH_ERROR)
        assert "불러오지 못했습니다" in out, name
        # 문구는 "자료"로 통일했다 — 같은 헬퍼를 기업개요·임원보수도 쓰는데
        # 그쪽은 공시가 아니다(#216에서 일반화).
        assert "자료가 없다는 뜻이 아닙니다" in out, name

    @pytest.mark.parametrize("name,call", TOOLS)
    def test_자료_없음은_실패로_말하지_않는다(self, name, call):
        """진짜로 공시가 없는 회사까지 '조회 실패'라고 하면 안 된다."""
        out = self._run(call, dc.FETCH_EMPTY)
        assert "불러오지 못했습니다" not in out, name

    def test_실패_안내가_원인을_짚어준다(self):
        out = srv._fetch_failed_notice("가나", "365일")
        assert "API 키" in out
        assert "한도" in out
