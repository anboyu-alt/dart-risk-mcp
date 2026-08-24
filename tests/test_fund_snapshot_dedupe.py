"""같은 조달건의 옛 연도 스냅샷이 이벤트 목록에서 중복되지 않는지 잠근다.

`fetch_fund_usage`는 최근 3년 정기보고서를 훑으므로 한 조달건이 여러 연도
보고서에 각각 실린다. `analyze_company_risk`는 그걸 그대로 펼쳐, 같은 줄이
두세 번 나오고 관찰 건수까지 부풀렸다.

**실측(2026-08-24)** — 오성첨단소재(052420) 1년 리포트:

    관찰 31건  →  25건   (플래그 9줄이 실제로는 조달건 3건)
    오르비텍(046120)      플래그 13줄 → 5건

CLAUDE.md가 `FUND_UNREPORTED` 오탐의 구조적 원인으로 적어 둔 "다년 보고
스냅샷 미정산"이 이것이다. `track_fund_usage`의 판정은 이미 최신 연도
라인아이템을 보는데 `analyze_company_risk`의 이벤트 목록만 그러지 않았다.

⚠ 5개사 실측에서 이 접기로 **사라지는 실질 신호는 0건**이었다 — 최신 연도에서
해소됐는데 옛 스냅샷만 플래그로 남은 경우가 없었다.
"""
import pytest

from dart_risk_mcp.server import _latest_fund_snapshots


def _rec(year, pay_de="2025.10.15", tm="25", prps="타법인 증권 취득자금", **kw):
    d = {"year": year, "pay_de": pay_de, "tm": tm, "plan_useprps": prps,
         "flags": ["FUND_UNREPORTED"]}
    d.update(kw)
    return d


def test_같은_조달건은_최신_연도만_남는다():
    got = _latest_fund_snapshots([_rec("2025"), _rec("2026"), _rec("2024")])
    assert len(got) == 1
    assert got[0]["year"] == "2026"


def test_회차가_다르면_별개다():
    got = _latest_fund_snapshots([_rec("2026", tm="25"), _rec("2026", tm="26")])
    assert len(got) == 2


def test_납입일이_다르면_별개다():
    got = _latest_fund_snapshots([_rec("2026", pay_de="2025.10.15"),
                                  _rec("2026", pay_de="2025.10.23")])
    assert len(got) == 2


def test_계획_용도가_다르면_별개다():
    """같은 조달건이라도 용도가 나뉘면 각각 봐야 한다."""
    got = _latest_fund_snapshots([_rec("2026", prps="타법인 증권 취득자금"),
                                  _rec("2026", prps="채무상환자금")])
    assert len(got) == 2


def test_최신_연도의_플래그를_따른다():
    """옛 스냅샷에 플래그가 있어도 최신에서 해소됐으면 최신을 쓴다."""
    old = _rec("2025")
    new = _rec("2026")
    new["flags"] = []
    got = _latest_fund_snapshots([old, new])
    assert len(got) == 1 and got[0]["flags"] == []


@pytest.mark.parametrize("records", [None, [], [{}]])
def test_빈_입력에서_죽지_않는다(records):
    out = _latest_fund_snapshots(records)
    assert isinstance(out, list)


def test_연도가_없어도_한_건은_남는다():
    got = _latest_fund_snapshots([{"pay_de": "x", "tm": "1", "plan_useprps": "y"}])
    assert len(got) == 1


def test_판정_도구는_영향받지_않는다():
    """`track_fund_usage`는 전체 레코드를 그대로 쓴다 — 접기는 이벤트 목록 전용."""
    import inspect

    import dart_risk_mcp.server as srv

    body = inspect.getsource(getattr(srv.track_fund_usage, "fn", srv.track_fund_usage))
    assert "_latest_fund_snapshots" not in body, (
        "판정 도구까지 접으면 연도별 추이를 볼 수 없다"
    )
