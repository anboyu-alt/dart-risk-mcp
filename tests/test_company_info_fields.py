"""기업 개요의 필드가 실제 응답과 맞는지 잠근다 (2026-08-26).

## 「법인구분」이 모든 회사에서 항상 「-」였다

옛 코드는 `info.get('corp_cls_nm', '-')`를 읽었다. **company.json에 그런
필드가 없다** — 주는 것은 `corp_cls`('Y'/'K'/'N'/'E')다. 골드 10개
전부에서 「• 법인구분: -」이었고, 코드베이스 전체에서 `corp_cls_nm`이
나오는 곳은 그 렌더 한 줄뿐이다(값을 넣는 곳이 없다).

`fetch_debt_balance`(#315)와 같은 종류다 — **존재하지 않는 응답 필드를
읽고 있었다.** 그때 배운 대로 실제 응답 키를 떠서 대조했다.

    acc_mt adres bizr_no ceo_nm corp_cls corp_code corp_name corp_name_eng
    est_dt fax_no hm_url induty_code ir_url jurir_no phn_no stock_code
    stock_name

## 함께 고친 세 가지

- `• IR: ` — `ir_url`이 **키는 있고 값이 빈 문자열**이라 `.get(k, '-')`가
  기본값을 안 쓴다. 라벨만 남았다(삼성전자 실측).
- `• 업종: 264` — 이름을 붙이는 `get_induty_name`이 이미 있는데
  `scan_financial_anomaly`만 쓰고 있었다.
- `• 설립일: 19690113` — 같은 파일의 `_fmt_date8`을 안 거쳤다.
"""
import pytest

import dart_risk_mcp.server as srv


_INFO = {
    "corp_name": "테스트(주)", "stock_code": "005930", "ceo_nm": "홍길동",
    "corp_cls": "Y", "induty_code": "264", "est_dt": "19690113",
    "acc_mt": "12", "adres": "서울", "hm_url": "x.com", "ir_url": "",
    "phn_no": "02-0000-0000",
}


def _render(**over):
    info = dict(_INFO, **over)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(srv, "_DART_API_KEY", "k")
        mp.setattr(srv, "resolve_corp",
                   lambda q, k: ("테스트(주)", {"corp_code": "00126380",
                                             "stock_code": "005930"}))
        mp.setattr(srv, "fetch_company_info", lambda *a, **kw: info)
        return srv.get_company_info("테스트")


@pytest.mark.parametrize("cls,want", [
    ("Y", "유가증권시장 상장"), ("K", "코스닥시장 상장"),
    ("N", "코넥스시장 상장"), ("E", "기타법인(비상장)"),
])
def test_법인구분이_실제_필드에서_나온다(cls, want):
    out = _render(corp_cls=cls)
    assert f"• 법인구분: {want} ({cls})" in out


def test_없는_필드를_읽지_않는다():
    """`corp_cls_nm`은 응답에 없다 — 코드에 남아 있으면 다시 「-」가 된다."""
    import pathlib

    src = (pathlib.Path(srv.__file__)).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "corp_cls_nm" not in code


def test_모르는_구분은_대시로():
    assert "• 법인구분: -" in _render(corp_cls="Z")


def test_빈_값은_대시로():
    """`.get(k, '-')`는 키가 있고 값이 빈 경우를 놓친다."""
    out = _render()
    assert "• IR: -" in out
    assert "• IR: \n" not in out


def test_업종에_이름이_붙는다():
    out = _render()
    assert "KSIC 264" in out
    assert "• 업종: 264" not in out, "코드만 내면 안 된다"


def test_설립일이_포맷된다():
    assert "• 설립일: 1969.01.13" in _render()


def test_설립일이_8자리가_아니면_원문(self=None):
    assert "• 설립일: 1969" in _render(est_dt="1969")


def test_업종이_없으면_대시():
    assert "• 업종: -" in _render(induty_code="")
