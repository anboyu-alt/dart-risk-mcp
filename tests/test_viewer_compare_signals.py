"""비교 화면의 신호 요약 표(`compareSnapshot`·`compareTableHTML`) 불변식.

겸직만 보면 「같은 사람이 오갔다」는 알지만 「그 회사들에서 무슨 일이
있었나」는 모른다. 같은 기간·같은 규칙으로 세어 나란히 놓는 표다.

여기서 조용히 깨질 수 있는 것:

  ① **집계 규칙 복제** — `buildResult`가 쓰는 것과 다른 규칙으로 세면 같은
     회사가 두 화면에서 다른 수를 갖는다. 규칙을 베끼지 않고 **같은 함수**를
     부른다.
  ② **전역 `CUR` 오염** — `buildResult`는 대시보드 상태를 통째로 갈아치운다.
     비교 화면에서 부르면 보고 있던 결과가 날아간다.
  ③ **`displayLabel` 오용** — 그 함수는 **현재 스캔**의 보정 라벨이라 여러
     회사를 나란히 놓는 표에서는 뜻이 맞지 않고, 대시보드를 돌리기 전이면
     `CUR`이 null이라 **터진다**(실제로 터졌다).
  ④ **조회 실패를 0건으로 그리는 것** — 「신호가 없다」로 읽힌다.
"""
import pathlib
import re

_HTML = pathlib.Path(__file__).parent.parent / "docs" / "tool" / "index.html"
_SRC = _HTML.read_text(encoding="utf-8")


def _fn(head: str) -> str:
    i = _SRC.find(head)
    assert i >= 0, f"{head!r}를 찾지 못했다"
    depth = 0
    for j in range(i, len(_SRC)):
        if _SRC[j] == "{":
            depth += 1
        elif _SRC[j] == "}":
            depth -= 1
            if depth == 0:
                return _SRC[i:j + 1]
    raise AssertionError(f"{head!r}의 중괄호가 닫히지 않았다")


class TestCompareSignals:
    def test_같은_함수로_센다(self):
        """규칙을 복제하면 한쪽만 고쳐질 때 두 화면이 다른 말을 한다."""
        body = _fn("function compareSnapshot(")
        for fn in ("AMEND_RE.test", "matchSignals(", "qualifySignals(", "isObservedSig"):
            assert fn in body, f"대시보드와 같은 {fn}를 쓰지 않는다"

    def test_전역_상태를_건드리지_않는다(self):
        body = _fn("async function compareActors(")
        assert "buildResult(" not in body, (
            "buildResult는 CUR를 갈아치운다 — 보고 있던 대시보드가 날아간다"
        )
        assert "CUR =" not in body and "CUR=" not in body

    def test_비교표는_기본_라벨을_쓴다(self):
        """`displayLabel`은 현재 스캔(CUR)의 보정 라벨이라 여기서는 맞지 않는다."""
        body = _fn("function compareTableHTML(")
        assert "displayLabel(" not in body, (
            "여러 회사를 나란히 놓는 표에서 특정 회사의 보정 라벨을 쓰면 안 된다"
        )
        assert "signalLabel(" in body

    def test_CUR이_없어도_라벨_함수가_터지지_않는다(self):
        """대시보드를 돌리기 전에도 다른 화면이 부를 수 있다."""
        for head in ("function displayLabel(", "function commonNote("):
            body = _fn(head)
            assert "(CUR && CUR.observedEvents)" in body, (
                f"{head}에 CUR 가드가 없다 — 스캔 전에 부르면 터진다"
            )

    def test_조회_실패를_0건으로_그리지_않는다(self):
        body = _fn("function compareTableHTML(")
        assert "s.failed" in body, "실패한 회사를 따로 그리지 않는다"
        assert "신호가 없다는 뜻이 아닙니다" in body

    def test_상한과_생략을_밝힌다(self):
        body = _fn("function compareTableHTML(")
        assert "COMPARE_SCAN_MAX" in body
        assert "조회하지 않은 회사" in body, "무엇을 안 봤는지 적어야 한다"
        assert "전체" in body, "수집이 잘린 회사의 전체 건수를 밝혀야 한다"

    def test_이름_뒤에_조사를_붙이지_않는다(self):
        """받침에 따라 「은/는」이 갈린다 — 「두산는」이 실제로 나왔다."""
        body = _fn("function compareTableHTML(")
        assert not re.search(r'\{esc\(skipped\.join\([^)]*\)\)\}(는|은|이|가|을|를)', body), (
            "회사 이름 뒤에 조사를 붙이고 있다 — 이름은 무엇이든 올 수 있다"
        )

    def test_판정하지_않는다(self):
        body = _fn("function compareTableHTML(")
        assert "건수가 많은 회사가 더 위험하다는 뜻이 아닙니다" in body, (
            "나란히 놓는 표는 순위처럼 읽히기 쉽다 — 아니라고 적어야 한다"
        )
