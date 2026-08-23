"""릴레이 3곳의 화이트리스트가 어긋나지 않는다.

CLAUDE.md의 계약: JS 릴레이 `api/[endpoint].js`(Vercel)·`relay/worker.js`
(Cloudflare)·`scripts/dev_relay.py`(로컬) 3곳이 **동일 화이트리스트**를 복제
유지하고, "하나 추가하면 3곳 모두 갱신"한다.

복제는 어긋나기 쉽고, 어긋나면 **어떤 환경에서만** 조회가 실패한다. 사용자
화면에는 "자료 없음"으로 보인다 — 실패와 부재를 구분하지 않는 그 실패 모드다.

그리고 뷰어가 부르는 엔드포인트가 화이트리스트 밖이면 그 기능은
**프로덕션에서만** 죽는다(로컬 릴레이는 같은 목록이라 개발 중에는 안 보인다).

2026-08-23 실측: 3곳 모두 10종 동일, 뷰어 호출 9종 전부 허용 목록 안.
테스트가 없어 지금까지 사람이 지켜 왔다.
"""
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
_ENDPOINT_RE = re.compile(r"['\"]([a-zA-Z][a-zA-Z0-9]*\.json)['\"]")

_RELAYS = {
    "vercel": _ROOT / "api" / "[endpoint].js",
    "cloudflare": _ROOT / "relay" / "worker.js",
    "local": _ROOT / "scripts" / "dev_relay.py",
}


def _whitelist(path: pathlib.Path) -> set:
    """파일에서 `*.json` 문자열 리터럴을 모은다.

    세 파일 모두 화이트리스트 외에 `.json` 리터럴을 쓰지 않는다(2026-08-23
    확인). 나중에 그게 깨지면 이 테스트가 먼저 알려 준다.
    """
    return set(_ENDPOINT_RE.findall(path.read_text(encoding="utf-8")))


def test_세_릴레이가_모두_존재한다():
    for name, p in _RELAYS.items():
        assert p.exists(), f"{name} 릴레이가 없다: {p}"


def test_화이트리스트가_세_곳에서_같다():
    sets = {n: _whitelist(p) for n, p in _RELAYS.items()}
    union = set().union(*sets.values())
    diffs = {n: sorted(union - s) for n, s in sets.items() if union - s}
    assert not diffs, f"릴레이별로 빠진 엔드포인트가 있다: {diffs}"


def test_화이트리스트가_비어_있지_않다():
    """추출 정규식이 깨지면 세 곳이 모두 빈 집합이 되어 위 테스트가
    조용히 통과한다 — 그 구멍을 막는다."""
    for name, p in _RELAYS.items():
        assert len(_whitelist(p)) >= 5, f"{name}에서 엔드포인트를 못 읽었다"


def _viewer_calls() -> set:
    html = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
    calls = set(re.findall(r'dartGet\(\s*"([a-zA-Z0-9.]+\.json)"', html))
    # 동적 호출: `for (const ep of FUND_USAGE_ENDPOINTS) dartGet(ep, …)`
    for m in re.finditer(r"const\s+FUND_USAGE_ENDPOINTS\s*=\s*\[([^\]]*)\]", html):
        calls |= set(_ENDPOINT_RE.findall(m.group(1)))
    return calls


def test_뷰어가_부르는_엔드포인트를_모두_허용한다():
    allowed = set().union(*(_whitelist(p) for p in _RELAYS.values()))
    missing = _viewer_calls() - allowed
    assert not missing, (
        f"뷰어가 부르는데 릴레이가 막는다(프로덕션에서만 죽는다): {sorted(missing)}"
    )


def test_뷰어_호출을_실제로_찾았다():
    """정규식이 깨져 0종이 되면 위 테스트가 무의미해진다."""
    calls = _viewer_calls()
    assert len(calls) >= 7, f"뷰어 호출을 못 읽었다: {sorted(calls)}"
    # 동적 목록(자금사용내역 2종)이 빠지면 이 단언이 먼저 깨진다
    assert "pssrpCptalUseDtls.json" in calls
    assert "prvsrpCptalUseDtls.json" in calls


@pytest.mark.parametrize("name", sorted(_RELAYS))
def test_각_릴레이가_GET만_통과시킨다(name):
    """계약: 통과 프록시는 GET만 받는다(키·파라미터를 저장하지 않는다)."""
    txt = _RELAYS[name].read_text(encoding="utf-8")
    assert "GET" in txt, f"{name}에 GET 제한이 보이지 않는다"
