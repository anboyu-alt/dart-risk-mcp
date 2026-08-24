"""겸직 비교가 **두 창**을 하나로 뭉뚱그리지 않는지 잠근다.

뷰어의 「임원 겸직 비교」 화면을 처음 열어 검증하다 찾았다(2026-08-25).

`find_actor_overlap`은 창이 **둘**이다:

    인수자(CB·유상증자)   `lookback_years * 365`일
    등기임원 겸직         `range(올해-N, 올해+1)` = **N+1개 사업연도**

임원현황은 사업보고서 기재 항목이라 연도 단위이고, 당해년도는 아직 미제출일
수 있어 루프가 올해까지 포함한다(의도된 설계). 그런데 면책 문구는 둘을
**한 label로 묶어** *"{window_label} 이내 … 인수자와 임원현황 겸직을 함께
대조하며"*라 적었다 — `lookback_years=1`이면 공시는 365일인데 명부는 **두
사업연도**다.

실측(2026-08-25): CG인바이츠의 신승수는 **2022·2023** 명부에 있다.
`lookback_years=4`로 부르면 core는 2022~2026 **5개 연도**를 훑는다.

창의 길이를 바꾸지 않는다(결과가 달라진다) — **적는 방식**만 고친다.
"""
import inspect
import pathlib
import re

from dart_risk_mcp.core.dart_client import fetch_executive_roster

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SERVER = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")


def test_명부_루프는_N더하기1개_연도다():
    """이 사실이 바뀌면 문구도 함께 고쳐야 한다."""
    src = inspect.getsource(fetch_executive_roster)
    assert "range(current_year - lookback_years, current_year + 1)" in src


def test_면책이_두_창을_구분한다():
    i = _SERVER.index("이 결과는 DART 공개 API 범위 내 분석입니다")
    block = _SERVER[i:i + 500]
    assert "roster_label" in block, "명부 창이 문구에 없다"
    assert "두 창의 길이가 다릅니다" in block
    assert "{window_label} 이내 \"\n        \"CB/BW/EB" not in _SERVER


def test_명부_창_라벨이_실제_범위를_쓴다():
    assert "_ry_from = _ry_to - lookback_years" in _SERVER
    assert 'roster_label = f"{_ry_from}~{_ry_to} 사업연도"' in _SERVER


def test_뷰어도_실제_연도_범위를_적는다():
    """「최근 4개 사업연도」는 당해년도(대개 미제출)를 한 해로 센다."""
    assert "const ROSTER_YEARS" in _HTML
    assert "ROSTER_YEARS.label" in _HTML
    assert "for (let y = ROSTER_YEARS.from; y <= ROSTER_YEARS.to; y++)" in _HTML
    assert "· 최근 4개 사업연도</div>" not in _HTML


def test_뷰어_안내가_미제출_가능성을_말한다():
    assert "당해년도는 사업보고서 미제출일 수 있습니다" in _HTML


def test_뷰어_루프_범위가_core와_같은_모양이다():
    """core는 올해-N..올해, 뷰어는 올해-3..올해 — 둘 다 당해년도를 포함한다."""
    m = re.search(r"return \{ from: y - (\d+), to: y,", _HTML)
    assert m and m.group(1) == "3"
