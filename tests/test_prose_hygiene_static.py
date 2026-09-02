"""원천 문구에 hygiene 검사기를 **직접** 건다(골든을 거치지 않고).

`tests/test_golden_output_hygiene.py`는 `tests/fixtures/sample_outputs/*.txt`를
훑는다 — 그 골든은 실 API 호출로만 재생성되므로, 해설 문구를 고친 직후에는
「이 문구가 골든 hygiene을 통과할지」를 알 수 없다. 이 파일은 같은 검사기를
**원천 dict에 그대로** 적용해 그 시차를 없앤다.

검사기는 복제하지 않고 import한다 — 복제하면 한쪽만 갱신돼 조용히 갈린다
(CLAUDE.md의 core↔뷰어 쌍둥이 드리프트와 같은 부류).

대상: `SIGNAL_PROSE` · `PATTERN_PROSE` · `PATTERN_CHECKPOINTS` ·
`CROSS_SIGNAL_PATTERNS[*]["description"]` · `GLOSSARY`(표제어·풀이).
"""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from test_golden_output_hygiene import (  # noqa: E402
    _ALLOWED_PAREN_ABBREVS,
    _INTERNAL_CODES,
    _SCORE_GRADE_PATTERNS,
    _SEVERITY_EMOJI,
)

from dart_risk_mcp.core.explain import (  # noqa: E402
    GLOSSARY,
    PATTERN_CHECKPOINTS,
    PATTERN_PROSE,
    SIGNAL_PROSE,
)
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS  # noqa: E402

_PAREN_CODE_RE = re.compile(r"\(([A-Z][A-Z_]{1,30})\)")


def _sources() -> list[tuple[str, str]]:
    """(어디, 문자열) 목록 — 사용자 화면에 그대로 나가는 원천 문구."""
    out: list[tuple[str, str]] = []
    for key, text in SIGNAL_PROSE.items():
        out.append((f"SIGNAL_PROSE[{key}]", text))
    for pid, text in PATTERN_PROSE.items():
        out.append((f"PATTERN_PROSE[{pid}]", text))
    for pid, bullets in PATTERN_CHECKPOINTS.items():
        for i, b in enumerate(bullets):
            out.append((f"PATTERN_CHECKPOINTS[{pid}][{i}]", b))
    for pid, pat in CROSS_SIGNAL_PATTERNS.items():
        out.append((f"CROSS_SIGNAL_PATTERNS[{pid}].description",
                    pat.get("description", "")))
    for term, prose in GLOSSARY.items():
        out.append((f"GLOSSARY[{term}] 표제어", term))
        out.append((f"GLOSSARY[{term}]", prose))
    return out


_SOURCES = _sources()
_IDS = [where for where, _ in _SOURCES]


@pytest.mark.parametrize("where,text", _SOURCES, ids=_IDS)
def test_점수_등급_표기가_없다(where, text):
    """v0.8.5 — 기업 위험도를 정량화하거나 등급으로 부여하지 않는다."""
    for pattern, desc in _SCORE_GRADE_PATTERNS:
        m = re.search(pattern, text)
        assert m is None, f"{where}: {desc} — '{m.group(0)}'"


@pytest.mark.parametrize("where,text", _SOURCES, ids=_IDS)
def test_등급_이모지가_없다(where, text):
    for emoji in _SEVERITY_EMOJI:
        assert emoji not in text, f"{where}: 등급 이모지 {emoji}"


@pytest.mark.parametrize("where,text", _SOURCES, ids=_IDS)
def test_내부_flag_코드가_없다(where, text):
    for code in _INTERNAL_CODES:
        assert code not in text, f"{where}: 내부 flag 코드 {code}"


@pytest.mark.parametrize("where,text", _SOURCES, ids=_IDS)
def test_미등록_영문_코드를_괄호로_인용하지_않는다(where, text):
    for code in _PAREN_CODE_RE.findall(text):
        assert code in _ALLOWED_PAREN_ABBREVS, (
            f"{where}: 괄호 인용 '({code})' — 한국어 라벨로 바꾸거나 "
            "_ALLOWED_PAREN_ABBREVS를 검토하세요"
        )


@pytest.mark.parametrize("where,text", _SOURCES, ids=_IDS)
def test_서술형_단정을_쓰지_않는다(where, text):
    """무판정 원칙은 낱말뿐 아니라 문장에도 걸린다 — 「위험합니다」류."""
    for word in ("위험합니다", "의심됩니다", "나쁩니다", "위험한 기업",
                 "안전합니다", "양호합니다"):
        assert word not in text, f"{where}: 단정 표현 '{word}'"
