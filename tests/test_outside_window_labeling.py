"""창 밖에서 **관찰된** 신호를 「안 보임」이라 적지 않는지 잠근다.

`find_pattern_overlaps`의 창 게이트(2026-08-21)는 `timeline_months` 밖의 신호를
`missing`으로 보낸다. 렌더는 `missing`을 "안 보임"으로 적었다 — 그런데 그
신호는 같은 리포트 위쪽 「관찰된 신호」 절에 실려 있다. **한 화면이 서로
반대되는 말을 했다.**

라이브 실측(2026-08-24, 7개사 × 5년): 1건.
  KR모터스 `fake_new_biz` — 4.3이 2022-03-22에 관찰됐는데 창 밖이라 밀렸다.

드물지만 사실이 아닌 표기이고, 게이트 판정을 건드리지 않고 표기만 가르면
된다. `missing`은 하위 호환을 위해 그대로 두고 `outside_window`(그 부분집합)를
더했다.
"""
import pytest

from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS, find_pattern_overlaps

# 요구 신호 2개짜리 패턴 — 창 게이트를 시험하기 가장 단순하다
PAIR = "capital_backflow"
SEQ = CROSS_SIGNAL_PATTERNS[PAIR]["signal_sequence"]
MONTHS = CROSS_SIGNAL_PATTERNS[PAIR]["timeline_months"]


def _ov(dates, min_overlap=1):
    res = find_pattern_overlaps(sorted(dates), min_overlap=min_overlap,
                                taxonomy_dates=dates)
    return {r["pattern_id"]: r for r in res}


def test_창_안이면_둘_다_관찰됨이다():
    a, b = SEQ[0], SEQ[1]
    got = _ov({a: ["20250101"], b: ["20250301"]}).get(PAIR)
    assert got and set(got["matched"]) == {a, b}
    assert got["missing"] == []
    assert got["outside_window"] == []


def test_창_밖_관찰은_안_보임이_아니라_창_밖_관찰이다():
    """2026-08-25: 카드 임계가 패턴 크기에 비례하게 바뀌어(60%) 2신호 패턴은
    하나만 남으면 카드 자체가 서지 않는다. 표기 구분을 재는 것이 목적이므로
    3신호 패턴(`audit_insider_dump`, 2개면 선다)으로 옮긴다."""
    pid = "audit_insider_dump"
    seq = CROSS_SIGNAL_PATTERNS[pid]["signal_sequence"]
    months = CROSS_SIGNAL_PATTERNS[pid]["timeline_months"]
    # seq[2]를 창 길이보다 훨씬 뒤에 둔다 → 한 창에 못 담긴다
    late = f"20{40 + months // 12:02d}0601"
    got = _ov({seq[0]: ["20200101"], seq[1]: ["20200301"],
               seq[2]: [late]}).get(pid)
    assert got, "겹침 자체는 성립해야 한다"
    assert len(got["matched"]) == 2
    dropped = got["missing"]
    assert len(dropped) == 1
    assert got["outside_window"] == dropped, "관찰됐으므로 창 밖 관찰로 분류"


def test_관찰되지_않은_신호는_그대로_안_보임이다():
    """반대 방향 — 진짜 없는 것까지 '창 밖 관찰'로 올리면 없는 사실을 만든다."""
    seq = CROSS_SIGNAL_PATTERNS["zombie_ma"]["signal_sequence"]
    # 6신호 패턴은 이제 4개가 필요하다(60% 임계) — 4개를 창 안에 둔다.
    seen = seq[:4]
    dates = {t: [f"2025{1 + i:02d}01"] for i, t in enumerate(seen)}
    got = _ov(dates, min_overlap=2).get("zombie_ma")
    assert got
    assert got["outside_window"] == [], "관찰된 적 없는 id가 섞이면 안 된다"
    assert set(got["missing"]) == set(seq) - set(seen)


def test_outside_window는_missing의_부분집합이다():
    a, b = SEQ[0], SEQ[1]
    late = f"20{28 + MONTHS // 12:02d}0601"
    for res in find_pattern_overlaps(
            sorted({a: 1, b: 1}), min_overlap=1,
            taxonomy_dates={a: ["20200101"], b: [late]}):
        assert set(res["outside_window"]) <= set(res["missing"])


def test_날짜를_안_주면_창_밖_관찰이_없다():
    """하위 호환 — 게이트를 안 걸면 밀려나는 신호 자체가 없다."""
    for res in find_pattern_overlaps(list(SEQ), min_overlap=2):
        assert res["outside_window"] == []


@pytest.mark.parametrize("pid", sorted(CROSS_SIGNAL_PATTERNS))
def test_모든_패턴이_새_키를_갖는다(pid):
    """렌더가 `.get()` 없이 읽어도 깨지지 않게 항상 존재해야 한다."""
    seq = CROSS_SIGNAL_PATTERNS[pid]["signal_sequence"]
    res = find_pattern_overlaps(list(seq), min_overlap=2)
    for r in res:
        assert "outside_window" in r


def test_뷰어도_같은_구분을_한다():
    """이식본이 core와 어긋나면 같은 회사가 두 화면에서 다르게 보인다."""
    import pathlib

    html = (pathlib.Path(__file__).resolve().parents[1]
            / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
    assert "outside_window: outside.slice().sort(tidCompare)" in html
    assert "창 밖에서 관찰됨" in html
    # core 렌더도 같은 문구를 쓴다
    srv = (pathlib.Path(__file__).resolve().parents[1]
           / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    assert "창 밖에서 관찰됨" in srv
