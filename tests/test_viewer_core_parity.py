"""core(Python) ↔ 뷰어(JS) 한정층 동등성 — 실측 코퍼스 전수 대조.

`tests/se/test_se_app_js.py`도 index.html에서 함수를 잘라 node로 돌려 비교하지만
픽스처 몇 개만 본다. 여기서는 실측 코퍼스의 **신호가 붙는 고유 제목 전부**를
양쪽에 통과시켜 (key, label, tier, reason, note) 다섯 값이 완전히 같은지 본다.

두 레이어는 규칙 문자열을 signals-data.json으로 공유하지만 **로직은 각자 이식**
이라 드리프트가 생길 수 있다. 실제로 이번 라운드에 core에만 넣고 뷰어에 빠뜨리기
쉬운 변경이 셋 있었다(R2 국면 상승 예외 · R2b 포장 제목 · 방향 안내 마커 확장).

node가 없으면 건너뛴다(CI에 node가 없을 수 있다).
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from dart_risk_mcp.core.qualifiers import parse_report_name, qualify_signals
from dart_risk_mcp.core.signals import match_signals

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = _ROOT / "docs" / "tool" / "index.html"
_JSON = _ROOT / "docs" / "tool" / "signals-data.json"
_CORPUS = _ROOT / "tests" / "fixtures" / "corpus" / "signal_titles_90d.json"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없어 뷰어 JS를 실행할 수 없다"
)

# 한정층이 의존하는 함수 — 선언 순서대로 잘라 붙인다
_FUNCS = (
    "function foldCorpName(name)",
    "function tailOf(text)",
    "function parseReportName(",
    "function isAmendmentTag(",
    "function isFalseAmendment(",
    "function demotionReason(",
    "function adjustedLabel(",
    "function directionNote(",
    "function qualifySignals(",
    "function matchSignals(",
)


def _cut(html: str, marker: str) -> str:
    """marker로 시작하는 함수를 중괄호 균형으로 잘라낸다."""
    i = html.index(marker)
    b = html.index("{", i)
    depth = 0
    for j in range(b, len(html)):
        if html[j] == "{":
            depth += 1
        elif html[j] == "}":
            depth -= 1
            if depth == 0:
                return html[i:j + 1]
    raise AssertionError(f"중괄호가 맞지 않는다: {marker}")


def _run_viewer(titles):
    html = _HTML.read_text(encoding="utf-8")
    src = "\n".join(_cut(html, f) for f in _FUNCS)
    js = (
        f"const DATA = {_JSON.read_text(encoding='utf-8')};\n"
        'const AMEND_RE = new RegExp(DATA.amendment_pattern);\n'
        'const TIER_OBSERVED = "observed", TIER_PROCEDURAL = "procedural";\n'
        "function qrules() { return (DATA && DATA.qualifier_rules) || {}; }\n"
        f"{src}\n"
        f"const TITLES = {json.dumps(titles, ensure_ascii=False)};\n"
        "const out = {};\n"
        "for (const t of TITLES) {\n"
        "  const sigs = matchSignals(t) || [];\n"
        "  const qs = qualifySignals(sigs, parseReportName(t), {});\n"
        '  out[t] = qs.map(q => [q.key, q.label, q.tier, q.reason || "", q.note || ""]);\n'
        "}\n"
        "console.log(JSON.stringify(out));\n"
    )
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(js)
    tf.close()
    try:
        r = subprocess.run([shutil.which("node"), tf.name],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, f"node 실패:\n{(r.stderr or '')[:2000]}"
        return json.loads(r.stdout)
    finally:
        os.unlink(tf.name)


def _core(title):
    sigs = match_signals(title)
    return sorted(
        (s["key"], q.label, q.tier, q.reason or "", q.note or "")
        for s, q in zip(sigs, qualify_signals(sigs, parse_report_name(title), {}))
    )


class TestParity:
    def test_코퍼스_전수에서_두_레이어가_같은_판정을_낸다(self):
        titles = [t["nm"] for t in
                  json.loads(_CORPUS.read_text(encoding="utf-8"))["titles"]]
        assert len(titles) >= 300, "코퍼스가 너무 작다"
        js = _run_viewer(titles)
        mismatch = []
        for t in titles:
            got = sorted(tuple(x) for x in js.get(t, []))
            if got != _core(t):
                mismatch.append((t, _core(t), got))
        assert not mismatch, (
            f"{len(mismatch)}종이 어긋난다. 첫 3건:\n" +
            "\n".join(f"  {t}\n    core={c}\n    view={v}" for t, c, v in mismatch[:3])
        )

    def test_이번_라운드_변경이_양쪽에_다_들어갔다(self):
        """core에만 넣고 뷰어에 빠뜨리기 쉬운 변경 3종을 콕 집어 확인한다."""
        cases = [
            # R2 국면 상승 예외
            "주권매매거래정지해제 (상장폐지에 따른 정리매매 개시)",
            # R2b 포장 제목
            "기타주요경영사항(제3자배정유상증자결정철회)",
            # 방향 안내 마커 확장
            "주요사항보고서(자기전환사채만기전취득결정)",
            "교환사채(해외교환사채포함)발행후만기전사채취득",
            "주식소각결정(상환전환우선주)",
        ]
        js = _run_viewer(cases)
        for t in cases:
            assert sorted(tuple(x) for x in js.get(t, [])) == _core(t), t
