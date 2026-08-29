"""피드 필터 칩의 **숫자 단위**가 필터 결과와 같은지 잠근다.

뷰어 피드를 실제로 눌러 보다 찾았다(2026-08-30, 제이스코홀딩스 1년).

    칩         전체 93 · ● 신호만 19 · CB/채권 11 · **위기/부실 7** · 자본구조 1
               · 시장감시 1 · 정정 42
    클릭 결과  93 · 19 · 11 · **6** · 1 · 1 · 42

「위기/부실 7」을 누르면 6행이 나온다. 한 공시가 `INSOLVENCY`와 `AUDIT`를
함께 켜서 카테고리 8이 **두 번** 세어진 것이다.

원인은 **단위 불일치**다. 필터 predicate는 `rows.filter(...)`로 **행**을
고르는데, 카테고리 칩의 라벨만 `catCount`(**신호** 수)를 썼다. 같은 줄의
나머지 세 칩은 전부 행 수다 — `CUR.items.length` · `observedEvents.length` ·
`CUR.amendCount`. 나란히 놓이면 같은 단위로 읽힌다.

⚠ 앞선 리뷰 라운드들이 이 줄을 손댔지만(주석: 「필터 predicate도 observed만
매칭해야 라벨과 결과가 어긋나지 않는다」) **observed 축만 맞추고 행/신호 축은
못 봤다.** 축이 둘인데 하나만 맞춘 것이다.

`catCount`(신호 분포)는 지우지 않았다 — 막대 그래프(`categoryBars`)와 범례는
신호 수가 맞는 자리다. 필터 칩만 `catRows`를 쓴다.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")


def _feed_chip_block() -> str:
    i = _HTML.index("function renderFeed()")
    return _HTML[i:i + 2200]


def test_행_단위_카운트가_존재한다():
    assert "const catRows = {};" in _HTML
    assert "for (const c of seenCats) catRows[c] = (catRows[c] || 0) + 1;" in _HTML


def test_신호_단위_카운트를_지우지_않았다():
    """막대·범례는 신호 분포가 맞는 자리다 — 둘 다 있어야 한다."""
    assert "const catCount = {};" in _HTML
    assert "catCount[s.category] = (catCount[s.category] || 0) + 1;" in _HTML
    assert "categoryBars(catCount)" in _HTML


def test_필터_칩_라벨이_행_수를_쓴다():
    body = _feed_chip_block()
    assert "${catRows[c]}</span>" in body, "칩 라벨이 아직 신호 수다"
    assert "${catCount[c]}</span>" not in body


def test_칩_정렬도_같은_단위를_쓴다():
    """라벨은 행 수인데 정렬만 신호 수면 큰 수가 아래에 온다."""
    body = _feed_chip_block()
    assert "Object.keys(catRows).map(Number).sort((a, b) => catRows[b] - catRows[a])" in body


def test_같은_줄의_다른_칩들도_행_수다():
    """단위가 섞이면 안 된다 — 이 셋은 원래부터 행 수였다."""
    body = _feed_chip_block()
    assert "전체 ${CUR.items.length}" in body
    assert "신호만 ${observedEvents.length}" in body
    assert "정정 ${CUR.amendCount}" in body


def test_필터_predicate가_행을_고른다():
    """라벨이 행 수인 근거 — 필터가 행을 세기 때문이다."""
    i = _HTML.index('FEED_FILTER.mode === "cat") list = list.filter(')
    body = _HTML[i:i + 200]
    assert "r.signals.some((s) => isObservedSig(s) && s.category === FEED_FILTER.cat)" in body


def test_renderFeed가_catRows를_꺼낸다():
    body = _feed_chip_block()
    assert re.search(r"const \{[^}]*catRows[^}]*\} = CUR;", body)


def test_CUR에_실려_있다():
    i = _HTML.index("CUR = { name, stockCode, corpCode,")
    assert "catRows" in _HTML[i:i + 500]


def test_대시보드_막대는_단위를_밝힌다():
    """같은 라벨(위기/부실)에 대시보드 7 · 피드 6이 나온다 — 둘 다 맞지만
    단위가 다르다. 막대는 신호 수라 그대로 두고 **밝히기만** 한다."""
    i = _HTML.index("▍CATEGORY DISTRIBUTION")
    body = _HTML[i:i + 900]
    assert "categoryBars(catCount)" in body, "막대는 신호 수를 유지한다"
    assert "신호 수 기준" in body
    assert "피드 칩은 공시 수" in body
