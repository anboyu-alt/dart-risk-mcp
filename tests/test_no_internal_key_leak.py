"""내부 식별자가 사용자 출력에 그대로 나가지 않는지 **구조로** 잡는다.

2026-08-24, 제보 회사(오성첨단소재 052420) 리포트를 눈으로 읽다 찾았다.

    • 20251218 · [결정:tangible_div] 오성하이테크놀로지(주)

`tangible_div`는 DS005 엔드포인트를 고르는 **내부 키**다. 더 나쁜 것은
같은 누출이 **이미 골든에 있었다**는 점이다 — `아틀라스링크_analyze.txt`의
`[결정:tangible_acq]`. `test_golden_output_hygiene.py`가 있는데도 통과했다.

**왜 못 잡았나**: 그 검사는 손으로 적은 금칙어 목록(`_INTERNAL_CODES`·
`_ENGLISH_ABBR`)을 쓴다. 12종 decision_type이 목록에 없었다. #241에서
같은 교훈을 적었다 — "금칙어 목록을 손으로 지으면 이런 구멍이 생긴다".

그래서 이 파일은 **목록이 아니라 모양**을 본다: 대괄호 라벨 안에 라틴
문자로 된 snake_case 식별자가 있으면 걸린다. 새 내부 키가 어떤 이름으로
새든 잡힌다.
"""
import pathlib
import re

import pytest

from dart_risk_mcp.core import decision_type_label_ko
from dart_risk_mcp.core.dart_client import _DECISION_NAME_MAP, _MAJOR_DECISION_URLS

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GOLDEN = _ROOT / "tests" / "fixtures" / "sample_outputs"

# `[결정:tangible_div]` · `[flag:AR_SURGE]` 처럼 대괄호 안의 내부 식별자
_BRACKET_KEY = re.compile(r"\[[^\]\n]{0,12}[:：]\s*([a-z][a-z0-9_]{3,})\s*\]")
# 대괄호 라벨 자체가 snake_case 영문인 경우
_BRACKET_SNAKE = re.compile(r"\[([a-z]+_[a-z0-9_]+)\]")


def _fixtures():
    return sorted(_GOLDEN.glob("*.txt"))


@pytest.mark.parametrize("path", _fixtures(), ids=lambda p: p.name)
def test_골든에_내부_식별자가_없다(path):
    text = path.read_text(encoding="utf-8")
    for pat, what in ((_BRACKET_KEY, "대괄호 안 내부 키"),
                      (_BRACKET_SNAKE, "snake_case 라벨")):
        m = pat.search(text)
        assert not m, f"{path.name}: {what} '{m.group(0)}'"


def test_12종_decision_type이_모두_한글_라벨을_갖는다():
    """엔드포인트가 늘면 라벨도 함께 늘어야 한다."""
    for key in _MAJOR_DECISION_URLS:
        label = decision_type_label_ko(key)
        assert label, f"{key}: 한글 라벨이 없다"
        assert re.search(r"[가-힣]", label), f"{key}: {label!r}"
        assert not re.search(r"[A-Za-z]", label), f"{key}: 영문이 섞였다"


def test_라벨을_손으로_다시_적지_않는다():
    """제목→키 목록을 뒤집어 쓴다 — 두 벌을 두면 갈린다."""
    assert len(_DECISION_LABELS()) == len(_DECISION_NAME_MAP)
    for title, key in _DECISION_NAME_MAP:
        assert decision_type_label_ko(key) == title.removesuffix("결정")


def _DECISION_LABELS():
    return {k: decision_type_label_ko(k) for _, k in _DECISION_NAME_MAP}


def test_모르는_키는_빈_값이다():
    """호출부가 원 제목으로 폴백할 수 있어야 한다 — 키를 찍으면 안 된다."""
    assert decision_type_label_ko("nope_x") == ""
    assert decision_type_label_ko("") == ""


def test_렌더_헬퍼가_폴백한다():
    """라벨을 모를 때 내부 키 대신 원 공시 제목을 쓴다."""
    from dart_risk_mcp.server import _decision_event_name

    row = {"report_nm": "주요사항보고서(유형자산양도결정)"}
    assert _decision_event_name({"decision_type": "nope"}, row) == row["report_nm"]

    got = _decision_event_name(
        {"decision_type": "tangible_div", "counterparty": "오성하이테크놀로지(주)"}, row)
    assert got == "[유형자산양도] 오성하이테크놀로지(주)"
    assert "tangible" not in got

    # 상대방을 못 뽑았으면 라벨 + 원 제목
    got2 = _decision_event_name({"decision_type": "tangible_div"}, row)
    assert got2.startswith("[유형자산양도]") and row["report_nm"] in got2


def test_기존_hygiene의_한계를_기록한다():
    """손으로 적은 금칙어 목록으로는 이 부류를 못 잡는다."""
    hygiene = (_ROOT / "tests" / "test_golden_output_hygiene.py").read_text(encoding="utf-8")
    assert "tangible_div" not in hygiene, (
        "금칙어 목록에 개별 키를 더하는 방식으로 되돌아가지 마세요 — "
        "이 파일의 모양 검사가 12종 전부와 앞으로 생길 키까지 덮습니다"
    )
