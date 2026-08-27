"""CLAUDE.md가 적어 둔 **1년 실측 건수**를 코퍼스로 되재 대조한다.

2026-08-22에 수집기의 청크 절단을 고쳐 코퍼스가 201,361 → **270,882건**
(+34.5%)이 됐는데, **개별 신호의 건수는 다시 재지 않았다.** 그래서 v1.12.3·
v1.13.5에 적힌 1년 값들이 10~15% 낮다.

    EARNINGS_SHOCK   1,958  →  2,251   (+15.0%)
    RELATED_PARTY    1,732  →  1,993   (+15.1%)
    ACQ_REVIEW         600  →    663   (+10.5%)

⚠ **함께 적힌 「N개사」는 대상이 아니다** — 고정 픽스처가 제목·빈도만 담아
회사 수를 복원할 수 없다.

⚠ **90일 창으로 잰 값은 대상이 아니다**(예: `CB_BW` 관찰 473건). 창이 다른
숫자를 견주면 「332% 어긋났다」는 헛된 결론이 나온다 — 2026-08-27에 실제로
그럴 뻔했다. 숫자를 고치기 전에 **어느 창에서 잰 것인지** 먼저 읽는다.

코퍼스를 다시 수집하면 이 테스트가 깨진다. 그때 문서를 함께 고치라는 뜻이다.
"""
import collections
import json
import pathlib
import re

import pytest

from dart_risk_mcp.core.qualifiers import parse_report_name, qualify_signals
from dart_risk_mcp.core.signals import match_signals

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MD = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
_CORPUS = json.loads(
    (_ROOT / "tests" / "fixtures" / "corpus" / "signal_titles_365d.json")
    .read_text(encoding="utf-8"))

# 문서의 ⚠ 표에 적힌 값 — 「신호: 현재 코퍼스 관찰 N」
_CLAIMS = {"EARNINGS_SHOCK": 2251, "RELATED_PARTY": 1993, "ACQ_REVIEW": 663}


def _observed() -> collections.Counter:
    c = collections.Counter()
    for r in _CORPUS["titles"]:
        nm, n = r["nm"], r["n"]
        sigs = match_signals(nm)
        if not sigs:
            continue
        for q in qualify_signals(sigs, parse_report_name(nm),
                                 {"report_nm": nm, "flr_nm": "회사"}):
            if q.tier == "observed":
                c[q.key] += n
    return c


@pytest.mark.parametrize("key,said", sorted(_CLAIMS.items()))
def test_적어_둔_값이_코퍼스와_맞는다(key, said):
    got = _observed()[key]
    assert got == said, (
        f"{key}: 문서 {said:,} · 코퍼스 {got:,} — 코퍼스를 다시 수집했다면 "
        "CLAUDE.md의 ⚠ 표를 함께 고치세요"
    )


@pytest.mark.parametrize("key,said", sorted(_CLAIMS.items()))
def test_그_값이_문서에_실제로_적혀_있다(key, said):
    """검사만 있고 문서에 없으면 아무것도 지키지 않는 것이다."""
    assert re.search(rf"{key}\s+문서\s+[\d,]+\s+→", _MD), f"{key} 행이 없다"
    assert f"{said:,}" in _MD, f"{key}의 재측정값 {said:,}이 문서에 없다"


def test_절단_사실이_적혀_있다():
    assert "270,882" in _MD and "201,361" in _MD


def test_코퍼스가_재수집본이다():
    assert _CORPUS["n_disclosures_scanned"] == 270_882
    assert not _CORPUS["truncated_days"], "절단일이 있으면 전수가 아니다"
