"""뷰어 렌더 경로의 불변식.

파서는 여러 번 검증했지만 **화면에 그리는 쪽**은 테스트가 없었다. 이쪽의
조용한 실패는 셋이다.

  ① `$("id")`가 가리키는 컨테이너가 HTML에 없다 → 패널이 통째로 안 뜬다
  ② DART 값을 이스케이프 없이 innerHTML에 넣는다 → `<`가 든 값이 레이아웃을
     깨거나 주입 경로가 된다
  ③ 스피너를 띄워 놓고 **아무것도 안 하고 빠지는 분기**가 있다 → 영원히
     돈다. 사용자는 "아직 불러오는 중"으로 읽고 기다린다 — 실패보다 나쁘다
     (실패는 최소한 끝난 걸 안다)

2026-08-23 감사에서 셋 다 건전함을 확인했다(컨테이너 42/42 실재 · esc가
5문자 처리 · 모든 로더가 `return` 직전에 화면을 채움). 유일한 예외였던
`loadCapitalBackflowGate`의 `if (!hits.length) return;`은 형제 게이트와
같게 고쳤다 — 오늘은 도달하지 않지만(카드가 겹침 2개일 때만 그려지고 같은
`observedEvents`를 넘기므로 5.7 증거가 반드시 있다) 두 형제의 처리가 달라야
할 이유가 없다.
"""
import pathlib
import re

import pytest

_HTML = pathlib.Path(__file__).parent.parent / "docs" / "tool" / "index.html"
_SRC = _HTML.read_text(encoding="utf-8")


def _fn_body(name: str, kind: str = "async function") -> str:
    i = _SRC.find(f"{kind} {name}")
    if i < 0:
        return ""
    depth = 0
    for j in range(i, len(_SRC)):
        if _SRC[j] == "{":
            depth += 1
        elif _SRC[j] == "}":
            depth -= 1
            if depth == 0:
                return _SRC[i:j + 1]
    return ""


class TestContainers:
    def test_참조하는_id가_모두_실재한다(self):
        used = set(re.findall(r'\$\(\s*"([A-Za-z][\w-]*)"\s*\)', _SRC))
        declared = set(re.findall(r'\bid="([\w-]+)"', _SRC))
        assert used, "$() 참조를 못 읽었다 — 정규식이 깨졌다"
        missing = sorted(used - declared)
        assert not missing, f"선언이 없는 컨테이너: {missing}"


class TestEscaping:
    @pytest.mark.parametrize("ch", ["&", "<", ">", '"', "'"])
    def test_esc가_다섯_문자를_처리한다(self, ch):
        body = _fn_body("esc", kind="function")
        assert body, "esc 헬퍼를 못 찾았다"
        assert ch in body, f"esc가 {ch!r}를 처리하지 않는다"

    def test_esc를_실제로_쓴다(self):
        """헬퍼만 있고 안 쓰면 의미가 없다."""
        assert len(re.findall(r"\$\{[^}]*esc\(", _SRC)) >= 100


class TestSpinnersAlwaysReplaced:
    """스피너를 띄운 자리는 반드시 교체된다."""

    LOADERS = sorted(set(re.findall(r"async function (load\w+)", _SRC)))

    def test_로더를_찾았다(self):
        assert len(self.LOADERS) >= 10, f"로더를 못 읽었다: {self.LOADERS}"

    @pytest.mark.parametrize("name", LOADERS)
    def test_화면을_바꾸지_않고_빠지는_분기가_없다(self, name):
        body = _fn_body(name)
        assert body, f"{name} 본문을 못 찾았다"
        if not re.search(r"\.(innerHTML|outerHTML)\s*=", body):
            pytest.skip(f"{name}은 화면을 직접 쓰지 않는다")
        for m in re.finditer(r"return;", body):
            head = body[:m.start()]
            # `if (!el) return;` — 컨테이너 자체가 없는 정상 가드
            if re.search(r"if\s*\(!el\)\s*$", head.rstrip()[-20:] or ""):
                continue
            tail = head[-260:]
            if "!el" in tail[-40:]:
                continue
            assert re.search(r"\.(innerHTML|outerHTML)\s*=", tail), (
                f"{name}: 화면을 채우지 않고 return한다 — 스피너가 남는다\n"
                f"    …{' '.join(tail[-120:].split())}"
            )


class TestGatesConsistent:
    """두 원문 확인 게이트는 같은 상황을 같게 처리한다."""

    def test_증거가_없으면_둘_다_카드를_걷는다(self):
        for name in ("loadCapitalBackflowGate", "loadFundDiversionGate"):
            body = _fn_body(name)
            assert body, name
            m = re.search(r"if\s*\(!hits\.length\)\s*(\{[^}]*\}|[^\n]*)", body)
            assert m, f"{name}: !hits.length 분기를 못 찾았다"
            assert "outerHTML" in m.group(1), (
                f"{name}: 증거가 없을 때 카드를 걷지 않는다 — {m.group(1)[:60]}"
            )
