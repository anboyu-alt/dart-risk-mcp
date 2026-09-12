"""사용자에게 보이는 문장에 내부 severity 토큰이 섞이지 않는다.

v0.8.5: 기업 위험도를 정량화하거나 등급으로 부여하는 표기는 사용자 출력에
노출되면 안 된다. 내부에서는 `severity`·`base_score`로 정렬하되 렌더 경로로
유출되면 안 된다.

2026-08-23 카탈로그 감사에서 **실제 유출**을 찾았다.

    taxonomy 3.7 정의:
    "…흔한 자금 조달 방식이라 이 신호 하나만으로는 판단 근거가 되지 않아
     참고 수준(MEDIUM)으로 다룹니다."

라이브 확인: 인카금융서비스 `analyze_company_risk` 1년 출력에 그대로 찍혔다
(카탈로그 발췌 경로). 「참고 강도」로 고쳤다 — 이 레포가 다른 곳에서 이미
쓰는 표현이다.

**왜 기존 검사가 못 잡았나.** `test_golden_output_hygiene`의
`test_no_unknown_internal_code_parens`는 `(MEDIUM)`을 미등록 영문 코드로
잡을 수 있다. 그런데 **그 문장이 담긴 골든이 없었다** — 골든은 6개 회사
표본이고 STAKE_PLEDGE + 카탈로그 발췌가 함께 나오는 회사가 그 안에 없었다.
골든 기반 검사는 **표본이 닿지 않는 곳을 보지 못한다**.

그래서 이 테스트는 출력이 아니라 **원천 문자열**을 직접 훑는다.
"""
import pathlib
import re

import pytest

from dart_risk_mcp.core import explain, signals, taxonomy
from dart_risk_mcp.core.catalog import load_catalog_excerpt

_TOKENS = re.compile(r"\b(CRITICAL|HIGH|MEDIUM|LOW|base_score|confidence)\b")

# severity·base_score 필드 자체는 내부값이라 대상이 아니다 — 문제는 **한글
# 서술 문장**에 그 토큰이 섞이는 것이다.
_SKIP_FIELDS = ("severity", "base_score", "confidence")


def _strings(obj, path=""):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")


def _leaks(root, label):
    out = []
    for path, s in _strings(root, label):
        if any(f".{f}" in path for f in _SKIP_FIELDS):
            continue
        if not re.search(r"[가-힣]", s):
            continue          # 한글 서술만 — 영문 name 필드는 사용자 노출 아님
        m = _TOKENS.search(s)
        if m:
            out.append(f"{path}: …{s[max(0, m.start() - 30):m.start() + 20]}…")
    return out


def test_taxonomy_서술에_severity_토큰이_없다():
    assert not _leaks(taxonomy.TAXONOMY, "TAXONOMY")


def test_패턴_서술에_severity_토큰이_없다():
    assert not _leaks(taxonomy.CROSS_SIGNAL_PATTERNS, "CROSS_SIGNAL_PATTERNS")


@pytest.mark.parametrize("name", ["FLAG_PROSE", "SIGNAL_PROSE",
                                  "PATTERN_PROSE", "CATEGORY_PROSE",
                                  "GLOSSARY", "METRIC_PROSE"])
def test_해설에_severity_토큰이_없다(name):
    obj = getattr(explain, name, None)
    if obj is None:
        pytest.skip(f"{name} 없음")
    assert not _leaks(obj, name)


def test_신호_라벨에_severity_토큰이_없다():
    bad = [s["key"] for s in signals.SIGNAL_TYPES
           if _TOKENS.search(s.get("label", ""))]
    assert not bad


def test_카탈로그_발췌에_severity_토큰이_없다():
    """사용자 출력 경로 그 자체 — 발췌는 리포트에 그대로 들어간다."""
    bad = []
    for tid in taxonomy.TAXONOMY:
        ex = load_catalog_excerpt([tid]) or ""
        m = _TOKENS.search(ex)
        if m:
            bad.append(f"{tid}: …{ex[max(0, m.start() - 30):m.start() + 20]}…")
    assert not bad


def test_검사가_실제로_잡는지():
    """규칙이 죽어 있으면 위 테스트가 조용히 통과한다 — 그 구멍을 막는다."""
    assert _leaks({"x": {"description": "참고 수준(MEDIUM)으로 다룹니다"}}, "T")
    assert not _leaks({"x": {"description": "참고 강도로 다룹니다"}}, "T")
    # severity 필드 자체는 걸리면 안 된다(내부값)
    assert not _leaks({"x": {"severity": "MEDIUM", "description": "정상 문장"}}, "T")


# ── 뷰어(docs/tool/index.html) ────────────────────────────────────────────
# 2026-09-13: 이 파일은 core의 `explain`/`signals`/`taxonomy`만 훑고 **뷰어는
# 한 번도 보지 않았다**. 그런데 사용자가 보는 것은 뷰어다(CLAUDE.md가 여러 번
# 적은 드리프트 방향). core를 이식할 때 core 쪽 MCP 산문(「가능성 검토 권장」·
# 「전조 가능성」)을 그대로 옮기면 뷰어에만 판정 어휘가 남는다.
#
# ⚠ 「위험」 낱말 자체는 금지하지 않는다 — 이 도구가 하는 일이 위험 신호
#   모니터링이고, 「위험 신호」·「불공정거래 위험」은 정상 표현이다. 금지하는
#   것은 **회사에 등급·점수를 매기는 표기**다.

_VIEWER = pathlib.Path(__file__).parent.parent / "docs" / "tool" / "index.html"

# 한글이 섞인 문자열 리터럴만 본다 — CSS 변수(`--c7`)·코드 식별자는 대상이 아니다.
_KO_STR = re.compile(r"[\"'`]([^\"'`\n]*[가-힣][^\"'`\n]*)[\"'`]")

_GRADE_WORDS = (
    "매우위험", "매우 위험", "고위험", "중위험", "저위험",
    "위험등급", "위험 등급", "위험도 점수", "위험 점수", "위험점수",
    "종합 점수", "안전 등급",
)


def test_뷰어_한글_문장에_severity_토큰이_없다():
    src = _VIEWER.read_text(encoding="utf-8")
    bad = [s for s in _KO_STR.findall(src) if _TOKENS.search(s)]
    assert not bad, (
        "뷰어의 한글 문장에 내부 severity 토큰이 섞였다 — 사용자에게 등급으로 "
        "읽힌다(v0.8.5):\n  " + "\n  ".join(bad[:10])
    )


def test_뷰어에_등급_어휘가_없다():
    src = _VIEWER.read_text(encoding="utf-8")
    bad = []
    for s in _KO_STR.findall(src):
        for w in _GRADE_WORDS:
            if w in s:
                bad.append(f"{w!r} ← {s[:80]}")
    assert not bad, (
        "뷰어에 회사를 등급·점수로 매기는 표기가 있다(v0.8.5):\n  "
        + "\n  ".join(bad[:10])
    )
