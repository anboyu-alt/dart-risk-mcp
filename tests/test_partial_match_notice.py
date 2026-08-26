"""부분 일치로 **다른 회사**를 돌려줄 때 그 사실을 알리는지 잠근다.

재무 축 감사를 시작하며 대형주 명단을 훑다 찾았다(2026-08-25).

    resolve_corp("현대차") → **현대차증권**

「현대자동차」는 "현대차"를 부분 문자열로 **포함하지도 않는다**(현대**자동**차).
그래서 후보에조차 없고, 후보 중 가장 짧은 「현대차증권」이 **조용히** 선택된다.
사용자는 현대자동차를 물었는데 증권사 리포트를 받고, 그 사실을 알려 주는
줄이 없었다.

⚠ **이 세션의 대형주 대조군에도 그렇게 섞여 들어갔다** — 패턴 임계를 검증할
때 「현대차」로 조회해 실제로는 현대차증권을 측정했다. 도구의 결함이 측정을
오염시킨 사례다.

브랜드명 34개 표본:

    해석 실패(None)     KT&G · LS일렉트릭 · SK바이오팜   (법인명은 「케이티앤지」 등)
    다른 회사로 해석     현대차 → 현대차증권 · KT → KTE

## 고른 방식

**무엇을 고르는지는 바꾸지 않았다** — 어느 후보가 '옳은'지 일반적으로 정할
수 없다. 대신 **부분 일치였다는 사실과 다른 후보**를 `alias_note`로 알린다.
별칭 해석이 이미 쓰는 통로라 4개 도구(`analyze_company_risk` ·
`build_event_timeline` · `list_disclosures_by_stock` · `get_company_info`)가
그대로 표면화한다.
"""
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "dart_risk_mcp" / "core" / "dart_client.py").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _cache(monkeypatch):
    import dart_risk_mcp.core.dart_client as dc

    fake = {
        "현대차증권": {"corp_code": "1", "stock_code": "001500"},
        "현대차정몽구재단": {"corp_code": "2", "stock_code": ""},
        "현대자동차": {"corp_code": "3", "stock_code": "005380"},
        "삼성바이오로직스": {"corp_code": "4", "stock_code": "207940"},
        "케이티앤지": {"corp_code": "5", "stock_code": "033780"},
    }
    monkeypatch.setattr(dc, "_corp_cache", fake, raising=False)
    monkeypatch.setattr(dc, "load_corp_aliases", lambda: {})
    return dc


def test_부분_일치면_사실을_알린다(_cache):
    name, info = _cache.resolve_corp("현대차", "k")
    assert name == "현대차증권"
    note = info.get("alias_note", "")
    assert "부분 일치" in note, note
    assert "종목코드" in note, "다른 회사를 찾는 길을 알려주지 않는다"


def test_다른_후보를_함께_보여준다(_cache):
    _, info = _cache.resolve_corp("현대차", "k")
    assert "현대차정몽구재단" in info["alias_note"]


def test_정확_일치는_안내가_없다(_cache):
    _, info = _cache.resolve_corp("현대자동차", "k")
    assert "부분 일치" not in (info.get("alias_note") or "")


def test_종목코드는_안내가_없다(_cache):
    name, info = _cache.resolve_corp("005380", "k")
    assert name == "현대자동차"
    assert "부분 일치" not in (info.get("alias_note") or "")


def test_후보가_하나여도_알린다(_cache):
    """「삼성바이오」→「삼성바이오로직스」는 유용하지만 여전히 부분 일치다."""
    name, info = _cache.resolve_corp("삼성바이오", "k")
    assert name == "삼성바이오로직스"
    assert "부분 일치" in info.get("alias_note", "")


def test_고르는_규칙은_바뀌지_않았다(_cache):
    """가장 짧은 이름 — 이 수정은 표기만 더한다."""
    name, _ = _cache.resolve_corp("현대차", "k")
    assert name == "현대차증권"
    assert "matches.sort(key=lambda x: (len(x[0]), x[0]))" in _SRC


def test_없는_이름은_그대로_None(_cache):
    assert _cache.resolve_corp("존재하지않는회사명", "k") is None


def test_안내가_한_통로를_쓴다():
    """`alias_note`는 4개 도구가 이미 표면화한다 — 새 필드를 만들지 않았다."""
    srv = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    assert srv.count("alias_note") >= 4
    assert _SRC.count('info["alias_note"]') >= 2
