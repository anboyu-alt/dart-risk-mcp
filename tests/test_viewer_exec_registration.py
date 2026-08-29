"""뷰어 겸직 비교가 **등기 여부를 단정하지 않는지** 잠근다.

뷰어의 비교 화면을 실제로 눌러 보다 찾았다(2026-08-30).

    뷰어  「2개사 이상에 **등기임원으로** 등장한 인물 1명」
          이혁재 — 삼성전자(2025) · 셀트리온(2023, 2024, 2025)

    core  「이혁재 — 2개 회사에 [임원] 경로로 등장:
           삼성전자(이사/사외이사), 셀트리온(수석부사장/**미등기**)」

`exctvSttus` 응답에는 `rgist_exctv_at`(등기/미등기) 필드가 **있다**(라이브 확인:
셀트리온 00413046 2025 사업연도 89행, 이혁재 = 수석부사장 · **미등기**).
뷰어는 그 필드를 **안 읽고** 「등기임원으로」라 단정했다 — core는 정확히
표기하고 있었으니 **뷰어만 틀렸다.**

미등기 임원은 흔하다. 「등기임원 겸직」은 지배구조상 무게가 다른 사실이라
단정하면 안 된다.

수정 후:

    2개사 이상에 임원으로 등장한 인물 1명
    이혁재 — 2개사: 삼성전자(2025 · 사외이사) · 셀트리온(2023, 2024, 2025 · 미등기)
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")


def test_등기임원이라_단정하지_않는다():
    assert "등기임원으로 등장한 인물" not in _HTML, (
        "미등기 임원까지 「등기임원」이라 부른다"
    )
    assert "임원으로 등장한 인물" in _HTML


def test_등기_여부_필드를_읽는다():
    i = _HTML.index("async function fetchRoster(")
    body = _HTML[i:_HTML.index("\n}", i)]
    assert "rgist_exctv_at" in body, "응답에 있는 필드를 안 읽는다"
    assert "e.rgist.add(rg)" in body


def test_수집_구조가_연도와_등기를_함께_담는다():
    i = _HTML.index("async function fetchRoster(")
    body = _HTML[i:_HTML.index("\n}", i)]
    assert "{ years: new Set(), rgist: new Set() }" in body


def test_빈_등기_값은_담지_않는다():
    """DART가 빈 값을 주는 회사가 있다 — 「()」가 찍히면 안 된다."""
    i = _HTML.index("async function fetchRoster(")
    body = _HTML[i:_HTML.index("\n}", i)]
    assert re.search(r"if \(rg\) e\.rgist\.add\(rg\)", body)


def test_겹침_렌더가_등기_여부를_표시한다():
    i = _HTML.index("임원으로 등장한 인물")
    body = _HTML[i:i + 900]
    assert "info.rgist" in body
    assert "info.years" in body
    assert "info.rgist.size" in body, "등기 값이 없을 때 「 · 」만 남는다"


def test_전체_명단_렌더도_새_구조를_쓴다():
    """수집 구조를 바꾸면서 이 소비처를 놓치면 「[object Object]」가 찍힌다."""
    i = _HTML.index("회사별 전체 임원 명단 보기")
    body = _HTML[i:i + 600]
    assert "info.years" in body
    assert "[...ys].sort()" not in body, "옛 Set 구조를 그대로 쓴다"


def test_중간_소비처도_객체를_그대로_넘긴다():
    i = _HTML.index("const byPerson = new Map();")
    body = _HTML[i:i + 500]
    assert "byPerson.get(nm).set(company, info)" in body
    assert "[...years].sort()" not in body, "옛 구조가 남아 있다"
