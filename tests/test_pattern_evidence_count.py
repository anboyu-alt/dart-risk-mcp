"""한 신호가 같은 패턴에 두 번 세어지지 않는지 잠근다.

「무자본 M&A」 임계 수정(#286) 뒤 시장 전수를 다시 훑다 찾았다. 남은 패턴 중
**창업주 퇴장**만 유독 많았고(37장), 근거를 보니 전부 같은 모양이었다.

    founder_fade = [3.2, 3.1, 4.1, 5.3, 8.1]   6개 중 3개 필요, 4.1은 absent

    3.1  Major Shareholder Change via Debt Conversion   ┐ 둘 다
    3.2  Controlling Shareholder Below-Market Exit      ┘ `SHAREHOLDER` 소유

**최대주주변경 공시 한 건이 3개 중 2개를 혼자 채운다.** 자산처분(5.3)이나
횡령(8.1) 한 건만 더 있으면 CRITICAL 카드가 섰다 — **공시 두 건**으로.

1년 코퍼스 실측: `SHAREHOLDER` 관찰 361건·11종이 **전부 최대주주변경 계열**
이고 제목에 「출자전환」·「헐값」·「저가」·「시가」가 **0건**이다. 3.2 자체
키워드(「지분매각」·「경영권이양」)도 **매칭 0건**이다.

## 왜 매핑을 좁히지 않았나

`SIGNAL_KEY_TO_TAXONOMY["SHAREHOLDER"]`에서 3.2를 빼면 그 taxonomy를 켜는
신호가 0개가 되어 고아가 된다. `tests/test_embezzle_taxonomy.py`가 앞선
라운드에 **명시적으로 그러지 않기로** 결정하고 고정해 둔 지점이다
("고아를 만들지 않는 선에서만 좁힌다"). 실제로 좁혀 재 보니 창업주 퇴장이
37 → **0**이 됐다 — 진짜 사례까지 잃는다.

## 대신 고른 것

**세는 방법**을 고쳤다. `_evidence_count`는 겹친 taxonomy를 **서로 다른 관찰
몇 건**이 뒷받침하는지 본다.

⚠ 「서로 다른 신호 개수」만 세면 **반대로 부푼다** — 5.3처럼 한 taxonomy를
여러 신호가 켜는 경우(ASSET_TRANSFER·FUND_DIVERSION·DECISION_OVERSIZED)
신호 수가 taxonomy 수를 넘는다. 그렇게 재 보니 **없던 카드가 14장 생겼다**
(특수관계 자산 공동화 0→10 · 상폐 회피 0→4). 그래서 **두 수의 최솟값**을 쓴다.

1년 전수: 카드 315 → **285**, 창업주 퇴장 37 → **7**. 다른 패턴은 불변.
"""
import pathlib

import pytest

from dart_risk_mcp.core.signals import SIGNAL_KEY_TO_TAXONOMY as SKT
from dart_risk_mcp.core.taxonomy import (
    CROSS_SIGNAL_PATTERNS, _evidence_count, find_pattern_overlaps,
    required_overlap,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FF = CROSS_SIGNAL_PATTERNS["founder_fade"]["signal_sequence"]


def test_한_신호가_둘을_켜면_하나로_센다():
    owners = {"3.1": {"SHAREHOLDER"}, "3.2": {"SHAREHOLDER"}}
    assert _evidence_count({"3.1", "3.2"}, owners) == 1


def test_서로_다른_신호는_그대로_센다():
    owners = {"3.1": {"SHAREHOLDER"}, "5.3": {"ASSET_TRANSFER"}}
    assert _evidence_count({"3.1", "5.3"}, owners) == 2


def test_한_taxonomy를_여럿이_켜도_부풀지_않는다():
    """이 방향으로 틀리면 없던 카드가 생긴다(실측 14장)."""
    owners = {"5.3": {"ASSET_TRANSFER", "FUND_DIVERSION", "DECISION_OVERSIZED"}}
    assert _evidence_count({"5.3"}, owners) == 1


def test_미전달이면_기존_동작():
    assert _evidence_count({"3.1", "3.2", "5.3"}, None) == 3


def test_소유_정보가_비면_기존_동작():
    assert _evidence_count({"3.1", "3.2"}, {}) == 2


def test_창업주_퇴장이_공시_두_건으로_서지_않는다():
    """최대주주변경 1건 + 자산처분 1건 = 서로 다른 관찰 2건 < 필요 3개."""
    tax = ["3.1", "3.2", "5.3"]
    owners = {"3.1": {"SHAREHOLDER"}, "3.2": {"SHAREHOLDER"},
              "5.3": {"ASSET_TRANSFER"}}
    names = {o["pattern_id"] for o in
             find_pattern_overlaps(tax, 2, taxonomy_owners=owners)}
    assert "founder_fade" not in names
    # 소유 정보를 안 주면 옛 동작 — 이 차이가 이번 수정의 전부다
    old = {o["pattern_id"] for o in find_pattern_overlaps(tax, 2)}
    assert "founder_fade" in old


def test_서로_다른_세_관찰이면_그대로_뜬다():
    """반대로 넓게 막으면 진짜 사례를 잃는다."""
    tax = ["3.1", "3.2", "5.3", "8.1"]
    owners = {"3.1": {"SHAREHOLDER"}, "3.2": {"SHAREHOLDER"},
              "5.3": {"ASSET_TRANSFER"}, "8.1": {"EMBEZZLE"}}
    names = {o["pattern_id"] for o in
             find_pattern_overlaps(tax, 2, taxonomy_owners=owners)}
    assert "founder_fade" in names


def test_삼점이는_고아가_되지_않았다():
    """매핑을 좁히지 **않았다**는 사실을 고정한다(앞선 라운드의 결정 존중)."""
    assert SKT["SHAREHOLDER"] == ["3.1", "3.2"]
    lighting = {k for k, v in SKT.items() if "3.2" in v}
    assert lighting == {"SHAREHOLDER"}


@pytest.mark.parametrize("pid", sorted(CROSS_SIGNAL_PATTERNS))
def test_증폭_조합을_모두_안다(pid):
    """한 신호가 같은 패턴에 2개 이상 기여하는 조합은 둘뿐이다 —
    늘어나면 이 테스트가 알려 준다."""
    seq = set(CROSS_SIGNAL_PATTERNS[pid]["signal_sequence"])
    hits = {k for k, v in SKT.items() if len(seq & set(v)) >= 2}
    known = {"founder_fade": {"SHAREHOLDER", "FUND_DIVERSION"}}
    assert hits == known.get(pid, set()), f"{pid}: {hits}"


def test_서버가_두_도구_모두에_배선했다():
    src = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    assert src.count("taxonomy_owners=") >= 3
    assert "tax_owners_all" in src and "all_tax_owners" in src


def test_뷰어도_같은_계산을_한다():
    html = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
    assert "function evidenceCount(" in html
    assert "Math.min(matched.length, owners.size)" in html
    assert "taxOwners[t] = taxOwners[t] || new Set()" in html
