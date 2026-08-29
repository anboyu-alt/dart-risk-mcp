"""한정층 산출물을 **버리는 소비처**가 없는지 전수로 잠근다.

이번 세션에서 「core는 아는데 한 층만 모른다」가 **여섯 번** 반복됐다:

    #277  뷰어 헤드라인·커멘터리가 보정 라벨을 안 씀
    #280  결과보고(발행결과)를 한정층만 모름
    #283  피드·상세가 tier를 안 봄
    #284  패턴 층이 방향 안내를 버림
    #305  타임라인이 방향 안내를 버림
    #307  시장 스캔이 방향 안내를 버림   ← 이 파일이 생긴 계기

전부 같은 모양이다 — `qualify_signals`가 사실을 만들어 냈는데 **소비처
하나가 그 필드를 안 읽는다**. 그래서 화면마다 같은 공시가 다르게 보였다.

이 파일은 `qualify_signals` 호출부를 **전수로 세고**, 각 소비처가
`tier`·`label`·`note`를 쓰는지 본다. 새 소비처가 생기면 여기서 걸린다.

## 소비처별 계약

    analyze_company_risk      tier · label · note · reason   (전부)
    build_event_timeline      tier · label · note
    search_market_disclosures tier · label · note
    check_disclosure_risk     tier · label · note · reason
    check_disclosure_anomaly  tier                           (2026-08-30 신설)

⚠ `reason`은 **강등된 것만** 쓰므로 관찰만 다루는 소비처엔 없어도 된다.
"""
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")

# 호출부 → (그 뒤 몇 줄 안에서 쓰여야 하는 필드)
_CONTRACT = {
    "analyze_company_risk": ("tier", "label", "note", "reason"),
    "build_event_timeline": ("tier", "label", "note"),
    "search_market_disclosures": ("tier", "label", "note"),
    "check_disclosure_risk": ("tier", "label", "note"),
    # 2026-08-30 신설. **`tier`만** 쓴다 — 이 도구는 신호 라벨이 아니라
    # **원문 제목**을 찍고(라벨 주장 자체가 없다), 지표가 쓰는 일곱 키
    # (AUDIT·DISCLOSURE_VIOL·INQUIRY + _CAPITAL_STRESS 넷) 중
    # `DIRECTION_NOTES` 대상은 **하나도 없다**(실측). 버리는 사실이 아니라
    # 해당 없는 필드다. 이 근거가 깨지면 아래 테스트가 잡는다.
    "check_disclosure_anomaly": ("tier",),
}


def _call_sites():
    return [m.start() for m in re.finditer(r"qualify_signals\(", _SRC)]


def _enclosing_def(pos):
    head = _SRC[:pos]
    m = None
    for m in re.finditer(r"^def ([a-z_][a-z0-9_]*)\(", head, re.M):
        pass
    return m.group(1) if m else ""


def test_호출부가_계약과_같다():
    """늘어나면 계약을 함께 적어야 한다."""
    names = {_enclosing_def(p) for p in _call_sites()}
    # `_filter_market_rows`는 search_market_disclosures의 헬퍼다
    names = {"search_market_disclosures" if n == "_filter_market_rows" else n
             for n in names}
    assert names == set(_CONTRACT), names


@pytest.mark.parametrize("fn,fields", sorted(_CONTRACT.items()))
def test_소비처가_한정층_필드를_버리지_않는다(fn, fields):
    """함수 본문 전체에서 그 필드가 쓰이는지 본다."""
    i = _SRC.index(f"def {fn}(")
    nxt = _SRC.find("\ndef ", i + 1)
    body = _SRC[i:nxt if nxt > 0 else len(_SRC)]
    if fn == "search_market_disclosures":
        j = _SRC.index("def _filter_market_rows(")
        k = _SRC.find("\ndef ", j + 1)
        body += _SRC[j:k if k > 0 else len(_SRC)]
    for f in fields:
        assert re.search(rf"\bq(?:q)?\.{f}\b|\bq\.{f}\b|\"{f}\"", body), (
            f"{fn}이 한정층의 `{f}`를 쓰지 않는다 — 화면마다 같은 공시가 "
            f"다르게 보이는 원인이 된다"
        )


def test_방향_안내를_내는_소비처가_셋_이상이다():
    """`※ {note}` 렌더가 사라지면 안내가 조용히 없어진다."""
    n = len(re.findall(r'※ \{(?:_note|q\.note|note)\}', _SRC))
    assert n >= 3, f"방향 안내 렌더가 {n}곳뿐이다"


def test_시장_스캔이_안내를_중복해서_내지_않는다():
    """한 공시에 같은 안내가 여러 신호에서 나올 수 있다."""
    i = _SRC.index('lines.append(f"  🔖 [{sig_labels}] rcept_no={rcept_no}")')
    block = _SRC[i:i + 600]
    assert "dict.fromkeys" in block, "중복 제거 없이 안내를 반복한다"


def test_골드가_안내를_담고_있다():
    """렌더만 고치고 골드가 낡으면 hygiene이 옛 출력을 훑는다(#301)."""
    gold = _ROOT / "tests" / "fixtures" / "sample_outputs"
    hits = [p.name for p in gold.glob("market_*.txt")
            if "※ 발행이 아니라" in p.read_text(encoding="utf-8")]
    assert hits, "시장 골드에 방향 안내가 하나도 없다 — 재생성이 밀렸다"


def test_anomaly가_note를_무시해도_되는_근거():
    """`check_disclosure_anomaly`의 계약이 `tier`뿐인 이유를 코드로 확인한다.

    「해당 없는 필드」라는 주장은 지표가 쓰는 키에 방향 안내가 없다는 사실에
    기댄다. 그 사실이 바뀌면(새 키에 `DIRECTION_NOTES`가 붙으면) 이 도구는
    방향을 버리는 소비처가 된다 — 그때 여기서 걸린다.
    """
    from dart_risk_mcp.core.qualifiers import DIRECTION_NOTES

    i = _SRC.index("def check_disclosure_anomaly(")
    j = _SRC.index("\n@mcp.tool()", i)
    body = _SRC[i:j]
    m = re.search(r"_CAPITAL_STRESS = \{([^}]*)\}", body)
    assert m, "_CAPITAL_STRESS를 못 찾았다"
    keys = {k.strip().strip('"') for k in m.group(1).split(",") if k.strip()}
    keys |= {"AUDIT", "DISCLOSURE_VIOL", "INQUIRY"}
    overlap = keys & set(DIRECTION_NOTES)
    assert not overlap, (
        f"{sorted(overlap)}에 방향 안내가 생겼다 — 이 도구가 그것을 버리고 있다. "
        "계약에 'note'를 넣고 렌더에서 반영하라"
    )
