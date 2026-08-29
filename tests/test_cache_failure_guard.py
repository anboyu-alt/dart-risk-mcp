"""**못 받은 결과를 캐시하지 않는지** 잠근다 — 남아 있던 세 곳.

한도 초과·점검 같은 일시적 실패를 10분 캐시하면, 한도가 풀린 뒤에도 같은
거짓말을 되풀이한다. 화면은 「이 회사는 그런 게 없다」로 읽힌다.

2026-08-27에 세 곳을 고쳤다 — `fetch_debt_balance` · `fetch_fund_usage` ·
`fetch_audit_opinion_history`. 그때 **세 곳이 더 남아 있었다**(2026-08-30
캐시 감사에서 발견):

    fetch_treasury_decisions
    fetch_distress_events
    fetch_dividend_history

⚠ **진짜 「없음」은 캐시해야 한다.** 실패와 부재를 구분하지 못하면 캐시가
통째로 무력해진다. 정상 응답(000·013)을 한 번이라도 받았으면 빈 결과도
캐시한다 — 기존 `_ins_ok`·`_fu_ok` 관례와 같다.

라이브 확인(2026-08-30, 두산):

    잘못된 키로 호출 → 캐시 0개 (실패를 붙들지 않는다)
    정상 키로 호출   → 캐시 1개 (부실 이벤트 0건도 캐시된다)
"""
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "dart_risk_mcp" / "core" / "dart_client.py").read_text(encoding="utf-8")

# (함수, 카운터 이름, 캐시 이름)
_GUARDED = [
    ("fetch_treasury_decisions", "_tre_ok", "_treasury_decisions_cache"),
    ("fetch_distress_events", "_dis_ok", "_distress_events_cache"),
    ("fetch_dividend_history", "_div_ok", "_dividend_history_cache"),
]


def _body(fn: str) -> str:
    i = _SRC.index(f"def {fn}(")
    j = _SRC.index("\ndef ", i + 10)
    return _SRC[i:j]


@pytest.mark.parametrize("fn,counter,cache", _GUARDED)
def test_성공_카운터가_선언되고_증가한다(fn, counter, cache):
    body = _body(fn)
    assert f"{counter} = 0" in body, f"{fn}에 카운터 선언이 없다"
    assert f"{counter} += 1" in body, f"{fn}에서 카운터가 증가하지 않는다"


@pytest.mark.parametrize("fn,counter,cache", _GUARDED)
def test_실패하면_캐시하지_않는다(fn, counter, cache):
    body = _body(fn)
    m = re.search(rf"if \w+ or {counter}:\s*\n\s*_cache_set\({cache}", body)
    assert m, f"{fn}이 실패를 캐시할 수 있다"


@pytest.mark.parametrize("fn,counter,cache", _GUARDED)
def test_정상_응답_두_종류를_모두_성공으로_센다(fn, counter, cache):
    """013(자료 없음)은 **정상 응답**이다 — 그것까지 실패로 세면 진짜
    「없음」을 영영 캐시하지 못한다."""
    body = _body(fn)
    i = body.index(f"{counter} += 1")
    seg = body[max(0, i - 200):i]
    assert '"000", "013"' in seg or '("000", "013")' in seg, (
        f"{fn}이 013을 성공으로 세지 않는다"
    )


def test_고쳐진_세_곳도_여전히_가드를_갖고_있다():
    """2026-08-27에 고친 것들이 되돌아가지 않았는지 함께 본다."""
    for fn in ("fetch_debt_balance", "fetch_fund_usage",
               "fetch_audit_opinion_history"):
        body = _body(fn)
        assert re.search(r"_\w*ok\b", body), f"{fn}의 성공 카운터가 사라졌다"


def test_캐시_가드가_없는_cache_set이_남지_않았다():
    """새 캐시를 추가하면서 가드를 잊는 것을 막는다."""
    lines = _SRC.splitlines()
    unguarded = []
    for i, ln in enumerate(lines):
        if "_cache_set(" not in ln or "def _cache_set" in ln:
            continue
        window = "\n".join(lines[max(0, i - 14):i + 1])
        # 실패 판정에 쓰이는 표현 중 하나라도 있으면 가드가 있는 것으로 본다
        if not re.search(r"_ok\b|fetch_failed|sentinel|status|if not |if r\b|if out\b",
                         window):
            unguarded.append((i + 1, ln.strip()[:70]))
    assert not unguarded, (
        "실패 가드 없이 캐시에 넣는 자리가 있다:\n"
        + "\n".join(f"  {n}: {t}" for n, t in unguarded)
    )
