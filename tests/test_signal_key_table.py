"""CLAUDE.md의 「사용 가능한 신호 키」 표가 실제 신호를 다 담는지 잠근다.

문서에는 테스트가 없어 조용히 늙는다(`test_doc_facts`와 같은 취지).
2026-08-27 대조에서 **제목으로 실제 발화하는 신호 셋**이 표에 없었다 —

    DISCLOSURE_VIOL   공시의무위반   (4.3)
    EQUITY_SPLIT      주식분할/액면분할 (5.1)
    EARNINGS_SHOCK    손익구조 급변  (8.5) — 1년 1,958건으로 발화량이 큰 축

셋 다 `NON_TITLE_SIGNALS`가 아니다(즉 정말 발화한다). 표를 보고 키를 고르는
사람에게는 없는 기능처럼 보였다.

표에 **키워드 없는 키가 있는 것은 정상**이다 — `CB_REPAY`류 9종은 제목으로
발화하지 않는다는 사실을 함께 적어 두려고 일부러 남겨 둔 것이고, 표 바로
위의 ⚠ 주석이 그 사실을 설명한다.
"""
import pathlib
import re

from dart_risk_mcp.core.signals import NON_TITLE_SIGNALS, SIGNAL_TYPES

_MD = (pathlib.Path(__file__).resolve().parents[1] / "CLAUDE.md").read_text(
    encoding="utf-8")


def _table_keys() -> set:
    i = _MD.index("| 카테고리 | 키 목록 |")
    j = _MD.index("v1.6.0 신규:", i)
    return set(re.findall(r"`([A-Z0-9_]{2,})`", _MD[i:j]))


def test_제목으로_발화하는_신호가_전부_표에_있다():
    keys = _table_keys()
    firing = {s["key"] for s in SIGNAL_TYPES if s.get("keywords")}
    missing = sorted(firing - keys)
    assert not missing, (
        "제목으로 발화하는데 표에 없다 — 표를 보고 키를 고르는 사람에게는 "
        f"없는 기능이다: {missing}"
    )


def test_표의_키가_전부_실존한다():
    keys = _table_keys()
    real = {s["key"] for s in SIGNAL_TYPES}
    assert not sorted(keys - real), sorted(keys - real)


def test_적어_둔_개수가_표와_맞는다():
    m = re.search(r"사용 가능한 신호 키 \(아래 표 (\d+)개", _MD)
    assert m, "개수 문구를 찾지 못했다"
    assert int(m.group(1)) == len(_table_keys())


def test_키워드_없는_키는_미발화로_설명돼_있다():
    """표에 남겨 둔 `CB_REPAY`류는 ⚠ 주석이 이유를 적고 있어야 한다."""
    keys = _table_keys()
    kwless = {k for k in keys
              if not next((s for s in SIGNAL_TYPES if s["key"] == k),
                          {}).get("keywords")}
    assert kwless, "검사가 헛돈다 — 키워드 없는 키가 하나도 없다"
    for k in kwless:
        assert k in NON_TITLE_SIGNALS, f"{k}는 키워드도 없고 설명도 없다"
