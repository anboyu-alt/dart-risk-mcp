"""뷰어 회전율 블록의 **사업연도 수 선택**(1~5)을 잠근다.

MCP `track_turnover_trend(lookback_years)`와 같은 계약을 뷰어에도 준다.
칩을 바꾸면 회전율 블록만 다시 그린다 — 공시 목록·신호·패턴은 사업연도 수와
무관하므로 전체 재스캔을 하지 않는다.

⚠ 이 파일이 잡는 실제 결함: 추세 문구가 「3기간 연속 상승」으로 **하드코딩**돼
있어, 5년을 고르면 5기간인데도 「3기간」이라 적혔다. 회사에 대한 거짓 표기다.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")


def test_칩이_1년부터_5년까지_있다():
    m = re.search(r"\[1, 2, 3, 4, 5\]\.map\(\(n\) =>", _HTML)
    assert m, "회전율 사업연도 칩 목록을 찾지 못했다"
    assert 'data-tyears="${n}"' in _HTML


def test_기본값이_3년이고_1에서_5로_묶인다():
    m = re.search(r"let TURNOVER_YEARS = \(\(\) => \{(.+?)\}\)\(\);", _HTML, re.S)
    assert m, "TURNOVER_YEARS 초기화를 찾지 못했다"
    body = m.group(1)
    assert "v >= 1 && v <= 5 ? v : 3" in body, "범위·기본값 계약이 바뀌었다"
    assert "dart_turnover_years" in body, "선택이 브라우저에 남지 않는다"


def test_로더가_고정_3년을_쓰지_않는다():
    m = re.search(r"async function loadTurnoverTrend\(corpCode\) \{(.+?)\n\}", _HTML, re.S)
    assert m, "loadTurnoverTrend를 찾지 못했다"
    body = m.group(1)
    assert "TURNOVER_YEARS" in body, "선택값을 읽지 않는다"
    assert "Array.from({ length: n }" in body
    assert "thisYear - 3]" not in body, "연도 배열이 3개로 고정돼 있다"


def test_추세_문구가_실제_기간_수를_말한다():
    """「3기간」 하드코딩이 되살아나면 5년 조회에서 거짓 표기가 된다."""
    i = _HTML.index("function turnoverTrendBlockHTML(")
    block = _HTML[i:i + 4000]
    assert "${ms.length}기간 연속 상승" in block
    assert "${ms.length}기간 연속 하락" in block
    assert '" — 3기간 연속' not in block


def test_칩_변경이_전체_재스캔을_부르지_않는다():
    m = re.search(r"function bindTurnoverYearChips\(corpCode\) \{(.+?)\n\}\n", _HTML, re.S)
    assert m, "bindTurnoverYearChips를 찾지 못했다"
    body = m.group(1)
    assert "runTurnoverTrend(corpCode)" in body
    for heavy in ("analyze(", "buildResult(", "loadDeepBlocks("):
        assert heavy not in body, f"칩 클릭이 {heavy}까지 다시 부른다"


def test_같은_값을_다시_누르면_아무것도_하지_않는다():
    m = re.search(r"function bindTurnoverYearChips\(corpCode\) \{(.+?)\n\}\n", _HTML, re.S)
    assert "n === TURNOVER_YEARS) return;" in m.group(1)


def test_서버_키가_있으면_브라우저_키를_요구하지_않는다():
    """로컬 개발 릴레이(`/api/health`)가 키를 갖고 있을 때만이다.

    공용 배포에는 그 경로가 없어 `SERVER_KEY`가 false로 남고 기존대로 막힌다.
    """
    assert "if (!key && !SERVER_KEY) {" in _HTML
    assert "async function probeServerKey()" in _HTML
    i = _HTML.index("async function probeServerKey()")
    body = _HTML[i:i + 700]
    assert "j.server_key" in body
    assert "await probeServerKey();" in _HTML, "부팅 때 확인하지 않는다"
