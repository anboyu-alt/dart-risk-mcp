"""헤드라인 배지의 낱말이 **그것이 붙는 집합과 맞는지** 잠근다.

위험 목록 8번을 제작자 승인으로 처리한 결과(2026-08-30).

## 무엇이 문제였나

피드 SIGNAL 열의 배지가 「MAX」였다. 조건은 이렇다.

    isTop = heavyKey && r.signals.some(observed && s.key === heavyKey)

`heavyKey`는 `pickHeadline`이 고른 **신호 키**다. 그러니 그 키를 가진 행이
여럿이면 **전부** 붙는다 — 「최대」가 여러 줄에 찍힌다.

실측(15개사 1년, 관찰 행 215건):

    HLB       16행 중 **14행(88%)**   헤드라인 CB_BW · CB 공시가 14건
    오르비텍   17행 중 10행(59%)
    코아스     24행 중 12행(50%)
    합계                59행(**27.4%**)

참고로 「먼저」 배지는 13.0%이고, CLAUDE.md는 그 언저리를 **「배지가 아니라
기본값이 되는 경계」**로 기록해 뒀다. 27.4%는 그 두 배다.

세 가지가 겹쳤다.
  ① 「MAX」는 하나를 가리키는 최상급인데 최대 88%에 붙는다
  ② 같은 줄의 다른 배지는 전부 한국어 사실 표기(먼저·참고·● 신호·절차·사후)
  ③ 상세 화면의 두 자리(`SIGNAL · TOP WEIGHT`·「이 기간 최상위」)도 같은
     `isTop` 조건이라 같은 문제를 갖는다

## 무엇을 고쳤나

**집합은 그대로 두고 낱말만 사실에 맞췄다.** 배지 자체는 「이 회사에서 가장
무거운 유형이 이 줄에 있다」는 쓸모 있는 정보라 없애지 않았다.

    피드      MAX                  → 대표 유형
    상세 헤더  SIGNAL · TOP WEIGHT  → SIGNAL · HEADLINE TYPE
    상세 META  이 기간 최상위        → 이 기간 대표 유형

곁가지: `.badge-max`에 `background: var(--red)fff;`라는 **유효하지 않은 선언**이
있었다. 바로 다음 줄이 덮어써서 화면은 멀쩡했지만 죽은 코드라 지웠다.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")


def _code() -> str:
    """주석을 뺀 코드만 — 근거 주석이 옛 낱말을 인용한다."""
    body = re.sub(r"<!--.*?-->", "", _HTML, flags=re.S)
    keep = [l for l in body.splitlines() if not l.strip().startswith("//")]
    return chr(10).join(keep)


def test_최상급_낱말을_쓰지_않는다():
    body = _code()
    for bad in (">MAX<", "TOP WEIGHT", "이 기간 최상위"):
        assert bad not in body, f"최상급 낱말이 남아 있다: {bad}"


def test_세_자리가_모두_바뀌었다():
    body = _code()
    assert '<span class="badge-max">대표 유형</span>' in body
    assert "SIGNAL · HEADLINE TYPE" in body
    assert '"이 기간 대표 유형"' in body


def test_집합은_건드리지_않았다():
    """낱말만 고쳤다 — 조건이 바뀌면 다른 행에 붙는다."""
    i = _HTML.index("const isTop = heavyKey")
    assert (
        "heavyKey && r.signals.some((s) => isObservedSig(s) && s.key === heavyKey)"
        in _HTML[i:i + 200]
    )
    j = _HTML.index("const isTop = CUR.heaviest")
    assert (
        "r.signals.some((s) => isObservedSig(s) && s.key === CUR.heaviest.key)"
        in _HTML[j:j + 200]
    )


def test_강등된_행은_여전히_제외된다():
    """절차·사후 보고가 헤드라인 키를 우연히 공유해도 배지를 물려받지 않는다."""
    for anchor in ("const isTop = heavyKey", "const isTop = CUR.heaviest"):
        i = _HTML.index(anchor)
        assert "isObservedSig(s)" in _HTML[i:i + 200]


def test_형제_배지는_그대로다():
    """이 수정의 범위 밖 — 우선순위 배지는 건드리지 않았다."""
    body = _code()
    for sib in ('<span class="badge-cau">먼저</span>',
                '<span class="badge-ctx">참고</span>',
                '<span class="sigdot">● 신호</span>',
                '<span class="procmark">절차·사후</span>'):
        assert sib in body, f"형제 배지가 바뀌었다: {sib}"


def test_상세_헤더가_형제와_같은_영문_계열이다():
    """`SIGNAL DETECTED`·`PROCEDURAL FILING`과 한 세트다."""
    body = _code()
    for sib in ("SIGNAL DETECTED", "PROCEDURAL FILING", "NO SIGNAL MATCH"):
        assert sib in body
    assert "SIGNAL · HEADLINE TYPE" in body


def test_죽은_CSS_선언을_지웠다():
    """`background: var(--red)fff;`는 유효하지 않은 값이었다."""
    assert "var(--red)fff" not in _HTML
    i = _HTML.index(".badge-max {")
    assert "background: #c03a3a;" in _HTML[i:i + 220], "실제 배경이 사라졌다"


def test_근거가_주석에_남아_있다():
    """왜 「MAX」를 버렸는지 — 없으면 다음 사람이 되돌린다."""
    i = _HTML.index("const isTop = heavyKey")
    note = _HTML[i - 1400:i]
    assert "88%" in note and "27.4%" in note
    assert "MAX" in note
