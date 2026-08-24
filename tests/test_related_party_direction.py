"""`RELATED_PARTY` 해설이 거래 **방향**을 잘못 단정하지 않는지 잠근다.

삼성전자 리포트를 읽다 찾았다(2026-08-24).

    • 20260730 · 특수관계인에대한출자
      → 계열사·최대주주 같은 특수관계인**에게서** 돈이나 담보를 **받아온**
         공시입니다. … 반대로 회사가 특수관계인에게 돈을 빌려주거나 담보를
         제공한 건은 '자금유출성거래'로 잡힙니다.

그 공시는 삼성전자가 SVIC 83호 조합에 **2,970억원을 출자**한 건이다 — 돈이
**나간** 것이다. 해설은 방향을 단정했을 뿐 아니라, 나가는 건은 다른 신호가
잡는다고 **명시적으로 갈라** 놓기까지 했다.

1년 코퍼스 실측 — 이 신호의 키워드 셋 중 하나만 나가는 방향이다.

| 키워드 | 관찰 | 방향 |
|---|---:|---|
| 특수관계인으로부터자금차입 | 1,532 | 들어옴 |
| 특수관계인으로부터받은담보 | 240 | 들어옴 |
| **특수관계인에대한출자** | **221** | **나감** |

해설이 양쪽을 다 설명하도록 고쳤다. **신호 배정은 바꾸지 않았다** — 옮기면
`capital_backflow` 게이트에 확인 불가 후보만 늘어난다(게이트 파서가 출자
서식을 못 읽는다). 판단은 `docs/superpowers/decisions/OPEN-QUESTIONS.md` #7.
"""
import pytest

from dart_risk_mcp.core.explain import SIGNAL_PROSE
from dart_risk_mcp.core.signals import SIGNAL_TYPES, match_signals

_KEYWORDS = next(s for s in SIGNAL_TYPES if s["key"] == "RELATED_PARTY")["keywords"]
_PROSE = SIGNAL_PROSE["RELATED_PARTY"]


def test_방향을_한쪽으로_단정하지_않는다():
    """⚠ 같은 문장이 **두 군데**에 있었다 — `SIGNAL_PROSE`와 원문 확인 블록
    헤더(`server.py`의 「🤝 특수관계인 자금거래 확인」). 해설만 고쳤더니 골든에
    옛 문구가 남아 발견했다. 두 곳을 함께 본다."""
    import inspect

    import dart_risk_mcp.server as srv

    targets = ((_PROSE, "SIGNAL_PROSE"), (inspect.getsource(srv), "server.py"))
    for text, where in targets:
        for phrase in ("에게서 돈이나 담보를 받아온 공시입니다",
                       "에게서 돈이나 담보를 받아온 건입니다"):
            assert phrase not in text, f"{where}: '{phrase}'"


def test_양쪽_방향을_모두_설명한다():
    assert "으로부터" in _PROSE and "대한 출자" in _PROSE
    assert "받아온" in _PROSE, "들어오는 방향"
    assert "넣은 것" in _PROSE or "나간" in _PROSE, "나가는 방향"


@pytest.mark.parametrize("kw", _KEYWORDS)
def test_키워드가_해설에서_설명된다(kw):
    """키워드가 늘면 해설도 함께 손봐야 한다."""
    core = kw.replace("특수관계인", "")
    token = core[:4].replace("으로부터", "")
    assert any(t in _PROSE for t in (core, token, "출자", "차입", "담보")), kw


def test_나가는_키워드가_실제로_섞여_있다():
    """이 테스트가 지키려는 사실 자체 — 사라지면 해설을 다시 단순화해도 된다."""
    outgoing = [k for k in _KEYWORDS if "에대한" in k]
    assert outgoing == ["특수관계인에대한출자"], (
        f"나가는 방향 키워드가 바뀌었다: {outgoing} — 해설과 OPEN-QUESTIONS #7을 갱신하세요"
    )


def test_출자_제목이_다른_신호로_새지_않는다():
    """지금은 RELATED_PARTY만 잡는다. 옮기면 이 테스트가 알려 준다."""
    keys = {s["key"] for s in match_signals("특수관계인에대한출자")}
    assert keys == {"RELATED_PARTY"}, (
        f"배정이 바뀌었다: {keys} — OPEN-QUESTIONS #7의 판단이 내려진 것이라면 "
        "이 테스트와 해설을 함께 갱신하세요"
    )


def test_판단이_문서에_남아_있다():
    import pathlib

    doc = (pathlib.Path(__file__).resolve().parents[1] / "docs" / "superpowers"
           / "decisions" / "OPEN-QUESTIONS.md").read_text(encoding="utf-8")
    assert "특수관계인에 대한 출자" in doc
    assert "capital_backflow" in doc, "왜 지금 옮기지 않았는지가 적혀 있어야 한다"
