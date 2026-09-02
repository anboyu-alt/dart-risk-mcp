"""뷰어 상세 화면의 해설이 방향 안내를 함께 내는지 잠근다.

#307이 core 쪽 소비처(`qualify_signals` 호출부 넷)를 전수로 닫은 뒤,
**같은 sweep을 뷰어에 적용해** 찾았다(2026-08-25). 뷰어는 손으로 이식한
쌍둥이라 같은 종류가 남아 있었다.

    function renderWhyRow(s, rcept) {
      const p = `<p><b>${s.label}</b> — ${s.prose}</p>`;   ← note가 없다
      ...

`s.note`는 넘어오는데 렌더가 버렸다. 결과가 특히 나쁘다 — CB/BW 해설이
**"방향은 제목과 함께 표시되는 안내에서 확인하세요"**라고 적는데 **그 안내가
화면에 없다.** 해설이 자기를 배신한다.

    CB/BW발행 — 전환사채·신주인수권부사채 관련 공시입니다. 발행만 들어오지
    않습니다 — … 방향은 제목과 함께 표시되는 안내에서 확인하세요. …
    (안내 없음)

core의 세 소비처는 모두 이 줄을 낸다(`analyze_company_risk` ·
`build_event_timeline` #305 · `search_market_disclosures` #307).

⚠ **소스 문자열 검색으로 확인하지 않는다.** 이번 세션에서 그 방법이 주석·
docstring 자기참조로 이미 한 번 실패했다(#301). node로 **실제 렌더 결과**를
만들어 본다.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
_NODE = shutil.which("node")

_ESC = (
    'function esc(s){return String(s==null?"":s)'
    '.replace(/[&<>"\']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'
    '"\\"":"&quot;","\'":"&#39;"}[c]));}'
)


def _extract(name):
    m = re.search(r"^function " + name + r"\(.*?\n\}", _HTML, re.M | re.S)
    assert m, f"{name}을 찾지 못했다"
    return m.group(0)


# `isSoftenedSig`가 원본 라벨을 찾으려 `DATA.signals`를 읽는다 — 최소 형태로 준다.
_DATA = {"signals": [{"key": "CB_BW", "label": "CB/BW발행"},
                     {"key": "3PCA", "label": "제3자배정유상증자"}]}


def _run(expr, data=None):
    # PR-V(뷰어 「지표 읽는 법」 일반화)로 renderWhyRow의 s.prose가
    # esc(...) 대신 proseTextHTML(...)(esc → boldMarksHTML → glossTermsHTML)을
    # 거치게 됐다 — 그 세 함수도 함께 끌어와야 한다. DATA에 glossary가
    # 없어도 proseTextHTML은 `typeof DATA !== "undefined" && DATA && ...`로
    # 안전하게 빈 사전으로 떨어진다.
    src = "\n".join([_ESC, _extract("isSoftenedSig"), _extract("renderWhyRow"),
                      _extract("proseTextHTML"), _extract("boldMarksHTML"),
                      _extract("glossTermsHTML")])
    payload = json.dumps(data if data is not None else _DATA, ensure_ascii=False)
    script = (f"const DATA = {payload};\n{src}\n"
              f"process.stdout.write(String({expr}));")
    out = subprocess.run([_NODE, "-e", script], capture_output=True, text=True,
                         encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return out.stdout


_SIG = {"key": "CB_BW", "label": "CB/BW발행", "category": 1,
        "prose": "전환사채 관련 공시입니다.", "taxonomies": ["1.1"]}


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 렌더를 실행할 수 없습니다")
def test_안내가_있으면_렌더된다():
    sig = dict(_SIG, note="발행이 아니라 사채 취득·매도·소각 건입니다")
    html = _run(f"renderWhyRow({json.dumps(sig, ensure_ascii=False)}, 'R1')")
    assert "※ 발행이 아니라 사채 취득·매도·소각 건입니다" in html


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 렌더를 실행할 수 없습니다")
def test_안내가_없으면_빈_줄을_넣지_않는다():
    html = _run(f"renderWhyRow({json.dumps(_SIG, ensure_ascii=False)}, 'R1')")
    assert "※" not in html


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 렌더를 실행할 수 없습니다")
def test_공백만_있는_안내도_넣지_않는다():
    sig = dict(_SIG, note="   ")
    assert "※" not in _run(f"renderWhyRow({json.dumps(sig, ensure_ascii=False)}, 'R1')")


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 렌더를 실행할 수 없습니다")
def test_해설과_안내가_모두_남는다():
    sig = dict(_SIG, note="발행이 아니라 사채 취득·매도·소각 건입니다")
    html = _run(f"renderWhyRow({json.dumps(sig, ensure_ascii=False)}, 'R1')")
    assert "전환사채 관련 공시입니다." in html
    assert html.index("전환사채 관련") < html.index("※"), "안내가 해설보다 앞에 온다"


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 렌더를 실행할 수 없습니다")
def test_원문_확인_버튼과_공존한다():
    """`3PCA`처럼 라벨이 보정된 신호는 버튼이 붙는다 — 안내가 그걸 지우면 안 된다."""
    sig = {"key": "3PCA", "label": "유상증자(배정방식 미상)", "category": 2,
           "prose": "유상증자 공시입니다.", "taxonomies": ["2.4"],
           "note": "테스트 안내"}
    html = _run(f"renderWhyRow({json.dumps(sig, ensure_ascii=False)}, 'R1')")
    assert "※ 테스트 안내" in html
    assert "원문 확인" in html, "보정 라벨 신호의 확인 버튼이 사라졌다"


def test_해설이_안내를_가리킨다는_전제():
    """이 수정이 필요한 이유 — 해설이 '함께 표시되는 안내'를 지시한다."""
    from dart_risk_mcp.core.explain import SIGNAL_PROSE

    assert "안내에서 확인" in SIGNAL_PROSE["CB_BW"]


def test_core_세_소비처는_이미_낸다():
    """뷰어만 빠져 있었다는 사실을 고정한다."""
    src = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    assert len(re.findall(r"※ \{(?:_note|q\.note|note)\}", src)) >= 3
