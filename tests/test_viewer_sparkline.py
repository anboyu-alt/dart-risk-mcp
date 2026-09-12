"""뷰어 스파크라인(`sparklineSVG`)의 불변식.

숫자 시계열 옆에 얹는 보조 그림이다. core에 짝이 없는 뷰어 전용 함수라
패리티 대상이 아니고, 대신 여기서 잠근다.

여기서 조용히 깨질 수 있는 것:

  ① **결측을 건너뛰고 잇는 것** — 2023·2025만 있는 값을 나란한 두 점으로
     그리면 없는 2024가 사라져 「연속된 관측」처럼 읽힌다. 그림이 제 데이터와
     다른 것을 말한다. 결측이 하나라도 있으면 **그리지 않는다**(숫자 줄이
     「―」로 결측을 그대로 밝힌다).
  ② **오르내림을 색으로 칠하는 것** — 상승 초록·하락 빨강은 그 자체가 좋고
     나쁨의 판정이다(v0.8.5). 이 도구가 내는 것은 사실이지 방향에 대한
     평가가 아니다.
  ③ **0으로 나누기** — 값이 전부 같으면 span이 0이라 좌표가 NaN이 된다.
     SVG는 NaN 좌표를 조용히 무시해 선이 사라진다.
"""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = _ROOT / "docs" / "tool" / "index.html"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없으면 뷰어 쪽을 돌릴 수 없다"
)


def _cut(src: str, head: str) -> str:
    i = src.index(head)
    depth, j, in_s, q = 0, i, False, ""
    while j < len(src):
        c = src[j]
        if in_s:
            if c == "\\":
                j += 2
                continue
            if c == q:
                in_s = False
        elif c in "\"'`":
            in_s, q = True, c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    raise AssertionError(f"{head!r}의 끝을 찾지 못했다")


def _run(calls: list) -> list:
    src = _HTML.read_text(encoding="utf-8")
    # ⚠ `esc`는 `_cut`으로 자를 수 없다 — 본문의 정규식 리터럴 `/[&<>"]/g`에
    #   든 따옴표를 문자열 시작으로 오인해 중괄호 균형이 깨진다. 한 줄짜리라
    #   그 줄을 통째로 가져온다(손으로 베끼면 배포본과 갈린다).
    m = re.search(r"^function esc\(.*$", src, re.M)
    assert m, "뷰어에서 esc 정의를 찾지 못했다"
    js = (
        m.group(0) + "\n"
        + _cut(src, "function sparklineSVG(") + "\n"
        + f"const CALLS = {json.dumps(calls, ensure_ascii=False)};\n"
        "console.log(JSON.stringify(CALLS.map(([v, o]) => sparklineSVG(v, o))));\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False,
                                     encoding="utf-8") as f:
        f.write(js)
        path = f.name
    try:
        # ⚠ 인코딩을 못 박는다 — 윈도우 기본(cp949)으로 디코드하면 한글 라벨이
        #   든 출력에서 UnicodeDecodeError가 나고 stdout이 None이 된다.
        r = subprocess.run(["node", path], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        assert r.returncode == 0, f"node 실패:\n{(r.stderr or '')[:1200]}"
        return json.loads(r.stdout)
    finally:
        pathlib.Path(path).unlink(missing_ok=True)


class TestSparkline:
    def test_결측이_섞이면_그리지_않는다(self):
        """건너뛰고 이으면 없는 구간이 사라져 시간축이 왜곡된다."""
        got = _run([
            [[1.0, None, 3.0], None],
            [[1.0, 2.0, float("nan")], None],   # JSON을 거치면 null이 된다
            [[], None],
            [None, None],
        ])
        assert got == ["", "", "", ""]

    def test_값이_전부_같아도_선이_사라지지_않는다(self):
        """span이 0일 때 좌표가 NaN이 되면 SVG가 조용히 아무것도 안 그린다."""
        out = _run([[[5.0, 5.0, 5.0], None]])[0]
        assert "NaN" not in out
        assert "<polyline" in out
        nums = re.findall(r"points=\"([^\"]+)\"", out)
        assert nums, "polyline에 points가 없다"
        for pair in nums[0].split():
            x, y = pair.split(",")
            assert float(x) == float(x) and float(y) == float(y)  # NaN이 아니다

    def test_관측_1건은_점으로_찍는다(self):
        out = _run([[[7.5], None]])[0]
        assert "<circle" in out and "<polyline" not in out

    def test_여러_값은_선과_끝점(self):
        out = _run([[[1.0, 5.0, 3.0], None]])[0]
        assert "<polyline" in out
        assert out.count("<circle") == 1, "점을 전부 찍으면 선을 덮어 추세가 안 보인다"

    def test_방향을_색으로_칠하지_않는다(self):
        """상승 초록·하락 빨강은 그 자체가 판정이다(v0.8.5)."""
        up = _run([[[1.0, 2.0, 3.0], None]])[0]
        down = _run([[[3.0, 2.0, 1.0], None]])[0]
        stroke = re.compile(r'stroke="([^"]+)"')
        assert stroke.findall(up) == stroke.findall(down), (
            "오르는 선과 내리는 선의 색이 다르다 — 방향에 대한 평가가 된다"
        )
        for out in (up, down):
            assert "--red" not in out and "--green" not in out

    def test_그림에_대체_텍스트가_있다(self):
        out = _run([[[1.0, 2.0], {"label": "홍길동 보유비율 추이"}]])[0]
        assert 'role="img"' in out
        assert 'aria-label="홍길동 보유비율 추이"' in out
        assert "<title>홍길동 보유비율 추이</title>" in out

    def test_라벨을_이스케이프한다(self):
        out = _run([[[1.0, 2.0], {"label": '<script>"&'}]])[0]
        assert "<script>" not in out
        assert "&lt;" in out


def test_숫자_시계열을_대체하지_않는다():
    """그림은 옆에 얹는 것이다 — 링크 달린 숫자 줄이 그대로 남아야 한다."""
    src = _HTML.read_text(encoding="utf-8")
    i = src.index("function loadHoldings(")
    body = _cut(src, "function loadHoldings(")
    assert "sparklineSVG(" in body
    assert "dartUrl(p.rcept)" in body, (
        "보고자별 숫자 시계열의 공시 링크가 사라졌다 — 스파크라인은 보조이지 "
        "대체가 아니다(그림을 못 보는 환경의 대체 표현이기도 하다)"
    )
