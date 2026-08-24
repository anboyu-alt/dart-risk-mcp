"""타임라인의 붉은 칠·발광이 카테고리가 아니라 `isHeavySignal`을 따르는지 잠근다.

#275가 배너와 **점 크기**를 `priority` 축으로 옮길 때 **밀도 막대**와 **범례
문구**는 옛 기준(`category >= 7`)에 남아 있었다. 뷰어를 띄워 SK하이닉스를
스캔하다 발견했다(2026-08-24).

남아 있던 결과는 #275가 고친 것과 같다 — 「매출액또는손익구조30%이상변경」
한 건이 그 달을 **붉게 칠하고 발광**시킨다. 실적이 좋아진 공시에도 붙는다.

실측(2026-08-24 라이브, 10개사 1년):

    붉게 칠해지는 회사-월 19개 중 **9개(47%)**가 손익구조 급변 하나뿐
    — 삼성전자 2026.01 · 셀트리온 2026.02 · 두산에너빌리티 2026.02 포함

1년 코퍼스로도 같은 몫이 나온다 — `category >= 7` 관찰 신호 4,085건 중
**2,251건(55.1%)**이 `EARNINGS_SHOCK` 하나다.

범례는 그 사이 **거짓말이 돼 있었다** — 점은 이미 `isHeavySignal`로 걸러지는데
문구는 여전히 "큰 점 = 시장감시·위기/부실"이라 적었다. `context` 신호는
위기/부실인데도 작은 점으로 그려진다.

부수: 점 툴팁이 방향 안내를 버려서 되사기 건도 「교환사채(EB)발행」로 떴다
(SK하이닉스 20260428 「자기교환사채만기전취득결정」 실물 확인) — #277이
헤드라인·커멘터리에서 고친 것과 같은 결함이 툴팁에 남아 있었다.
"""
import json
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
_DENSITY = _HTML[_HTML.index("function timelinePanel("):]
_DENSITY = _DENSITY[:_DENSITY.index("// 레인 타임라인")]


def test_밀도_막대가_카테고리로_붉어지지_않는다():
    assert "x.maxCat >= 7 ? 7" not in _DENSITY, "옛 기준이 남아 있다"
    assert 'x.heavy ? 7 : x.maxCat || 2' in _DENSITY


def test_발광도_같은_기준을_쓴다():
    assert "${x.heavy ? \"box-shadow:0 0 8px" in _DENSITY
    assert "${x.maxCat >= 7 ? \"box-shadow" not in _DENSITY


def test_월_버킷이_heavy를_모은다():
    assert "obsSigs.some(isHeavySignal)" in _DENSITY
    assert "heavy: false" in _DENSITY, "초기화가 없으면 undefined가 샌다"


def test_범례가_실제_기준을_말한다():
    """점은 `isHeavySignal`로 걸러지는데 문구만 카테고리를 말하면 거짓이 된다."""
    assert "큰 점 = 시장감시·위기/부실" not in _HTML
    assert "먼저 볼 공시" in _HTML


def test_점_툴팁이_방향_안내를_담는다():
    i = _HTML.index("<title>${esc(fmtDate(e.date))}")
    tip = _HTML[i:i + 220]
    assert "s.note" in tip, tip
    assert "(클릭 → DART 원문)" in tip, "툴팁 꼬리가 끊겼다"


@pytest.mark.parametrize("key", ["EARNINGS_SHOCK"])
def test_그_신호가_실제로_context다(key):
    """전제가 무너지면(우선순위가 바뀌면) 이 수정의 근거도 바뀐다."""
    from dart_risk_mcp.core.signals import observation_priority

    assert observation_priority(key) == "context"


def test_카테고리는_그대로_8이다():
    """분류 자체를 바꾼 것이 아니다 — 표시 기준만 바꿨다."""
    import sys

    sys.path.insert(0, str(_ROOT / "scripts"))
    from export_tool_data import _category_of

    assert _category_of("EARNINGS_SHOCK") == 8
    data = json.loads((_ROOT / "docs" / "tool" / "signals-data.json")
                      .read_text(encoding="utf-8"))
    row = next(s for s in data["signals"] if s["key"] == "EARNINGS_SHOCK")
    assert row["category"] == 8
    assert row["priority"] == "context"


def test_상한에_걸리면_전체라_적지_않는다():
    """삼성전자 1년 실물: 카드 「전체 공시 1000」 vs 주석 「전체 공시는 2892건」.

    같은 패널에서 두 숫자가 어긋났다. 숫자를 총계로 바꾸면 옆의 「신호 감지」와
    분모가 달라지므로 **라벨을 사실에 맞춘다**.
    """
    assert '${CUR.truncated ? "수집 공시" : "전체 공시"}' in _HTML
    assert '<div class="k">전체 공시</div>' not in _HTML


def test_무신호_안내도_수집분만_말한다():
    i = _HTML.index("등록된 위험 신호 유형이 감지되지 않았습니다")
    head = _HTML[i - 160:i]
    assert "CUR.truncated" in head, head[-90:]
    assert "수집한 최근" in head
