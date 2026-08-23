"""관찰 윈도우 게이트의 core(Python) ↔ 뷰어(JS) 동등성 — 전수 대조.

2026-08-21에 들어간 윈도우 게이트(`find_pattern_overlaps(taxonomy_dates=)`)는
뷰어에도 손으로 이식됐다(`windowEnd`/`bestWindow`/`findPatternOverlaps`).
그런데 **이식본에 파리티 테스트가 없었다** — 이 레포에서 드리프트가 두 번
난 자리다(`classifyOutflowRelation`의 부정 표기 검사 누락, `escalation_subtitles`
export 누락). 눈으로 비교하는 대신 입력을 전수로 돌려 대조한다.

달 연산은 특히 어긋나기 쉽다 — 말일 오버플로(1/31 + 1개월)와 윤년, 그리고
JS의 `%`는 음수에서 Python과 다르게 동작한다.
"""
import itertools
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

from dart_risk_mcp.core.taxonomy import _best_window, _window_end

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = _ROOT / "docs" / "tool" / "index.html"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없어 뷰어 JS를 실행할 수 없다"
)


def _cut(html: str, name: str) -> str:
    m = re.search(r"^function " + name + r"\s*\(", html, re.M)
    assert m, "함수를 찾지 못했다: " + name
    depth, started, i = 0, False, m.start()
    for j in range(i, len(html)):
        if html[j] == "{":
            depth += 1
            started = True
        elif html[j] == "}":
            depth -= 1
            if started and depth == 0:
                return html[i:j + 1]
    raise AssertionError("중괄호가 맞지 않는다: " + name)


# ── 입력 격자 ───────────────────────────────────────────────
# 말일·윤년·연말을 반드시 포함한다.
STARTS = [
    "20240131", "20240229", "20240331", "20240430", "20241231",
    "20250131", "20250228", "20250831", "20260101", "20260229",  # 2026은 평년
    "20230630", "20231130", "20200229", "21000228",              # 2100은 윤년 아님
]
MONTHS = [0, 1, 2, 3, 6, 9, 12, 18, 21, 27, 30, 33, 36, 120]

# bestWindow 시나리오 — (신호 목록, 관찰일, 창 길이)
SCENARIOS = [
    (["1.1", "5.8"], {"1.1": ["20240101"], "5.8": ["20240601"]}, 12),
    (["1.1", "5.8"], {"1.1": ["20240101"], "5.8": ["20250601"]}, 12),   # 창 밖
    (["1.1", "5.8"], {"1.1": ["20240101"], "5.8": ["20250101"]}, 12),   # 경계 정확히
    (["1.1", "5.8"], {"1.1": ["20240101"], "5.8": ["20250102"]}, 12),   # 하루 초과
    (["3.1", "5.7"], {"3.1": ["20240101", "20250301"],
                      "5.7": ["20250401"]}, 12),                        # 동수 → 늦은 창
    (["a", "b", "c"], {"a": ["20240101"], "b": ["20240201"],
                       "c": ["20240301"]}, 3),
    (["a", "b", "c"], {"a": ["20240101"], "b": ["20240201"]}, 3),       # 하나는 날짜 없음
    (["a", "b"], {}, 12),                                               # 날짜 전무
    (["a"], {"a": []}, 12),                                             # 빈 리스트
    (["x", "y"], {"x": ["20240131"], "y": ["20240229"]}, 1),            # 말일 경계
]


@pytest.fixture(scope="module")
def js_out():
    html = _HTML.read_text(encoding="utf-8")
    src = _cut(html, "windowEnd") + "\n" + _cut(html, "bestWindow")
    grid = [[s, m] for s, m in itertools.product(STARTS, MONTHS)]
    scen = [[list(seq), dates, months] for seq, dates, months in SCENARIOS]
    js = (
        src + "\n"
        + "const GRID = " + json.dumps(grid) + ";\n"
        + "const SCEN = " + json.dumps(scen, ensure_ascii=False) + ";\n"
        + "console.log(JSON.stringify({\n"
        + "  ends: GRID.map(([s, m]) => windowEnd(s, m)),\n"
        # 뷰어는 객체({matched,start,end})를, core는 튜플을 돌려준다 —
        # JS 관용 표현 차이라 값만 맞으면 된다.
        + "  wins: SCEN.map(([seq, d, m]) => {\n"
        + "    const r = bestWindow(seq, d, m);\n"
        + "    return [Array.from(r.matched).sort(), r.start, r.end];\n"
        + "  }),\n"
        + "}));\n"
    )
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(js)
    tf.close()
    try:
        r = subprocess.run([shutil.which("node"), tf.name],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, "node 실패:\n" + (r.stderr or "")[:2000]
        return json.loads(r.stdout)
    finally:
        os.unlink(tf.name)


def test_창_종료일이_전수에서_일치한다(js_out):
    grid = list(itertools.product(STARTS, MONTHS))
    mismatch = [
        (s, m, _window_end(s, m), got)
        for (s, m), got in zip(grid, js_out["ends"])
        if _window_end(s, m) != got
    ]
    assert not mismatch, f"{len(mismatch)}건 불일치: {mismatch[:5]}"
    assert len(grid) >= 150, "격자가 너무 작다"


def test_말일_오버플로가_그_달_마지막_날로_잘린다():
    assert _window_end("20240131", 1) == "20240229"   # 윤년 2월
    assert _window_end("20250131", 1) == "20250228"   # 평년 2월
    assert _window_end("20240131", 3) == "20240430"   # 30일 달
    assert _window_end("20241231", 2) == "20250228"   # 해를 넘김


def test_윤년_규칙이_400년_예외까지_맞다():
    assert _window_end("20000131", 1) == "20000229"   # 400의 배수 → 윤년
    assert _window_end("21000131", 1) == "21000228"   # 100의 배수 → 평년


def test_최적_창이_전수에서_일치한다(js_out):
    for (seq, dates, months), got in zip(SCENARIOS, js_out["wins"]):
        matched, ws, we = _best_window(set(seq), dates, months)
        assert sorted(matched) == got[0], (seq, dates, months)
        assert ws == got[1] and we == got[2], (seq, dates, months, got)


def test_창_경계는_포함이다():
    """[d, d+months] 양끝을 포함한다 — 하루 차이로 사례가 빠지면 안 된다."""
    inc, _, _ = _best_window({"a", "b"},
                             {"a": ["20240101"], "b": ["20250101"]}, 12)
    assert inc == {"a", "b"}
    # 하루 초과하면 둘이 한 창에 못 들어온다. 이때 담기는 개수가 1로 같으므로
    # 늦은 창(b)이 선택된다 — 아래 동수 규칙과 같은 동작이다.
    exc, ws, _ = _best_window({"a", "b"},
                              {"a": ["20240101"], "b": ["20250102"]}, 12)
    assert len(exc) == 1 and exc == {"b"} and ws == "20250102"


def test_동수면_늦은_창을_고른다():
    """관측 도구라 같은 겹침이면 최근 것이 유용하다 — 결정적이어야 한다."""
    matched, ws, we = _best_window(
        {"3.1", "5.7"},
        {"3.1": ["20240101", "20250301"], "5.7": ["20250401"]}, 12)
    assert matched == {"3.1", "5.7"}
    assert ws == "20250301", "이른 창이 아니라 늦은 창"
