"""WATCH 블록이 **「먼저」 배지의 낱말을 빌려 쓰지 않는지** 잠근다.

대시보드를 눌러 보다 찾았다(2026-08-30, 제이스코홀딩스 1년).

    WATCH        「**먼저** 볼 공시 6건 관찰 — 자본잠식/부도·감사의견·
                  상장폐지 절차 외 1종 유형입니다」 + 목록 6줄
    COMMENTARY   같은 화면에서 「먼저」 배지가 붙은 신호는 3종 · 공시 5건

6번째 줄은 조회공시였다. `isHeavySignal`은 `category >= 7 && priority !==
"context"`라 cat 7인 조회공시가 걸리는데, 그 신호의 priority는 `watch`라
「먼저」 배지는 안 붙는다 — **같은 낱말이 두 집합을 가리켰다.**

## 집합이 아니라 낱말을 고쳤다

처음엔 `isHeavySignal`을 `priority === "first"`로 바꿨다. 그런데
`test_heavy_signal_gate.py`가 `{cat 7, watch} → true`를 **「# INQUIRY」 주석과
함께 사례로 못 박고** 있었다. 의도된 포함이다. 게다가 그 테스트의 문서가
인용하는 2026-08-24 당시 화면 문구는

    ▍WATCH
    시장감시·위기/부실 카테고리 공시 1건 관찰

즉 **카테고리 표현**이었다. 집합은 그때부터 카테고리 기준이었고, 나중에 문구만
「먼저 볼 공시」라는 priority 표현으로 바뀌면서 어긋난 것이다. 그래서 되돌린
쪽은 문구다 — 남의 결정을 뒤집지 않는 쪽.

⚠ 참고로 두 축의 차이는 정확히 둘뿐이다: `INQUIRY`(cat 7·watch, 포함됨) ·
`BUYBACK_NEG`(cat 5·first, 빠짐 — 단 `NON_TITLE_SIGNALS`라 제목 발화 없음).
나중에 축을 정말 바꿀 일이 생기면 영향 범위는 이 둘이다.
"""
import json
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
_DATA = json.loads(
    (_ROOT / "docs" / "tool" / "signals-data.json").read_text(encoding="utf-8"))


def _render() -> str:
    """주석이 아니라 **렌더 지점**을 본다 — 근거 주석에도 옛 문구가 나온다."""
    i = _HTML.index("${crisisEvents.length}건 관찰")
    return _HTML[i - 200:i + 400]


def test_배지_낱말을_집합_이름으로_쓰지_않는다():
    body = _render()
    assert "먼저 볼 공시 ${crisisEvents.length}건" not in body, (
        "「먼저」는 priority=first 배지의 이름이다 — 카테고리 기준 집합에 쓰면 안 된다"
    )
    assert "시장감시·위기/부실 유형 공시 ${crisisEvents.length}건 관찰" in body


def test_원문을_확인하라는_안내는_남긴다():
    """낱말을 고치느라 실제로 할 일을 지우면 안 된다."""
    assert "원문을 먼저 확인해 보세요" in _render()


def test_타임라인_범례도_같은_이름을_쓴다():
    """붉은 막대는 같은 함수로 갈리므로 이름도 같아야 한다."""
    i = _HTML.index("큰 점·붉은 막대 =")
    body = _HTML[i:i + 80]
    assert "시장감시·위기/부실 유형" in body
    assert "먼저 볼 공시" not in body


def test_판정_집합은_건드리지_않았다():
    """`test_heavy_signal_gate.py`가 못 박은 결정을 뒤집지 않았다."""
    i = _HTML.index("function isHeavySignal(s)")
    body = _HTML[i:_HTML.index("\n}", i)]
    assert 's.category >= 7 && s.priority !== "context"' in body


def test_두_축의_차이가_실제로_이_둘뿐이다():
    """나중에 축을 바꿀 때의 영향 범위 — 신호가 늘면 여기서 드러난다."""
    heavy = {s["key"] for s in _DATA["signals"]
             if s["category"] >= 7 and s.get("priority") != "context"}
    first = {s["key"] for s in _DATA["signals"] if s.get("priority") == "first"}
    assert heavy - first == {"INQUIRY"}, f"예상 밖: {sorted(heavy - first)}"
    assert first - heavy == {"BUYBACK_NEG"}, f"예상 밖: {sorted(first - heavy)}"


def test_조회공시가_이_집합에_남아_있다():
    s = next(x for x in _DATA["signals"] if x["key"] == "INQUIRY")
    assert s["category"] == 7 and s.get("priority") == "watch"


def test_이_결정의_근거가_주석에_남아_있다():
    body = _HTML[_HTML.index("// 「가장 무거운 유형」으로 다룰 신호인가."):
                 _HTML.index("function isHeavySignal(s)")]
    for token in ("INQUIRY", "BUYBACK_NEG", "먼저 볼 공시"):
        assert token in body, f"근거에서 {token}이 사라졌다"
