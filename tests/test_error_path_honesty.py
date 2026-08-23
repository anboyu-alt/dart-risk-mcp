"""조회 실패가 "자료 없음"처럼 보이지 않는지 — 도구 × 실패 시나리오 전수.

이 레포의 방침은 "API 호출 실패 시 빈 값 반환"이다. 맞는 방침인데, 빈 값이
그대로 화면이 되면 **"이 회사는 조용하다"와 "못 봤다"가 같은 모양**이 된다.
리스크를 알리는 도구에서 그 둘이 섞이면 안 된다.

2026-08-23 감사(5 시나리오 × 10 도구 = 50조합)에서 실제로 둘을 찾았다.
  ① 네트워크 예외·020·900에서 "공시 없음" — `fetch_company_disclosures`
     경로(별도 수정)
  ② `{"status":"000"}`만 온 응답을 유효로 보고 **전 필드가 "-"인 기업 개요
     표**를 냈다 — 여기서 고친다

⚠ 이 테스트의 "알림 표현" 목록이 좁으면 멀쩡한 안내를 결함으로 오탐한다.
실제로 "찾지 못했습니다"를 빠뜨려 두 도구를 잘못 셌다. 도구가 쓰는 표현을
코드에서 확인하고 넣는다.
"""
from unittest.mock import patch

import pytest

import dart_risk_mcp.core.dart_client as dc
import dart_risk_mcp.server as srv


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


FAIL_MARKS = ("❌", "⚠", "실패", "없습니다", "없거나", "찾을 수 없",
              "찾지 못", "확인하지 못", "불러올 수 없", "불러오지 못",
              "조회되지", "오류", "낼 수 없")

# 두 부류를 갈라야 계약이 정확해진다.
#   실패   — 못 받았다. 사용자에게 알려야 한다.
#   자료없음 — 정상 응답인데 내용이 없다. "없다"고 말하면 되고,
#             오히려 "실패했다"고 하면 거짓이 된다.
FAILURE_SCENARIOS = [
    ("네트워크 예외", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net"))),
    ("DART 020 한도초과", lambda *a, **k: _Resp({"status": "020"})),
    ("DART 900 키오류", lambda *a, **k: _Resp({"status": "900"})),
]
EMPTY_SCENARIOS = [
    ("DART 013 자료없음", lambda *a, **k: _Resp({"status": "013"})),
    ("알맹이 없는 200", lambda *a, **k: _Resp({"status": "000"})),
]
SCENARIOS = FAILURE_SCENARIOS + EMPTY_SCENARIOS

TOOLS = [
    ("get_company_info", lambda: srv.get_company_info("삼성전자")),
    ("get_financial_summary", lambda: srv.get_financial_summary("삼성전자")),
    ("track_debt_balance", lambda: srv.track_debt_balance("삼성전자")),
    ("get_shareholder_info", lambda: srv.get_shareholder_info("삼성전자")),
    ("get_affiliate_investments", lambda: srv.get_affiliate_investments("삼성전자")),
    ("get_executive_compensation", lambda: srv.get_executive_compensation("삼성전자")),
]


def _run(call, side):
    with patch.object(srv, "_DART_API_KEY", "k"), \
         patch.object(dc, "_retry", side_effect=side), \
         patch.object(srv, "resolve_corp",
                      return_value=("삼성전자", {"corp_code": "00126380",
                                              "stock_code": "005930"})):
        return call()


class TestNoSilentFailure:
    @pytest.mark.parametrize("sname,side", FAILURE_SCENARIOS,
                             ids=[s[0] for s in FAILURE_SCENARIOS])
    @pytest.mark.parametrize("tname,call", TOOLS, ids=[t[0] for t in TOOLS])
    def test_실패를_사용자에게_알린다(self, tname, call, sname, side):
        out = _run(call, side)
        assert any(m in out for m in FAIL_MARKS), (
            f"{tname} / {sname}: 실패했는데 정상처럼 보인다 — "
            f"첫 줄 {out.splitlines()[0][:60]!r}"
        )

    @pytest.mark.parametrize("sname,side", EMPTY_SCENARIOS,
                             ids=[s[0] for s in EMPTY_SCENARIOS])
    @pytest.mark.parametrize("tname,call", TOOLS, ids=[t[0] for t in TOOLS])
    def test_자료없음을_실패로_말하지_않는다(self, tname, call, sname, side):
        """정상 응답인데 "조회가 실패했다"고 하면 그것도 거짓이다."""
        out = _run(call, side)
        assert "불러오지 못했습니다" not in out, f"{tname} / {sname}"

    @pytest.mark.parametrize("sname,side", SCENARIOS,
                             ids=[s[0] for s in SCENARIOS])
    @pytest.mark.parametrize("tname,call", TOOLS, ids=[t[0] for t in TOOLS])
    def test_예외가_새어나가지_않는다(self, tname, call, sname, side):
        _run(call, side)          # 예외가 나면 그대로 실패한다


class TestEmptyPayloadGuard:
    """`{"status":"000"}`만 온 응답 — 알맹이가 없으면 받은 게 아니다."""

    def test_기업개요_빈_응답은_빈_dict다(self):
        with patch.object(dc, "_retry", return_value=_Resp({"status": "000"})):
            assert dc.fetch_company_info("00126380", "k") == {}

    def test_corp_name이_있으면_유효하다(self):
        payload = {"status": "000", "corp_name": "삼성전자(주)"}
        with patch.object(dc, "_retry", return_value=_Resp(payload)):
            assert dc.fetch_company_info("00126380", "k")["corp_name"] == "삼성전자(주)"

    def test_도구가_빈_응답을_실패로_알린다(self):
        out = _run(lambda: srv.get_company_info("삼성전자"),
                   lambda *a, **k: _Resp({"status": "000"}))
        assert "불러올 수 없습니다" in out
        assert "대표자: -" not in out, "알맹이 없는 표를 그리면 안 된다"
