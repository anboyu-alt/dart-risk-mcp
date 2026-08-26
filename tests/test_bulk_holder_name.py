"""5% 대량보유자 목록이 **누구인지** 내는지 잠근다 (2026-08-26).

## 이름 자리가 늘 비어 있었다

    nm = h.get("reprt_nm", h.get("nm", "-"))

`majorstock.json`에는 `reprt_nm`도 `nm`도 **없다**. 보고자 필드는 `repror`다.
그래서 골드 전수에서 이렇게 나왔다 —

    ━━ 5% 이상 대량보유자 ━━
      • -: 1,198,889,258주 (20.08%)
      • -: 1,198,946,824주 (20.08%)

**누가 들고 있는지가 이 절의 전부인데** 그 자리가 모든 회사에서 비어 있었다.
`fetch_debt_balance`(#315)·`corp_cls_nm`(#327)에 이은 **세 번째 죽은 필드**다.

실제 응답 키:

    corp_code corp_name ctr_stkqy ctr_stkrt rcept_dt rcept_no report_resn
    report_tp repror stkqy stkqy_irds stkrt stkrt_irds

## 응답은 '현재 보유자'가 아니라 보고 이력이다

삼성전자는 삼성물산 한 곳이 40건을 낸다. 보고자별로 접어 가장 최근 보고만
보이고 몇 건인지 적는다. 같은 응답에 있던 `stkrt_irds`(비율 증감)·
`report_resn`(보고사유)·`rcept_dt`도 함께 낸다 — 「채무자의 기한이익 상실로
채권자가 담보 주식에 대한 처분권을 취득」 같은 사실이 그동안 안 보였다.

⚠ `report_resn`은 **원문에 개행이 섞여 온다** — 접지 않으면 줄이 깨진다.
"""
import pytest

import dart_risk_mcp.server as srv


def _render(bulk):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(srv, "_DART_API_KEY", "k")
        mp.setattr(srv, "resolve_corp",
                   lambda q, k: ("테스트", {"corp_code": "00126380",
                                          "stock_code": "005930"}))
        mp.setattr(srv, "fetch_shareholder_status",
                   lambda *a, **kw: {"major_holders": [], "bulk_holders": bulk})
        return srv.get_shareholder_info("테스트")


_H = {"repror": "삼성물산", "stkqy": "1,198,889,258", "stkrt": "20.08",
      "rcept_dt": "20260731", "stkrt_irds": "", "report_resn": ""}


def test_보고자_이름이_나온다():
    assert "• 삼성물산: 1,198,889,258주 (20.08%)" in _render([_H])


def test_없는_필드를_읽지_않는다():
    import pathlib

    src = pathlib.Path(srv.__file__).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "reprt_nm" not in code


def test_이름이_비면_대시():
    assert "• -:" in _render([dict(_H, repror="")])


def test_보고자별로_접는다():
    rows = [dict(_H, rcept_dt="20240101", stkrt="19.00"),
            dict(_H, rcept_dt="20260731", stkrt="20.08")]
    out = _render(rows)
    assert out.count("• 삼성물산") == 1
    assert "20.08%" in out and "19.00%" not in out, "가장 최근 보고를 남긴다"
    assert "보고 2건 중 최근" in out


def test_보고사유의_개행을_접는다():
    out = _render([dict(_H, report_resn="- 보유주식등의 변동\n- 계약의 변경")])
    body = [l for l in out.splitlines() if "삼성물산" in l][0]
    assert "보유주식등의 변동 - 계약의 변경" in body


def test_증감이_0이면_적지_않는다():
    for z in ("", "-", "0", "0.00", "-0.00"):
        assert "비율 증감" not in _render([dict(_H, stkrt_irds=z)]), z


def test_증감이_있으면_적는다():
    assert "비율 증감 -5.71%p" in _render([dict(_H, stkrt_irds="-5.71")])


def test_많으면_잘렸다고_적는다():
    rows = [dict(_H, repror=f"보유자{i}", rcept_dt=f"2026073{i % 10}")
            for i in range(20)]
    out = _render(rows)
    assert "... 외 5명" in out
