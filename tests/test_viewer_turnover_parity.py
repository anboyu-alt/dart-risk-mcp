"""core `compute_turnover_metrics` ↔ 뷰어 `computeTurnoverMetrics` 쌍둥이 대조.

뷰어(`docs/tool/index.html`)의 TURNOVER TREND 블록은 core
`dart_client.compute_turnover_metrics`/`_pick_account`의 JS 이식본이다.
이식은 로직이 조용히 갈리기 쉽다는 것이 이 리포지토리에서 여러 번 실물로
나왔다(`tests/test_viewer_twin_parity.py` 참고 — `parseOutflowDetail`의
자기자본대비 누락, `pickHeadline`의 indexOf -1 버그). 같은 입력 dict를
core와 뷰어 양쪽에 먹여 회전율 5종(value·basis·reason)과 CCC를 대조한다.

harness는 `test_viewer_twin_parity.py`의 `_cut`(중괄호 균형 파서)·
`_cut_decl`·node 실행 방식을 그대로 재사용한다(같은 파일에서 import하지
않고 복제한 이유: 그쪽 파일은 자기 완결형 모듈 스크립트라 공유 유틸을
따로 빼지 않고 있다 — 다른 쌍둥이 테스트들과 같은 패턴).
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

from dart_risk_mcp.core.dart_client import compute_turnover_metrics

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = _ROOT / "docs" / "tool" / "index.html"
_JSON = _ROOT / "docs" / "tool" / "signals-data.json"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없으면 뷰어 쪽을 돌릴 수 없다"
)


def _cut(html: str, head: str) -> str:
    """`head`로 시작하는 함수/상수 선언 하나를 중괄호 균형으로 잘라 온다."""
    i = html.index(head)
    depth, j, in_s, q = 0, i, False, ""
    while j < len(html):
        c = html[j]
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
                return html[i:j + 1]
        j += 1
    raise AssertionError(f"뷰어에서 {head!r}의 끝을 찾지 못했다")


def _cut_decl(html: str, name: str) -> "str | None":
    """`const NAME = …;` 선언 하나를 잘라 온다. 한 줄이면 그 줄, 아니면 중괄호 균형."""
    m = re.search(r"^(?:const|let|var)\s+" + re.escape(name) + r"\s*=", html, re.M)
    if not m:
        return None
    i = m.start()
    eol = html.index("\n", i)
    line = html[i:eol]
    if line.rstrip().endswith(";") and line.count("{") == line.count("}"):
        return line
    return _cut(html, html[i:m.end()])


_FUNCS = ("function computeTurnoverMetrics(", "function pickAccountByAliases(",
          "function turnoverYoyPct(")


def _node(code: str):
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(code)
    tf.close()
    try:
        return subprocess.run([shutil.which("node"), tf.name],
                              capture_output=True, text=True, encoding="utf-8")
    finally:
        os.unlink(tf.name)


def _viewer(calls: list) -> list:
    """`[[period, prior], ...]`를 뷰어 `computeTurnoverMetrics`로 돌려 결과 배열을 받는다."""
    html = _HTML.read_text(encoding="utf-8")
    src = "\n".join(_cut(html, f) for f in _FUNCS)
    js = (
        f"const DATA = {_JSON.read_text(encoding='utf-8')};\n"
        f"{src}\n"
        f"const CALLS = {json.dumps(calls, ensure_ascii=False)};\n"
        "const out = CALLS.map(([period, prior]) => computeTurnoverMetrics(period, prior));\n"
        "console.log(JSON.stringify(out));\n"
    )
    pre = ""
    for _ in range(24):
        r = _node(pre + js)
        if r.returncode == 0:
            return json.loads(r.stdout)
        m = re.search(r"ReferenceError: (\w+) is not defined", r.stderr or "")
        if not m:
            raise AssertionError(f"node 실패:\n{(r.stderr or '')[:1500]}")
        d = _cut_decl(html, m.group(1))
        assert d is not None, (
            f"뷰어에서 {m.group(1)} 선언을 찾지 못했다 — 이식본이 함수 밖의 "
            "무언가에 기대고 있다"
        )
        pre = d + "\n" + pre
    raise AssertionError("보조 선언을 24번 끌어와도 안 돈다")


# core metric 키 → 뷰어(camelCase) metric 키.
_METRIC_KEYS = {
    "receivable": "receivable",
    "inventory": "inventory",
    "payable": "payable",
    "working_capital": "workingCapital",
    "asset": "asset",
}


def _approx_eq(a, b, tol=1e-6):
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) < tol


def _assert_metrics_match(core_result: dict, js_result: dict, *, label: str, check_prior: bool = False):
    for ck, jk in _METRIC_KEYS.items():
        cm = core_result["metrics"][ck]
        jm = js_result["metrics"][jk]
        assert _approx_eq(cm.get("value"), jm.get("value")), (
            f"{label}/{ck} value: core={cm.get('value')!r} 뷰어={jm.get('value')!r}"
        )
        assert _approx_eq(cm.get("numerator"), jm.get("numerator")), (
            f"{label}/{ck} numerator: core={cm.get('numerator')!r} 뷰어={jm.get('numerator')!r}"
        )
        assert _approx_eq(cm.get("denominator"), jm.get("denominator")), (
            f"{label}/{ck} denominator: core={cm.get('denominator')!r} 뷰어={jm.get('denominator')!r}"
        )
        assert cm.get("basis") == jm.get("basis"), (
            f"{label}/{ck} basis: core={cm.get('basis')!r} 뷰어={jm.get('basis')!r}"
        )
        assert cm.get("reason") == jm.get("reason"), (
            f"{label}/{ck} reason: core={cm.get('reason')!r} 뷰어={jm.get('reason')!r}"
        )
        if check_prior:
            assert _approx_eq(cm.get("prior_value"), jm.get("priorValue")), (
                f"{label}/{ck} prior_value: core={cm.get('prior_value')!r} 뷰어={jm.get('priorValue')!r}"
            )
            assert _approx_eq(cm.get("yoy_pct"), jm.get("yoyPct")), (
                f"{label}/{ck} yoy_pct: core={cm.get('yoy_pct')!r} 뷰어={jm.get('yoyPct')!r}"
            )
            assert _approx_eq(cm.get("numerator_yoy_pct"), jm.get("numeratorYoyPct")), (
                f"{label}/{ck} numerator_yoy_pct"
            )
            assert _approx_eq(cm.get("denominator_yoy_pct"), jm.get("denominatorYoyPct")), (
                f"{label}/{ck} denominator_yoy_pct"
            )

    cc, jc = core_result["ccc"], js_result["ccc"]
    for k in ("dso", "dio", "dpo", "value"):
        assert _approx_eq(cc.get(k), jc.get(k)), f"{label}/ccc.{k}: core={cc.get(k)!r} 뷰어={jc.get(k)!r}"
    assert cc.get("reason") == jc.get("reason"), f"{label}/ccc.reason: core={cc.get('reason')!r} 뷰어={jc.get('reason')!r}"

    assert _approx_eq(core_result.get("working_capital"), js_result.get("workingCapital")), (
        f"{label}/working_capital: core={core_result.get('working_capital')!r} 뷰어={js_result.get('workingCapital')!r}"
    )


# ── 케이스 ────────────────────────────────────────────────────────────────

_NORMAL = {
    "매출액": 1_000_000_000,
    "매출원가": 600_000_000,
    "매출채권": 200_000_000,
    "재고자산": 150_000_000,
    "매입채무": 100_000_000,
    "유동자산": 500_000_000,
    "유동부채": 300_000_000,
    "자산총계": 2_000_000_000,
}

_COGS_MISSING = {k: v for k, v in _NORMAL.items() if k != "매출원가"}

_COGS_NEGATIVE = {**_NORMAL, "매출원가": -600_000_000}

_NEGATIVE_DENOMINATOR = {**_NORMAL, "재고자산": -50_000_000}

_ZERO_DENOMINATOR = {**_NORMAL, "매입채무": 0}

_WORKING_CAPITAL_NEGATIVE = {**_NORMAL, "유동자산": 100_000_000, "유동부채": 500_000_000}

# 번호 접두 — 「Ⅱ.매출원가」류(고려아연 실측 서식). 정확 일치로는 전혀
# 못 찾고 접두를 뗀 뒤에만 잡힌다.
_ORDINAL_PREFIX = {
    "매출액": 900_000_000,
    "Ⅱ.매출원가": 500_000_000,
    "매출채권": 180_000_000,
    "재고자산": 120_000_000,
    "매입채무": 90_000_000,
    "Ⅰ.유동자산": 400_000_000,
    "유동부채": 250_000_000,
    "자산총계": 1_800_000_000,
}

# 별칭 변형 — 「유동재고자산」·「매출채권 및 기타수취채권」(이마트류 실측 서식).
_ALIAS_VARIANTS = {
    "매출액": 700_000_000,
    "매출원가": 420_000_000,
    "매출채권 및 기타수취채권": 140_000_000,
    "유동재고자산": 95_000_000,
    "매입채무": 80_000_000,
    "유동자산": 350_000_000,
    "유동부채": 210_000_000,
    "자산총계": 1_500_000_000,
}

_PRIOR = {
    "매출액": 800_000_000,
    "매출원가": 500_000_000,
    "매출채권": 180_000_000,
    "재고자산": 130_000_000,
    "매입채무": 90_000_000,
    "유동자산": 420_000_000,
    "유동부채": 280_000_000,
    "자산총계": 1_700_000_000,
}

# 스팩(기업인수목적회사)은 영업이 없어 **매출이 0원**이다. 실측:
# 하나금융21호기업인수목적 2023 — 매출 0원, 매출채권 3억, 운전자본 151억.
# 산술로는 0.00회가 나오지만 회전율로 읽히면 "회전이 느리다"로 오해된다.
_ZERO_REVENUE = {
    "매출액": 0,
    "매출원가": 0,
    "매출채권": 300_000_000,
    "재고자산": 100_000_000,
    "매입채무": 50_000_000,
    "유동자산": 16_000_000_000,
    "유동부채": 900_000_000,
    "자산총계": 16_100_000_000,
}

_CASES = [
    ("정상", _NORMAL, None),
    ("매출원가_미노출_폴백", _COGS_MISSING, None),
    ("음수_매출원가", _COGS_NEGATIVE, None),
    ("음수_분모", _NEGATIVE_DENOMINATOR, None),
    ("분모_0", _ZERO_DENOMINATOR, None),
    ("운전자본_음수", _WORKING_CAPITAL_NEGATIVE, None),
    ("번호_접두_폴백", _ORDINAL_PREFIX, None),
    ("별칭_변형", _ALIAS_VARIANTS, None),
    ("매출_0원_스팩", _ZERO_REVENUE, None),
    ("prior_지정_yoy", _NORMAL, _PRIOR),
]


def test_회전율_케이스_전수가_core와_같다():
    calls = [[period, prior] for _, period, prior in _CASES]
    core_results = [compute_turnover_metrics(period, prior=prior) for _, period, prior in _CASES]
    js_results = _viewer(calls)
    assert len(js_results) == len(_CASES)
    for (label, _, prior), core_r, js_r in zip(_CASES, core_results, js_results):
        _assert_metrics_match(core_r, js_r, label=label, check_prior=prior is not None)


def test_케이스가_실제로_갈라지는_값을_담고_있다():
    """음수·0·미노출·접두 케이스가 서로 다른 reason을 내는지 확인 — 케이스
    설계 자체가 아무것도 구분 못 하면 위 테스트가 항상 통과해도 의미 없다."""
    reasons = set()
    for _, period, prior in _CASES:
        r = compute_turnover_metrics(period, prior=prior)
        for m in r["metrics"].values():
            if m.get("reason"):
                reasons.add(m["reason"])
    assert len(reasons) >= 3, f"reason 다양성이 낮다: {reasons}"


def test_음수_매출원가가_basis에_절댓값_사실을_남긴다():
    r = compute_turnover_metrics(_COGS_NEGATIVE)
    assert r["metrics"]["inventory"]["basis"] == "매출원가(음수 보고, 절댓값)"
    assert r["metrics"]["inventory"]["numerator"] == 600_000_000

    js = _viewer([[_COGS_NEGATIVE, None]])[0]
    assert js["metrics"]["inventory"]["basis"] == "매출원가(음수 보고, 절댓값)"
    assert js["metrics"]["inventory"]["numerator"] == 600_000_000


def test_매출이_0원이면_회전율을_내지_않는다():
    """스팩·개발단계 회사 — 「0.00회」는 값이 아니라 오해다.

    실측(하나금융21호기업인수목적 2023): 표에는 「0.00회」가 찍히는데 CCC 사유는
    「매출채권회전율이 없어」라고 말해 **화면이 자기모순**이었다. 운전자본
    회전율은 `_simple_metric`을 거치지 않는 별도 분기라 그 한 줄만 따로 남았다.
    """
    r = compute_turnover_metrics(_ZERO_REVENUE)
    js = _viewer([[_ZERO_REVENUE, None]])[0]
    for key in ("receivable", "asset", "working_capital"):
        assert r["metrics"][key]["value"] is None, key
        assert "0원" in r["metrics"][key]["reason"], key
    # 뷰어는 camelCase 키를 쓴다
    for key in ("receivable", "asset", "workingCapital"):
        assert js["metrics"][key]["value"] is None, key
        assert "0원" in js["metrics"][key]["reason"], key
    assert r["ccc"]["value"] is None
