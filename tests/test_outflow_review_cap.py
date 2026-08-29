"""유출성 공시 원문 확인의 **상한을 밝히는지** 잠근다.

`capital_backflow` 패턴은 「유출 상대가 계열·특수관계로 확인될 때만」 표시한다.
그 확인은 **원문 조회**로 하는데, 비용 때문에 최근 4건만 본다.

문제는 그 제한을 **말하지 않았다**는 것이다. 유출성 공시가 10건인 회사에서
6건은 아예 열어보지도 않는데, 화면은 「확인된 특수관계 유출: A」만 보여 준다.
**그 6건에 계열 유출이 있어도 목록에 없다** — 패턴 판정의 근거를 제한하면서
그 제한을 숨기는 것이다.

실측(2026-08-30, 아틀라스링크):

    MCP   유출성 공시 10건 중 최근 4건의 원문만 확인 · 6건 미확인
    뷰어  유출성 공시  5건 중 최근 4건의 원문만 확인 · 1건 미확인

(두 화면의 전체 건수가 다른 것은 조회 창이 달라서다 — MCP 3년 · 뷰어 1년.)

⚠ **상한 자체는 그대로 둔다.** 원문 ZIP 조회 비용이 있고, 이건 **표기** 문제다.

## 뷰어의 죽은 파라미터

`capitalBackflowCardHTML(pattern, events, results, totalCount, affiliateFacts)`가
`totalCount`를 **받기만 하고 쓰지 않았다.** 호출부는 `allHits.length`를 넘기고
있었으니 사실은 이미 손에 있었다.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")


def test_core_상한이_상수로_있다():
    assert "_OUTFLOW_REVIEW_MAX = 4" in _SRC
    assert "_all_candidates[:_OUTFLOW_REVIEW_MAX]" in _SRC, "리터럴이 남아 있다"


def test_core가_미확인_건수를_계산한다():
    i = _SRC.index("_OUTFLOW_REVIEW_MAX = 4")
    body = _SRC[i:i + 600]
    assert "_outflow_unreviewed" in body
    assert "len(_all_candidates) - len(candidates)" in body


def test_core_헤더가_전체와_미확인을_밝힌다():
    # ⚠ 이 문구는 주석에도 나온다 — **렌더 지점**을 잡아야 한다.
    i = _SRC.index('"🔍 **자금유출·양수거래 상대방 확인** "')
    body = _SRC[i - 200:i + 600]
    assert "_oc_unreviewed" in body
    assert "미확인" in body
    assert "if _oc_unreviewed else" in body, "미확인 0건일 때 소음을 만든다"


def test_core가_호출부_시그니처를_바꾸지_않았다():
    """리스트에 속성을 붙여 넘긴다 — FetchList가 fetch_failed를 붙이는 결."""
    assert 'getattr(outflow_confirmations, "unreviewed", 0)' in _SRC
    assert "class _Reviewed(list):" in _SRC


def test_뷰어_상한이_상수로_있다():
    assert "const OUTFLOW_REVIEW_MAX = 4;" in _HTML
    assert "allHits.slice(0, OUTFLOW_REVIEW_MAX)" in _HTML


def test_뷰어가_받기만_하던_totalCount를_쓴다():
    i = _HTML.index("function capitalBackflowCardHTML(")
    body = _HTML[i:i + 4800]
    assert "(totalCount || 0) - results.length" in body, "죽은 파라미터가 그대로다"
    assert "미확인" in body


def test_뷰어가_미확인_0건일_때_문구를_붙이지_않는다():
    i = _HTML.index("function capitalBackflowCardHTML(")
    body = _HTML[i:i + 4800]
    assert re.search(r"if \(_unreviewed\)\s*\{", body)


def test_자금사용_용도가_잘리면_밝힌다():
    """한 조달건에 용도가 5개면 3개만 보이고 2개는 흔적이 없었다."""
    i = _HTML.index("function fundEntryCardHTML(")
    body = _HTML[i:i + 1400]
    assert "_useAll.length > _useShown.length" in body
    assert "외 ${_useAll.length - _useShown.length}개" in body
