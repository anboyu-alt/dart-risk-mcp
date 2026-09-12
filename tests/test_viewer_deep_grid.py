"""딥 블록 반응형 격자(`.deepgrid`)의 불변식.

대시보드 아래쪽 패널들을 넓은 화면에서 2~3열로 펴는 격자다. 여기서 조용히
깨질 수 있는 것이 셋이라 기계로 잠근다.

  ① **태그 불균형** — `renderDash`는 문자열을 이어 붙여 `innerHTML`에 넣는다.
     여는 `<div class="deepgrid">`만 있고 닫는 `</div>`가 없으면 브라우저가
     **조용히 교정**해 버려 화면으로는 안 보인다. 그런데 그 교정은 뒤따르는
     `convoPanel`을 격자 안으로 빨아들여 전폭 CTA가 한 트랙으로 찌그러진다.
  ② **격자 밖으로 새는 패널** — 딥 블록을 새로 추가하면서 여는 태그 앞에
     두면 그 패널만 1열로 남는다. 화면이 어색해질 뿐 오류는 안 난다.
  ③ **`.wide`(전폭 span)의 부활** — 실측으로 뺀 것이다(아래 근거). 다시
     넣으면 격자 높이가 도로 늘어나는데, 되레 "넓게 보이니 좋아졌다"고
     오인하기 쉽다.

실측 근거(코아스 1920px · 딥 블록 10개):

    전               7,369px (6.8화면)
    후 2열           6,033px (5.6화면)   ← 채택
    후 3열           6,135px             트랙 528px, MEZZANINE이 한 행 지배
    후 2열 + .wide   6,558px             wide 3개가 연달아 행마다 구멍

`.wide`를 뺄 수 있었던 것은 표를 감싼 div가 이미 `overflow-x:auto`여서다 —
트랙 388px에서 TURNOVER 표 498px가 **표 안에서만** 가로 스크롤되고 패널·
페이지는 넘치지 않는다(실측).
"""
import pathlib
import re

import pytest

_HTML = pathlib.Path(__file__).parent.parent / "docs" / "tool" / "index.html"
_SRC = _HTML.read_text(encoding="utf-8")


def _css_without_comments() -> str:
    """`<style>` 블록에서 `/* … */` 주석을 지운 것.

    금지 선언을 검사할 때 **왜 금지했는지 적어 둔 주석**에 걸리면 안 된다.
    """
    i, j = _SRC.find("<style>"), _SRC.find("</style>")
    assert 0 <= i < j, "style 블록을 찾지 못했다"
    return re.sub(r"/\*.*?\*/", " ", _SRC[i:j], flags=re.S)

# 격자에 들어가야 하는 딥 블록의 컨테이너 id — renderDash가 스켈레톤을 만들고
# loadDeepBlocks가 나중에 채운다.
_DEEP_IDS = [
    "ctrlCore", "rpCore", "atCore", "esCore", "finCore",
    "turnoverCore", "mezzanineCore", "dilutionCore", "divCore",
    "fundCore", "holdCore", "auditCore",
]

# 펼칠 때만 받는 블록 — 스켈레톤에 스피너가 없는 것이 **맞다**(아직 아무것도
# 조회하지 않았으므로). 대신 무엇을 여는 것인지 접힌 상태에서 알 수 있어야 한다.
_LAZY_IDS = ["debtCore", "auditSvcCore"]


def _render_dash() -> str:
    """`renderDash` 함수 본문(중괄호 균형으로 잘라낸다)."""
    i = _SRC.find("function renderDash(")
    assert i >= 0, "renderDash를 찾지 못했다"
    depth = 0
    for j in range(i, len(_SRC)):
        if _SRC[j] == "{":
            depth += 1
        elif _SRC[j] == "}":
            depth -= 1
            if depth == 0:
                return _SRC[i:j + 1]
    raise AssertionError("renderDash의 중괄호가 닫히지 않았다")


