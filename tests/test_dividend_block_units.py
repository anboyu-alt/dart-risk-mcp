"""배당 블록의 **단위**와 **빈 행**을 잠근다.

## 한 리포트 안에서 단위가 섞였다

`track_fund_usage`의 자금사용 목록은 원 단위로 적는다.

    계획: 채무상환자금 (33,000,000,000원)

그런데 같은 리포트의 배당 유출 문장만 DART 원시 단위(백만원)를 그대로 썼다.

    당기순이익 -388,279백만원 + 현금배당금총액 35,772백만원

두 수를 나란히 두고도 어느 쪽이 큰지 바로 읽히지 않는다(330억 vs 358억).
리포트 공통 표기(`_format_amount`)로 환산한다 — 뷰어도 억원으로 보여준다.

## 아무것도 말하지 않는 행이 30%였다

    - 2023  (연결)현금배당성향(%) (-)  당기 - / 전기 -

두산 실측 27줄 중 8줄이 이 형태였다(dedup 전 전체로는 22건). 목록에서만
빼고 몇 건인지 밝힌다 — 자금사용 목록과 같은 태도.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SERVER = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")


def _dividend_block() -> str:
    i = _SERVER.index('lines += ["", "**배당 이력 (alotMatter)**"]')
    return _SERVER[i:i + 3600]


def test_유출_문장이_리포트_공통_단위를_쓴다():
    body = _dividend_block()
    assert "_format_amount(str(_ni_won))" in body, "당기순이익이 환산되지 않는다"
    assert "_format_amount(str(_dv_won))" in body, "배당금이 환산되지 않는다"
    assert "* 1_000_000" in body, "백만원 → 원 환산이 없다"


def test_백만원_원시값을_그대로_찍지_않는다():
    body = _dividend_block()
    assert "백만원 + 현금배당금총액" not in body, "옛 원시 단위 표기가 남아 있다"
    assert not re.search(r"\{fl\['net_income'\]:,\.0f\}백만원", body)


def test_환산이_반올림된다():
    """소수점 절사로 억 단위가 틀어지지 않게 int(round(...))를 쓴다."""
    body = _dividend_block()
    assert "int(round(fl[\"net_income\"] * 1_000_000))" in body
    assert "int(round(fl[\"dividend\"] * 1_000_000))" in body


def test_당기_전기가_모두_미기재인_행은_빠진다():
    body = _dividend_block()
    assert "def _div_blank(" in body, "빈 행 판정이 없다"
    assert '_fund_text(r.get("thstrm"))' in body
    assert '_fund_text(r.get("frmtrm"))' in body


def test_제외_건수를_밝힌다():
    """조용히 자르지 않는다 — 프로젝트의 명시적 원칙."""
    body = _dividend_block()
    assert "_div_blank_n" in body
    assert "모두 미기재인" in body and "제외" in body


def test_한쪽만_있으면_남긴다():
    """당기만 있어도 사실이다 — 둘 다 없을 때만 뺀다."""
    body = _dividend_block()
    m = re.search(r"return not _fund_text\(r\.get\(\"thstrm\"\)\)\s*and\s*"
                  r"not _fund_text\(r\.get\(\"frmtrm\"\)\)", body)
    assert m, "or로 바뀌면 한쪽만 있는 행까지 사라진다"


def test_fund_text가_서버까지_배선됐다():
    assert re.search(r"^\s+_fund_text,$", _SERVER, re.M), "server가 import하지 않는다"
    init = (_ROOT / "dart_risk_mcp" / "core" / "__init__.py").read_text(encoding="utf-8")
    assert "_fund_text" in init, "core가 export하지 않는다"
