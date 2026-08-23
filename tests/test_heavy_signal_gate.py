"""뷰어의 「가장 무거운 유형」 표시가 방향 미상 신호까지 삼키지 않는지 잠근다.

**사용자 제보(2026-08-24)** — 오성첨단소재(052420) 1년 스캔 화면:

    ▍WATCH
    시장감시·위기/부실 카테고리 공시 1건 관찰
    — 거래정지·상장폐지 관련·횡령 등 가장 무거운 유형입니다.
      • 2026.02.26 · 매출액또는손익구조30%(대규모법인은15%)이상변동

그 공시(20260226900516)는 실적이 **개선**됐다는 내용이었다.

원인은 판정 기준이 `category >= 7` 하나였던 것이다. 그 카테고리에는 제목만으로
정상/이상이 갈리지 않는 신호도 들어 있다 — `EARNINGS_SHOCK`은 score 0 ·
severity OBSERVATION이고, 해설 자체가 "늘어난 경우와 줄어든 경우가 모두
들어온다"고 적는다.

**1년 코퍼스 실측**: 이 기준에 걸리던 4,000건 중 **2,251건(56%)이
EARNINGS_SHOCK 하나**였다. 절반이 넘으면 '무거운 유형' 표시가 아니라 기본값이다.

v1.15.0이 severity와 분리해 만든 `priority` 축이 정확히 이 질문을 담당한다.
core는 이미 `AMBIGUOUS_SIGNAL_KEYS`로 헤드라인 승격을 막고 있었고, **뷰어만
샜다** — 같은 판단이 두 레이어에서 갈린 또 하나의 사례.
"""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

from dart_risk_mcp.core.qualifiers import (
    TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import AMBIGUOUS_SIGNAL_KEYS, match_signals

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = _ROOT / "docs" / "tool" / "index.html"
_DATA = json.loads((_ROOT / "docs" / "tool" / "signals-data.json")
                   .read_text(encoding="utf-8"))
_BY_KEY = {s["key"]: s for s in _DATA["signals"]}

# 제보된 실제 제목
REPORTED = "매출액또는손익구조30%(대규모법인은15%)이상변동"


def test_제보된_공시가_신호를_내지만_무판정이다():
    """신호 자체는 유지한다 — 사실 표기는 맞다. 문제는 '무거운 유형' 취급이었다."""
    sigs = match_signals(REPORTED)
    keys = {s["key"] for s in sigs}
    assert "EARNINGS_SHOCK" in keys
    assert "EARNINGS_SHOCK" in AMBIGUOUS_SIGNAL_KEYS
    assert _BY_KEY["EARNINGS_SHOCK"]["priority"] == "context"
    quals = qualify_signals(sigs, parse_report_name(REPORTED), {})
    assert any(q.tier == TIER_OBSERVED for q in quals), "관찰 자체는 정상"


def test_방향을_모른다고_해설에_적혀_있다():
    prose = _BY_KEY["EARNINGS_SHOCK"]["prose"]
    assert "늘어난 경우와 줄어든 경우가 모두" in prose


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_판정_함수가_context를_제외한다():
    html = _HTML.read_text(encoding="utf-8")
    m = re.search(r"^function isHeavySignal\(s\) \{\n(?:.*\n)*?\}", html, re.M)
    assert m, "isHeavySignal이 없다"
    cases = [
        ({"category": 8, "priority": "context"}, False),   # EARNINGS_SHOCK
        ({"category": 8, "priority": "first"}, True),      # DELISTING_RISK 등
        ({"category": 7, "priority": "watch"}, True),      # INQUIRY
        ({"category": 7, "priority": "context"}, False),   # THEME_STOCK
        ({"category": 6, "priority": "first"}, False),     # 카테고리 밖
        (None, False),
    ]
    js = (m.group(0) + "\nconsole.log(JSON.stringify("
          + json.dumps([c[0] for c in cases]) + ".map(isHeavySignal)));\n")
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(js)
    tf.close()
    try:
        r = subprocess.run([shutil.which("node"), tf.name],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr[:800]
        got = json.loads(r.stdout)
    finally:
        pathlib.Path(tf.name).unlink()
    assert got == [bool(c[1]) for c in cases], got


def test_네_지점이_모두_같은_함수를_쓴다():
    """배너·상세 테두리·경고 콜아웃·타임라인 강조점이 갈리면 안 된다."""
    html = _HTML.read_text(encoding="utf-8")
    # 판정 자리에 날 `category >= 7`이 남아 있으면 안 된다(함수 정의·주석 제외)
    for i, line in enumerate(html.splitlines(), 1):
        if ("category >= 7" in line and "isHeavySignal" not in line
                and 'priority !== "context"' not in line
                and not line.strip().startswith("//")):
            pytest.fail(f"{i}행에 날 기준이 남아 있다: {line.strip()[:90]}")
    assert html.count("isHeavySignal") >= 5, "네 지점 + 정의"


def test_core는_이미_막고_있었다():
    """뷰어만 샜다는 사실을 고정 — 같은 판단이 두 레이어에서 갈리지 않게."""
    from dart_risk_mcp.core.qualifiers import pick_headline

    sigs = match_signals(REPORTED)
    quals = qualify_signals(sigs, parse_report_name(REPORTED), {})
    assert pick_headline(quals) is None, "core 헤드라인은 이 신호를 승격하지 않는다"


def test_무거운_유형_표시가_기본값이_아니다():
    """1년 코퍼스에서 이 표시가 붙는 비율 — 절반을 넘으면 표시가 아니라 기본값이다."""
    corpus = json.loads(
        (_ROOT / "tests" / "fixtures" / "corpus" / "signal_titles_365d.json")
        .read_text(encoding="utf-8"))
    heavy = observed = 0
    for t in corpus["titles"]:
        nm, n = t["nm"], t["n"]
        sigs = match_signals(nm)
        obs = [s for s, q in zip(sigs, qualify_signals(sigs, parse_report_name(nm), {}))
               if q.tier == TIER_OBSERVED]
        if not obs:
            continue
        observed += n
        if any(_BY_KEY.get(s["key"], {}).get("category", 0) >= 7
               and _BY_KEY[s["key"]]["priority"] != "context" for s in obs):
            heavy += n
    assert observed > 0
    ratio = heavy / observed
    assert ratio < 0.20, f"관찰 공시의 {ratio:.1%}에 붙는다 — 변별력을 다시 재세요"
