"""어미가 '해제'여도 국면이 올라간 제목을 강등하지 않는지 잠근다.

v1.12.2가 90일 창에서 R2 강등 23건을 전수 확인해 「정리매매 개시」를 갈라냈다.
2026-08-23에 **1년 창**으로 같은 검토를 반복하니(38행 / 1,105건) 두 종류가
더 나왔다 — 창을 넓히지 않으면 안 보이는 것들이었다.

| 제목 | 건수 | 왜 강등이 틀렸나 |
|---|---:|---|
| 「매매거래정지및정지해제(풍문등조회공시)」 | 10 | 본체가 정지와 해제를 **함께** 알리는데 어미만 '해제'다. 사건은 풍문 조회공시이고, 형제 「조회공시요구(풍문또는보도)」 28건은 관찰이다 |
| 「주권매매거래정지해제(회생절차개시결정)」 | 1 | 법원이 회생을 **개시**해서 정지가 풀린 것이다. 같은 부제의 「…기간변경(회생절차 개시결정)」 11건은 관찰인데 이것만 강등됐다 |

나머지 36행은 정당한 강등이다 — 결과보고서·계약해제ㆍ취소·철회·
「상장폐지 사유 해소」·「실질심사 대상 제외 결정」.
"""
import pytest

from dart_risk_mcp.core.qualifiers import (
    ESCALATION_SUBTITLES, TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import match_signals


def _tiers(nm):
    sigs = match_signals(nm)
    return {s["key"]: q for s, q in zip(sigs, qualify_signals(sigs, parse_report_name(nm), {}))}


# 관찰이어야 하는 것 — (제목, 신호 키)
ESCALATED = [
    ("매매거래정지및정지해제(풍문등조회공시)", "INQUIRY"),
    ("주권매매거래정지해제              (회생절차개시결정)", "GOING_CONCERN"),
    ("주권매매거래정지해제              (상장폐지에 따른 정리매매 개시)", "DELISTING_RISK"),
]

# 강등이 맞는 것 — 어미가 해제·철회이고 뜻도 그렇다
STILL_DEMOTED = [
    ("주권매매거래정지해제              (상장적격성 실질심사 대상 제외 결정)", "DELISTING_RISK"),
    ("주권매매거래정지해제              (상장폐지 사유 해소)", "DELISTING_RISK"),
    ("주권매매거래정지해제              (상장폐지사유 미해당)", "DELISTING_RISK"),
    ("주권매매거래정지해제              (합병결정 철회)", "MGMT"),
    ("자기주식취득결과보고서", "TREASURY"),
    ("최대주주변경을수반하는주식담보제공계약해제ㆍ취소등", "STAKE_PLEDGE"),
]


@pytest.mark.parametrize("nm,key", ESCALATED)
def test_국면이_올라간_제목은_관찰이다(nm, key):
    q = _tiers(nm).get(key)
    assert q is not None, f"{key}가 매칭되지 않는다"
    assert q.tier == TIER_OBSERVED, f"강등 사유: {q.reason}"


@pytest.mark.parametrize("nm,key", STILL_DEMOTED)
def test_진짜_해제_철회는_그대로_강등된다(nm, key):
    """예외를 넓게 잡아 정상 강등까지 관찰로 올리면 반대 방향의 오류가 된다."""
    q = _tiers(nm).get(key)
    assert q is not None, f"{key}가 매칭되지 않는다"
    assert q.tier != TIER_OBSERVED, nm


def test_형제_제목과_판정이_같다():
    """같은 사건인데 어미·본체 때문에 갈리던 것이 이 결함의 정체다."""
    assert _tiers("조회공시요구(풍문또는보도)")["INQUIRY"].tier == TIER_OBSERVED
    assert _tiers("매매거래정지및정지해제(풍문등조회공시)")["INQUIRY"].tier == TIER_OBSERVED

    tail = "주권매매거래정지기간변경              (회생절차 개시결정)"
    assert _tiers(tail)["GOING_CONCERN"].tier == TIER_OBSERVED
    assert _tiers("주권매매거래정지해제              (회생절차개시결정)")[
        "GOING_CONCERN"].tier == TIER_OBSERVED


def test_목록이_근거와_함께_유지된다():
    """항목을 넣을 때는 코퍼스 전수 근거를 주석으로 남기는 것이 이 파일의 규약."""
    assert set(ESCALATION_SUBTITLES) == {
        "정리매매개시", "정리매매재개", "풍문등조회공시", "회생절차개시결정",
    }


def test_뷰어가_같은_값을_읽는다():
    """뷰어는 이 목록을 signals-data.json에서 읽는다 — 코드가 아니라 데이터라
    core만 고치면 따라오지만, export를 잊으면 어긋난다."""
    import json
    import pathlib

    p = pathlib.Path(__file__).resolve().parents[1] / "docs" / "tool" / "signals-data.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert (tuple(data["qualifier_rules"]["escalation_subtitles"])
            == ESCALATION_SUBTITLES)
