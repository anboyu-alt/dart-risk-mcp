"""위험 목록 10번의 근거를 고정한다 — 전환청구권행사가 무신호다.

메자닌 창(v1.21.22)을 만들며 드러났다. **정정을 빼고** 세면 4개사 3년 메자닌
공시 원본 168건 중 **50건(30%)이 무신호**다.

    전환청구권ㆍ신주인수권ㆍ교환청구권행사     22
    전환청구권행사 (+ 「(제3회차)」)          18   ← 실제 전환이 일어난 공시
    전환주식의전환청구권행사                   2
    전환가액ㆍ신주인수권행사가액ㆍ교환가액의조정(안내공시)  6   ← 리픽싱 발동
    신주인수권행사가액의조정(제37회차)            2

`CB_BW`는 「전환가액의조정」은 잡지만 **결합 표기**는 못 잡고, **전환청구권행사는
아예 키워드가 없다**.

⚠ **정정을 빼지 않으면 무신호 집계가 부풀려진다.** 계획 단계에서 나는 이 공백을
「자기전환사채매도결정 73건이 전부 무신호」로 적었는데 틀렸다 — 그 73건 중
49건이 정정이라 `match_signals`가 빈 값을 준 것이고, 원본 24건은 `CB_BW`가
정상적으로 잡는다. 이 테스트가 그 구분을 고정한다.

⚠ **이 파일은 「고쳐야 한다」가 아니라 「지금은 이렇다」를 고정한다.** 키워드
확장은 `INQUIRY` 실사고(v1.12.1) 전례가 있어 시장 전수 측정이 선행돼야 한다
(위험 목록 10번의 선택지 참고). 나중에 메우면 이 테스트가 실패하면서 **기록을
함께 고치라고 알린다.**
"""
import pathlib

import pytest

from dart_risk_mcp.core.dart_client import classify_mezzanine_filing
from dart_risk_mcp.core.signals import is_amendment_disclosure, match_signals

_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("title", [
    # 실측(4개사 3년) — 정정이 아닌데 신호가 붙지 않는 제목
    "전환청구권ㆍ신주인수권ㆍ교환청구권행사",
    "전환청구권행사",
    "전환청구권행사 (제3회차)",
    "전환주식의전환청구권행사",
    "전환가액ㆍ신주인수권행사가액ㆍ교환가액의조정(안내공시)",
    "신주인수권행사가액의조정(제37회차)",
])
def test_아직_무신호인_메자닌_제목(title):
    """메우면 실패한다 — 그때 위험 목록 10번을 함께 고쳐라."""
    assert classify_mezzanine_filing(title), f"메자닌 분류에서도 빠졌다: {title}"
    assert not match_signals(title), (
        f"신호가 붙기 시작했다: {title} → {[m['key'] for m in match_signals(title)]}\n"
        "위험 목록 10번과 이 테스트를 함께 갱신하라.")


@pytest.mark.parametrize("title", [
    # 반대로 **이미 잡히는** 것들 — 무신호 집계에 넣으면 부풀려진다
    "주요사항보고서(자기전환사채매도결정)",
    "주요사항보고서(자기전환사채만기전취득결정)",
    "전환사채(해외전환사채포함)발행후만기전사채취득",
    "전환가액의조정",
    "주요사항보고서(전환사채권발행결정)",
])
def test_이미_신호가_붙는_메자닌_제목(title):
    assert match_signals(title), f"신호가 사라졌다: {title}"


def test_정정은_원래_빈_결과다():
    """`match_signals`는 정정에 빈 리스트를 준다 — 「무신호」로 세면 안 된다.

    이 한 줄을 놓쳐 「자기전환사채매도결정 73건이 전부 무신호」라는 틀린 집계를
    만들었다(그중 49건이 정정이었다).
    """
    amended = "[기재정정]주요사항보고서(자기전환사채매도결정)"
    original = "주요사항보고서(자기전환사채매도결정)"
    assert is_amendment_disclosure(amended)
    assert match_signals(amended) == []       # 정정이라 빈 값 — 「무신호」가 아니다
    assert match_signals(original)            # 원본은 잡힌다


def test_위험_목록에_항목이_적혀_있다():
    """근거만 있고 기록이 없으면 다음 사람이 다시 재야 한다."""
    doc = (_ROOT / "docs" / "DEFERRED-DECISIONS.md").read_text(encoding="utf-8")
    assert "## 10. 전환청구권행사가 무신호다" in doc
    assert "정정을 빼지" in doc or "정정을 빼고" in doc, (
        "정정 제외가 왜 필요한지가 기록에서 사라졌다")
