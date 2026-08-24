"""패턴 카드의 최소 충족 개수가 패턴 크기에 비례하는지 잠근다.

사용자 제보(2026-08-25) — *"SK하이닉스에 부채악순환·무자본M&A가 잡히는데
이런 게 잡히면 안 된다"*. 방향 게이트(#284)가 「부채 악순환」을 없앤 뒤에도
「무자본 M&A」가 남았고, 그 원인이 **임계 규칙**이었다.

옛 규칙은 `min_overlap=2` **고정**이라 2신호 패턴이든 6신호 패턴이든 2개면
카드가 섰다 — **6개 중 2개(33%)로 CRITICAL 카드가 뜬다**는 뜻이다.

    SK하이닉스   무자본 M&A 2/6     ← 유상증자 + 조회공시
    POSCO홀딩스  허위 신사업 2/4·무자본 M&A 2/6
    카카오       허위 신사업 2/4    ← 회사합병결정 + 조회공시

전부 **대형주라면 어느 해에나 있는 일**이다.

## 검증셋 실측 (365일 창)

             규칙            대조군(대형주 14)   양성군(부실·문서화 33)
    현행 (>=2 고정)          3곳 21% ⚠           26곳 79%
    절반 이상               2곳 14% ⚠           17곳 52%
    최소 3                  0곳  0%             13곳 39%
    **60% 이상**            **0곳  0%**         16곳 48%

60%를 택했다 — 「최소 3」과 대조군 성적이 같은데(둘 다 0), 3신호 패턴에
100% 일치를 요구하지 않아 패턴 크기에 따라 기준이 뒤집히지 않는다.

**대조군을 코스피 대형주 40곳으로 넓혀 재확인: 카드가 뜨는 곳 0.**

⚠ 하한 2는 유지한다 — 2신호 패턴(자금 역류·조달-유용 체인)은 2개가 곧
전부 일치이고, 그 둘은 별도의 원문 확인 게이트를 이미 갖고 있다.
"""
import math

import pytest

from dart_risk_mcp.core.taxonomy import (
    CROSS_SIGNAL_PATTERNS, PATTERN_MIN_RATIO, find_pattern_overlaps,
    required_overlap,
)


@pytest.mark.parametrize("n,want", [
    # n=1은 실재하지 않지만, 상한 규칙(전부 일치보다 많이 요구하지 않는다)이
    # 하한 2보다 우선한다는 사실을 함께 고정한다.
    (1, 1), (2, 2), (3, 2), (4, 3), (5, 3), (6, 4), (7, 5),
])
def test_필요_개수가_비례한다(n, want):
    assert required_overlap(n) == want


def test_전부_일치보다_많이_요구하지_않는다():
    for n in range(1, 12):
        assert required_overlap(n) <= max(n, 2)


def test_하한_2를_지킨다():
    """2신호 패턴이 1개로 서면 안 된다."""
    assert required_overlap(2) == 2
    assert required_overlap(3, min_overlap=2) >= 2


def test_이신호_패턴은_전부_일치가_필요하다():
    two = [k for k, v in CROSS_SIGNAL_PATTERNS.items()
           if len(v["signal_sequence"]) == 2]
    assert two, "2신호 패턴이 없어졌다 — 이 테스트의 전제가 바뀌었다"
    for k in two:
        assert required_overlap(2) == 2


def test_육신호_패턴은_둘로_서지_않는다():
    """SK하이닉스 재현 — 6개 중 2개로 CRITICAL 카드가 떴다."""
    zombie = CROSS_SIGNAL_PATTERNS["zombie_ma"]["signal_sequence"]
    assert len(zombie) == 6
    got = find_pattern_overlaps(["2.4", "7.1"], min_overlap=2)
    assert not [o for o in got if o["name"] == CROSS_SIGNAL_PATTERNS["zombie_ma"]["name"]]


def test_사신호_패턴도_둘로_서지_않는다():
    """카카오·POSCO홀딩스 재현."""
    fake = CROSS_SIGNAL_PATTERNS["fake_new_biz"]
    got = find_pattern_overlaps(list(fake["signal_sequence"][:2]), min_overlap=2)
    assert not [o for o in got if o["name"] == fake["name"]]


def test_충분히_겹치면_그대로_뜬다():
    """반대로 넓게 막으면 진짜 사례를 잃는다."""
    zombie = CROSS_SIGNAL_PATTERNS["zombie_ma"]["signal_sequence"]
    got = find_pattern_overlaps(list(zombie[:4]), min_overlap=2)
    names = {o["name"] for o in got}
    assert CROSS_SIGNAL_PATTERNS["zombie_ma"]["name"] in names


def test_창_게이트도_같은_기준을_쓴다():
    """창이 신호를 밀어낸 뒤에도 옛 임계로 판정하면 규칙이 두 개가 된다."""
    zombie = CROSS_SIGNAL_PATTERNS["zombie_ma"]
    seq = list(zombie["signal_sequence"][:4])
    months = zombie["timeline_months"]
    # 4개 중 2개만 창 안에 두고 나머지는 아주 멀리 둔다
    dates = {seq[0]: ["20260101"], seq[1]: ["20260201"],
             seq[2]: ["20200101"], seq[3]: ["20200201"]}
    got = find_pattern_overlaps(seq, min_overlap=2, taxonomy_dates=dates)
    assert months > 0
    assert not [o for o in got if o["name"] == zombie["name"]], (
        "창 밖으로 밀린 뒤 2개만 남았는데 카드가 섰다"
    )


def test_비율_상수가_노출되지_않는_판정어가_아니다():
    """v0.8.5 — 점수·등급이 아니라 '몇 개 중 몇 개'라는 사실 기준이다."""
    assert 0 < PATTERN_MIN_RATIO <= 1


def test_뷰어와_export가_따라온다():
    import json
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    html = (root / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
    assert "function requiredOverlap(" in html
    assert "evidenceCount(matched, taxOwners) < need" in html
    assert "if (matched.length < minOverlap) continue;" not in html, (
        "뷰어가 아직 고정 임계를 쓴다"
    )
    data = json.loads((root / "docs" / "tool" / "signals-data.json")
                      .read_text(encoding="utf-8"))
    assert data["pattern_min_ratio"] == PATTERN_MIN_RATIO


@pytest.mark.parametrize("pid", sorted(CROSS_SIGNAL_PATTERNS))
def test_모든_패턴이_도달_가능한_임계를_갖는다(pid):
    """요구 개수가 관찰 가능한 신호 수를 넘으면 패턴이 조용히 죽는다."""
    seq = CROSS_SIGNAL_PATTERNS[pid]["signal_sequence"]
    assert required_overlap(len(seq)) <= len(seq)
    assert required_overlap(len(seq)) == min(
        len(seq), max(2, math.ceil(len(seq) * PATTERN_MIN_RATIO)))
