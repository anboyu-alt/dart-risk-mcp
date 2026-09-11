"""공시 원문 열람(docViewer)이 **조용히 빈 패널**로 끝나지 않게 한다.

제보(2026-09-11): 「원문 이 화면에서 보기」를 눌러도 본문이 안 나오고 「DART
원문 열기」로만 볼 수 있다. 서버는 멀쩡했다 — 프로덕션 `/api/doc`에 같은
공시 5건을 직접 호출하니 전부 200 + 2,400~3,824자였다.

라이브 재현으로 잡은 원인은 **`matchedKeywordsFor`의 TypeError**였다:

    TypeError: s.keywords is not iterable
      at matchedKeywordsFor → renderDocViewer → toggleDocViewer

`r.signals`는 `matchSignals`가 돌려준 `DATA.signals` 원본이 아니라 한정층
(`qualifySignals`)이 만든 객체다. 거기에는 `keywords`가 **없다**(실측 코아스
1년: 신호 객체 63개 전부). 예외가 렌더를 중단시키고, `toggleDocViewer`에는
try/catch가 없어 패널이 빈 채로 남는다 — 사용자에게는 "원문이 없는 공시"와
똑같이 보인다. 즉 **신호가 붙은 공시에서는 원문 열람이 한 번도 되지 않았다**.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest


_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
_DATA = json.loads(
    (_ROOT / "docs" / "tool" / "signals-data.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없으면 뷰어 쪽을 돌릴 수 없다")


def _fn(name: str) -> str:
    i = _HTML.index(f"function {name}(")
    depth, j, in_s, q = 0, i, False, ""
    while j < len(_HTML):
        c = _HTML[j]
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
                return _HTML[i:j + 1]
        j += 1
    raise AssertionError(name)


def _run(signals: list, report_nm: str):
    src = (f"const DATA = {json.dumps(_DATA, ensure_ascii=False)};\n"
           + "let _SIGNAL_KW_BY_KEY = null;\n"
           + _fn("signalKeywordsByKey") + "\n"
           + _fn("matchedKeywordsFor") + "\n"
           + f"const R = {{ nm: {json.dumps(report_nm, ensure_ascii=False)},"
             f" signals: {json.dumps(signals, ensure_ascii=False)} }};\n"
           + "console.log(JSON.stringify(matchedKeywordsFor(R)));\n")
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(src)
    tf.close()
    try:
        r = subprocess.run([shutil.which("node"), tf.name],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, f"node 실패:\n{(r.stderr or '')[:800]}"
        return json.loads(r.stdout)
    finally:
        os.unlink(tf.name)


def test_한정층_객체에는_keywords가_없다():
    """전제를 못 박는다 — 이게 아니면 아래 테스트가 헛돈다."""
    q = _fn("qualifySignals")
    assert "keywords" not in q, (
        "한정층이 keywords를 싣기 시작했다면 이 파일의 전제를 다시 재라")


def test_keywords가_없어도_키워드를_되찾는다():
    sig = {"key": "CB_BW", "label": "CB/BW발행", "tier": "observed"}
    kws = _run([sig], "주요사항보고서(전환사채권발행결정)")
    assert kws, "한정층 객체에서 키워드를 못 찾으면 원문 강조가 죽는다"
    assert any(k in "주요사항보고서(전환사채권발행결정)" for k in kws)


def test_모르는_키도_던지지_않는다():
    assert _run([{"key": "NOT_A_REAL_KEY"}], "아무 제목") == []
    assert _run([{}], "아무 제목") == []


def test_원본_객체도_그대로_동작한다():
    """`matchSignals` 원본(keywords 있음) 경로가 깨지지 않았는지."""
    cb = next(s for s in _DATA["signals"] if s["key"] == "CB_BW")
    kws = _run([cb], "주요사항보고서(전환사채권발행결정)")
    assert kws


def test_원문_렌더_실패가_조용하지_않다():
    """예외·빈 본문이 같은 빈 패널로 뭉개지지 않게 한다."""
    assert "function docRenderFailed(" in _HTML
    toggle = _fn("toggleDocViewer")
    assert toggle.count("docRenderFailed") == 2, (
        "캐시 경로와 fetch 경로 **둘 다** 보호해야 한다 — 실제로 죽던 쪽은 캐시다")
    render = _fn("renderDocViewer")
    assert "blocks.length" in render and "블록 0개" in render, (
        "200을 받고도 그릴 것이 없으면 그 사실을 적어야 한다")


def test_조회_실패에_HTTP_상태를_남긴다():
    fetch = _fn("fetchDisclosureText")
    assert re.search(r"\$\{j\.error\}\s*\(HTTP \$\{res\.status\}\)", fetch), (
        "서버는 400/404/502를 구분해 주는데 화면이 그것을 지우면 안 된다")