class TestDeepGrid:
    def test_격자를_한_번만_열고_닫는다(self):
        body = _render_dash()
        opens = body.count('<div class="deepgrid">')
        closes = body.count("// .deepgrid 닫기")
        assert opens == 1, f"딥 블록 격자는 하나여야 한다(열림 {opens}개)"
        assert closes == 1, (
            "닫는 `</div>`에 `// .deepgrid 닫기` 주석을 붙여 둔다 — "
            "innerHTML은 태그 불균형을 조용히 교정해 눈으로 못 찾는다"
        )

    def test_딥_블록이_모두_격자_안에_있다(self):
        body = _render_dash()
        open_at = body.find('<div class="deepgrid">')
        close_at = body.find("// .deepgrid 닫기")
        assert 0 < open_at < close_at
        for cid in _DEEP_IDS + _LAZY_IDS:
            at = body.find(f'id="{cid}"')
            assert at >= 0, f"{cid} 컨테이너가 renderDash에 없다"
            assert open_at < at < close_at, (
                f"{cid}가 격자 밖에 있다 — 이 패널만 1열로 남아 줄이 어긋난다"
            )

    def test_convoPanel은_격자_밖이다(self):
        body = _render_dash()
        close_at = body.find("// .deepgrid 닫기")
        convo_at = body.find("convoPanel(name)")
        assert close_at < convo_at, (
            "GO DEEPER는 대화 유도 CTA라 전폭이 맞다 — 격자 밖에 둔다"
        )

    def test_격자_CSS가_실재한다(self):
        assert ".deepgrid { display: grid;" in _SRC
        assert ".deepgrid > .panel { margin-bottom: 0; }" in _SRC, (
            "패널의 margin-bottom이 gap과 이중으로 먹으면 행 간격이 어긋난다"
        )
        assert ".deepgrid > * { min-width: 0; }" in _SRC, (
            "표가 트랙을 밀어내는 것을 막는다(.mainarea와 같은 처방)"
        )
        assert "@media (min-width: 1280px) { .deepgrid" in _SRC
        assert "@media (min-width: 2280px) { .deepgrid" in _SRC

    def test_dense_배치를_쓰지_않는다(self):
        """빈 칸을 메우려고 순서를 재배치하면 위험도 순서를 암시한다(v0.8.5).

        ⚠ 주석에 적힌 금지 문구까지 세면 안 된다 — 왜 안 쓰는지를 적어 둔
        자리가 있어서, 원문 검색은 그 설명 자체에 걸린다(첫 판이 그랬다).
        """
        assert not re.search(r"grid-auto-flow\s*:", _css_without_comments()), (
            "dense는 DOM 순서와 다르게 그려 '앞에 온 것이 더 중요하다'는 "
            "오해를 만든다. 구멍이 생겨도 순서를 지킨다"
        )

    def test_패널에_overflow를_걸지_않는다(self):
        """`.headline`에서 같은 이유로 overflow:hidden을 뺀 전례가 있다."""
        css = _css_without_comments()
        assert not re.search(r"\.deepgrid\s*>\s*\.panel\s*\{[^}]*overflow", css), (
            "패널에 overflow를 걸면 용어 사전 툴팁(.term-def)이 잘린다"
        )

    def test_전폭_span이_되살아나지_않는다(self):
        """실측으로 뺐다 — 격자 높이가 2,702 → 3,243px로 되레 늘었다."""
        assert 'class="panel wide"' not in _SRC, (
            "표가 넓은 패널에 2트랙을 주면 그 행의 남은 트랙이 통째로 빈다. "
            "셋이 DOM에서 연달아 있고 dense 금지라 메울 방법이 없다. "
            "넓은 표는 부모 div의 overflow-x:auto가 이미 처리한다"
        )
        assert ".deepgrid > .wide" not in _SRC


@pytest.mark.parametrize("cid", _DEEP_IDS)
def test_딥_블록_컨테이너는_스피너로_시작한다(cid):
    """격자로 옮겨도 로딩 표시는 그대로여야 한다 — 빈 칸은 '자료 없음'으로 읽힌다."""
    body = _render_dash()
    at = body.find(f'id="{cid}"')
    assert at >= 0
    assert 'class="spinner"' in body[at:at + 200], (
        f"{cid}가 스피너 없이 시작한다 — 비어 있는 칸이 '자료 없음'으로 읽힌다"
    )


@pytest.mark.parametrize("cid", _LAZY_IDS)
def test_지연_로드_블록은_무엇을_여는지_밝힌다(cid):
    """접힌 채로는 아무것도 조회하지 않는다 — 그렇다면 무엇을 여는지 적어야 한다.

    스피너를 미리 띄우면 「이미 받고 있다」는 거짓말이 되고, 아무 말도 없으면
    「자료가 없다」로 읽힌다.
    """
    body = _render_dash()
    at = body.find(f'id="{cid}"')
    assert at >= 0
    head = body[max(0, at - 400):at + 300]
    assert "<details" in head, f"{cid}는 <details>로 접혀 있어야 한다"
    assert "펼쳐서 조회" in head or "펼칠 때" in head, (
        f"{cid}가 무엇을 여는 것인지 접힌 상태에서 알 수 없다"
    )
    assert 'class="spinner"' not in body[at:at + 200], (
        f"{cid}는 아직 조회하지 않았다 — 스피너는 「받고 있다」는 거짓말이 된다"
    )


@pytest.mark.parametrize("fn", ["loadDebtBalance", "loadAuditServices"])
def test_지연_로드가_한_번만_받는다(fn):
    """<details>는 열고 닫을 때마다 toggle이 난다 — 매번 다시 쏘면 안 된다."""
    i = _SRC.find(f"async function {fn}(")
    assert i >= 0, f"{fn}을 찾지 못했다"
    body = _SRC[i:i + 700]
    assert "dataset.loaded" in body, (
        f"{fn}에 재진입 가드가 없다 — 접었다 펴면 엔드포인트를 다시 조회한다"
    )
